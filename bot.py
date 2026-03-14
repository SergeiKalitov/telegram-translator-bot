#!/usr/bin/env python3
"""
Telegram bot for translating text between English and Russian
"""

import io
import logging
import tempfile
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from deep_translator import GoogleTranslator
import edge_tts
import asyncio
from langdetect import detect, LangDetectException
import os
from pydub import AudioSegment
import speech_recognition as sr
from telegram.ext import PicklePersistence
from dotenv import load_dotenv

# Voice options: 0 = female, 1 = male
VOICES = {
    "en": {
        0: "en-US-AvaNeural",      # female
        1: "en-US-AndrewNeural",   # male
    },
    "ru": {
        0: "ru-RU-SvetlanaNeural",  # female
        1: "ru-RU-DmitryNeural",    # male
    },
}

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _is_russian(text: str) -> bool:
    """Check if text is primarily Russian (Cyrillic)."""
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    return cyrillic > len(text) * 0.3


def translate_text(text: str) -> tuple[str, str]:
    """
    Translate text: Russian → English, other languages → Russian.
    Returns (translated_text, target_lang) where target_lang is 'ru' or 'en'.
    """
    if _is_russian(text):
        lang = "ru"
    else:
        try:
            lang = detect(text)
        except LangDetectException:
            lang = "en"

    if lang == "ru":
        translator = GoogleTranslator(source="ru", target="en")
        return translator.translate(text), "en"
    else:
        translator = GoogleTranslator(source="auto", target="ru")
        return translator.translate(text), "ru"


def speech_to_text(voice_bytes: bytes) -> str:
    """Convert voice (OGG) to text. Supports English and Russian."""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as ogg_tmp:
        ogg_tmp.write(voice_bytes)
        ogg_path = ogg_tmp.name
    try:
        audio = AudioSegment.from_file(ogg_path, format="ogg")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_tmp:
            wav_path = wav_tmp.name
        try:
            audio.export(wav_path, format="wav")
            r = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                recorded = r.record(source)
            try:
                text = r.recognize_google(recorded, language="ru-RU")
            except sr.UnknownValueError:
                try:
                    text = r.recognize_google(recorded, language="en-US")
                except sr.UnknownValueError:
                    raise ValueError("Speech not recognized")
            return text
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
    finally:
        try:
            os.unlink(ogg_path)
        except OSError:
            pass


def _get_voice(lang: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Get voice ID for language from user preference. Default: 0 (female)."""
    key = f"voice_{lang}"
    idx = context.user_data.get(key, 0)
    return VOICES[lang][idx]


async def text_to_speech(text: str, voice_id: str) -> bytes:
    """Generate voice from text using edge-tts. voice_id e.g. 'en-US-AvaNeural'."""
    communicate = edge_tts.Communicate(text, voice_id)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    await communicate.save(tmp_path)
    try:
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /start command"""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi, {user.mention_html()}! 👋\n\n"
        "I'm a translation bot. Available commands:\n"
        "/start - Show this message\n"
        "/help - Help\n"
        "/info - Bot information\n"
        "/voice - Choose voice (male/female)\n"
        "/echo <text> - Repeat text\n\n"
        "Send text or voice in English or Russian: I translate EN↔RU."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /help command"""
    await update.message.reply_text(
        "Bot commands:\n\n"
        "/start - Start the bot\n"
        "/help - Show help\n"
        "/info - Bot information (translation)\n"
        "/voice [en|ru] [0|1] - Set voice: 0=female, 1=male\n"
        "/echo <text> - Echo your message\n\n"
        "Send text or voice in English or Russian for translation (EN↔RU)."
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /info command"""
    await update.message.reply_text(
        "ℹ️ Bot information\n\n"
        "I translate between English and Russian (text and voice). "
        "English ↔ Russian."
    )


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /voice - set or show voice preference."""
    args = context.args or []
    en_cur = context.user_data.get("voice_en", 0)
    ru_cur = context.user_data.get("voice_ru", 0)
    if not args:
        await update.message.reply_text(
            f"Current voice:\n"
            f"English: {'female' if en_cur == 0 else 'male'}\n"
            f"Russian: {'female' if ru_cur == 0 else 'male'}\n\n"
            f"Change: /voice en 0 | /voice en 1 | /voice ru 0 | /voice ru 1\n"
            f"0 = female, 1 = male"
        )
        return
    if len(args) >= 2 and args[0] in ("en", "ru") and args[1] in ("0", "1"):
        lang, idx = args[0], int(args[1])
        context.user_data[f"voice_{lang}"] = idx
        label = "female" if idx == 0 else "male"
        await update.message.reply_text(f"Voice for {lang.upper()} set to {label}.")
    else:
        await update.message.reply_text(
            "Usage: /voice en 0 | /voice en 1 | /voice ru 0 | /voice ru 1\n"
            "0 = female, 1 = male"
        )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /echo command"""
    text = " ".join(context.args) if context.args else "No text provided"
    await update.message.reply_text(text)


async def _send_translation(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Translate text and send result (text + audio). Shared by text and voice handlers."""
    translated, target_lang = await asyncio.to_thread(translate_text, text)
    await update.message.reply_text(translated)
    voice_id = _get_voice(target_lang, context)
    voice_bytes = await text_to_speech(translated, voice_id)
    await update.message.reply_audio(audio=io.BytesIO(voice_bytes), title="Translation")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for voice messages - transcribe, translate, send text + audio"""
    try:
        voice = update.message.voice
        tg_file = await context.bot.get_file(voice.file_id)
        voice_bytes = await tg_file.download_as_bytearray()
        text = await asyncio.to_thread(speech_to_text, bytes(voice_bytes))
        if not text.strip():
            await update.message.reply_text("Could not recognize speech. Please try again.")
            return
        await _send_translation(update, context, text)
    except Exception as e:
        if "recognition could not understand" in str(e).lower() or "unknown value" in str(e).lower():
            await update.message.reply_text("Could not recognize speech. Try speaking more clearly.")
        else:
            logger.exception("Voice processing failed")
            await update.message.reply_text("Sorry, voice processing failed. Please try again.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for text messages - translates EN↔RU and sends voice"""
    text = update.message.text
    try:
        await _send_translation(update, context, text)
    except Exception:
        logger.exception("Translation failed")
        await update.message.reply_text("Sorry, translation failed. Please try again.")


def main() -> None:
    """Run the bot"""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: Set the TELEGRAM_BOT_TOKEN environment variable")
        print("Get a token: https://t.me/BotFather")
        return

    persistence = PicklePersistence(filepath="bot_data.pickle")
    application = Application.builder().token(token).persistence(persistence).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("voice", voice_command))
    application.add_handler(CommandHandler("echo", echo))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
