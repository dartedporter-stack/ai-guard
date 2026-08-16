import os
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import (
    TELEGRAM_TOKEN,
    MAX_MESSAGE_LENGTH,
    validate_all_config,
)

from guard.service import analyze_and_format
from voice.telegram_voice import transcribe_audio_file


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🛡️ AI GUARD активирован!\n\n"

        "Отправьте:\n"
        "• текст;\n"
        "• голосовое сообщение.\n\n"

        "Я проанализирую риск мошенничества."
    )


# ============================================================
# TEXT
# ============================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    text = update.message.text

    if not text:
        return

    text = text.strip()

    if not text:
        return

    if len(text) > MAX_MESSAGE_LENGTH:

        await update.message.reply_text(
            "⚠️ Сообщение слишком длинное.\n"
            f"Максимум — {MAX_MESSAGE_LENGTH} символов."
        )

        return

    try:

        result = await __import__(
            "asyncio"
        ).to_thread(
            analyze_and_format,
            text,
            False,
        )

        await update.message.reply_text(
            result,
            parse_mode="Markdown",
        )

    except Exception as exc:

        print(
            "⚠️ Ошибка анализа текста:",
            repr(exc),
        )

        await update.message.reply_text(
            "⚠️ Не удалось выполнить анализ.\n"
            "Попробуйте ещё раз."
        )


# ============================================================
# VOICE
# ============================================================

async def handle_voice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    if not update.message.voice:
        return

    try:

        await update.message.reply_text(
            "🎙️ Голосовое получено.\n"
            "🧠 Расшифровываю и анализирую..."
        )

        voice = update.message.voice

        telegram_file = await context.bot.get_file(
            voice.file_id
        )

        with tempfile.NamedTemporaryFile(
            suffix=".ogg",
            delete=False,
        ) as temp_file:

            temp_path = temp_file.name

        try:

            await telegram_file.download_to_drive(
                custom_path=temp_path
            )

            # Gemini 3.1 Flash-Lite умеет напрямую
            # транскрибировать аудиофайлы.
            transcript = await __import__(
                "asyncio"
            ).to_thread(
                transcribe_audio_file,
                temp_path,
            )

            print(
                "🎙️ TRANSCRIPT:",
                transcript,
            )

            result = await __import__(
                "asyncio"
            ).to_thread(
                analyze_and_format,
                transcript,
                False,
            )

            final_message = (
                "🎙️ *ТРАНСКРИПЦИЯ:*\n"
                f"{transcript}\n\n"
                f"{result}"
            )

            await update.message.reply_text(
                final_message,
                parse_mode="Markdown",
            )

        finally:

            Path(temp_path).unlink(
                missing_ok=True
            )

    except Exception as exc:

        print(
            "⚠️ Ошибка голосового:",
            repr(exc),
        )

        await update.message.reply_text(
            "⚠️ Не удалось обработать голосовое.\n"
            "Попробуйте отправить его ещё раз."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    validate_all_config()

    app = (
        Application
        .builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    # Text
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    # Telegram Voice
    app.add_handler(
        MessageHandler(
            filters.VOICE,
            handle_voice,
        )
    )

    print(
        "🛡️ AI GUARD CLEAN ARCHITECTURE запущен!"
    )

    app.run_polling()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()