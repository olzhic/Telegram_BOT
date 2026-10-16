import argparse
import asyncio
import logging
from pathlib import Path

from app.ai.retrieval import OllamaEmbedder, PostgresRetriever
from app.config import Settings
from app.persistence.db import create_database

# CLI tool: query the vector index directly to inspect retrieval quality.
# Usage: python scripts/inspect_retrieval.py "query text" [--category category_name]


async def main(query: str, category: str | None) -> None:
    """Run a retrieval query and print top chunks with scores for debugging."""
    settings = Settings()
    engine, sessions = create_database(settings.database_url)
    try:
        retriever = PostgresRetriever(
            sessions,
            OllamaEmbedder(
                endpoint=settings.ollama_embedding_url,
                model=settings.embedding_model,
                timeout_s=settings.llm_timeout_local_s,
            ),
            settings,
        )
        for chunk in await retriever.search(query, category):
            print(f"{chunk.score:.3f} {chunk.chunk_id} — {chunk.title}\n{chunk.content}\n{chunk.url}\n")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--category")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.query, arguments.category))
