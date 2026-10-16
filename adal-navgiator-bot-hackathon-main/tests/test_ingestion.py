from datetime import date
from pathlib import Path

import pytest

from app.knowledge.ingestion import split_into_chunks, verified_source_content
from app.knowledge.source_registry import SourceEntry


def test_nonverified_source_is_never_read_for_indexing(tmp_path: Path):
    source = SourceEntry(
        source_id="pending-source",
        title="Pending",
        publisher="Official",
        url="https://example.gov.kz",
        language="ru",
        category="appeals",
        status="needs_verification",
        claims=[],
    )
    assert verified_source_content([source], tmp_path) == []


def test_verified_source_requires_review_date_and_nonempty_content(tmp_path: Path):
    source = SourceEntry(
        source_id="verified-source",
        title="Official",
        publisher="Official",
        url="https://example.gov.kz",
        language="ru",
        category="appeals",
        checked_at=date(2026, 10, 14),
        status="verified",
        claims=["The reviewed passage supports the included instruction."],
    )
    (tmp_path / "verified-source.md").write_text("Reviewed text.", encoding="utf-8")
    assert verified_source_content([source], tmp_path) == [(source, "Reviewed text.")]


def test_verified_source_must_declare_supported_claims(tmp_path: Path):
    source = SourceEntry(
        source_id="verified-source",
        title="Official",
        publisher="Official",
        url="https://example.gov.kz",
        language="ru",
        category="appeals",
        checked_at=date(2026, 10, 14),
        status="verified",
    )
    (tmp_path / "verified-source.md").write_text("Reviewed text.", encoding="utf-8")
    with pytest.raises(ValueError, match="supported claims"):
        verified_source_content([source], tmp_path)


def test_chunking_keeps_sentence_boundaries_and_paragraphs():
    content = "Короткое первое предложение. Еще одно.\n\n" + "Длинный абзац. " * 80
    chunks = split_into_chunks(content, max_chars=100)
    assert len(chunks) > 1
    assert all(chunk.endswith((".",)) for chunk in chunks)
