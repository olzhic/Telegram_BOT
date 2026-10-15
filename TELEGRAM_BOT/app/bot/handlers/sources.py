import logging
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.i18n import t, user_language_storage
from app.bot.keyboards.main_menu import get_main_menu_keyboard
from app.bot.services.api_client import api_client

logger = logging.getLogger(__name__)

router = Router(name="sources_router")


async def render_sources_response(user_id: int, responder: Message | CallbackQuery) -> None:
    """Общая функция запроса источников в API и вывода результата пользователю."""
    lang = user_language_storage.get(user_id)
    try:
        data = await api_client.get_sources()
        items = data.get("items", [])
        status = data.get("status")

        if status == "timeout":
            text = t("api_timeout", lang)
        elif status in ("error", "connection_error"):
            text = t("api_error", lang)
        elif not items:
            text = t("no_sources", lang)
        else:
            header = t("sources_header", lang)
            lines = []
            for idx, item in enumerate(items, start=1):
                title = item.get("title", f"Источник #{idx}")
                url = item.get("url")
                if url:
                    lines.append(f"{idx}. {title}\n   🔗 {url}")
                else:
                    lines.append(f"{idx}. {title}")
            text = f"{header}\n\n" + "\n\n".join(lines)
    except Exception as exc:
        logger.exception("Error while rendering sources: %s", exc)
        text = t("api_error", lang)

    if isinstance(responder, Message):
        await responder.answer(text, reply_markup=get_main_menu_keyboard(lang))
    elif isinstance(responder, CallbackQuery):
        await responder.answer()
        if isinstance(responder.message, Message):
            await responder.message.answer(text, reply_markup=get_main_menu_keyboard(lang))


@router.message(Command("sources"), StateFilter("*"))
async def handle_sources_command(message: Message, state: FSMContext) -> None:
    """Обработчик команды /sources."""
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
    await render_sources_response(user_id, message)


@router.message(
    F.text.in_({t("btn_sources", "ru"), t("btn_sources", "kk")}),
    StateFilter("*"),
)
async def handle_sources_button(message: Message, state: FSMContext) -> None:
    """Обработчик кнопки «Источники» из главного меню."""
    await state.clear()
    user_id = message.from_user.id if message.from_user else 0
    await render_sources_response(user_id, message)


@router.callback_query(F.data == "action:sources", StateFilter("*"))
async def handle_action_sources(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик инлайн-кнопки «Источники»."""
    await state.clear()
    user_id = callback.from_user.id
    await render_sources_response(user_id, callback)
