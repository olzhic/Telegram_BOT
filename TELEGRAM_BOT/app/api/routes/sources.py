import logging
from fastapi import APIRouter, HTTPException, status
from app.api.schemas import SourcesResponse
from app.api.services.ai_provider import get_ai_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Sources"])


@router.get(
    "/sources",
    response_model=SourcesResponse,
    status_code=status.HTTP_200_OK,
    summary="Получить список зарегистрированных источников",
    description=(
        "Возвращает перечень нормативно-правовых и справочных источников, "
        "доступных текущей AI/RAG системе. Если источники не подключены, возвращает пустой список."
    ),
)
async def list_sources() -> SourcesResponse:
    provider = get_ai_provider()
    try:
        return await provider.list_sources()
    except Exception as exc:
        logger.exception("Ошибка при получении списка источников: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка при получении списка источников.",
        ) from exc
