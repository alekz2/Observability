from __future__ import annotations

import asyncio
import base64
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field

import asyncssh

from remote_query_service.core.models import HostPolicy, LogChunk, QueryPolicy, SearchMatch
from remote_query_service.remote.base import RemoteExecutionError, RemoteLogClient

# Errors that indicate a dropped connection and are safe to retry.
_RETRYABLE = (asyncssh.ConnectionLost, asyncssh.DisconnectError)
_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 0.5  # seconds; doubles each attempt

# Pooled connections are reused for up to this many seconds.
_POOL_TTL = 300.0

REMOTE_HELPER = r"""
import base64
import collections
import json
import os
import re
import shlex
import subprocess
import sys

mode = sys.argv[1]
path = sys.argv[2]
max_bytes = int(sys.argv[3])

def encode(lines):
    return [base64.b64encode(line.rstrip(b"\n").decode("utf-8", errors="replace").encode("utf-8")).decode("ascii") for line in lines]

if mode == "initial":
    st = os.stat(path)
    inode = str(getattr(st, "st_ino", ""))
    size = st.st_size
    start = sys.argv[4]
    lines = int(sys.argv[5])
    with open(path, "rb") as fh:
        if start == "beginning":
            data = fh.read(max_bytes)
            next_offset = fh.tell()
            raw_lines = data.splitlines()
            if len(raw_lines) > lines:
                raw_lines = raw_lines[:lines]
        else:
            seek_from = max(size - max_bytes, 0)
            fh.seek(seek_from)
            data = fh.read(max_bytes)
            next_offset = size
            raw_lines = data.splitlines()[-lines:]
    print(json.dumps({
        "lines": encode(raw_lines),
        "next_offset": next_offset,
        "file_size": size,
        "inode": inode,
        "rotated": False,
    }))
    raise SystemExit(0)

if mode == "search":
    pattern = sys.argv[4]
    max_matches = int(sys.argv[5])
    before_ctx = int(sys.argv[6])
    after_ctx = int(sys.argv[7])
    regex = re.compile(pattern)
    before_buf = collections.deque(maxlen=before_ctx) if before_ctx > 0 else collections.deque(maxlen=0)
    matches = []
    # pending: list of dicts with keys "entry" (the match dict) and "remaining" (after-lines left)
    pending = []
    with open(path, "rb") as fh:
        for line_num, raw_line in enumerate(fh, start=1):
            line_str = raw_line.rstrip(b"\n").decode("utf-8", errors="replace")
            line_bytes = line_str.encode("utf-8")
            # Feed this line as after-context to any pending matches.
            next_pending = []
            for p in pending:
                p["entry"]["lines"].append(line_bytes)
                p["remaining"] -= 1
                if p["remaining"] > 0:
                    next_pending.append(p)
            pending = next_pending
            if len(matches) < max_matches and regex.search(line_str):
                entry = {
                    "line_number": line_num,
                    "lines": [b.encode("utf-8") for b in list(before_buf)] + [line_bytes],
                }
                matches.append(entry)
                if after_ctx > 0:
                    pending.append({"entry": entry, "remaining": after_ctx})
            before_buf.append(line_str)
    print(json.dumps({"matches": [{"line_number": m["line_number"], "lines": encode(m["lines"])} for m in matches]}))
    raise SystemExit(0)

if mode == "query":
    payload = json.loads(sys.argv[4])
    max_lines = int(sys.argv[5])
    command = payload["command"]
    if isinstance(command, list):
        argv = [*command, *payload.get("args", [])]
    else:
        argv = [*shlex.split(command), *payload.get("args", [])]
    completed = subprocess.run(
        argv,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines = completed.stdout.splitlines()
    stderr_lines = completed.stderr.splitlines()
    for line in stderr_lines:
        if line not in output_lines:
            output_lines.append(line)
    output_lines = output_lines[:max_lines]
    while sum(len(line.encode("utf-8")) for line in output_lines) > max_bytes and output_lines:
        output_lines.pop()
    print(json.dumps({
        "command": argv,
        "lines": encode([line.encode("utf-8") for line in output_lines]),
    }))
    raise SystemExit(0)

offset = int(sys.argv[4])
max_lines = int(sys.argv[5])
expected_inode = sys.argv[6] or None
st = os.stat(path)
inode = str(getattr(st, "st_ino", ""))
size = st.st_size
rotated = expected_inode is not None and inode != expected_inode
with open(path, "rb") as fh:
    if rotated:
        offset = 0
    fh.seek(min(offset, size))
    data = fh.read(max_bytes)
    next_offset = fh.tell()
raw_lines = data.splitlines()[:max_lines]
print(json.dumps({
    "lines": encode(raw_lines),
    "next_offset": next_offset,
    "file_size": size,
    "inode": inode,
    "rotated": rotated,
}))
"""


@dataclass
class _PoolEntry:
    connection: asyncssh.SSHClientConnection
    expires_at: float = field(default_factory=lambda: time.monotonic() + _POOL_TTL)

    def is_usable(self) -> bool:
        return not self.connection.is_closed() and time.monotonic() < self.expires_at


class SSHRemoteLogClient(RemoteLogClient):
    _TEMPLATE_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def __init__(self) -> None:
        self._pool: dict[tuple[str, int, str], _PoolEntry] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection pool
    # ------------------------------------------------------------------

    @staticmethod
    def _pool_key(host: HostPolicy) -> tuple[str, int, str]:
        return (host.address, host.port, host.username or "")

    @staticmethod
    def _resolve_known_hosts(host: HostPolicy):
        # None or "UNSAFE_DISABLE" both disable host-key verification (preserves original behaviour).
        # Any other string is treated as a path to a known_hosts file.
        if host.known_hosts_path is None or host.known_hosts_path == "UNSAFE_DISABLE":
            return None
        return asyncssh.read_known_hosts(host.known_hosts_path)

    async def _open_connection(self, host: HostPolicy) -> asyncssh.SSHClientConnection:
        known_hosts = self._resolve_known_hosts(host)
        connect_kwargs: dict = {
            "host": host.address,
            "port": host.port,
            "known_hosts": known_hosts,
            "keepalive_interval": 60,
        }
        if host.username:
            connect_kwargs["username"] = host.username
        if host.private_key_path:
            connect_kwargs["client_keys"] = [host.private_key_path]
        return await asyncssh.connect(**connect_kwargs)

    async def _get_connection(self, host: HostPolicy) -> asyncssh.SSHClientConnection:
        key = self._pool_key(host)
        async with self._lock:
            entry = self._pool.get(key)
            if entry is not None and entry.is_usable():
                return entry.connection
            conn = await self._open_connection(host)
            self._pool[key] = _PoolEntry(connection=conn)
            return conn

    def _invalidate(self, host: HostPolicy) -> None:
        self._pool.pop(self._pool_key(host), None)

    # ------------------------------------------------------------------
    # Remote execution with retry
    # ------------------------------------------------------------------

    async def _run_remote_command(self, host: HostPolicy, remote_command: str) -> asyncssh.SSHCompletedProcess:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                conn = await self._get_connection(host)
                return await conn.run(remote_command, check=True)
            except _RETRYABLE as exc:
                self._invalidate(host)
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2**attempt))
            except asyncssh.PermissionDenied as exc:
                raise RemoteExecutionError(
                    f"Permission denied for user '{host.username}' on host {host.address}"
                ) from exc
            except asyncssh.ProcessError as exc:
                stderr = (exc.stderr or "").strip()
                raise RemoteExecutionError(
                    f"Remote command failed on host {host.address}: {stderr or exc}"
                ) from exc
            except asyncssh.Error as exc:
                raise RemoteExecutionError(f"SSH error on host {host.address}: {exc}") from exc
            except Exception as exc:
                raise RemoteExecutionError(
                    f"Unexpected error on host {host.address}: {type(exc).__name__}: {exc}"
                ) from exc
        raise RemoteExecutionError(
            f"SSH connection to {host.address} lost after {_MAX_RETRIES} retries"
        ) from last_exc

    async def _run_helper(self, host: HostPolicy, command: str, args: list[str]) -> dict:
        if host.os_family != "posix":
            raise RemoteExecutionError(f"Log access is not supported for Windows host {host.address}")
        encoded_helper = base64.b64encode(command.encode("utf-8")).decode("ascii")
        quoted_args = " ".join(shlex.quote(arg) for arg in args)
        remote_command = (
            "python3 -c \"import base64; exec(base64.b64decode('"
            + encoded_helper
            + "').decode('utf-8'))\" "
            + quoted_args
        )
        result = await self._run_remote_command(host, remote_command)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RemoteExecutionError(f"Invalid response from host {host.address}: {exc}") from exc

    # ------------------------------------------------------------------
    # Template helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_template(value: str, arguments: dict[str, str]) -> str:
        return SSHRemoteLogClient._TEMPLATE_PATTERN.sub(
            lambda match: arguments.get(match.group(1), match.group(0)),
            value,
        )

    @staticmethod
    def _format_query_argv(host: HostPolicy, query: QueryPolicy, arguments: dict[str, str]) -> list[str]:
        formatted_args = [SSHRemoteLogClient._format_template(item, arguments) for item in query.args]
        if isinstance(query.command, list):
            return [*query.command, *formatted_args]
        return [
            *shlex.split(
                SSHRemoteLogClient._format_template(query.command, arguments),
                posix=host.os_family == "posix",
            ),
            *formatted_args,
        ]

    @staticmethod
    def _build_query_command(host: HostPolicy, argv: list[str]) -> str:
        if host.os_family == "windows":
            return subprocess.list2cmdline(argv)
        return shlex.join(argv)

    @staticmethod
    def _truncate_output(stdout: str, stderr: str, max_lines: int, max_bytes: int) -> list[str]:
        output_lines = stdout.splitlines()
        stderr_lines = stderr.splitlines()
        for line in stderr_lines:
            if line not in output_lines:
                output_lines.append(line)
        output_lines = output_lines[:max_lines]
        while sum(len(line.encode("utf-8")) for line in output_lines) > max_bytes and output_lines:
            output_lines.pop()
        return output_lines

    @staticmethod
    def _to_chunk(payload: dict) -> LogChunk:
        lines = [
            base64.b64decode(encoded.encode("ascii")).decode("utf-8", errors="replace")
            for encoded in payload["lines"]
        ]
        return LogChunk(
            lines=lines,
            next_offset=payload["next_offset"],
            file_size=payload["file_size"],
            inode=payload.get("inode"),
            rotated=payload.get("rotated", False),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def read_initial(self, host: HostPolicy, path: str, start: str, lines: int, max_bytes: int) -> LogChunk:
        payload = await self._run_helper(
            host,
            REMOTE_HELPER,
            ["initial", path, str(max_bytes), start, str(lines)],
        )
        return self._to_chunk(payload)

    async def read_from_offset(
        self,
        host: HostPolicy,
        path: str,
        offset: int,
        max_lines: int,
        max_bytes: int,
        expected_inode: str | None,
    ) -> LogChunk:
        payload = await self._run_helper(
            host,
            REMOTE_HELPER,
            ["read", path, str(max_bytes), str(offset), str(max_lines), expected_inode or ""],
        )
        return self._to_chunk(payload)

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
        payload = await self._run_helper(
            host,
            REMOTE_HELPER,
            ["search", path, str(max_bytes), pattern, str(max_matches), str(before), str(after)],
        )
        return [
            SearchMatch(
                line_number=item["line_number"],
                lines=[
                    base64.b64decode(encoded.encode("ascii")).decode("utf-8", errors="replace")
                    for encoded in item["lines"]
                ],
            )
            for item in payload["matches"]
        ]

    async def run_query(
        self,
        host: HostPolicy,
        query: QueryPolicy,
        arguments: dict[str, str],
        max_lines: int,
        max_bytes: int,
    ) -> tuple[list[str], list[str]]:
        command = self._format_query_argv(host, query, arguments)
        result = await self._run_remote_command(host, self._build_query_command(host, command))
        return command, self._truncate_output(result.stdout, result.stderr, max_lines, max_bytes)
