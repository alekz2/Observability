from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from redis.asyncio import Redis

from remote_query_service.core.models import TailSession


class SessionStore(ABC):
    @abstractmethod
    async def put(self, session: TailSession) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get(self, session_id: str) -> TailSession | None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, TailSession] = {}

    async def put(self, session: TailSession) -> None:
        self._sessions[session.session_id] = session

    async def get(self, session_id: str) -> TailSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(datetime.now(timezone.utc)):
            self._sessions.pop(session_id, None)
            return None
        return session

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class RedisSessionStore(SessionStore):
    def __init__(self, client: Redis, prefix: str = "remote_query:session:") -> None:
        self._client = client
        self._prefix = prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def put(self, session: TailSession) -> None:
        ttl_seconds = max(int((session.expires_at - datetime.now(timezone.utc)).total_seconds()), 1)
        await self._client.set(
            self._key(session.session_id),
            session.model_dump_json(),
            ex=ttl_seconds,
        )

    async def get(self, session_id: str) -> TailSession | None:
        payload = await self._client.get(self._key(session_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        session = TailSession.model_validate_json(payload)
        if session.is_expired(datetime.now(timezone.utc)):
            await self.delete(session_id)
            return None
        return session

    async def delete(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))

