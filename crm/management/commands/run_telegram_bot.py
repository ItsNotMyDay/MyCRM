import asyncio

from django.core.management.base import BaseCommand
from django.conf import settings

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

from crm.telegram_handler import handle_telegram_message


class Command(BaseCommand):
    help = "Запускает Telegram-бота (long polling) для приёма сообщений от клиентов"

    def handle(self, *args, **options):
        # Создаём event loop по умолчанию для текущего потока
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        if not bot_token:
            self.stderr.write(self.style.ERROR("TELEGRAM_BOT_TOKEN не указан в settings.py"))
            return

        proxy_url = getattr(settings, "TELEGRAM_PROXY_URL", None)

        if proxy_url:
            self.stdout.write(
                self.style.WARNING(f"Telegram-бот будет использовать SOCKS5-прокси: {proxy_url}")
            )
            request = HTTPXRequest(
                proxy=proxy_url,
                connect_timeout=10.0,
                read_timeout=30.0,
                http_version="1.1",
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "TELEGRAM_PROXY_URL не указан, бот будет пытаться работать без прокси."
                )
            )
            request = HTTPXRequest(
                connect_timeout=10.0,
                read_timeout=30.0,
                http_version="1.1",
            )

        application = (
            ApplicationBuilder()
            .token(bot_token)
            .request(request)
            .build()
        )

        # /start
        async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            print("[Telegram] /start update:", update.to_dict())
            if update.message:
                await update.message.reply_text(
                    "Здравствуйте! Это бот CRM. Ваши сообщения видит менеджер."
                )

        # Текстовые сообщения от клиента
        async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            print("[Telegram] message update:", update.to_dict())
            try:
                handle_telegram_message(update.to_dict())
            except Exception as e:
                print(f"[Telegram] Ошибка обработки сообщения: {e}")

        application.add_handler(CommandHandler("start", start_handler))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
        )

        self.stdout.write(self.style.SUCCESS("Запуск Telegram-бота (long polling)..."))

        # Библиотека сама управляет своим циклом и long polling
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
        )
