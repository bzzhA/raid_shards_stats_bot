import os
import signal
import asyncio
import requests
from telebot.async_telebot import AsyncTeleBot
from telebot import types
import logging
from flask import Flask, request

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Получаем токен из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана!")

# Получаем URL вебхука из переменных окружения или вычисляем
KOYEB_APP_DOMAIN = os.getenv('KOYEB_APP_DOMAIN')
if not KOYEB_APP_DOMAIN:
    # Если домен не указан, попробуем получить из другого источника
    # или использовать заглушку (потребуется ручная настройка)
    KOYEB_APP_DOMAIN = "koyeb.app"

WEBHOOK_URL = f"https://{KOYEB_APP_DOMAIN}/webhook"

# Создаём Flask приложение
app = Flask(__name__)

# Создаём бота
bot = AsyncTeleBot(BOT_TOKEN)

# Хранение данных в памяти (для продакшена — использовать Redis/БД)
user_shards_data = {}  # {user_id: {shard_type: count}}
waiting_for_input = {}  # {user_id: shard_type}

# Пороги
LEGENDARY_THRESHOLDS = {
    'shard_blue': 200,
    'shard_void': 200,
    'shard_mythic': 200,
    'shard_sacred': 12
}

EPIC_THRESHOLDS = {
    'shard_blue': 20,
    'shard_void': 20,
    'shard_mythic': None,
    'shard_sacred': None
}


# === Вспомогательные функции ===

def create_reply_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("📥 Ввести кол-во осколков"),
        types.KeyboardButton("🎉 ВЫПАЛО!"),
        types.KeyboardButton("ℹ️ Информация"),
        types.KeyboardButton("❓ Помощь")
    )
    return keyboard


def create_shards_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Синий 💠", callback_data='shard_blue'),
        types.InlineKeyboardButton("Войд 🔷", callback_data='shard_void'),
        types.InlineKeyboardButton("Мифик ♦️", callback_data='shard_mythic'),
        types.InlineKeyboardButton("Сакрал ✨", callback_data='shard_sacred')
    )
    markup.add(types.InlineKeyboardButton("📊 Статистика", callback_data='show_stats'))
    return markup


def create_shards_reset_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Синий 💠", callback_data='reset_choice_shard_blue'),
        types.InlineKeyboardButton("Войд 🔷", callback_data='reset_choice_shard_void'),
        types.InlineKeyboardButton("Мифик ♦️", callback_data='reset_choice_shard_mythic'),
        types.InlineKeyboardButton("Сакрал ✨", callback_data='reset_choice_shard_sacred')
    )
    return markup


def create_reset_rarity_keyboard(shard_type):
    markup = types.InlineKeyboardMarkup(row_width=1)
    buttons = []
    if EPIC_THRESHOLDS.get(shard_type) is not None:
        buttons.append(types.InlineKeyboardButton("Эпический герой 🟣", callback_data=f"reset_{shard_type}_epic"))
    if LEGENDARY_THRESHOLDS.get(shard_type) is not None:
        buttons.append(types.InlineKeyboardButton("Легендарный герой 🟡", callback_data=f"reset_{shard_type}_legendary"))
    if shard_type == 'shard_mythic':
        buttons.append(types.InlineKeyboardButton("Мифический герой 🔮", callback_data=f"reset_{shard_type}_mythic"))
    if buttons:
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_reset"))
    else:
        markup.add(types.InlineKeyboardButton("Нет доступных редкостей", callback_data="cancel_reset"))
    return markup


def format_stats(user_id):
    if user_id not in user_shards_data or not user_shards_data[user_id]:
        return None
    
    stats = user_shards_data[user_id]
    shard_display = {
        'shard_blue': '💠 Синий',
        'shard_void': '🔷 Войд',
        'shard_mythic': '♦️ Мифик',
        'shard_sacred': '✨ Сакрал'
    }
    stats_text = "📊 <b>Статистика открытых осколков</b>\n\n"
    
    for shard_type in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred']:
        count = stats.get(shard_type, 0)
        display_name = shard_display[shard_type]
        threshold = LEGENDARY_THRESHOLDS[shard_type]
        epic_threshold = EPIC_THRESHOLDS[shard_type]
        remaining = max(0, threshold - count)
        epic_remaining = max(0, epic_threshold - count) if epic_threshold else None
        stats_text += f"{display_name}: <b>{count}</b>\n"
        if epic_remaining is not None and epic_remaining > 0:
            stats_text += f"   ⚡ До эпического: <b>{epic_remaining}</b>\n"
        stats_text += f"   ⏳ До легендарного: <b>{remaining}</b>\n\n"
    
    return stats_text


def setup_webhook_sync():
    """Синхронная функция для установки вебхука через GET запрос"""
    try:
        # Формируем URL для установки вебхука
        telegram_api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        
        # Параметры для запроса
        params = {
            'url': WEBHOOK_URL,
            'max_connections': 40,
            'drop_pending_updates': True
        }
        
        logger.info(f"🔄 Устанавливаем вебхук на URL: {WEBHOOK_URL}")
        
        # Отправляем GET запрос
        response = requests.get(telegram_api_url, params=params, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                logger.info(f"✅ Вебхук успешно установлен: {WEBHOOK_URL}")
                logger.info(f"📝 Ответ Telegram API: {result.get('description', 'Успешно')}")
                
                # Проверяем информацию о вебхуке
                check_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
                check_response = requests.get(check_url, timeout=10)
                if check_response.status_code == 200:
                    webhook_info = check_response.json()
                    if webhook_info.get('ok'):
                        logger.info(f"🔍 Информация о вебхуке: {webhook_info.get('result', {})}")
            else:
                logger.error(f"❌ Ошибка установки вебхука: {result}")
        else:
            logger.error(f"❌ HTTP ошибка: {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка сети при установке вебхука: {e}")
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при установке вебхука: {e}")


# === Обработчики команд ===

@bot.message_handler(commands=['start'])
async def send_welcome(message):
    reply_keyboard = create_reply_keyboard()
    await bot.reply_to(message, (
        "👋 Привет! Я бот для статистики Raid Shards.\n\n"
        "🎯 Выберите тип осколка или воспользуйтесь кнопками ниже!\n\n"
        "💡 Нажмите «🎉 ВЫПАЛО!», если получили героя и хотите сбросить счётчик."
    ), reply_markup=reply_keyboard)
    await bot.send_message(message.chat.id, "Выберите тип осколка:", reply_markup=create_shards_keyboard())


@bot.message_handler(commands=['help'])
async def send_help(message):
    help_text = """📚 <b>Доступные команды:</b>

/start — 🚀 Начать
/info_shard — ℹ️ Шансы призыва
/stats — 📊 Статистика
📥 Ввести кол-во осколков — указать количество
🎉 ВЫПАЛО! — сбросить счётчик"""
    await bot.reply_to(message, help_text, parse_mode='HTML', reply_markup=create_reply_keyboard())


@bot.message_handler(commands=['stats'])
async def send_stats_command(message):
    user_id = message.from_user.id
    stats_text = format_stats(user_id)
    if not stats_text:
        await bot.reply_to(
            message,
            "📊 <b>Статистика открытых осколков</b>\n\n"
            "❌ У вас пока нет данных.\n"
            "👉 Укажите количество или нажмите «📥 Ввести кол-во осколков».",
            parse_mode='HTML',
            reply_markup=create_reply_keyboard()
        )
    else:
        await bot.reply_to(message, stats_text, parse_mode='HTML', reply_markup=create_reply_keyboard())


@bot.message_handler(commands=['info_shard'])
async def send_shard_info(message):
    info_text = """📊 <b>Шансы призыва по системе компенсации неудач</b>

🔵 <b>Древний / Темный осколок</b>
   • Эпик: 20+ → +2%
   • Легенда: 200+ → +5%

💎 <b>Циркон Первозданный осколок</b>
   • Мифик: 200+ → +10%

⭐ <b>Сакральный осколок</b>
   • Легенда: 12+ → +2%"""
    await bot.reply_to(message, info_text, parse_mode='HTML', reply_markup=create_reply_keyboard())


# === Callback-обработчики ===

@bot.callback_query_handler(func=lambda call: call.data == 'show_stats')
async def show_stats_callback(call):
    await bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    stats_text = format_stats(user_id)
    if not stats_text:
        await bot.send_message(
            call.message.chat.id,
            "📊 <b>Статистика открытых осколков</b>\n\n"
            "❌ У вас пока нет данных.\n"
            "👉 Укажите количество или нажмите «📥 Ввести кол-во осколков».",
            parse_mode='HTML',
            reply_markup=create_reply_keyboard()
        )
    else:
        await bot.send_message(call.message.chat.id, stats_text, parse_mode='HTML', reply_markup=create_reply_keyboard())


@bot.callback_query_handler(func=lambda call: call.data in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred'])
async def handle_shard_selection(call):
    await bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    shard_type = call.data

    shard_names = {
        'shard_blue': 'Синий 💠',
        'shard_void': 'Войд 🔷',
        'shard_mythic': 'Мифик ♦️',
        'shard_sacred': 'Сакрал ✨'
    }
    shard_name = shard_names[shard_type]

    if user_id not in user_shards_data:
        user_shards_data[user_id] = {}

    current_count = user_shards_data[user_id].get(shard_type, 0)

    if current_count == 0:
        waiting_for_input[user_id] = shard_type
        await bot.send_message(
            call.message.chat.id,
            f"✅ Выбран {shard_name}!\n\n📝 Укажите кол-во открытых осколков!\n\n"
            f"ℹ️ Текущее количество: <b>0</b>\n"
            f"💡 Введите число, чтобы добавить к текущему количеству.",
            parse_mode='HTML',
            reply_markup=create_reply_keyboard()
        )
    else:
        threshold = LEGENDARY_THRESHOLDS[shard_type]
        epic_threshold = EPIC_THRESHOLDS[shard_type]
        remaining = max(0, threshold - current_count)
        epic_remaining = max(0, epic_threshold - current_count) if epic_threshold else None

        stats_text = f"✅ {shard_name}\n📦 Открыто: <b>{current_count}</b>\n"
        if epic_remaining is not None and epic_remaining > 0:
            stats_text += f"⚡ До эпического: <b>{epic_remaining}</b>\n"
        stats_text += f"⏳ До легендарного: <b>{remaining}</b>\n\n"
        stats_text += f"💡 Введите число, чтобы добавить к текущему количеству:"

        await bot.send_message(call.message.chat.id, stats_text, parse_mode='HTML', reply_markup=create_reply_keyboard())
        waiting_for_input[user_id] = shard_type


@bot.callback_query_handler(func=lambda call: call.data.startswith("show_reset_menu_"))
async def show_reset_menu(call):
    shard_type = call.data.replace("show_reset_menu_", "")
    if shard_type in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred']:
        await bot.answer_callback_query(call.id)
        markup = create_reset_rarity_keyboard(shard_type)
        await bot.send_message(call.message.chat.id, "Выберите редкость героя, который выпал:", reply_markup=markup)
    else:
        await bot.answer_callback_query(call.id, "Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("reset_choice_"))
async def handle_reset_shard_choice(call):
    shard_type = call.data.replace("reset_choice_", "")
    if shard_type in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred']:
        await bot.answer_callback_query(call.id)
        markup = create_reset_rarity_keyboard(shard_type)
        await bot.send_message(call.message.chat.id, "Выберите редкость героя, который выпал:", reply_markup=markup)
    else:
        await bot.answer_callback_query(call.id, "Неверный тип осколка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("reset_"))
async def handle_reset_shard(call):
    user_id = call.from_user.id
    parts = call.data.split('_', 3)
    if len(parts) != 4:
        await bot.answer_callback_query(call.id, "Ошибка", show_alert=True)
        return

    shard_type = f"{parts[1]}_{parts[2]}"
    rarity_key = parts[3]

    if shard_type not in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred']:
        await bot.answer_callback_query(call.id, "Неверный тип", show_alert=True)
        return

    if user_id not in user_shards_data:
        user_shards_data[user_id] = {}
    user_shards_data[user_id][shard_type] = 0

    shard_names = {
        'shard_blue': 'Синий 💠',
        'shard_void': 'Войд 🔷',
        'shard_mythic': 'Мифик ♦️',
        'shard_sacred': 'Сакрал ✨'
    }
    rarity_names = {
        'epic': 'Эпического',
        'legendary': 'Легендарного',
        'mythic': 'Мифического'
    }

    shard_name = shard_names[shard_type]
    rarity_name = rarity_names.get(rarity_key, 'Неизвестной')

    await bot.answer_callback_query(call.id, "Счётчик сброшен!")
    await bot.send_message(
        call.message.chat.id,
        f"✅ Счётчик для {shard_name}, {rarity_name} героя сброшен!",
        reply_markup=create_reply_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data == "cancel_reset")
async def handle_cancel_reset(call):
    await bot.answer_callback_query(call.id, "Сброс отменён")
    try:
        await bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass


# === Обработка текстовых кнопок ===

@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
async def stats_from_button(message):
    await send_stats_command(message)


@bot.message_handler(func=lambda message: message.text == "📥 Ввести кол-во осколков")
async def enter_count_button(message):
    await bot.reply_to(message, 
        "🎯 Выберите тип осколка для ввода количества!",
        reply_markup=create_reply_keyboard()
    )
    await bot.send_message(message.chat.id, "Выберите тип осколка:", reply_markup=create_shards_keyboard())


@bot.message_handler(func=lambda message: message.text == "🎉 ВЫПАЛО!")
async def handle_reset_button(message):
    await bot.send_message(
        message.chat.id,
        "Выберите тип осколка, по которому выпал герой:",
        reply_markup=create_shards_reset_keyboard()
    )


@bot.message_handler(func=lambda message: message.text == "ℹ️ Информация")
async def info_from_button(message):
    await send_shard_info(message)


@bot.message_handler(func=lambda message: message.text == "❓ Помощь")
async def help_from_button(message):
    await send_help(message)


@bot.message_handler(func=lambda message: True)
async def handle_message(message):
    user_id = message.from_user.id
    text = message.text.strip()

    if text.startswith('/'):
        return

    if user_id in waiting_for_input:
        shard_type = waiting_for_input[user_id]
        try:
            count = int(text)
            if count < 0:
                await bot.reply_to(message, "❌ Число должно быть ≥ 0!", reply_markup=create_reply_keyboard())
                return

            if user_id not in user_shards_data:
                user_shards_data[user_id] = {}
            
            # Получаем текущее количество и прибавляем новое
            current_count = user_shards_data[user_id].get(shard_type, 0)
            new_count = current_count + count
            
            user_shards_data[user_id][shard_type] = new_count

            shard_names = {
                'shard_blue': 'Синий 💠',
                'shard_void': 'Войд 🔷',
                'shard_mythic': 'Мифик ♦️',
                'shard_sacred': '✨ Сакрал'
            }
            shard_name = shard_names[shard_type]
            
            # Сообщаем о добавлении
            threshold = LEGENDARY_THRESHOLDS[shard_type]
            epic_threshold = EPIC_THRESHOLDS[shard_type]
            remaining = max(0, threshold - new_count)
            epic_remaining = max(0, epic_threshold - new_count) if epic_threshold else None

            stats_text = f"✅ Обновлено: {shard_name}\n"
            stats_text += f"📈 Добавлено: +{count}\n"
            stats_text += f"📦 Всего открыто: <b>{new_count}</b>\n"
            
            if epic_remaining is not None and epic_remaining > 0:
                stats_text += f"⚡ До эпического: <b>{epic_remaining}</b>\n"
            stats_text += f"⏳ До легендарного: <b>{remaining}</b>"

            reset_markup = types.InlineKeyboardMarkup()
            reset_markup.add(types.InlineKeyboardButton("🎉 ВЫПАЛО! → Сбросить счётчик", callback_data=f"show_reset_menu_{shard_type}"))
            await bot.reply_to(message, stats_text, parse_mode='HTML', reply_markup=reset_markup)

            del waiting_for_input[user_id]

        except ValueError:
            await bot.reply_to(message, "❌ Введите число!", reply_markup=create_reply_keyboard())
    else:
        await bot.reply_to(message, "Неизвестная команда. Используйте кнопки.", reply_markup=create_reply_keyboard())


# === Flask роуты для вебхука ===

@app.route('/')
def index():
    return "Telegram Bot is running on Koyeb! Webhook URL: " + WEBHOOK_URL

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        
        # Обрабатываем обновление асинхронно
        asyncio.run(bot.process_new_updates([update]))
        
        return ''
    return 'Bad Request', 400

@app.route('/setup_webhook', methods=['GET'])
def setup_webhook_route():
    """Ручка для ручной установки вебхука через браузер"""
    setup_webhook_sync()
    return f"Webhook setup attempted for URL: {WEBHOOK_URL}<br>Check logs for details."


# === Запуск бота на Koyeb ===

def run_flask():
    """Запуск Flask приложения"""
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"🚀 Запускаем Flask на порту {port}")
    logger.info(f"🌐 Домен приложения: {KOYEB_APP_DOMAIN}")
    logger.info(f"🔗 Вебхук URL: {WEBHOOK_URL}")
    app.run(host='0.0.0.0', port=port)


if __name__ == "__main__":
    logger.info("🚀 Бот запускается на Koyeb...")
    
    # Устанавливаем вебхук при старте
    setup_webhook_sync()
    
    logger.info("✅ Вебхук установлен, запускаем Flask сервер...")
    logger.info("🌐 Проверьте работу: /start в Telegram")
    logger.info(f"🔧 Для повторной установки вебхука откройте: https://{KOYEB_APP_DOMAIN}/setup_webhook")
    
    # Запускаем Flask сервер
    run_flask()