"""
Greek Words Bot — бот для ежедневной рассылки греческих слов в Telegram-группу.
Тематический режим: каждый день недели — своя тема.
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
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
CHAT_ID = os.getenv("CHAT_ID")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Nicosia")
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

# ---------- Загрузка словарей ----------
BASE_DIR = Path(__file__).parent

# Случайный словарь (для /words и fallback)
with open(BASE_DIR / "words.json", "r", encoding="utf-8") as f:
    RANDOM_WORDS = json.load(f)

# Тематический словарь
with open(BASE_DIR / "words_by_theme.json", "r", encoding="utf-8") as f:
    THEMES = json.load(f)

# Маппинг weekday (0=Пн, 6=Вс) -> ключ темы
WEEKDAY_TO_THEME = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}

logger.info(f"Загружено {len(RANDOM_WORDS)} случайных слов и {len(THEMES)} тем")

# ---------- Бот ----------
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


def get_theme_for_today():
    """Возвращает тему дня по текущему дню недели в кипрском TZ."""
    try:
        now = datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        now = datetime.now()
    weekday = now.weekday()  # 0 = Monday
    theme_key = WEEKDAY_TO_THEME.get(weekday)
    return THEMES.get(theme_key) if theme_key else None


def format_words_message(words: list, theme=None) -> str:
    """Форматирует сообщение со словами. Если передана тема — показывает её в шапке."""
    today = datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y")
    
    if theme:
        header = (
            f"🇬🇷 <b>Греческие слова дня</b> · {today}\n"
            f"{theme['emoji']} <b>Тема: {theme['title']}</b>\n\n"
        )
    else:
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
    """Выбирает n случайных слов из общего словаря."""
    return random.sample(RANDOM_WORDS, min(n, len(RANDOM_WORDS)))


def pick_theme_words():
    """Возвращает (слова, тема) для текущего дня недели.
    Берёт WORDS_PER_DAY случайных слов из темы — так каждую неделю
    в одной и той же теме выпадают разные слова.
    Если темы нет или в ней слов меньше нужного — добирает из общего словаря."""
    theme = get_theme_for_today()
    if theme and theme.get("words"):
        theme_words = list(theme["words"])
        # Случайная подборка из темы (а не первые N)
        if len(theme_words) >= WORDS_PER_DAY:
            words = random.sample(theme_words, WORDS_PER_DAY)
        else:
            # В теме мало слов — берём всё что есть + добираем случайными
            words = list(theme_words)
            extra = pick_random_words(WORDS_PER_DAY - len(words))
            words.extend(extra)
        return words, theme
    # Fallback на случайные
    return pick_random_words(WORDS_PER_DAY), None


async def send_daily_words():
    """Отправляет ежедневные слова в чат (тематические по дню недели)."""
    if not CHAT_ID:
        logger.warning("CHAT_ID не задан — пропускаю рассылку")
        return
    
    try:
        words, theme = pick_theme_words()
        text = format_words_message(words, theme)
        await bot.send_message(chat_id=CHAT_ID, text=text)
        theme_name = theme["title"] if theme else "случайные"
        logger.info(f"Отправлено {len(words)} слов ({theme_name}) в чат {CHAT_ID}")
    except Exception as e:
        logger.error(f"Ошибка при отправке: {e}")


# ---------- Команды ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    themes_list = "\n".join(
        f"  {t['emoji']} {key.capitalize()} — {t['title']}"
        for key, t in THEMES.items()
    )
    await message.answer(
        "🇬🇷 <b>Καλώς ήρθες!</b>\n\n"
        f"Каждый день в <b>{SEND_HOUR:02d}:{SEND_MINUTE:02d}</b> (Кипр) "
        f"я присылаю <b>{WORDS_PER_DAY} слов</b> по теме дня:\n\n"
        f"{themes_list}\n\n"
        "Команды:\n"
        "/words — 10 случайных слов\n"
        "/today — слова сегодняшней темы\n"
        "/chatid — ID чата\n"
        "/about — о боте"
    )


@dp.message(Command("words"))
async def cmd_words(message: Message):
    """Случайная подборка (вне темы дня)."""
    words = pick_random_words(WORDS_PER_DAY)
    text = format_words_message(words, theme=None)
    await message.answer(text)


@dp.message(Command("today"))
async def cmd_today(message: Message):
    """Слова сегодняшней темы."""
    words, theme = pick_theme_words()
    text = format_words_message(words, theme)
    await message.answer(text)


@dp.message(Command("chatid"))
async def cmd_chatid(message: Message):
    await message.answer(
        f"<b>Chat ID этого чата:</b>\n<code>{message.chat.id}</code>\n\n"
        f"Тип: {message.chat.type}"
    )


@dp.message(Command("about"))
async def cmd_about(message: Message):
    total_themed = sum(len(t["words"]) for t in THEMES.values())
    await message.answer(
        "🇬🇷 <b>Greek Words Bot</b>\n\n"
        f"Случайный словарь: <b>{len(RANDOM_WORDS)} слов</b>\n"
        f"Тематический: <b>{total_themed} слов</b> в {len(THEMES)} темах\n"
        f"Рассылка: ежедневно в {SEND_HOUR:02d}:{SEND_MINUTE:02d} ({TIMEZONE})\n\n"
        "В 10:00 — слова по теме дня недели.\n"
        "/words — случайная подборка в любой момент.\n"
        "/today — тема сегодняшнего дня."
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
