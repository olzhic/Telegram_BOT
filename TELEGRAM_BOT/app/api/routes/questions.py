import logging
from fastapi import APIRouter, HTTPException, status
from app.api.schemas import AskRequest, AskResponse
from app.api.services.ai_provider import get_ai_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Questions"])


@router.post(
    "/ask",
    response_model=AskResponse,
    status_code=status.HTTP_200_OK,
    summary="Задать вопрос AI/RAG системе",
    description=(
        "Основной endpoint для отправки вопросов. "
        "Делегирует обработку текущему AI-провайдеру (RAG/LLM). "
        "Если AI-провайдер ещё не зарегистрирован, возвращает статус 'not_configured'."
    ),
)
async def ask_question(payload: AskRequest) -> AskResponse:
    provider = get_ai_provider()
    try:
        response = await provider.answer_question(
            question=payload.question,
            language=payload.language,
        )
        return response
    except Exception as exc:
        logger.exception("Ошибка при обработке вопроса в AI-провайдере: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка при обработке вопроса.",
        ) from exc
