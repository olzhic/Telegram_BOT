import json
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TypeVar

import httpx
from google import genai
from google.genai.errors import APIError
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.ai.llm.base import (
    InvalidStructuredOutputError,
    ProviderRequestError,
    classify_http_status,
)

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)


def _parse_result(raw: str, schema: type[T]) -> T:
    try:
        return schema.model_validate_json(raw)
    except (TypeError, ValidationError, ValueError) as exc:
        raise InvalidStructuredOutputError("Provider returned invalid structured output") from exc


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def generate_structured(
        self, *, system: str, user: str, schema: type[T], timeout_s: float
    ) -> T:
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
                ),
            )
        except (APIError, TimeoutError, OSError) as exc:
            if isinstance(exc, APIError):
                status_code = _provider_status_code(exc)
                category = (
                    classify_http_status(status_code)
                    if status_code is not None
                    else "provider_api_error"
                )
            elif isinstance(exc, TimeoutError):
                status_code = None
                category = "provider_timeout"
            else:
                status_code = None
                category = "connection_error"
            raise ProviderRequestError(
                "Gemini request failed",
                category=category,
                status_code=status_code,
                model=self.model,
            ) from exc
        if not response.text:
            raise InvalidStructuredOutputError("Gemini returned an empty response")
        return _parse_result(response.text, schema)


class OpenRouterProvider:
    name = "openrouter"
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, *, api_key: str, models: list[str]):
        self.api_key = api_key
        self.models = models

    async def generate_structured(
        self, *, system: str, user: str, schema: type[T], timeout_s: float
    ) -> T:
        failures: list[str] = []
        retry_after_s = None
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            for model in self.models:
                try:
                    response = await client.post(
                        self.endpoint,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                            "response_format": {
                                "type": "json_schema",
                                "json_schema": {
                                    "name": schema.__name__,
                                    "strict": True,
                                    "schema": schema.model_json_schema(),
                                },
                            },
                        },
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    result = _parse_result(content, schema)
                    logger.info(
                        "llm provider=openrouter model=%s outcome=success",
                        model,
                    )
                    return result
                except InvalidStructuredOutputError:
                    logger.warning(
                        "llm provider=openrouter model=%s outcome=failure "
                        "error_category=invalid_structured_output",
                        model,
                    )
                    failures.append(f"{model}:invalid_structured_output")
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    category = classify_http_status(status_code)
                    retry = exc.response.headers.get("Retry-After")
                    if status_code == 429 and retry:
                        try:
                            retry_seconds = float(retry)
                        except ValueError:
                            try:
                                retry_time = parsedate_to_datetime(retry)
                                retry_seconds = max(
                                    0,
                                    (retry_time - datetime.now(timezone.utc)).total_seconds(),
                                )
                            except (TypeError, ValueError, OverflowError):
                                retry_seconds = 0
                        retry_after_s = max(retry_after_s or 0, retry_seconds)
                    logger.warning(
                        "llm provider=openrouter model=%s outcome=failure "
                        "error_category=%s status_code=%d",
                        model,
                        category,
                        status_code,
                    )
                    failures.append(f"{model}:{category}")
                except httpx.TimeoutException:
                    logger.warning(
                        "llm provider=openrouter model=%s outcome=failure "
                        "error_category=provider_timeout",
                        model,
                    )
                    failures.append(f"{model}:provider_timeout")
                except httpx.HTTPError:
                    logger.warning(
                        "llm provider=openrouter model=%s outcome=failure "
                        "error_category=connection_error",
                        model,
                    )
                    failures.append(f"{model}:connection_error")
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    logger.warning(
                        "llm provider=openrouter model=%s outcome=failure "
                        "error_category=malformed_provider_response",
                        model,
                    )
                    failures.append(f"{model}:malformed_provider_response")
        if failures and all(
            failure.endswith(":invalid_structured_output") for failure in failures
        ):
            raise InvalidStructuredOutputError(
                "OpenRouter models returned invalid structured output"
            )
        raise ProviderRequestError(
            "All OpenRouter models failed",
            category=_openrouter_failure_category(failures),
            retry_after_s=retry_after_s,
        )


class OllamaProvider:
    name = "ollama"

    def __init__(self, *, base_url: str, model: str):
        self.endpoint = base_url.rstrip("/") + "/api/chat"
        self.model = model

    async def generate_structured(
        self, *, system: str, user: str, schema: type[T], timeout_s: float
    ) -> T:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(
                    self.endpoint,
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "format": schema.model_json_schema(),
                        "stream": False,
                    },
                )
                response.raise_for_status()
                content = response.json()["message"]["content"]
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise ProviderRequestError(
                "Ollama request failed",
                category=classify_http_status(status_code),
                status_code=status_code,
                model=self.model,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderRequestError(
                "Ollama request timed out",
                category="provider_timeout",
                model=self.model,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderRequestError(
                "Ollama request failed",
                category="connection_error",
                model=self.model,
            ) from exc
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderRequestError(
                "Ollama returned a malformed response",
                category="malformed_provider_response",
                model=self.model,
            ) from exc
        return _parse_result(content, schema)


def _provider_status_code(exc: APIError) -> int | None:
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _openrouter_failure_category(failures: list[str]) -> str:
    categories = [failure.rsplit(":", 1)[-1] for failure in failures]
    for category in (
        "authentication_failed",
        "permission_denied",
        "billing_or_credits",
        "model_or_endpoint_not_found",
        "invalid_request_or_model_parameters",
        "rate_limited",
        "provider_overloaded_or_unavailable",
        "provider_timeout",
        "connection_error",
    ):
        if category in categories:
            return category
    if categories and all(category == "invalid_structured_output" for category in categories):
        return "invalid_structured_output"
    if categories:
        return categories[-1]
    return "no_models_configured"
