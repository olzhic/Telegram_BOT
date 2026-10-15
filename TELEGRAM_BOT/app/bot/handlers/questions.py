import logging
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.i18n import t, user_language_storage
from app.bot.keyboards.answer import get_answer_actions_keyboard
from app.bot.services.api_client import api_client
from app.bot.states import QuestionState

logger = logging.getLogger(__name__)

router = Router(name="questions_router")

MAX_QUESTION_LENGTH = 1000
MAX_TELEGRAM_MESSAGE_LENGTH = 4000


def split_text_into_chunks(text: str, max_chunk_size: int = MAX_TELEGRAM_MESSAGE_LENGTH) -> list[str]:
    """Разбивает длинный текст на части, не превышающие лимит Telegram."""
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    current_chunk = []
    current_length = 0

    lines = text.split("\n")
    for line in lines:
        if current_length + len(line) + 1 > max_chunk_size:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_length = 0

            # Если даже одна строка длиннее лимита
            while len(line) > max_chunk_size:
                chunks.append(line[:max_chunk_size])
                line = line[max_chunk_size:]

        current_chunk.append(line)
        current_length += len(line) + 1

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


def format_answer_response(response_data: dict, lang: str) -> str:
    """
    Форматирует структурированный ответ от API backend в текст для пользователя.
    Обрабатывает статусы: answered, insufficient_evidence, not_configured, timeout, error.
    """
    status = response_data.get("status")

    if status == "answered":
        answer_text = response_data.get("answer", "").strip()
        sources = response_data.get("sources", [])

        if sources:
            sources_header = t("used_sources_header", lang)
            sources_lines = []
            for idx, src in enumerate(sources, start=1):
                title = src.get("title") or f"Источник {idx}"
                section = src.get("section")
                url = src.get("url")

                src_desc = title
                if section:
                    src_desc += f" ({section})"
                if url:
                    src_desc += f"\n   🔗 {url}"

                sources_lines.append(f"{idx}. {src_desc}")

            sources_block = "\n".join(sources_lines)
            return f"{answer_text}\n\n{sources_header}\n{sources_block}"
        return answer_text

    elif status == "insufficient_evidence":
        custom_answer = response_data.get("answer")
        return custom_answer if custom_answer else t("insufficient_evidence", lang)

    elif status == "not_configured":
        custom_answer = response_data.get("answer")
        return custom_answer if custom_answer else t("not_configured", lang)

    elif status == "timeout":
        return t("api_timeout", lang)

    else:
        # status == "error" or "connection_error" or unknown
        return t("api_error", lang)


@router.message(
    F.text.in_({t("btn_ask_question", "ru"), t("btn_ask_question", "kk")}),
    StateFilter("*"),
)
async def handle_ask_button(message: Message, state: FSMContext) -> None:
    """Обработчик кнопки «Задать вопрос»."""
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    await state.set_state(QuestionState.waiting_for_question)
    await message.answer(t("ask_prompt", lang))


@router.callback_query(F.data == "action:ask_new", StateFilter("*"))
async def handle_action_ask_new(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик инлайн-кнопки «Задать новый вопрос»."""
    await callback.answer()
    user_id = callback.from_user.id
    lang = user_language_storage.get(user_id)
    await state.set_state(QuestionState.waiting_for_question)
    if isinstance(callback.message, Message):
        await callback.message.answer(t("ask_prompt", lang))


@router.message(QuestionState.waiting_for_question, F.text)
async def handle_user_question(message: Message, state: FSMContext) -> None:
    """
    Обработчик текстового вопроса пользователя в состоянии ожидания.
    1. Валидация входных данных.
    2. Отправка статуса «Обрабатываю вопрос…».
    3. Запрос к FastAPI backend.
    4. Отображение ответа и инлайн-кнопок.
    """
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    raw_text = message.text or ""
    clean_question = raw_text.strip()

    # Валидация пустоты
    if not clean_question:
        await message.answer(t("empty_question_error", lang))
        return

    # Валидация длины
    if len(clean_question) > MAX_QUESTION_LENGTH:
        await message.answer(t("too_long_question_error", lang))
        return

    # Сообщение об обработке
    processing_msg = await message.answer(t("processing", lang))

    # Запрос в backend
    try:
        response_data = await api_client.ask_question(
            question=clean_question,
            language=lang,
        )
    except Exception as exc:
        logger.exception("Unexpected error in bot question handler: %s", exc)
        response_data = {"status": "error"}

    # Удаляем или обновляем сообщение об обработке
    try:
        await processing_msg.delete()
    except Exception:
        pass

    formatted_text = format_answer_response(response_data, lang)
    chunks = split_text_into_chunks(formatted_text)

    # Отправляем части сообщения. К последней части прикрепляем инлайн-кнопки
    for idx, chunk in enumerate(chunks):
        if idx == len(chunks) - 1:
            await message.answer(
                chunk,
                reply_markup=get_answer_actions_keyboard(lang),
            )
        else:
            await message.answer(chunk)

    # Сбрасываем FSM состояние (вопрос обработан)
    await state.clear()


@router.message(QuestionState.waiting_for_question)
async def handle_unsupported_question_type(message: Message, state: FSMContext) -> None:
    """Обработка нетекстовых сообщений (голосовые, стикеры, картинки) в режиме вопроса."""
    user_id = message.from_user.id if message.from_user else 0
    lang = user_language_storage.get(user_id)
    await message.answer(t("unsupported_content_error", lang))
