from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.ai.answer import AnswerResult
from app.ai.intent import IntentResult
from app.ai.retrieval import RetrievedChunk
from app.application.dialogue_service import DialogueService
from app.config import Settings
from app.main import create_app


class MemoryRepository:
    def __init__(self):
        self.rows = {}

    async def load(self, key):
        return self.rows.get(key, ("await_description", {}))

    async def save(self, key, state, data):
        self.rows[key] = (state, data)

    async def reset(self, key):
        self.rows.pop(key, None)


async def classify(_: str):
    return IntentResult(
        intent="civic_issue",
        category="garbage",
        summary="Мусор не вывезли",
        city="Алматы",
    )


async def retrieve(_: str, __: str | None):
    return [
        RetrievedChunk(
            chunk_id="source#0",
            content="Проверенная инструкция.",
            title="Official",
            url="https://example.gov.kz",
            checked_at="2026-10-14",
            score=0.9,
        )
    ]


async def answer(_: str, __: list[RetrievedChunk], language: str):
    return AnswerResult(
        answer="Инструкция из источника.",
        citations=[
            {
                "chunk_id": "source#0",
                "title": "Official",
                "url": "https://example.gov.kz",
                "checked_at": "2026-10-14",
            }
        ],
        supported=True,
    )


def test_chat_endpoint_runs_without_database_or_real_model():
    service = DialogueService(
        repository=MemoryRepository(),
        classifier=classify,
        retriever=retrieve,
        answerer=answer,
        hmac_secret="test-secret-that-is-at-least-thirty-two-bytes",
        max_message_length=4000,
    )
    with TestClient(
        create_app(
            Settings(chat_id_hmac_secret="test-secret-that-is-at-least-thirty-two-bytes"),
            service,
        )
    ) as client:
        response = client.post(
            "/chat",
            json={
                "session_id": "browser-session",
                "message": "В Алматы не вывезли мусор",
                "action": "message",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "confirmation"
        assert response.headers["X-Request-ID"]


def test_health_is_available_with_injected_dialogue_service():
    service = DialogueService(
        repository=MemoryRepository(),
        classifier=classify,
        retriever=retrieve,
        answerer=answer,
        hmac_secret="test-secret-that-is-at-least-thirty-two-bytes",
        max_message_length=4000,
    )
    with TestClient(
        create_app(
            Settings(chat_id_hmac_secret="test-secret-that-is-at-least-thirty-two-bytes"),
            service,
        )
    ) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_health_returns_503_when_database_cannot_be_reached():
    settings = Settings(
        app_env="development",
        database_url="postgresql+asyncpg://adal_app:test@127.0.0.1:1/adal",
        chat_id_hmac_secret="test-secret-that-is-at-least-thirty-two-bytes",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    assert "DATABASE_URL" in response.json()["diagnosis"]
    assert response.json()["request_id"]


def test_production_health_hides_internal_diagnostics():
    settings = Settings(
        app_env="production",
        database_url="postgresql+asyncpg://adal_app:password@127.0.0.1:1/adal",
        chat_id_hmac_secret="test-secret-that-is-at-least-thirty-two-bytes",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "X-Request-ID" not in response.headers


def test_chat_database_error_has_sanitized_diagnostics_in_development():
    settings = Settings(
        app_env="development",
        database_url="postgresql+asyncpg://adal_app:test@127.0.0.1:1/adal",
        chat_id_hmac_secret="test-secret-that-is-at-least-thirty-two-bytes",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/chat",
            json={"session_id": "browser-session", "message": "hello", "action": "message"},
        )
    assert response.status_code == 503
    assert response.json()["diagnostics"]["stage"] == "persistence"
    assert response.json()["diagnostics"]["error_type"] in {
        "ConnectionRefusedError",
        "OperationalError",
    }
    assert response.json()["diagnostics"]["request_id"] == response.headers["X-Request-ID"]
    assert "DATABASE_URL" not in response.json()["detail"]
    assert response.headers["X-Request-ID"]


def test_production_chat_error_is_localized_and_redacted():
    class FailingService:
        async def handle(self, *_):
            raise SQLAlchemyError("private database connection details")

    settings = Settings(app_env="production")
    with TestClient(create_app(settings, FailingService())) as client:
        response = client.post(
            "/chat",
            json={
                "session_id": "browser-session",
                "message": "Мәселе болды",
                "action": "message",
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Қызмет уақытша қолжетімсіз. Кейінірек қайталап көріңіз."
    }
    assert "private database" not in response.text
    assert "diagnostics" not in response.json()
    assert "X-Request-ID" not in response.headers


def test_production_unexpected_error_is_generic_and_redacted():
    class FailingService:
        async def handle(self, *_):
            raise RuntimeError("private provider response")

    with TestClient(
        create_app(Settings(app_env="production"), FailingService()),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/chat",
            json={
                "session_id": "browser-session",
                "message": "Вопрос",
                "action": "message",
            },
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Сервис временно недоступен. Пожалуйста, попробуйте позже."}
    assert "private provider response" not in response.text
    assert "diagnostics" not in response.json()
    assert "X-Request-ID" not in response.headers


def test_production_validation_error_does_not_echo_submitted_data():
    with TestClient(create_app(Settings(app_env="production"))) as client:
        response = client.post(
            "/chat",
            json={
                "session_id": "browser-session",
                "message": "private submitted value",
                "action": "invalid-action",
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Не удалось обработать запрос. Попробуйте позже."}
    assert "private submitted value" not in response.text
    assert "diagnostics" not in response.json()
