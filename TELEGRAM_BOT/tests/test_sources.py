import httpx
import pytest
from app.api.main import app
from app.api.schemas import SourceListItem, SourcesResponse
from app.api.services.ai_provider import (
    BaseAIProvider,
    register_ai_provider,
    reset_ai_provider,
)


@pytest.fixture(autouse=True)
def cleanup_provider():
    reset_ai_provider()
    yield
    reset_ai_provider()


@pytest.mark.asyncio
async def test_sources_empty_when_not_configured() -> None:
    """6. GET /api/v1/sources возвращает пустой список, если источники не подключены."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


@pytest.mark.asyncio
async def test_sources_returns_items_from_mock_provider() -> None:
    """Проверка возврата зарегистрированных источников кастомного провайдера."""

    class MockSourcesProvider(BaseAIProvider):
        async def answer_question(self, question: str, language: str):
            pass

        async def list_sources(self) -> SourcesResponse:
            return SourcesResponse(
                items=[
                    SourceListItem(
                        id="src-100",
                        title="Конституция РК",
                        url="https://example.com/constitution",
                    )
                ],
                total=1,
            )

    register_ai_provider(MockSourcesProvider())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "src-100"
        assert data["items"][0]["title"] == "Конституция РК"
