import httpx
import pytest
from app.api.main import app
from app.api.schemas import AskResponse, SourceItem
from app.api.services.ai_provider import (
    BaseAIProvider,
    register_ai_provider,
    reset_ai_provider,
)


@pytest.fixture(autouse=True)
def cleanup_provider():
    """Сброс зарегистрированных провайдеров до и после каждого теста."""
    reset_ai_provider()
    yield
    reset_ai_provider()


@pytest.mark.asyncio
async def test_ask_rejects_empty_question() -> None:
    """2. POST /api/v1/ask отклоняет пустой вопрос (422)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Полностью пустая строка
        resp1 = await client.post("/api/v1/ask", json={"question": "", "language": "ru"})
        assert resp1.status_code == 422

        # Строка только из пробелов
        resp2 = await client.post("/api/v1/ask", json={"question": "   \n\t  ", "language": "ru"})
        assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_ask_rejects_unsupported_language() -> None:
    """3. API отклоняет неподдерживаемый язык (например, 'en' или 'es')."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/v1/ask",
            json={"question": "Что такое закон?", "language": "en"},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ask_returns_not_configured_when_no_ai() -> None:
    """4. Без подключённого AI возвращается статус 'not_configured'."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Русский язык
        resp_ru = await client.post(
            "/api/v1/ask",
            json={"question": "Что означает принцип «Закон и Порядок»?", "language": "ru"},
        )
        assert resp_ru.status_code == 200
        data_ru = resp_ru.json()
        assert data_ru["status"] == "not_configured"
        assert "AI-модуль пока не подключён" in data_ru["answer"]
        assert data_ru["sources"] == []
        assert data_ru["request_id"] != ""

        # Казахский язык
        resp_kk = await client.post(
            "/api/v1/ask",
            json={"question": "«Заң және Тәртіп» қағидаты нені білдіреді?", "language": "kk"},
        )
        assert resp_kk.status_code == 200
        data_kk = resp_kk.json()
        assert data_kk["status"] == "not_configured"
        assert "AI-модулі әлі қосылмаған" in data_kk["answer"]


@pytest.mark.asyncio
async def test_ask_returns_answered_with_mock_provider() -> None:
    """5. В режиме mock-провайдера возвращается 'answered' с переданными источниками."""

    class MockRAGProvider(BaseAIProvider):
        async def answer_question(self, question: str, language: str) -> AskResponse:
            return AskResponse(
                status="answered",
                answer=f"Ответ на вопрос: {question}",
                sources=[
                    SourceItem(
                        title="Закон о противодействии коррупции",
                        url="https://example.com/law",
                        section="Статья 1",
                    )
                ],
                request_id="test-mock-id-123",
            )

        async def list_sources(self):
            return None  # не используется в этом тесте

    register_ai_provider(MockRAGProvider())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/v1/ask",
            json={"question": "Что такое закон?", "language": "ru"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "answered"
        assert data["answer"] == "Ответ на вопрос: Что такое закон?"
        assert len(data["sources"]) == 1
        assert data["sources"][0]["title"] == "Закон о противодействии коррупции"
        assert data["sources"][0]["section"] == "Статья 1"
        assert data["sources"][0]["url"] == "https://example.com/law"
        assert data["request_id"] == "test-mock-id-123"


@pytest.mark.asyncio
async def test_ask_returns_demo_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка работы DEMO_MODE=True при отсутствии кастомного провайдера."""
    from app.api.config import settings

    monkeypatch.setattr(settings, "DEMO_MODE", True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/v1/ask",
            json={"question": "Что такое закон?", "language": "ru"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "answered"
        assert "[ДЕМО-РЕЖИМ]" in data["answer"]
        assert len(data["sources"]) > 0
        assert "[DEMO]" in data["sources"][0]["title"]

