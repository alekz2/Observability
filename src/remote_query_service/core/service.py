from __future__ import annotations

import logging
import re

from fastapi import HTTPException, status

from remote_query_service.core.audit import AuditSink
from remote_query_service.core.models import (
    Actor,
    AuditEvent,
    CloseSessionRequest,
    HostInfo,
    HostPolicy,
    OpenSessionRequest,
    QueryInfo,
    QueryPolicy,
    QueryResultResponse,
    ReadSessionRequest,
    RunQueryRequest,
    SearchLogsRequest,
    SearchLogsResponse,
    SearchMatch,
    SessionResponse,
    TailSession,
)
from remote_query_service.core.redaction import Redactor
from remote_query_service.core.session_store import SessionStore
from remote_query_service.core.settings import Settings
from remote_query_service.remote.base import RemoteExecutionError, RemoteLogClient

logger = logging.getLogger(__name__)


class RemoteQueryService:
    def __init__(
        self,
        settings: Settings,
        hosts: dict[str, HostPolicy],
        remote_client: RemoteLogClient,
        session_store: SessionStore,
        redactor: Redactor,
        audit_sink: AuditSink,
    ) -> None:
        self._settings = settings
        self._hosts = hosts
        self._remote_client = remote_client
        self._session_store = session_store
        self._redactor = redactor
        self._audit_sink = audit_sink

    def host_names(self) -> list[str]:
        return list(self._hosts)

    async def list_hosts(self, actor: Actor) -> list[HostInfo]:
        hosts = [
            HostInfo(
                name=host.name,
                address=host.address,
                port=host.port,
                allowed_paths=host.allowed_paths,
            )
            for host in self._hosts.values()
        ]
        await self._audit_sink.record(AuditEvent(actor=actor.subject, action="list_hosts"))
        return hosts

    async def list_queries(self, host_name: str, actor: Actor) -> list[QueryInfo]:
        host = self._resolve_host(host_name)
        queries = [
            QueryInfo(
                name=name,
                description=query.description,
                command=" ".join(query.command) if isinstance(query.command, list) else query.command,
                arg_names=[policy.name for policy in query.arg_policies],
            )
            for name, query in host.allowed_queries.items()
        ]
        await self._audit_sink.record(
            AuditEvent(actor=actor.subject, action="list_queries", host=host.name, line_count=len(queries))
        )
        return queries

    async def open_session(self, request: OpenSessionRequest, actor: Actor) -> SessionResponse:
        host = self._resolve_host(request.host)
        self._assert_allowed_path(host, request.path)
        try:
            chunk = await self._remote_client.read_initial(
                host=host,
                path=request.path,
                start=request.start,
                lines=request.lines,
                max_bytes=self._settings.max_chunk_bytes,
            )
        except RemoteExecutionError as exc:
            logger.error("Remote log session open failed for host=%s path=%s error=%s", host.name, request.path, exc)
            self._raise_remote_failure(exc)
        session = TailSession.create(
            host=host.name,
            path=request.path,
            offset=chunk.next_offset,
            ttl_seconds=self._settings.session_ttl_seconds,
            inode=chunk.inode,
        )
        await self._session_store.put(session)
        lines = self._redactor.redact_lines(chunk.lines)
        response = SessionResponse(
            session_id=session.session_id,
            host=session.host,
            path=session.path,
            cursor=session.offset,
            line_count=len(lines),
            rotated=chunk.rotated,
            lines=lines,
        )
        await self._audit_sink.record(
            AuditEvent(
                actor=actor.subject,
                action="open_session",
                host=session.host,
                path=session.path,
                session_id=session.session_id,
                cursor=session.offset,
                line_count=response.line_count,
                rotated=response.rotated,
            )
        )
        return response

    async def search_logs(self, request: SearchLogsRequest, actor: Actor) -> SearchLogsResponse:
        host = self._resolve_host(request.host)
        self._assert_allowed_path(host, request.path)
        try:
            matches = await self._remote_client.search_logs(
                host=host,
                path=request.path,
                pattern=request.pattern,
                max_matches=request.max_matches,
                before=request.before,
                after=request.after,
                max_bytes=self._settings.max_chunk_bytes,
            )
        except RemoteExecutionError as exc:
            logger.error(
                "Remote log search failed for host=%s path=%s pattern=%s error=%s",
                host.name,
                request.path,
                request.pattern,
                exc,
            )
            self._raise_remote_failure(exc)
        redacted_matches = [
            SearchMatch(
                line_number=match.line_number,
                lines=self._redactor.redact_lines(match.lines),
            )
            for match in matches
        ]
        response = SearchLogsResponse(
            host=host.name,
            path=request.path,
            pattern=request.pattern,
            match_count=len(redacted_matches),
            matches=redacted_matches,
        )
        await self._audit_sink.record(
            AuditEvent(
                actor=actor.subject,
                action="search_logs",
                host=host.name,
                path=request.path,
                line_count=response.match_count,
            )
        )
        return response

    async def run_query(self, request: RunQueryRequest, actor: Actor) -> QueryResultResponse:
        host = self._resolve_host(request.host)
        query = host.resolve_query(request.query_name)
        if query is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown query '{request.query_name}' for host '{host.name}'",
            )
        self._validate_query_arguments(query, request.arguments)
        try:
            command, lines = await self._remote_client.run_query(
                host=host,
                query=query,
                arguments=request.arguments,
                max_lines=request.max_lines,
                max_bytes=self._settings.max_chunk_bytes,
            )
        except RemoteExecutionError as exc:
            logger.error(
                "Remote query failed for host=%s query=%s arguments=%s error=%s",
                host.name,
                request.query_name,
                request.arguments,
                exc,
            )
            self._raise_remote_failure(exc)
        redacted_lines = self._redactor.redact_lines(lines)
        response = QueryResultResponse(
            host=host.name,
            query_name=request.query_name,
            command=command,
            line_count=len(redacted_lines),
            lines=redacted_lines,
        )
        await self._audit_sink.record(
            AuditEvent(
                actor=actor.subject,
                action="run_query",
                host=host.name,
                query_name=request.query_name,
                line_count=response.line_count,
            )
        )
        return response

    async def read_session(self, request: ReadSessionRequest, actor: Actor) -> SessionResponse:
        session = await self._session_store.get(request.session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        host = self._resolve_host(session.host)
        try:
            chunk = await self._remote_client.read_from_offset(
                host=host,
                path=session.path,
                offset=session.offset,
                max_lines=request.max_lines,
                max_bytes=self._settings.max_chunk_bytes,
                expected_inode=session.inode,
            )
        except RemoteExecutionError as exc:
            logger.error(
                "Remote session read failed for host=%s path=%s session_id=%s error=%s",
                host.name,
                session.path,
                request.session_id,
                exc,
            )
            self._raise_remote_failure(exc)
        session.offset = chunk.next_offset
        session.inode = chunk.inode
        await self._session_store.put(session)
        lines = self._redactor.redact_lines(chunk.lines)
        response = SessionResponse(
            session_id=session.session_id,
            host=session.host,
            path=session.path,
            cursor=session.offset,
            line_count=len(lines),
            rotated=chunk.rotated,
            lines=lines,
        )
        await self._audit_sink.record(
            AuditEvent(
                actor=actor.subject,
                action="read_session",
                host=session.host,
                path=session.path,
                session_id=session.session_id,
                cursor=session.offset,
                line_count=response.line_count,
                rotated=response.rotated,
            )
        )
        return response

    async def close_session(self, request: CloseSessionRequest, actor: Actor) -> None:
        session = await self._session_store.get(request.session_id)
        await self._session_store.delete(request.session_id)
        await self._audit_sink.record(
            AuditEvent(
                actor=actor.subject,
                action="close_session",
                host=session.host if session else None,
                path=session.path if session else None,
                session_id=request.session_id,
            )
        )

    def _resolve_host(self, name: str) -> HostPolicy:
        host = self._hosts.get(name)
        if host is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown host '{name}'")
        return host

    @staticmethod
    def _assert_allowed_path(host: HostPolicy, path: str) -> None:
        if not host.permits_path(path):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Path '{path}' is not allowed for host '{host.name}'",
            )

    @staticmethod
    def _validate_query_arguments(query: QueryPolicy, arguments: dict[str, str]) -> None:
        known_names = {policy.name for policy in query.arg_policies}
        extras = set(arguments) - known_names
        if extras:
            extra_names = ", ".join(sorted(extras))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unexpected query arguments: {extra_names}",
            )
        for policy in query.arg_policies:
            value = arguments.get(policy.name)
            if value is None:
                if policy.required:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Missing query argument '{policy.name}'",
                    )
                continue
            if re.fullmatch(policy.pattern, value) is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Query argument '{policy.name}' failed validation",
                )

    @staticmethod
    def _raise_remote_failure(exc: RemoteExecutionError) -> None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
