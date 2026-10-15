from aiogram import Router
from aiogram.types import Message

from app.bot.i18n import t, user_language_storage
from app.bot.keyboards.main_menu import get_main_menu_keyboard

router = Router(name="common_router")


@router.message()
async def handle_unhandled_message(message: Message) -> None:
    """
    Обработчик нераспознанных сообщений вне состояний.
    Направляет пользователя в главное меню.
    """
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    await message.answer(
        t("main_menu_prompt", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )
