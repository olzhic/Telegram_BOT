import re

from pydantic import BaseModel, Field


class RagAnswer(BaseModel):
    supported: bool
    answer: str
    citations: list[str] = Field(default_factory=list)
    missing_info: str | None = None


PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{6,}\d)(?!\w)")
URL_RE = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d+\b")
DEADLINE_RE = re.compile(
    r"\b\d+\s*(?:календарн\w*|рабоч\w*|дн(?:я|ей|и)?|күн(?:тізбелік)?|"
    r"жұмыс\s*күні|day(?:s)?|business\s+days?)\b",
    re.IGNORECASE,
)


def validate_answer(
    result: RagAnswer,
    retrieved: dict[str, str],
) -> bool:
    """Reject unsupported output, unknown citations, or answer facts absent from cited text."""
    if not result.supported or not result.answer.strip() or not result.citations:
        return False
    if any(chunk_id not in retrieved for chunk_id in result.citations):
        return False
    cited_text = "\n".join(retrieved[chunk_id] for chunk_id in result.citations)
    for pattern in (PHONE_RE, URL_RE, DEADLINE_RE, NUMBER_RE):
        if any(match.group(0).casefold() not in cited_text.casefold() for match in pattern.finditer(result.answer)):
            return False
    return True
