from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class Language(str, Enum):
    RU = "ru"
    KK = "kk"


class ResponseStatus(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"


class AskRequest(BaseModel):
    """Schema for incoming user question request."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Текст вопроса пользователя",
        examples=["Что означает принцип «Закон и Порядок»?"],
    )
    language: Literal["ru", "kk"] = Field(
        default="ru",
        description="Язык ответа: 'ru' (русский) или 'kk' (казахский)",
        examples=["ru"],
    )

    @field_validator("question")
    @classmethod
    def validate_question_not_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Вопрос не может быть пустым или состоять только из пробелов.")
        return trimmed


class SourceItem(BaseModel):
    """Source item attached to an answer."""

    title: str = Field(..., description="Название источника / документа")
    url: str | None = Field(default=None, description="Ссылка на источник (при наличии)")
    section: str | None = Field(default=None, description="Раздел или статья документа")


class AskResponse(BaseModel):
    """Structured response schema returned by backend."""

    status: str = Field(
        ...,
        description="Статус ответа: answered, insufficient_evidence, not_configured, error",
        examples=["answered"],
    )
    answer: str = Field(..., description="Текст ответа или поясняющее сообщение")
    sources: list[SourceItem] = Field(
        default_factory=list,
        description="Список подтверждающих источников",
    )
    request_id: str = Field(..., description="Уникальный идентификатор запроса")


class SourceListItem(BaseModel):
    """Single registered source in system catalog."""

    id: str = Field(..., description="Идентификатор источника")
    title: str = Field(..., description="Название зарегистрированного источника")
    url: str | None = Field(default=None, description="Ссылка на документ (при наличии)")


class SourcesResponse(BaseModel):
    """List of all registered sources in the system."""

    items: list[SourceListItem] = Field(
        default_factory=list,
        description="Список доступных источников",
    )
    total: int = Field(default=0, description="Общее количество источников")


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = Field(default="ok", description="Статус работоспособности сервиса")
    service: str = Field(default="adal-navigator-api", description="Имя сервиса")
