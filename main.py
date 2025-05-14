#!/usr/bin/env python3
"""
tts_bot.py — приватний Telegram-бот (тільки для OWNER_ID):
   текст або forward → OpenAI TTS → MP3-аудіо (webhook, Render-friendly).
"""
import os, asyncio, logging
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from telegram.ext import (
    ApplicationBuilder, MessageHandler, ContextTypes, filters
)
from telegram.ext.filters import MessageFilter

# ─── 1. ENV та логування ─────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_KEY  = os.environ["OPENAI_API_KEY"]
OWNER_ID    = int(os.environ["OWNER_ID"])
def detect_public_url() -> str:
    manual = os.getenv("PUBLIC_URL")                  # якщо ви задали вручну
    if manual:
        return manual.rstrip("/")
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")  # дає Render автоматично
    if hostname:                                      # → mybot.onrender.com
        return f"https://{hostname}"
    raise RuntimeError(
        "Не задано PUBLIC_URL і нема RENDER_EXTERNAL_HOSTNAME; "
        "для локального запуску використайте --webhook-url."
    )

PUBLIC_URL = detect_public_url()
PORT       = int(os.getenv("PORT", "10000"))          # не змінюємо

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s | %(name)s: %(message)s")
log = logging.getLogger("tts-bot")

client = OpenAI(api_key=OPENAI_KEY)

# ─── 2. TTS (синхронно, у фон-треді) ──────────────────────────────────────────
def tts(text: str, out: Path):
    with client.audio.speech.with_streaming_response.create(
        model="tts-1", voice="alloy", input=text, response_format="mp3"
    ) as r:
        r.stream_to_file(out)

# ─── 3. Кастомний фільтр (text OR caption) ───────────────────────────────────
class TextOrCaption(MessageFilter):
    def filter(self, msg) -> bool:     # type: ignore[override]
        return bool((msg.text and not msg.text.startswith("/")) or msg.caption)
TEXT_OR_CAPTION = TextOrCaption()

# ─── 4. Хендлер повідомлень ──────────────────────────────────────────────────
async def handle(update, ctx: ContextTypes.DEFAULT_TYPE):
    # if update.effective_user.id != OWNER_ID:
        # return                        # ігноруємо всіх, крім власника

    msg  = update.effective_message
    text = msg.text or msg.caption
    if not text:
        return

    note = await msg.reply_text("✅ Отримав! Озвучую…")
    mp3  = Path("speech.mp3")
    try:
        await asyncio.to_thread(tts, text, mp3)
        await msg.reply_audio(audio=mp3.open("rb"))
    finally:
        mp3.unlink(missing_ok=True)
        await note.delete()

# ─── 5. Error-handler (щоб лог був чистим) ───────────────────────────────────
async def on_error(update, ctx):
    log.error("Exception:", exc_info=ctx.error)
    if update and update.effective_chat and update.effective_user.id == OWNER_ID:
        await ctx.bot.send_message(update.effective_chat.id,
                                   "⚠️ Сталася помилка, спробуйте ще раз.")

# ─── 6. Запуск як webhook (TLS дає Render) ───────────────────────────────────
def main():
    app = (ApplicationBuilder()
           .token(BOT_TOKEN)
           .concurrent_updates(True)
           .build())

    app.add_handler(MessageHandler(TEXT_OR_CAPTION, handle))
    app.add_error_handler(on_error)

    # PTB сам реєструє /setWebhook, якщо передати webhook_url
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{PUBLIC_URL}/webhook",
        allowed_updates=["message"],
    )

if __name__ == "__main__":
    main()
