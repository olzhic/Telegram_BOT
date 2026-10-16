import json
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ConversationRepository(Protocol):
    async def load(self, chat_key: str) -> tuple[str, dict]: ...
    async def save(self, chat_key: str, state: str, data: dict) -> None: ...
    async def reset(self, chat_key: str) -> None: ...


class PostgresConversationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def load(self, chat_key: str) -> tuple[str, dict]:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    text("SELECT state, data FROM conversations WHERE chat_key = :key"),
                    {"key": chat_key},
                )
            ).mappings().first()
        if row is None:
            return "await_description", {}
        data = row["data"]
        return row["state"], data if isinstance(data, dict) else json.loads(data)

    async def save(self, chat_key: str, state: str, data: dict) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO conversations (chat_key, state, data)
                    VALUES (:key, :state, CAST(:data AS jsonb))
                    ON CONFLICT (chat_key) DO UPDATE
                    SET state = EXCLUDED.state, data = EXCLUDED.data, updated_at = now()
                    """
                ),
                {"key": chat_key, "state": state, "data": json.dumps(data, ensure_ascii=False)},
            )

    async def reset(self, chat_key: str) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                text("DELETE FROM conversations WHERE chat_key = :key"),
                {"key": chat_key},
            )
