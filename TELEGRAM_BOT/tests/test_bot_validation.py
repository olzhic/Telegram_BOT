import httpx
import pytest
from app.api.main import app
from app.api.schemas import AskResponse, SourceItem
from app.api.services.ai_provider import (
    BaseAIProvider,
    register_ai_provider,
    reset_ai_provider,
)
from app.bot.handlers.questions import (
    format_answer_response,
    split_text_into_chunks,
)
from app.bot.i18n import t, user_language_storage
from app.bot.services.api_client import ApiClient


@pytest.fixture(autouse=True)
def cleanup():
    reset_ai_provider()
    yield
    reset_ai_provider()


@pytest.mark.asyncio
async def test_telegram_client_sends_question_to_backend() -> None:
    """7. Telegram-клиент корректно отправляет вопрос в backend."""

    class TestProvider(BaseAIProvider):
        async def answer_question(self, question: str, language: str) -> AskResponse:
            return AskResponse(
                status="answered",
                answer=f"Получен вопрос: {question}",
                sources=[
                    SourceItem(
                        title="Тестовый источник",
                        url="https://example.com/test",
                        section="Глава 1",
                    )
                ],
                request_id="req-777",
            )

        async def list_sources(self):
            return None

    register_ai_provider(TestProvider())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as http_client:
        client = ApiClient(base_url="http://testserver", client=http_client)
        result = await client.ask_question("Что такое право?", "ru")

        assert result["status"] == "answered"
        assert result["answer"] == "Получен вопрос: Что такое право?"
        assert len(result["sources"]) == 1
        assert result["sources"][0]["title"] == "Тестовый источник"
        assert result["request_id"] == "req-777"


def test_telegram_bot_formats_answer_and_sources() -> None:
    """8. Telegram-бот корректно форматирует ответ и источники, а также разбивает длинные тексты."""
    response_data = {
        "status": "answered",
        "answer": "Это официальный ответ системы.",
        "sources": [
            {
                "title": "Закон РК «О противодействии коррупции»",
                "section": "Статья 1",
                "url": "https://example.com/law",
            },
            {
                "title": "Конституция РК",
                "section": "Раздел 1",
                "url": None,
            },
        ],
    }

    formatted_ru = format_answer_response(response_data, lang="ru")
    assert "Это официальный ответ системы." in formatted_ru
    assert "Закон РК «О противодействии коррупции»" in formatted_ru
    assert "https://example.com/law" in formatted_ru
    assert "Конституция РК" in formatted_ru

    # Проверка разбивки длинного текста
    very_long_text = "A" * 9000
    chunks = split_text_into_chunks(very_long_text, max_chunk_size=4000)
    assert len(chunks) == 3
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(chunks) == very_long_text


@pytest.mark.asyncio
async def test_telegram_bot_handles_timeout_and_unavailability() -> None:
    """9. Telegram-бот корректно обрабатывает таймаут и недоступность API."""

    # Проверка обработки таймаута
    timeout_client = ApiClient(
        base_url="http://127.0.0.1:54321",
        timeout=0.001,
    )

    # Заведомо несуществующий адрес для проверки сетевой ошибки / таймаута
    res = await timeout_client.ask_question("Вопрос?", "ru")
    assert res["status"] in ("timeout", "connection_error", "error")

    # Форматирование сообщений для пользователя при ошибке
    msg_timeout = format_answer_response({"status": "timeout"}, "ru")
    assert "Сервер не ответил вовремя" in msg_timeout

    msg_error = format_answer_response({"status": "connection_error"}, "ru")
    assert "Произошла временная ошибка" in msg_error

    msg_error_kk = format_answer_response({"status": "connection_error"}, "kk")
    assert "Серверге жүгіну кезінде уақытша қате" in msg_error_kk

    await timeout_client.close()


def test_different_users_can_choose_different_languages() -> None:
    """10. Разные пользователи могут изолированно выбирать разные языки."""
    user_1 = 10001
    user_2 = 10002
    user_default = 10003

    user_language_storage.set(user_1, "ru")
    user_language_storage.set(user_2, "kk")

    # Изоляция языков между пользователями
    assert user_language_storage.get(user_1) == "ru"
    assert user_language_storage.get(user_2) == "kk"
    assert user_language_storage.get(user_default) == "ru"

    # Проверка локализации для каждого пользователя
    welcome_user_1 = t("welcome", user_language_storage.get(user_1))
    welcome_user_2 = t("welcome", user_language_storage.get(user_2))

    assert "Привет! Я Adal Navigator" in welcome_user_1
    assert "Сәлем! Мен Adal Navigator-мын" in welcome_user_2
    assert welcome_user_1 != welcome_user_2
