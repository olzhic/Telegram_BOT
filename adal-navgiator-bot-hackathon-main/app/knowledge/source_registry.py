from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl


class SourceEntry(BaseModel):
    source_id: str
    title: str
    publisher: str
    url: HttpUrl
    language: Literal["ru", "kk"]
    category: str
    checked_at: date | None = None
    status: Literal["verified", "needs_verification", "excluded"]
    claims: list[str] = Field(default_factory=list)


def load_registry(path: Path) -> list[SourceEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise ValueError("Source registry must be a YAML list")
    return [SourceEntry.model_validate(item) for item in raw]
