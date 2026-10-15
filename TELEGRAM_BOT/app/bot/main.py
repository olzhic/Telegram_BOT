import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.config import bot_settings
from app.bot.handlers import common, menu, questions, sources, start
from app.bot.services.api_client import api_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("adal_bot")


def build_dispatcher() -> Dispatcher:
    """Создание и конфигурирование Dispatcher бота."""
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутеров в строгом порядке
    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(questions.router)
    dp.include_router(sources.router)
    dp.include_router(common.router)

    return dp


async def main() -> None:
    """Точка входа запуска Telegram-бота."""
    token = bot_settings.TELEGRAM_BOT_TOKEN.strip()
    if not token or token == "your_telegram_bot_token_here":
        logger.error(
            "ОШИБКА: TELEGRAM_BOT_TOKEN не задан! "
            "Пожалуйста, укажите токен вашего бота в файле .env (переменная TELEGRAM_BOT_TOKEN). "
            "Получить токен можно у @BotFather в Telegram."
        )
        sys.exit(1)

    bot = Bot(token=token)
    dp = build_dispatcher()

    logger.info("Проверка доступности FastAPI backend по адресу %s...", bot_settings.API_BASE_URL)
    is_api_alive = await api_client.check_health()
    if is_api_alive:
        logger.info("FastAPI backend доступен и готов к обработке запросов.")
    else:
        logger.warning(
            "FastAPI backend в данный момент недоступен (%s). "
            "Бот запустится, но ответы будут возвращать ошибку связи, пока backend не поднят.",
            bot_settings.API_BASE_URL,
        )

    try:
        logger.info("Запуск Telegram-бота Adal Navigator в режиме polling...")
        # Удаляем вебхуки перед поллингом
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        logger.info("Остановка бота и закрытие ресурсов...")
        await api_client.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Telegram-бот остановлен.")
