import telebot
from telebot import types
from config import BOT_TOKEN

bot = telebot.TeleBot(BOT_TOKEN)


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот для статистики Raid Shards.")


# Обработчик команды /help
@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
Доступные команды:
/start - Начать работу с ботом
/help - Показать это сообщение
    """
    bot.reply_to(message, help_text)


# Обработчик всех текстовых сообщений
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, message.text)


# Запуск бота
if __name__ == '__main__':
    print("Бот запущен...")
    bot.polling(none_stop=True)

