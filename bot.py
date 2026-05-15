"""
Greek Words Bot — бот для ежедневной рассылки 10 случайных греческих слов
в Telegram-группу. Уровень A1-A2 для изучения греческого на Кипре.
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

# ---------- Настройка ----------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # ID группы куда слать слова
TIMEZONE = os.getenv("TIMEZONE", "Asia/Nicosia")  # Кипрское время
SEND_HOUR = int(os.getenv("SEND_HOUR", "10"))
SEND_MINUTE = int(os.getenv("SEND_MINUTE", "0"))
WORDS_PER_DAY = int(os.getenv("WORDS_PER_DAY", "10"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------- Загрузка словаря ----------
WORDS_FILE = Path(__file__).parent / "words.json"
with open(WORDS_FILE, "r", encoding="utf-8") as f:
    WORDS = json.load(f)

logger.info(f"Загружено {len(WORDS)} слов из словаря")

# ---------- Бот ----------
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


def format_words_message(words: list) -> str:
    """Форматирует сообщение с 10 словами."""
    today = datetime.now().strftime("%d.%m.%Y")
    header = f"🇬🇷 <b>Греческие слова дня</b> · {today}\n\n"
    
    lines = []
    for i, w in enumerate(words, 1):
        lines.append(
            f"<b>{i}. {w['word']}</b> {w['transcription']}\n"
            f"   → {w['translation']}\n"
            f"   <i>{w['example']}</i>"
        )
    
    footer = "\n\n💡 <i>Καλή μάθηση! / Удачной учёбы!</i>"
    return header + "\n\n".join(lines) + footer


def pick_random_words(n: int = 10) -> list:
    """Выбирает n случайных слов из словаря."""
    return random.sample(WORDS, min(n, len(WORDS)))


async def send_daily_words():
    """Отправляет ежедневные слова в чат."""
    if not CHAT_ID:
        logger.warning("CHAT_ID не задан — пропускаю рассылку")
        return
    
    try:
        words = pick_random_words(WORDS_PER_DAY)
        text = format_words_message(words)
        await bot.send_message(chat_id=CHAT_ID, text=text)
        logger.info(f"Отправлено {len(words)} слов в чат {CHAT_ID}")
    except Exception as e:
        logger.error(f"Ошибка при отправке: {e}")


# ---------- Команды ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🇬🇷 <b>Καλώς ήρθες!</b>\n\n"
        "Я бот для изучения греческого. Каждый день в "
        f"<b>{SEND_HOUR:02d}:{SEND_MINUTE:02d}</b> (Кипр) присылаю "
        f"<b>{WORDS_PER_DAY} случайных слов</b> A1-A2 уровня.\n\n"
        "Команды:\n"
        "/words — получить слова прямо сейчас\n"
        "/chatid — узнать ID этого чата (нужно для настройки)\n"
        "/about — о боте"
    )


@dp.message(Command("words"))
async def cmd_words(message: Message):
    """Получить слова прямо сейчас."""
    words = pick_random_words(WORDS_PER_DAY)
    text = format_words_message(words)
    await message.answer(text)


@dp.message(Command("chatid"))
async def cmd_chatid(message: Message):
    """Показать ID чата — нужно для конфига."""
    await message.answer(
        f"<b>Chat ID этого чата:</b>\n<code>{message.chat.id}</code>\n\n"
        f"Тип: {message.chat.type}\n"
        f"Скопируй этот ID в переменную <code>CHAT_ID</code> файла .env"
    )


@dp.message(Command("about"))
async def cmd_about(message: Message):
    await message.answer(
        "🇬🇷 <b>Greek Words Bot</b>\n\n"
        f"Словарь: <b>{len(WORDS)} слов</b> A1-A2 уровня\n"
        f"Рассылка: каждый день в {SEND_HOUR:02d}:{SEND_MINUTE:02d} ({TIMEZONE})\n"
        f"Слов за раз: {WORDS_PER_DAY}\n\n"
        "Слова отбираются случайно. /words для получения вручную."
    )


# ---------- Запуск ----------
async def main():
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_daily_words,
        trigger=CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE),
        id="daily_words",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Планировщик запущен: рассылка ежедневно в "
        f"{SEND_HOUR:02d}:{SEND_MINUTE:02d} ({TIMEZONE})"
    )
    
    logger.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
