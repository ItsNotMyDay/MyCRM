import os
import asyncio

import django
from django.conf import settings

# Указываем Django, где искать настройки
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mycrm.settings")
django.setup()

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[TEST] /start update:", update.to_dict())
    if update.message:
        await update.message.reply_text("Тестовый бот запущен, вижу ваши сообщения.")


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[TEST] message update:", update.to_dict())
    if update.message:
        await update.message.reply_text(f"Вы написали: {update.message.text}")


async def main():
    # создаём event loop по умолчанию, если ещё нет
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("TELEGRAM_BOT_TOKEN не задан")
        return

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    print("=== Удаляю старый webhook, если был ===")
    await app.bot.delete_webhook(drop_pending_updates=True)

    print("=== Тестовый бот: run_polling() ===")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    asyncio.run(main())