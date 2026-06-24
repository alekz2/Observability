from __future__ import annotations

from abc import ABC, abstractmethod

from remote_query_service.core.models import HostPolicy, LogChunk, QueryPolicy, SearchMatch


class RemoteExecutionError(Exception):
    """Raised when a remote SSH-backed operation fails."""


class RemoteLogClient(ABC):
    @abstractmethod
    async def read_initial(self, host: HostPolicy, path: str, start: str, lines: int, max_bytes: int) -> LogChunk:
        raise NotImplementedError

    @abstractmethod
    async def read_from_offset(
        self,
        host: HostPolicy,
        path: str,
        offset: int,
        max_lines: int,
        max_bytes: int,
        expected_inode: str | None,
    ) -> LogChunk:
        raise NotImplementedError

    @abstractmethod
    async def search_logs(
        self,
        host: HostPolicy,
        path: str,
        pattern: str,
        max_matches: int,
        before: int,
        after: int,
        max_bytes: int,
    ) -> list[SearchMatch]:
        raise NotImplementedError

    @abstractmethod
    async def run_query(
        self,
        host: HostPolicy,
        query: QueryPolicy,
        arguments: dict[str, str],
        max_lines: int,
        max_bytes: int,
    ) -> tuple[list[str], list[str]]:
        raise NotImplementedError

