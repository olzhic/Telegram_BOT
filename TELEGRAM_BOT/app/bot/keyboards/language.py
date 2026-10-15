from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_language_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура выбора языка."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="lang:kk"),
            ]
        ]
    )
