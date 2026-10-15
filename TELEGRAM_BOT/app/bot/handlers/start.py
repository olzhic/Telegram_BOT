from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.i18n import t, user_language_storage
from app.bot.keyboards.language import get_language_keyboard
from app.bot.keyboards.main_menu import get_main_menu_keyboard

router = Router(name="start_router")


@router.message(CommandStart(), StateFilter("*"))
async def handle_start(message: Message, state: FSMContext) -> None:
    """
    Обработчик команды /start.
    Сбрасывает текущее состояние, показывает приветствие и предлагает выбор языка.
    """
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
    current_lang = user_language_storage.get(user_id)

    # Приветствие
    welcome_text = t("welcome", current_lang)
    choose_lang_text = t("choose_language", current_lang)

    full_text = f"{welcome_text}\n\n{choose_lang_text}"
    await message.answer(full_text, reply_markup=get_language_keyboard())


@router.message(Command("language"), StateFilter("*"))
async def handle_language_command(message: Message, state: FSMContext) -> None:
    """
    Обработчик команды /language для смены языка в любой момент.
    """
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    await message.answer(
        t("choose_language", lang),
        reply_markup=get_language_keyboard(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def handle_language_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик выбора языка через инлайн-кнопку.
    Сохраняет язык для пользователя и открывает главное меню.
    """
    if not callback.data or not callback.message:
        await callback.answer()
        return

    new_lang = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    user_language_storage.set(user_id, new_lang)

    await state.clear()
    await callback.answer()

    # Сообщение о подтверждении смены языка
    confirmation_text = t("language_selected", new_lang)
    menu_prompt = t("main_menu_prompt", new_lang)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"{confirmation_text}")
        await callback.message.answer(
            menu_prompt,
            reply_markup=get_main_menu_keyboard(new_lang),
        )
