from dataclasses import dataclass
import json

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings


class RetrievalUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    content: str
    title: str
    url: str
    checked_at: str
    score: float


class OllamaEmbedder:
    def __init__(self, *, endpoint: str, model: str, timeout_s: float = 60):
        self.endpoint = endpoint
        self.model = model
        self.timeout_s = timeout_s

    async def embed(self, text_to_embed: str) -> list[float]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    self.endpoint,
                    json={"model": self.model, "input": text_to_embed},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise RetrievalUnavailableError("Embedding service request failed") from exc
        embeddings = payload.get("embeddings")
        if not embeddings or not embeddings[0]:
            raise RetrievalUnavailableError("Embedding service returned no vector")
        if len(embeddings[0]) != 1024:
            raise RetrievalUnavailableError("Embedding dimensions must match vector(1024)")
        return embeddings[0]


class PostgresRetriever:
    """Retrieve only verified source chunks using the same local embedder as ingestion."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        embedder: OllamaEmbedder,
        settings: Settings,
    ):
        self.sessions = sessions
        self.embedder = embedder
        self.settings = settings

    async def search(self, query: str, category: str | None) -> list[RetrievedChunk]:
        async with self.sessions() as session:
            verified_count = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM chunks c JOIN sources s USING (source_id)
                    WHERE s.status = 'verified'
                      AND (:category IS NULL OR s.category IN (:category, 'general'))
                    """
                ),
                {"category": category},
            )
        if not verified_count:
            return []
        vector = await self.embedder.embed(query)
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT c.chunk_id, c.content, s.title, s.url, s.checked_at,
                               1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
                        FROM chunks c JOIN sources s USING (source_id)
                        WHERE s.status = 'verified'
                          AND (:category IS NULL OR s.category IN (:category, 'general'))
                        ORDER BY c.embedding <=> CAST(:embedding AS vector)
                        LIMIT :limit
                        """
                    ),
                    {
                        "embedding": "[" + ",".join(str(value) for value in vector) + "]",
                        "category": category,
                        "limit": self.settings.retrieval_top_k,
                    },
                )
            ).mappings().all()
        return [
            RetrievedChunk(
                chunk_id=row["chunk_id"],
                content=row["content"],
                title=row["title"],
                url=row["url"],
                checked_at=row["checked_at"].isoformat(),
                score=float(row["score"]),
            )
            for row in rows
            if float(row["score"]) >= self.settings.retrieval_min_score
        ]
