import asyncio
import logging
from pathlib import Path

from app.ai.retrieval import OllamaEmbedder
from app.config import Settings
from app.knowledge.ingestion import ingest_sources
from app.persistence.db import create_database

ROOT = Path(__file__).resolve().parents[1]

# CLI entry point: builds/rebuilds the knowledge base from verified sources.
# Uses the same local embedding model as runtime retrieval (critical for vector compatibility).


async def main() -> None:
    """Ingest verified sources from data/registry.yaml into PostgreSQL/pgvector."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings()
    engine, sessions = create_database(settings.database_url)
    try:
        count = await ingest_sources(
            registry_path=ROOT / "data" / "registry.yaml",
            source_directory=ROOT / "data" / "sources",
            sessions=sessions,
            embedder=OllamaEmbedder(
                endpoint=settings.ollama_embedding_url,
                model=settings.embedding_model,
                timeout_s=settings.llm_timeout_local_s,
            ),
        )
        print(f"Indexed {count} verified chunks.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
