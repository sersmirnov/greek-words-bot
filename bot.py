"""
Greek Words Bot — обучающий бот для группы изучающих греческий на Кипре.

Логика:
- Каждый день в 10:00 присылает следующий урок из 30 (старт: COURSE_START_DATE).
- После урока 30 переключается на тематические слова по дням недели.
- Команды: /lesson, /lesson N, /today, /words, /chatid, /about.
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, date
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

# ---------- Настройки ----------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Nicosia")
SEND_HOUR = int(os.getenv("SEND_HOUR", "10"))
SEND_MINUTE = int(os.getenv("SEND_MINUTE", "0"))
WORDS_PER_DAY = int(os.getenv("WORDS_PER_DAY", "10"))

# Дата старта курса (когда придёт урок 1). По умолчанию 17 мая 2026.
COURSE_START_DATE = os.getenv("COURSE_START_DATE", "2026-05-17")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------- Загрузка данных ----------
BASE_DIR = Path(__file__).parent

with open(BASE_DIR / "words.json", "r", encoding="utf-8") as f:
    RANDOM_WORDS = json.load(f)

with open(BASE_DIR / "words_by_theme.json", "r", encoding="utf-8") as f:
    THEMES = json.load(f)

with open(BASE_DIR / "lessons.json", "r", encoding="utf-8") as f:
    LESSONS = json.load(f)["lessons"]

WEEKDAY_TO_THEME = {
    0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday",
    4: "friday", 5: "saturday", 6: "sunday",
}

try:
    COURSE_START = date.fromisoformat(COURSE_START_DATE)
except ValueError:
    logger.error(f"Неверный формат COURSE_START_DATE: {COURSE_START_DATE}")
    COURSE_START = date(2026, 5, 17)

logger.info(
    f"Загружено: {len(RANDOM_WORDS)} случ.слов, {len(THEMES)} тем, "
    f"{len(LESSONS)} уроков. Старт курса: {COURSE_START}"
)

# ---------- Бот ----------
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


def now_local() -> datetime:
    try:
        return datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        return datetime.now()


def get_lesson_number_for_today():
    """Номер урока на сегодня (1..30) или None."""
    today = now_local().date()
    days_passed = (today - COURSE_START).days
    if days_passed < 0:
        return None
    lesson_num = days_passed + 1
    if lesson_num > len(LESSONS):
        return None
    return lesson_num


def find_lesson(num: int):
    for lesson in LESSONS:
        if lesson["id"] == num:
            return lesson
    return None


def split_message(text: str, max_len: int = 4000):
    """Разбить длинное сообщение по \\n\\n, чтобы влезло в лимит Telegram (4096)."""
    if len(text) <= max_len:
        return [text]
    parts = []
    current = ""
    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 > max_len:
            if current:
                parts.append(current.strip())
            current = block
        else:
            current += ("\n\n" if current else "") + block
    if current:
        parts.append(current.strip())
    return parts


def format_lesson(lesson: dict):
    """Возвращает список сообщений для отправки (одно или несколько частей)."""
    header = (
        f"🇬🇷 <b>Урок {lesson['id']} · {lesson['emoji']} {lesson['title']}</b>\n"
        f"📚 <i>{lesson['section']}</i>\n\n"
        f"{lesson['intro']}"
    )
    rule = (
        f"\n\n💡 <b>{lesson['rule']['title']}</b>\n"
        f"{lesson['rule']['text']}"
    )
    vocab_parts = ["\n\n🔤 <b>Словарь:</b>"]
    for i, w in enumerate(lesson["vocabulary"], 1):
        vocab_parts.append(
            f"\n<b>{i}. {w['word']}</b> {w['transcription']}\n"
            f"   → {w['translation']}\n"
            f"   <i>{w['example']}</i>"
        )
    vocab = "".join(vocab_parts)
    
    dialogue = ""
    if "dialogue" in lesson:
        d = [f"\n\n💬 <b>{lesson['dialogue']['title']}</b>"]
        for line in lesson["dialogue"]["lines"]:
            d.append(f"\n   {line}")
        dialogue = "".join(d)
    
    watch = f"\n\n⚠️ <b>Обрати внимание:</b>\n{lesson['watch_out']}"
    
    ex = [f"\n\n✏️ <b>Упражнение:</b> {lesson['exercise']['task']}"]
    for item in lesson["exercise"]["items"]:
        ex.append(f"\n• {item}")
    if "answers" in lesson["exercise"]:
        ex.append("\n\n<b>Ответы (нажми, чтобы увидеть):</b>")
        ex.append("\n<tg-spoiler>")
        for ans in lesson["exercise"]["answers"]:
            ex.append(f"\n• {ans}")
        ex.append("</tg-spoiler>")
    exercise = "".join(ex)
    
    tomorrow = f"\n\n➡️ <i>Завтра: {lesson['tomorrow']}</i>"
    
    return split_message(header + rule + vocab + dialogue + watch + exercise + tomorrow)


def get_theme_for_today():
    weekday = now_local().weekday()
    key = WEEKDAY_TO_THEME.get(weekday)
    return THEMES.get(key) if key else None


def pick_random_words(n: int = 10):
    return random.sample(RANDOM_WORDS, min(n, len(RANDOM_WORDS)))


def pick_theme_words():
    theme = get_theme_for_today()
    if theme and theme.get("words"):
        words = theme["words"]
        if len(words) >= WORDS_PER_DAY:
            return random.sample(words, WORDS_PER_DAY), theme
        return list(words) + pick_random_words(WORDS_PER_DAY - len(words)), theme
    return pick_random_words(WORDS_PER_DAY), None


def format_words_message(words: list, theme=None) -> str:
    today = now_local().strftime("%d.%m.%Y")
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
    return header + "\n\n".join(lines) + "\n\n💡 <i>Καλή μάθηση! / Удачной учёбы!</i>"


# ---------- Ежедневная отправка ----------
async def send_daily_content():
    if not CHAT_ID:
        logger.warning("CHAT_ID не задан — пропускаю рассылку")
        return
    
    lesson_num = get_lesson_number_for_today()
    
    if lesson_num is not None:
        lesson = find_lesson(lesson_num)
        if lesson:
            try:
                parts = format_lesson(lesson)
                for part in parts:
                    await bot.send_message(chat_id=CHAT_ID, text=part)
                    await asyncio.sleep(0.5)
                logger.info(f"Отправлен урок {lesson_num} ({len(parts)} сообщений)")
                return
            except Exception as e:
                logger.error(f"Ошибка отправки урока {lesson_num}: {e}")
    
    # Fallback: тематические слова
    try:
        words, theme = pick_theme_words()
        text = format_words_message(words, theme)
        await bot.send_message(chat_id=CHAT_ID, text=text)
        theme_name = theme["title"] if theme else "случайные"
        logger.info(f"Отправлено {len(words)} слов ({theme_name})")
    except Exception as e:
        logger.error(f"Ошибка отправки слов: {e}")


# ---------- Команды ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    today_lesson = get_lesson_number_for_today()
    if today_lesson is None:
        today = now_local().date()
        if today < COURSE_START:
            days = (COURSE_START - today).days
            status = f"📅 Курс стартует через {days} дн. ({COURSE_START.strftime('%d.%m.%Y')})\n"
        else:
            status = "🎓 Курс пройден! Теперь — тематические слова по дням недели.\n"
    else:
        status = f"📚 Сегодняшний урок: <b>№{today_lesson}</b> из {len(LESSONS)}\n"
    
    await message.answer(
        "🇬🇷 <b>Καλώς ήρθες!</b>\n\n"
        "Я — учебный бот по греческому для жизни на Кипре.\n\n"
        f"{status}\n"
        f"Каждый день в <b>{SEND_HOUR:02d}:{SEND_MINUTE:02d}</b> присылаю урок.\n\n"
        "📌 <b>Команды:</b>\n"
        "/lesson — сегодняшний урок\n"
        "/lesson 5 — конкретный урок (1-30)\n"
        "/today — слова темы дня (после 30-го)\n"
        "/words — 10 случайных слов\n"
        "/about — о боте"
    )


@dp.message(Command("lesson"))
async def cmd_lesson(message: Message):
    args = message.text.split(maxsplit=1)
    
    if len(args) > 1:
        try:
            num = int(args[1].strip())
        except ValueError:
            await message.answer("⚠️ Используй: <code>/lesson 5</code> (1-30)")
            return
        if num < 1 or num > len(LESSONS):
            await message.answer(f"⚠️ Урок №{num} не существует. Есть уроки 1-{len(LESSONS)}.")
            return
        lesson = find_lesson(num)
    else:
        num = get_lesson_number_for_today()
        if num is None:
            today = now_local().date()
            if today < COURSE_START:
                days = (COURSE_START - today).days
                await message.answer(
                    f"📅 Курс ещё не начался. Старт через {days} дн. "
                    f"({COURSE_START.strftime('%d.%m.%Y')}).\n\n"
                    f"Хочешь начать раньше? Напиши <code>/lesson 1</code>."
                )
            else:
                await message.answer(
                    f"🎓 Все {len(LESSONS)} уроков пройдены.\n"
                    f"Используй <code>/lesson N</code> для повторения."
                )
            return
        lesson = find_lesson(num)
    
    if not lesson:
        await message.answer("⚠️ Урок не найден.")
        return
    
    parts = format_lesson(lesson)
    for part in parts:
        await message.answer(part)
        await asyncio.sleep(0.3)


@dp.message(Command("today"))
async def cmd_today(message: Message):
    words, theme = pick_theme_words()
    await message.answer(format_words_message(words, theme))


@dp.message(Command("words"))
async def cmd_words(message: Message):
    words = pick_random_words(WORDS_PER_DAY)
    await message.answer(format_words_message(words, theme=None))


@dp.message(Command("chatid"))
async def cmd_chatid(message: Message):
    await message.answer(
        f"<b>Chat ID:</b> <code>{message.chat.id}</code>\n"
        f"Тип: {message.chat.type}"
    )


@dp.message(Command("about"))
async def cmd_about(message: Message):
    today_lesson = get_lesson_number_for_today()
    total_themed = sum(len(t["words"]) for t in THEMES.values())
    
    if today_lesson is None:
        today = now_local().date()
        if today < COURSE_START:
            status = f"Курс стартует {COURSE_START.strftime('%d.%m.%Y')}"
        else:
            status = f"Курс пройден ({len(LESSONS)} уроков)"
    else:
        status = f"Урок дня: <b>{today_lesson}</b> из {len(LESSONS)}"
    
    await message.answer(
        "🇬🇷 <b>Greek Words Bot</b>\n\n"
        f"📚 Уроков в курсе: <b>{len(LESSONS)}</b>\n"
        f"📖 Случайных слов: <b>{len(RANDOM_WORDS)}</b>\n"
        f"🗂 Тематических: <b>{total_themed}</b> в {len(THEMES)} темах\n\n"
        f"⏰ Рассылка: ежедневно в {SEND_HOUR:02d}:{SEND_MINUTE:02d} ({TIMEZONE})\n"
        f"🎯 {status}\n\n"
        "Команды: /lesson, /today, /words"
    )


# ---------- Запуск ----------
async def main():
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_daily_content,
        trigger=CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE),
        id="daily_content",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Планировщик: ежедневно в {SEND_HOUR:02d}:{SEND_MINUTE:02d} ({TIMEZONE})"
    )
    logger.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
