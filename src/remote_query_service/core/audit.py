from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import orjson

from remote_query_service.core.models import AuditEvent


class AuditSink(ABC):
    @abstractmethod
    async def record(self, event: AuditEvent) -> None:
        raise NotImplementedError


class NullAuditSink(AuditSink):
    async def record(self, event: AuditEvent) -> None:
        return None


class JsonlAuditSink(AuditSink):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def record(self, event: AuditEvent) -> None:
        payload = orjson.dumps(event.model_dump(mode="json")).decode("utf-8")
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")

