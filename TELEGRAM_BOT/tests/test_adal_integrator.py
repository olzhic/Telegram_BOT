import httpx
import pytest
from app.api.config import ApiSettings
from app.api.main import app
from app.api.schemas import AskResponse, ResponseStatus
from app.api.services.adal_rag_provider import (
    AdalNavigatorDirectProvider,
    AdalNavigatorHTTPProvider,
    ContextAwareAIProvider,
    KnowledgeIndex,
    register_context_provider,
)
from app.api.services.ai_provider import register_ai_provider, reset_ai_provider


@pytest.fixture(autouse=True)
def cleanup():
    reset_ai_provider()
    yield
    reset_ai_provider()


# ---------------------------------------------------------------------------
# 1. Knowledge Index & Verified Sources Tests
# ---------------------------------------------------------------------------

def test_knowledge_index_loads_verified_sources():
    index = KnowledgeIndex()
    assert len(index.registry) >= 3
    assert len(index.chunks) >= 3

    # Check that verified sources contain expected titles
    titles = [chunk.title for chunk in index.chunks]
    assert any("противодействии коррупции" in t for t in titles)
    assert any("Административный процедурно-процессуальный" in t for t in titles)


def test_knowledge_index_search():
    index = KnowledgeIndex()
    results = index.search("срок рассмотрения обращения")
    assert len(results) > 0
    top_chunk, score = results[0]
    assert "обращения" in top_chunk.content.lower() or "обращения" in top_chunk.title.lower()
    assert score > 0


# ---------------------------------------------------------------------------
# 2. AdalNavigatorDirectProvider Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_direct_provider_answers_grounded_appeals_question():
    provider = AdalNavigatorDirectProvider()
    resp = await provider.answer_question("Каков срок рассмотрения обращения гражданина?", "ru")

    assert isinstance(resp, AskResponse)
    assert resp.status == ResponseStatus.ANSWERED.value
    assert "15 рабочих дней" in resp.answer or "пятнадцать рабочих дней" in resp.answer
    assert len(resp.sources) > 0
    assert any("АППК" in s.title or "Административный" in s.title for s in resp.sources)
    assert any("adilet.zan.kz" in (s.url or "") for s in resp.sources)


@pytest.mark.asyncio
async def test_direct_provider_answers_anticorruption_question():
    provider = AdalNavigatorDirectProvider()
    resp = await provider.answer_question("Что означает принцип Закон и Порядок и противодействие коррупции?", "ru")

    assert isinstance(resp, AskResponse)
    assert resp.status == ResponseStatus.ANSWERED.value
    assert len(resp.sources) > 0
    assert any("коррупции" in s.title.lower() for s in resp.sources)


@pytest.mark.asyncio
async def test_direct_provider_answers_in_kazakh():
    provider = AdalNavigatorDirectProvider()
    resp = await provider.answer_question("Өтінішті қарау мерзімі қандай?", "kk")

    assert isinstance(resp, AskResponse)
    assert resp.status == ResponseStatus.ANSWERED.value
    assert len(resp.sources) > 0


@pytest.mark.asyncio
async def test_direct_provider_returns_insufficient_evidence_for_irrelevant_query():
    provider = AdalNavigatorDirectProvider()
    resp = await provider.answer_question("Какая температура на спутнике Юпитера Европе?", "ru")

    assert isinstance(resp, AskResponse)
    assert resp.status == ResponseStatus.INSUFFICIENT_EVIDENCE.value
    assert "не найдено подтвержденных сведений" in resp.answer
    assert resp.sources == []


@pytest.mark.asyncio
async def test_direct_provider_lists_sources():
    provider = AdalNavigatorDirectProvider()
    resp = await provider.list_sources()

    assert resp.total >= 3
    assert len(resp.items) >= 3
    source_ids = [item.id for item in resp.items]
    assert "adilet-appeals" in source_ids
    assert "adilet-anticorruption" in source_ids


# ---------------------------------------------------------------------------
# 3. AdalNavigatorHTTPProvider Tests (Mocked External Service)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_provider_handles_confirmation_pipeline(monkeypatch):
    """Verify HTTP provider handles the 2-step confirmation->answer state machine of Adal Navigator."""
    call_count = 0

    async def mock_post(self, url, json=None, **kwargs):
        nonlocal call_count
        call_count += 1

        class MockResponse:
            status_code = 200

            def json(self):
                if json.get("action") == "message":
                    return {
                        "status": "confirmation",
                        "reply": "Вы хотите узнать о сроках рассмотрения обращений? Подтвердите.",
                        "language": "ru",
                    }
                elif json.get("action") == "confirm":
                    return {
                        "status": "answer",
                        "reply": "Срок рассмотрения обращения составляет 15 рабочих дней.",
                        "language": "ru",
                        "citations": [
                            {
                                "chunk_id": "appk-art-76",
                                "title": "АППК РК",
                                "url": "https://adilet.zan.kz/rus/docs/K2000000350",
                                "checked_at": "2026-10-15",
                            }
                        ],
                    }
                return {"status": "error", "reply": "unknown"}

        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    provider = AdalNavigatorHTTPProvider(base_url="http://mock-service:8001")
    resp = await provider.answer_question("Сроки рассмотрения обращения", "ru")

    assert call_count == 2  # initial message + automatic confirm
    assert resp.status == ResponseStatus.ANSWERED.value
    assert "15 рабочих дней" in resp.answer
    assert len(resp.sources) == 1
    assert resp.sources[0].title == "АППК РК"
    assert resp.sources[0].section == "appk-art-76"


@pytest.mark.asyncio
async def test_http_provider_handles_timeout(monkeypatch):
    async def mock_post_timeout(*args, **kwargs):
        raise httpx.TimeoutException("Remote timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_timeout)

    provider = AdalNavigatorHTTPProvider(base_url="http://mock-service:8001")
    resp = await provider.answer_question("Вопрос", "ru")

    assert resp.status == ResponseStatus.ERROR.value
    assert "Превышено время ожидания" in resp.answer


# ---------------------------------------------------------------------------
# 4. ContextAwareAIProvider Context Selection Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_aware_provider_explicit_modes():
    # 1. Explicit Direct mode
    cfg_direct = ApiSettings(AI_PROVIDER_TYPE="direct")
    p_direct = ContextAwareAIProvider(cfg_direct)
    resolved = await p_direct.resolve_provider()
    assert isinstance(resolved, AdalNavigatorDirectProvider)

    # 2. Explicit Demo mode
    cfg_demo = ApiSettings(AI_PROVIDER_TYPE="demo")
    p_demo = ContextAwareAIProvider(cfg_demo)
    resolved_demo = await p_demo.resolve_provider()
    assert resolved_demo.__class__.__name__ == "DemoAIProvider"

    # 3. Explicit Not Configured mode
    cfg_none = ApiSettings(AI_PROVIDER_TYPE="not_configured")
    p_none = ContextAwareAIProvider(cfg_none)
    resolved_none = await p_none.resolve_provider()
    assert resolved_none.__class__.__name__ == "NotConfiguredAIProvider"


@pytest.mark.asyncio
async def test_context_aware_provider_auto_mode_selects_direct_when_sources_present(monkeypatch):
    """In auto mode without a running HTTP service, it selects direct provider because sources exist."""
    async def mock_get_fail(*args, **kwargs):
        raise httpx.ConnectError("Service unreachable")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get_fail)

    cfg = ApiSettings(AI_PROVIDER_TYPE="auto")
    provider = ContextAwareAIProvider(cfg)
    resolved = await provider.resolve_provider()
    assert isinstance(resolved, AdalNavigatorDirectProvider)


@pytest.mark.asyncio
async def test_context_aware_provider_auto_mode_selects_http_when_service_online(monkeypatch):
    """In auto mode with a reachable HTTP service, it selects HTTP provider."""
    async def mock_get_healthy(self, url, **kwargs):
        class MockHealthResponse:
            status_code = 200
            def json(self):
                return {"status": "ok", "service": "adal-navigator"}
        return MockHealthResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get_healthy)

    cfg = ApiSettings(AI_PROVIDER_TYPE="auto", ADAL_NAVIGATOR_URL="http://mock-adal:8001")
    provider = ContextAwareAIProvider(cfg)
    resolved = await provider.resolve_provider()
    assert isinstance(resolved, AdalNavigatorHTTPProvider)


# ---------------------------------------------------------------------------
# 5. Full End-to-End API Integration via TestClient
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_with_registered_context_provider():
    """Verify that registering the context provider hooks into POST /api/v1/ask seamlessly."""
    provider = register_context_provider()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Ask question
        resp = await client.post(
            "/api/v1/ask",
            json={"question": "Какой срок рассмотрения обращения по АППК?", "language": "ru"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "answered"
        assert len(data["sources"]) > 0

        # List sources
        sources_resp = await client.get("/api/v1/sources")
        assert sources_resp.status_code == 200
        sources_data = sources_resp.json()
        assert sources_data["total"] >= 3

        # Context diagnostic endpoint
        context_resp = await client.get("/api/v1/context")
        assert context_resp.status_code == 200
        context_data = context_resp.json()
        assert "active_provider_class" in context_data
        assert context_data["sources_count"] >= 3
