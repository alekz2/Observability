from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI

from remote_query_service.api.auth import get_actor
from remote_query_service.api.dependencies import get_service
from remote_query_service.core.logging import configure_error_logging
from remote_query_service.core.models import (
    Actor,
    CloseSessionRequest,
    HostInfo,
    OpenSessionRequest,
    QueryInfo,
    QueryResultResponse,
    ReadSessionRequest,
    RunQueryRequest,
    SearchLogsRequest,
    SearchLogsResponse,
    SessionResponse,
)
from remote_query_service.core.service import RemoteQueryService
from remote_query_service.core.settings import get_settings

_VERSION = "0.1.0"

logger = structlog.get_logger(__name__)
error_logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = get_settings()
    # Validate policy and API keys at startup; crash early on bad config.
    policy = settings.load_policy()
    settings.parsed_api_keys()
    logger.info("startup", host_count=len(policy.hosts), version=_VERSION)
    yield


def create_app() -> FastAPI:
    configure_error_logging(get_settings())
    app = FastAPI(
        title="Remote Query Service",
        version=_VERSION,
        lifespan=_lifespan,
    )

    @app.middleware("http")
    async def log_unhandled_exceptions(request, call_next):
        try:
            return await call_next(request)
        except Exception:
            error_logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
            raise

    @app.get("/healthz")
    async def healthcheck(service: RemoteQueryService = Depends(get_service)) -> dict[str, Any]:
        return {"status": "ok", "version": _VERSION, "host_count": len(service.host_names())}

    @app.get("/v1/hosts", response_model=list[HostInfo])
    async def list_hosts(
        actor: Actor = Depends(get_actor),
        service: RemoteQueryService = Depends(get_service),
    ) -> list[HostInfo]:
        return await service.list_hosts(actor)

    @app.get("/v1/hosts/{host_name}/queries", response_model=list[QueryInfo])
    async def list_queries(
        host_name: str,
        actor: Actor = Depends(get_actor),
        service: RemoteQueryService = Depends(get_service),
    ) -> list[QueryInfo]:
        logger.info("list_queries", actor=actor.subject, host=host_name)
        return await service.list_queries(host_name, actor)

    @app.post("/v1/sessions/open", response_model=SessionResponse)
    async def open_session(
        request: OpenSessionRequest,
        actor: Actor = Depends(get_actor),
        service: RemoteQueryService = Depends(get_service),
    ) -> SessionResponse:
        logger.info("open_session", actor=actor.subject, host=request.host, path=request.path)
        return await service.open_session(request, actor)

    @app.post("/v1/sessions/read", response_model=SessionResponse)
    async def read_session(
        request: ReadSessionRequest,
        actor: Actor = Depends(get_actor),
        service: RemoteQueryService = Depends(get_service),
    ) -> SessionResponse:
        logger.info("read_session", actor=actor.subject, session_id=request.session_id)
        return await service.read_session(request, actor)

    @app.post("/v1/logs/search", response_model=SearchLogsResponse)
    async def search_logs(
        request: SearchLogsRequest,
        actor: Actor = Depends(get_actor),
        service: RemoteQueryService = Depends(get_service),
    ) -> SearchLogsResponse:
        logger.info("search_logs", actor=actor.subject, host=request.host, path=request.path)
        return await service.search_logs(request, actor)

    @app.post("/v1/queries/run", response_model=QueryResultResponse)
    async def run_query(
        request: RunQueryRequest,
        actor: Actor = Depends(get_actor),
        service: RemoteQueryService = Depends(get_service),
    ) -> QueryResultResponse:
        logger.info("run_query", actor=actor.subject, host=request.host, query_name=request.query_name)
        return await service.run_query(request, actor)

    @app.post("/v1/sessions/close", status_code=204)
    async def close_session(
        request: CloseSessionRequest,
        actor: Actor = Depends(get_actor),
        service: RemoteQueryService = Depends(get_service),
    ) -> None:
        logger.info("close_session", actor=actor.subject, session_id=request.session_id)
        await service.close_session(request, actor)

    return app
