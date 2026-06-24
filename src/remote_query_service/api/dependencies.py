from __future__ import annotations

from functools import lru_cache

from redis.asyncio import from_url

from remote_query_service.core.audit import JsonlAuditSink, NullAuditSink
from remote_query_service.core.redaction import Redactor
from remote_query_service.core.service import RemoteQueryService
from remote_query_service.core.session_store import InMemorySessionStore, RedisSessionStore, SessionStore
from remote_query_service.core.settings import get_settings
from remote_query_service.remote.ssh import SSHRemoteLogClient


def _build_session_store(redis_url: str | None) -> SessionStore:
    if redis_url:
        return RedisSessionStore(from_url(redis_url, decode_responses=False))
    return InMemorySessionStore()


def _build_audit_sink(settings) -> JsonlAuditSink | NullAuditSink:
    if settings.audit_log_path:
        return JsonlAuditSink(settings.audit_log_path)
    return NullAuditSink()


@lru_cache(maxsize=1)
def get_service() -> RemoteQueryService:
    settings = get_settings()
    policy = settings.load_policy()
    return RemoteQueryService(
        settings=settings,
        hosts={host.name: host for host in policy.hosts},
        remote_client=SSHRemoteLogClient(),
        session_store=_build_session_store(settings.redis_url),
        redactor=Redactor(settings.compiled_redactions()),
        audit_sink=_build_audit_sink(settings),
    )

