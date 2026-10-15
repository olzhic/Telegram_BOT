import httpx
import pytest
from app.api.main import app


@pytest.mark.asyncio
async def test_health_check_returns_ok() -> None:
    """1. GET /health возвращает успешный статус ok и имя сервиса."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload == {"status": "ok", "service": "adal-navigator-api"}
