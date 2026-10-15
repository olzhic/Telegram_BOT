from fastapi import APIRouter
from app.api.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Проверка состояния сервиса")
async def health_check() -> HealthResponse:
    """
    Проверяет доступность и работоспособность API backend.
    Не зависит от состояния AI-модуля.
    """
    return HealthResponse(status="ok", service="adal-navigator-api")
