from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from app.bot.i18n import t


def get_main_menu_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    """Главное меню бота с кнопками в соответствии с выбранным языком."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t("btn_ask_question", lang)),
                KeyboardButton(text=t("btn_examples", lang)),
            ],
            [
                KeyboardButton(text=t("btn_sources", lang)),
                KeyboardButton(text=t("btn_about", lang)),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
