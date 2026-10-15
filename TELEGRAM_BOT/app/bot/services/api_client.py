import logging
from typing import Any
import httpx
from app.bot.config import bot_settings

logger = logging.getLogger(__name__)


class ApiClient:
    """HTTP-клиент для взаимодействия Telegram-бота с FastAPI backend."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or bot_settings.API_BASE_URL).rstrip("/")
        self.timeout = timeout or bot_settings.API_TIMEOUT_SECONDS
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(timeout=self.timeout)

    async def get_client(self) -> httpx.AsyncClient:
        if self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Корректное закрытие сессии HTTP-клиента."""
        if not self._client.is_closed and not self._external_client:
            await self._client.aclose()
            logger.info("HTTP API client session closed.")

    async def check_health(self) -> bool:
        """Проверка доступности backend."""
        try:
            client = await self.get_client()
            response = await client.get(f"{self.base_url}/health")
            if response.status_code == 200:
                data = response.json()
                return data.get("status") == "ok"
            return False
        except Exception as exc:
            logger.warning("Backend health check failed: %s", exc)
            return False

    async def ask_question(self, question: str, language: str) -> dict[str, Any]:
        """
        Отправка вопроса в backend.
        Возвращает структурированный словарь ответа со статусом.
        """
        client = await self.get_client()
        url = f"{self.base_url}/api/v1/ask"
        payload = {"question": question, "language": language}

        try:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(
                    "Backend error HTTP %s: %s",
                    response.status_code,
                    response.text[:200],
                )
                return {
                    "status": "error",
                    "answer": "",
                    "sources": [],
                    "request_id": "",
                    "error_type": "http_error",
                    "status_code": response.status_code,
                }
        except httpx.TimeoutException:
            logger.error("Timeout occurred while waiting for response from %s", url)
            return {
                "status": "timeout",
                "answer": "",
                "sources": [],
                "request_id": "",
                "error_type": "timeout",
            }
        except httpx.RequestError as exc:
            logger.error("Network error while connecting to backend: %s", exc)
            return {
                "status": "connection_error",
                "answer": "",
                "sources": [],
                "request_id": "",
                "error_type": "connection_error",
            }
        except Exception as exc:
            logger.exception("Unexpected exception in API client: %s", exc)
            return {
                "status": "error",
                "answer": "",
                "sources": [],
                "request_id": "",
                "error_type": "internal_error",
            }

    async def get_sources(self) -> dict[str, Any]:
        """
        Получение списка зарегистрированных источников из backend.
        """
        client = await self.get_client()
        url = f"{self.base_url}/api/v1/sources"

        try:
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error("Failed to fetch sources: HTTP %s", response.status_code)
                return {"items": [], "total": 0, "status": "error"}
        except httpx.TimeoutException:
            logger.error("Timeout while fetching sources from %s", url)
            return {"items": [], "total": 0, "status": "timeout"}
        except httpx.RequestError as exc:
            logger.error("Network error while fetching sources: %s", exc)
            return {"items": [], "total": 0, "status": "connection_error"}
        except Exception as exc:
            logger.exception("Unexpected exception while fetching sources: %s", exc)
            return {"items": [], "total": 0, "status": "error"}


# Singleton instance
api_client = ApiClient()
