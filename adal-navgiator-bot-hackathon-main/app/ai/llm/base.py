from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    name: str

    async def generate_structured(
        self, *, system: str, user: str, schema: type[T], timeout_s: float
    ) -> T: ...


class LLMUnavailableError(RuntimeError):
    pass


class InvalidStructuredOutputError(ValueError):
    pass


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str = "provider_error",
        status_code: int | None = None,
        model: str | None = None,
        retry_after_s: float | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.model = model
        self.retry_after_s = retry_after_s


def classify_http_status(status_code: int) -> str:
    """Map provider HTTP status to a safe, actionable troubleshooting category."""
    if status_code == 401:
        return "authentication_failed"
    if status_code == 402:
        return "billing_or_credits"
    if status_code == 403:
        return "permission_denied"
    if status_code == 404:
        return "model_or_endpoint_not_found"
    if status_code == 408 or status_code == 504:
        return "provider_timeout"
    if status_code == 429:
        return "rate_limited"
    if status_code == 400 or status_code == 422:
        return "invalid_request_or_model_parameters"
    if status_code >= 500:
        return "provider_overloaded_or_unavailable"
    return "provider_http_error"
