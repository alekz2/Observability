from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class QueryArgumentPolicy(BaseModel):
    name: str
    pattern: str = Field(min_length=1, max_length=200)
    required: bool = True


class QueryPolicy(BaseModel):
    command: str | list[str]
    args: list[str] = Field(default_factory=list)
    arg_policies: list[QueryArgumentPolicy] = Field(default_factory=list)
    description: str | None = None


class QueryServicePolicy(BaseModel):
    description: str | None = None
    queries: dict[str, QueryPolicy] = Field(default_factory=dict, min_length=1)


class HostPolicy(BaseModel):
    name: str
    address: str
    os_family: Literal["posix", "windows"] = "posix"
    port: int = 22
    username: str | None = None
    private_key_path: str | None = None
    known_hosts_path: str | None = None
    allowed_paths: list[str] = Field(min_length=1)
    query_services: list[str] = Field(default_factory=list)
    allowed_queries: dict[str, QueryPolicy] = Field(default_factory=dict)

    def permits_path(self, path: str) -> bool:
        return any(fnmatch(path, pattern) for pattern in self.allowed_paths)

    def resolve_query(self, query_name: str) -> "QueryPolicy | None":
        return self.allowed_queries.get(query_name)

    def with_query_services(self, shared_services: dict[str, QueryServicePolicy]) -> "HostPolicy":
        merged_queries: dict[str, QueryPolicy] = {}
        for service_name in self.query_services:
            service = shared_services.get(service_name)
            if service is None:
                raise ValueError(f"Unknown query service '{service_name}' referenced by host '{self.name}'")
            overlap = set(merged_queries).intersection(service.queries)
            if overlap:
                overlap_names = ", ".join(sorted(overlap))
                raise ValueError(
                    f"Duplicate query names across query services for host '{self.name}': {overlap_names}"
                )
            merged_queries.update(service.queries)
        merged_queries.update(self.allowed_queries)
        return self.model_copy(update={"allowed_queries": merged_queries})


class PolicyDocument(BaseModel):
    query_services: dict[str, QueryServicePolicy] = Field(default_factory=dict)
    hosts: list[HostPolicy] = Field(min_length=1)

    @model_validator(mode="after")
    def expand_host_query_services(self) -> "PolicyDocument":
        expanded_hosts: list[HostPolicy] = []
        seen_host_names: set[str] = set()
        for host in self.hosts:
            if host.name in seen_host_names:
                raise ValueError(f"Duplicate host policy name '{host.name}'")
            seen_host_names.add(host.name)
            expanded_hosts.append(host.with_query_services(self.query_services))
        self.hosts = expanded_hosts
        return self


class OpenSessionRequest(BaseModel):
    host: str
    path: str
    start: Literal["end", "beginning"] = "end"
    lines: int = Field(default=200, ge=1, le=5000)


class ReadSessionRequest(BaseModel):
    session_id: str
    max_lines: int = Field(default=200, ge=1, le=5000)


class SearchLogsRequest(BaseModel):
    host: str
    path: str
    pattern: str = Field(min_length=1, max_length=512)
    max_matches: int = Field(default=20, ge=1, le=200)
    before: int = Field(default=2, ge=0, le=50)
    after: int = Field(default=2, ge=0, le=50)


class RunQueryRequest(BaseModel):
    host: str
    query_name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, str] = Field(default_factory=dict)
    max_lines: int = Field(default=200, ge=1, le=5000)


class CloseSessionRequest(BaseModel):
    session_id: str


class LogChunk(BaseModel):
    lines: list[str]
    next_offset: int
    file_size: int
    inode: str | None = None
    rotated: bool = False


class TailSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    host: str
    path: str
    offset: int
    inode: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    @classmethod
    def create(cls, host: str, path: str, offset: int, ttl_seconds: int, inode: str | None) -> "TailSession":
        created_at = datetime.now(timezone.utc)
        return cls(
            host=host,
            path=path,
            offset=offset,
            inode=inode,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=ttl_seconds),
        )

    @field_validator("expires_at")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now >= self.expires_at


class SessionResponse(BaseModel):
    session_id: str
    host: str
    path: str
    cursor: int
    line_count: int
    rotated: bool
    lines: list[str]


class SearchMatch(BaseModel):
    line_number: int
    lines: list[str]


class SearchLogsResponse(BaseModel):
    host: str
    path: str
    pattern: str
    match_count: int
    matches: list[SearchMatch]


class QueryInfo(BaseModel):
    name: str
    description: str | None = None
    command: str
    arg_names: list[str]


class QueryResultResponse(BaseModel):
    host: str
    query_name: str
    command: list[str]
    line_count: int
    lines: list[str]


class HostInfo(BaseModel):
    name: str
    address: str
    port: int
    allowed_paths: list[str]


class Actor(BaseModel):
    subject: str


class AuditEvent(BaseModel):
    actor: str
    action: Literal["list_hosts", "open_session", "read_session", "close_session", "search_logs", "list_queries", "run_query"]
    host: str | None = None
    path: str | None = None
    query_name: str | None = None
    session_id: str | None = None
    cursor: int | None = None
    line_count: int | None = None
    rotated: bool | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
