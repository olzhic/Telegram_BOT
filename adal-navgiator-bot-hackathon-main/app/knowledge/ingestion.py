import logging
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.retrieval import OllamaEmbedder
from app.knowledge.source_registry import SourceEntry, load_registry

logger = logging.getLogger(__name__)
MAX_CHUNK_CHARS = 800

# Ingestion pipeline: reads verified sources from data/sources/, chunks them, embeds with local model,
# upserts into PostgreSQL/pgvector. Only status=verified sources are indexed.


def split_into_chunks(content: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split markdown into ~800-char chunks on paragraph/sentence boundaries.
    Keeps contacts with their context; no overlap between chunks."""
    paragraphs = [paragraph.strip() for paragraph in content.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        else:
            sentences = [paragraph]
        for sentence in sentences:
            candidate = f"{current}\n{sentence}".strip() if current else sentence
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def verified_source_content(
    sources: list[SourceEntry], source_directory: Path
) -> list[tuple[SourceEntry, str]]:
    """Load only verified sources; validate required fields and read .md files."""
    result = []
    for source in sources:
        if source.status != "verified":
            logger.info("knowledge source=%s outcome=skipped status=%s", source.source_id, source.status)
            continue
        if source.checked_at is None:
            raise ValueError(f"Verified source {source.source_id} must have checked_at")
        if not source.claims:
            raise ValueError(f"Verified source {source.source_id} must declare its supported claims")
        path = source_directory / f"{source.source_id}.md"
        if not path.is_file():
            raise FileNotFoundError(f"Verified source file not found: {path}")
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Verified source {source.source_id} has no content")
        result.append((source, content))
    return result


async def ingest_sources(
    *,
    registry_path: Path,
    source_directory: Path,
    sessions: async_sessionmaker[AsyncSession],
    embedder: OllamaEmbedder,
) -> int:
    registry = load_registry(registry_path)
    sources = verified_source_content(registry, source_directory)
    registered_ids = {source.source_id for source in registry}
    async with sessions() as session, session.begin():
        existing_ids = (
            await session.execute(text("SELECT source_id FROM sources"))
        ).scalars().all()
        for source_id in existing_ids:
            if source_id in registered_ids:
                continue
            await session.execute(
                text("UPDATE sources SET status = 'excluded' WHERE source_id = :source_id"),
                {"source_id": source_id},
            )
            await session.execute(
                text("DELETE FROM chunks WHERE source_id = :source_id"),
                {"source_id": source_id},
            )
        for source in registry:
            if source.status == "verified":
                continue
            await session.execute(
                text("UPDATE sources SET status = :status WHERE source_id = :source_id"),
                {"status": source.status, "source_id": source.source_id},
            )
            await session.execute(
                text("DELETE FROM chunks WHERE source_id = :source_id"),
                {"source_id": source.source_id},
            )
    indexed = 0
    for source, content in sources:
        chunks = split_into_chunks(content)
        if not chunks:
            raise ValueError(f"Verified source {source.source_id} has no indexable chunks")
        embeddings = [
            await embedder.embed(f"{source.title}\n{chunk}")
            for chunk in chunks
        ]
        if any(len(vector) != 1024 for vector in embeddings):
            raise ValueError(
                f"Embedding dimensions for {source.source_id} must match vector(1024)"
            )
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO sources
                        (source_id, title, publisher, url, language, category, checked_at, status)
                    VALUES
                        (:source_id, :title, :publisher, :url, :language, :category, :checked_at, 'verified')
                    ON CONFLICT (source_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        publisher = EXCLUDED.publisher,
                        url = EXCLUDED.url,
                        language = EXCLUDED.language,
                        category = EXCLUDED.category,
                        checked_at = EXCLUDED.checked_at,
                        status = EXCLUDED.status
                    """
                ),
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "publisher": source.publisher,
                    "url": str(source.url),
                    "language": source.language,
                    "category": source.category,
                    "checked_at": source.checked_at,
                },
            )
            await session.execute(
                text("DELETE FROM chunks WHERE source_id = :source_id"),
                {"source_id": source.source_id},
            )
            for position, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=True)):
                await session.execute(
                    text(
                        """
                        INSERT INTO chunks (chunk_id, source_id, position, content, embedding)
                        VALUES (:chunk_id, :source_id, :position, :content,
                                CAST(:embedding AS vector))
                        """
                    ),
                    {
                        "chunk_id": f"{source.source_id}#{position}",
                        "source_id": source.source_id,
                        "position": position,
                        "content": chunk,
                        "embedding": "[" + ",".join(str(value) for value in vector) + "]",
                    },
                )
        indexed += len(chunks)
    return indexed
