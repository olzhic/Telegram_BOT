from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.bot.i18n import t


def get_answer_actions_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Инлайн-кнопки дальнейших действий после получения ответа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_inline_sources", lang),
                    callback_data="action:sources",
                ),
                InlineKeyboardButton(
                    text=t("btn_inline_ask_new", lang),
                    callback_data="action:ask_new",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_inline_main_menu", lang),
                    callback_data="action:main_menu",
                )
            ],
        ]
    )
