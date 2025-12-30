import os
import telebot
from telebot import types

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана!")

bot = telebot.TeleBot(BOT_TOKEN)


@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот для статистики Raid Shards.")


@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
Доступные команды:
/start - Начать работу с ботом
/help - Показать это сообщение
    """
    bot.reply_to(message, help_text)


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, message.text)


if __name__ == '__main__':
    print("Бот запущен...")
    bot.polling(none_stop=True)