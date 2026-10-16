import asyncio
import logging
import time
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from app.ai.llm.base import (
    InvalidStructuredOutputError,
    LLMProvider,
    LLMUnavailableError,
    ProviderRequestError,
)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMRouter:
    """Try configured providers in order and isolate failures with per-provider cooldowns."""

    def __init__(
        self,
        providers: Sequence[LLMProvider],
        *,
        cloud_timeout_s: float,
        local_timeout_s: float,
        breaker_failures: int = 3,
        breaker_cooldown_s: float = 60,
    ):
        self.providers = list(providers)
        self.cloud_timeout_s = cloud_timeout_s
        self.local_timeout_s = local_timeout_s
        self.breaker_failures = breaker_failures
        self.breaker_cooldown_s = breaker_cooldown_s
        self._consecutive_failures = {provider.name: 0 for provider in providers}
        self._cooldown_until: dict[str, float] = {}
        self.last_used_provider: str | None = None

    async def generate_structured(
        self, *, system: str, user: str, schema: type[T]
    ) -> T:
        errors: list[str] = []
        for provider in self.providers:
            if self._cooldown_until.get(provider.name, 0) > time.monotonic():
                logger.info("llm provider=%s outcome=skipped reason=circuit_open", provider.name)
                continue
            timeout = self.local_timeout_s if provider.name == "ollama" else self.cloud_timeout_s
            repair = False
            while True:
                started_at = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        provider.generate_structured(
                            system=system,
                            user=user,
                            schema=schema,
                            timeout_s=timeout,
                        ),
                        timeout=timeout,
                    )
                    self.last_used_provider = provider.name
                    self._consecutive_failures[provider.name] = 0
                    self._cooldown_until.pop(provider.name, None)
                    logger.info(
                        "llm provider=%s outcome=success repair=%s latency_ms=%d",
                        provider.name,
                        repair,
                        int((time.monotonic() - started_at) * 1000),
                    )
                    return result
                except InvalidStructuredOutputError:
                    if not repair:
                        repair = True
                        system += "\nReturn only valid JSON matching the requested schema."
                        continue
                    errors.append(f"{provider.name}:invalid_output")
                    self._record_failure(provider.name, None)
                    logger.warning(
                        "llm provider=%s outcome=failure error_category=invalid_structured_output",
                        provider.name,
                    )
                except (TimeoutError, asyncio.TimeoutError, ProviderRequestError) as exc:
                    category = (
                        exc.category
                        if isinstance(exc, ProviderRequestError)
                        else "provider_timeout"
                    )
                    model = exc.model if isinstance(exc, ProviderRequestError) else None
                    if model is None:
                        model = getattr(provider, "model", None)
                    if model is None:
                        configured_models = getattr(provider, "models", None)
                        if isinstance(configured_models, list):
                            model = ",".join(configured_models)
                    status_code = (
                        exc.status_code if isinstance(exc, ProviderRequestError) else None
                    )
                    retry_after_s = (
                        exc.retry_after_s if isinstance(exc, ProviderRequestError) else None
                    )
                    errors.append(f"{provider.name}:{category}")
                    logger.warning(
                        "llm provider=%s model=%s outcome=failure error_category=%s "
                        "status_code=%s retry_after_s=%s",
                        provider.name,
                        model or "unspecified",
                        category,
                        status_code or "none",
                        retry_after_s if retry_after_s is not None else "none",
                    )
                    self._record_failure(provider.name, getattr(exc, "retry_after_s", None))
                break
        if not self.providers:
            logger.error("llm outcome=unavailable reason=no_configured_providers")
        else:
            logger.error("llm outcome=unavailable provider_failures=%s", ",".join(errors))
        raise LLMUnavailableError("All configured LLM providers failed: " + ", ".join(errors))

    def _record_failure(self, provider_name: str, retry_after_s: float | None) -> None:
        failures = self._consecutive_failures.get(provider_name, 0) + 1
        self._consecutive_failures[provider_name] = failures
        if failures >= self.breaker_failures or retry_after_s is not None:
            cooldown = max(self.breaker_cooldown_s, retry_after_s or 0)
            self._cooldown_until[provider_name] = time.monotonic() + cooldown
            logger.info(
                "llm provider=%s outcome=circuit_open cooldown_s=%.1f",
                provider_name,
                cooldown,
            )
