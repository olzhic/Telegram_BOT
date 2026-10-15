from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.i18n import t, user_language_storage
from app.bot.keyboards.main_menu import get_main_menu_keyboard

router = Router(name="menu_router")


@router.message(Command("menu"), StateFilter("*"))
async def handle_menu_command(message: Message, state: FSMContext) -> None:
    """Обработчик команды /menu: открывает главное меню."""
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    await message.answer(
        t("main_menu_prompt", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )


@router.callback_query(F.data == "action:main_menu", StateFilter("*"))
async def handle_action_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик инлайн-кнопки перехода в главное меню."""
    await state.clear()
    await callback.answer()
    user_id = callback.from_user.id
    lang = user_language_storage.get(user_id)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            t("main_menu_prompt", lang),
            reply_markup=get_main_menu_keyboard(lang),
        )


@router.message(Command("help"), StateFilter("*"))
async def handle_help_command(message: Message, state: FSMContext) -> None:
    """Обработчик команды /help: показывает справочную информацию."""
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    await message.answer(
        t("help_text", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )


@router.message(
    F.text.in_({t("btn_examples", "ru"), t("btn_examples", "kk")}),
    StateFilter("*"),
)
async def handle_examples_button(message: Message, state: FSMContext) -> None:
    """Обработчик кнопки «Примеры вопросов»."""
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    await message.answer(
        t("examples_text", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )


@router.message(
    F.text.in_({t("btn_about", "ru"), t("btn_about", "kk")}),
    StateFilter("*"),
)
async def handle_about_button(message: Message, state: FSMContext) -> None:
    """Обработчик кнопки «О проекте»."""
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    await message.answer(
        t("about_text", lang),
        reply_markup=get_main_menu_keyboard(lang),
    )
