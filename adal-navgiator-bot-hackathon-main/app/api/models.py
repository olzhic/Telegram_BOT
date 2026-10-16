from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(default="", max_length=4000)
    action: Literal["message", "confirm", "correct", "reset"] = "message"


class Citation(BaseModel):
    chunk_id: str
    title: str
    url: str
    checked_at: str


class ChatResponse(BaseModel):
    status: Literal["confirmation", "clarification", "answer", "fallback", "reset", "error"]
    reply: str
    language: Literal["ru", "kk"]
    summary: str | None = None
    category: str | None = None
    clarification_field: str | None = None
    citations: list[Citation] = Field(default_factory=list)
