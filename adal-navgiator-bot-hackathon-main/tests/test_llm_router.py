import asyncio
import logging

import httpx
import pytest

from app.ai.intent import IntentResult
from app.ai.llm.base import (
    InvalidStructuredOutputError,
    LLMUnavailableError,
    ProviderRequestError,
    classify_http_status,
)
from app.ai.llm.providers import OpenRouterProvider
from app.ai.llm.router import LLMRouter


class Provider:
    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate_structured(self, *, system, user, schema, timeout_s):
        self.calls += 1
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
async def test_router_fails_over_after_provider_error():
    expected = IntentResult(intent="smalltalk", summary="Hello")
    first = Provider("first", [ProviderRequestError("rate limited")])
    second = Provider("second", [expected])
    router = LLMRouter([first, second], cloud_timeout_s=1, local_timeout_s=2)

    result = await router.generate_structured(system="system", user="hello", schema=IntentResult)

    assert result == expected
    assert first.calls == 1
    assert second.calls == 1


@pytest.mark.asyncio
async def test_router_logs_safe_error_category_and_fails_over(caplog):
    expected = IntentResult(intent="smalltalk", summary="Hello")
    first = Provider(
        "openrouter",
        [
            ProviderRequestError(
                "must not be logged",
                category="authentication_failed",
                status_code=401,
                model="provider/model",
            )
        ],
    )
    second = Provider("fallback", [expected])
    router = LLMRouter([first, second], cloud_timeout_s=1, local_timeout_s=2)

    with caplog.at_level(logging.WARNING):
        assert (
            await router.generate_structured(system="system", user="hello", schema=IntentResult)
            == expected
        )

    assert "error_category=authentication_failed" in caplog.text
    assert "status_code=401" in caplog.text
    assert "model=provider/model" in caplog.text
    assert "must not be logged" not in caplog.text


@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (400, "invalid_request_or_model_parameters"),
        (401, "authentication_failed"),
        (402, "billing_or_credits"),
        (403, "permission_denied"),
        (404, "model_or_endpoint_not_found"),
        (408, "provider_timeout"),
        (422, "invalid_request_or_model_parameters"),
        (429, "rate_limited"),
        (500, "provider_overloaded_or_unavailable"),
        (503, "provider_overloaded_or_unavailable"),
        (504, "provider_timeout"),
    ],
)
def test_http_status_has_actionable_error_category(status_code, category):
    assert classify_http_status(status_code) == category


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (401, "authentication_failed"),
        (404, "model_or_endpoint_not_found"),
        (429, "rate_limited"),
        (503, "provider_overloaded_or_unavailable"),
    ],
)
async def test_openrouter_logs_model_and_status_without_provider_body(
    monkeypatch, caplog, status_code, category
):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code,
            headers={"Retry-After": "2"} if status_code == 429 else {},
            json={"error": {"message": "secret provider response"}},
            request=request,
        )
    )
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.ai.llm.providers.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    provider = OpenRouterProvider(api_key="secret-test-key", models=["vendor/model"])

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ProviderRequestError) as error:
            await provider.generate_structured(
                system="system",
                user="user",
                schema=IntentResult,
                timeout_s=1,
            )

    assert error.value.category == category
    assert f"error_category={category}" in caplog.text
    assert f"status_code={status_code}" in caplog.text
    assert "model=vendor/model" in caplog.text
    assert "secret provider response" not in caplog.text
    assert "secret-test-key" not in caplog.text


@pytest.mark.asyncio
async def test_openrouter_invalid_json_keeps_router_repair_attempt(monkeypatch):
    response_bodies = iter(
        [
            {"choices": [{"message": {"content": "not json"}}]},
            {
                "choices": [
                    {"message": {"content": '{"intent":"smalltalk","summary":"Hello"}'}}
                ]
            },
        ]
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=next(response_bodies), request=request)
    )
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.ai.llm.providers.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    provider = OpenRouterProvider(api_key="test-key", models=["vendor/model"])
    router = LLMRouter([provider], cloud_timeout_s=1, local_timeout_s=2)

    result = await router.generate_structured(
        system="system",
        user="user",
        schema=IntentResult,
    )

    assert result == IntentResult(intent="smalltalk", summary="Hello")


@pytest.mark.asyncio
async def test_invalid_output_gets_one_repair_attempt():
    expected = IntentResult(intent="smalltalk", summary="Hello")
    provider = Provider("first", [InvalidStructuredOutputError(), expected])
    router = LLMRouter([provider], cloud_timeout_s=1, local_timeout_s=2)

    assert await router.generate_structured(system="system", user="hello", schema=IntentResult) == expected
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_all_provider_failures_raise_typed_error():
    provider = Provider("first", [ProviderRequestError("offline"), ProviderRequestError("offline")])
    router = LLMRouter([provider], cloud_timeout_s=1, local_timeout_s=2)

    with pytest.raises(LLMUnavailableError):
        await router.generate_structured(system="system", user="hello", schema=IntentResult)


@pytest.mark.asyncio
async def test_circuit_breaker_skips_provider_during_cooldown_and_recovers():
    expected = IntentResult(intent="smalltalk", summary="Hello")
    provider = Provider("first", [ProviderRequestError("offline"), expected])
    router = LLMRouter(
        [provider],
        cloud_timeout_s=1,
        local_timeout_s=2,
        breaker_failures=1,
        breaker_cooldown_s=0.02,
    )

    with pytest.raises(LLMUnavailableError):
        await router.generate_structured(system="system", user="hello", schema=IntentResult)
    with pytest.raises(LLMUnavailableError):
        await router.generate_structured(system="system", user="hello", schema=IntentResult)
    assert provider.calls == 1

    await asyncio.sleep(0.03)
    assert await router.generate_structured(system="system", user="hello", schema=IntentResult) == expected
