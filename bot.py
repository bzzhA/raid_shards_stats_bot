import os
import telebot
from telebot import types
from flask import Flask, request

# Получаем токен из переменных окружения (Render)
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана!")

# Создаём бота и Flask-приложение
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

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
        types.KeyboardButton("📥 Ввести кол-во открытых осколков"),
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
    markup.add(types.InlineKeyboardButton("📊 Статистика открытых", callback_data='show_stats'))
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


# === Обработчики команд и кнопок ===

@bot.message_handler(commands=['start'])
def send_welcome(message):
    reply_keyboard = create_reply_keyboard()
    bot.reply_to(message, (
        "👋 Привет! Я бот для статистики Raid Shards.\n\n"
        "🎯 Выберите тип осколка или воспользуйтесь кнопками ниже!\n\n"
        "💡 Нажмите «🎉 ВЫПАЛО!», если получили героя и хотите сбросить счётчик."
    ), reply_markup=reply_keyboard)
    bot.send_message(message.chat.id, "Выберите тип осколка:", reply_markup=create_shards_keyboard())


@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """📚 <b>Доступные команды:</b>

/start — 🚀 Начать
/info_shard — ℹ️ Шансы призыва
/stats — 📊 Статистика
📥 Ввести кол-во открытых осколков — указать количество открытых осколков
🎉 ВЫПАЛО! — сбросить счётчик

💡 Совет: всегда обновляйте количество перед сбросом!"""
    bot.reply_to(message, help_text, parse_mode='HTML', reply_markup=create_reply_keyboard())


@bot.message_handler(commands=['stats'])
def send_stats_command(message):
    user_id = message.from_user.id
    if user_id not in user_shards_data or not user_shards_data[user_id]:
        bot.reply_to(
            message,
            "📊 <b>Статистика открытых осколков</b>\n\n"
            "❌ У вас пока нет данных.\n"
            "👉 Укажите количество или нажмите «📥 Ввести кол-во открытых осколков».",
            parse_mode='HTML',
            reply_markup=create_reply_keyboard()
        )
    else:
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
        bot.reply_to(message, stats_text, parse_mode='HTML', reply_markup=create_reply_keyboard())


@bot.message_handler(commands=['info_shard'])
def send_shard_info(message):
    info_text = """📊 <b>Шансы призыва по системе компенсации неудач</b>

🔵 <b>Древний / Темный осколок</b>
   • Эпик: 20+ → +2%
   • Легенда: 200+ → +5%

💎 <b>Циркон Первозданный осколок</b>
   • Мифик: 200+ → +10%

⭐ <b>Сакральный осколок</b>
   • Легенда: 12+ → +2%"""
    bot.reply_to(message, info_text, parse_mode='HTML', reply_markup=create_reply_keyboard())


# === Callback-обработчики ===

@bot.callback_query_handler(func=lambda call: call.data == 'show_stats')
def show_stats_callback(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    if user_id not in user_shards_data or not user_shards_data[user_id]:
        bot.send_message(
            call.message.chat.id,
            "📊 <b>Статистика открытых осколков</b>\n\n"
            "❌ У вас пока нет данных.\n"
            "👉 Укажите количество или нажмите «📥 Ввести кол-во открытых осколков».",
            parse_mode='HTML',
            reply_markup=create_reply_keyboard()
        )
    else:
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
        bot.send_message(call.message.chat.id, stats_text, parse_mode='HTML', reply_markup=create_reply_keyboard())


@bot.callback_query_handler(func=lambda call: call.data in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred'])
def handle_shard_selection(call):
    bot.answer_callback_query(call.id)
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
        bot.send_message(
            call.message.chat.id,
            f"✅ Выбран {shard_name}!\n\n📝 Укажите кол-во открытых осколков!",
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
        stats_text += f"⏳ До легендарного: <b>{remaining}</b>"

        reset_markup = types.InlineKeyboardMarkup()
        reset_markup.add(types.InlineKeyboardButton("🎉 ВЫПАЛО! → Сбросить счётчик", callback_data=f"show_reset_menu_{shard_type}"))
        bot.send_message(call.message.chat.id, stats_text, parse_mode='HTML', reply_markup=reset_markup)
        waiting_for_input[user_id] = shard_type


@bot.callback_query_handler(func=lambda call: call.data.startswith("show_reset_menu_"))
def show_reset_menu(call):
    shard_type = call.data.replace("show_reset_menu_", "")
    if shard_type in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred']:
        bot.answer_callback_query(call.id)
        markup = create_reset_rarity_keyboard(shard_type)
        bot.send_message(call.message.chat.id, "Выберите редкость героя, который выпал:", reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "Ошибка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("reset_choice_"))
def handle_reset_shard_choice(call):
    shard_type = call.data.replace("reset_choice_", "")
    if shard_type in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred']:
        bot.answer_callback_query(call.id)
        markup = create_reset_rarity_keyboard(shard_type)
        bot.send_message(call.message.chat.id, "Выберите редкость героя, который выпал:", reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "Неверный тип осколка", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("reset_"))
def handle_reset_shard(call):
    user_id = call.from_user.id
    parts = call.data.split('_', 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Ошибка", show_alert=True)
        return

    shard_type = f"{parts[1]}_{parts[2]}"
    rarity_key = parts[3]

    if shard_type not in ['shard_blue', 'shard_void', 'shard_mythic', 'shard_sacred']:
        bot.answer_callback_query(call.id, "Неверный тип", show_alert=True)
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

    bot.answer_callback_query(call.id, "Счётчик сброшен!")
    bot.send_message(
        call.message.chat.id,
        f"✅ Счётчик для {shard_name}, {rarity_name} героя сброшен!",
        reply_markup=create_reply_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data == "cancel_reset")
def handle_cancel_reset(call):
    bot.answer_callback_query(call.id, "Сброс отменён")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass


# === Обработка текстовых кнопок ===

@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
def stats_from_button(message):
    send_stats_command(message)


@bot.message_handler(func=lambda message: message.text == "📥 Ввести кол-во открытых осколков")
def enter_count_button(message):
    reply_keyboard = create_reply_keyboard()
    bot.reply_to(message, "🎯 Выберите тип осколка для ввода количества:", reply_markup=reply_keyboard)
    bot.send_message(message.chat.id, "Выберите тип осколка:", reply_markup=create_shards_keyboard())


@bot.message_handler(func=lambda message: message.text == "🎉 ВЫПАЛО!")
def handle_reset_button(message):
    bot.send_message(
        message.chat.id,
        "Выберите тип осколка, по которому выпал герой:",
        reply_markup=create_shards_reset_keyboard()
    )


@bot.message_handler(func=lambda message: message.text == "ℹ️ Информация")
def info_from_button(message):
    send_shard_info(message)


@bot.message_handler(func=lambda message: message.text == "❓ Помощь")
def help_from_button(message):
    send_help(message)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    text = message.text.strip()

    if text.startswith('/'):
        return

    if user_id in waiting_for_input:
        shard_type = waiting_for_input[user_id]
        try:
            count = int(text)
            if count < 0:
                bot.reply_to(message, "❌ Число должно быть ≥ 0!", reply_markup=create_reply_keyboard())
                return

            if user_id not in user_shards_data:
                user_shards_data[user_id] = {}
            user_shards_data[user_id][shard_type] = count

            shard_names = {
                'shard_blue': 'Синий 💠',
                'shard_void': 'Войд 🔷',
                'shard_mythic': 'Мифик ♦️',
                'shard_sacred': 'Сакрал ✨'
            }
            shard_name = shard_names[shard_type]
            current_count = count
            threshold = LEGENDARY_THRESHOLDS[shard_type]
            epic_threshold = EPIC_THRESHOLDS[shard_type]
            remaining = max(0, threshold - current_count)
            epic_remaining = max(0, epic_threshold - current_count) if epic_threshold else None

            stats_text = f"✅ Обновлено: {shard_name}\n📦 Открыто: <b>{current_count}</b>\n"
            if epic_remaining is not None and epic_remaining > 0:
                stats_text += f"⚡ До эпического: <b>{epic_remaining}</b>\n"
            stats_text += f"⏳ До легендарного: <b>{remaining}</b>"

            reset_markup = types.InlineKeyboardMarkup()
            reset_markup.add(types.InlineKeyboardButton("🎉 ВЫПАЛО! → Сбросить счётчик", callback_data=f"show_reset_menu_{shard_type}"))
            bot.reply_to(message, stats_text, parse_mode='HTML', reply_markup=reset_markup)

            del waiting_for_input[user_id]

        except ValueError:
            bot.reply_to(message, "❌ Введите число!", reply_markup=create_reply_keyboard())
    else:
        bot.reply_to(message, "Неизвестная команда. Используйте кнопки.", reply_markup=create_reply_keyboard())


# === Webhook и запуск сервера ===

# Render автоматически задаёт RENDER_EXTERNAL_URL
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_URL')}{WEBHOOK_PATH}"


@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Invalid content-type', 403


@app.route("/")
def health_check():
    return "✅ Raid Shards Bot is running on Render (webhook mode)!"


if __name__ == "__main__":
    # Устанавливаем webhook при старте
    try:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"✅ Webhook установлен: {WEBHOOK_URL}")
    except Exception as e:
        print(f"❌ Ошибка установки webhook: {e}")

    # Запускаем Flask-сервер на порту из Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)