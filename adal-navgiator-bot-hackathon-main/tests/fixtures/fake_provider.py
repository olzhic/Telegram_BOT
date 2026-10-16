from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class FakeProvider:
    name = "fake"

    def __init__(self, result: BaseModel | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = 0

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        timeout_s: float,
    ) -> T:
        self.calls += 1
        if self.error:
            raise self.error
        if self.result is None:
            raise AssertionError("FakeProvider requires a result")
        return schema.model_validate(self.result.model_dump())
