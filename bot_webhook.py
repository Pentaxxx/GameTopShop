import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import BOT_TOKEN
from bot import router  # переиспользуем всю логику из bot.py, ничего там не дублируем

logging.basicConfig(level=logging.INFO)

WEBHOOK_PATH = "/webhook"
# После первого деплоя Render даст домен вида https://имя-сервиса.onrender.com —
# впиши его в переменную окружения WEBHOOK_URL на Render (шаг 5 ниже).
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")


async def on_startup(bot: Bot):
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)
    else:
        logging.warning("WEBHOOK_URL не задан — вебхук не установлен!")


def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    # Render сам подставляет порт через переменную PORT — обязательно слушать именно его
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
