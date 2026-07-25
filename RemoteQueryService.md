# Remote Query Service

## Overview

This repository implements a read-only FastAPI service for remote query workflows. It exposes approved log access and a small catalog of pre-approved host commands over HTTP, then executes the work remotely over SSH under a policy defined in [`config/policy.json`](./config/policy.json).

The service is intentionally narrow:

- It only reads files that match allowlisted path patterns.
- It only runs queries defined in policy.
- Query arguments are regex-validated before execution.
- Output can be redacted before it leaves the service.
- Every API operation is audited to a JSONL audit log.

The policy file supports `${ENV_VAR}` substitution at load time, so host addresses, usernames, and key paths can be kept in `.env` rather than hardcoded in the policy. SSH connection defaults apply to any host that omits those fields.

The current implementation is packaged as `remote-query-service` and runs on Python 3.12+.

## Supported Functionality

1. Host discovery — list policy-approved remote hosts.
2. Tail-style log sessions — open a session on an approved log file, read incremental updates by cursor, detect log rotation through inode changes, and close sessions explicitly.
3. Log search — search an approved log file with a regex pattern across the full file, with before/after context around each match.
4. Approved remote queries — execute only named queries defined in policy, with positional/static args plus validated templated arguments.
5. Security and governance controls — optional bearer-token authentication, regex-based output redaction, JSONL audit trail, optional Redis-backed session storage.
6. SSH connection pooling — per-host connections are reused across requests for up to five minutes with SSH keepalives, then replaced on expiry or disconnection.
7. Automatic retry — transient SSH connection drops are retried up to twice with exponential backoff before the request fails.
8. Startup validation — bad policy files or malformed API key configuration terminate the process at boot rather than at first request.

## Runtime Architecture

### Main components

- [src/remote_query_service/api/app.py](src/remote_query_service/api/app.py) — FastAPI app, HTTP routes, and lifespan startup validation.
- [src/remote_query_service/api/auth.py](src/remote_query_service/api/auth.py) — resolves the caller identity from `Authorization: Bearer ...`.
- [src/remote_query_service/api/dependencies.py](src/remote_query_service/api/dependencies.py) — builds the singleton service, session store, redactor, and audit sink.
- [src/remote_query_service/core/service.py](src/remote_query_service/core/service.py) — main orchestration layer; enforces host/path/query policy and maps remote failures to HTTP 502.
- [src/remote_query_service/core/models.py](src/remote_query_service/core/models.py) — Pydantic request, response, policy, and session models.
- [src/remote_query_service/core/settings.py](src/remote_query_service/core/settings.py) — loads environment configuration, expands `${ENV_VAR}` tokens in the policy file, applies SSH defaults, and parses API keys.
- [src/remote_query_service/core/session_store.py](src/remote_query_service/core/session_store.py) — in-memory and Redis session persistence.
- [src/remote_query_service/core/redaction.py](src/remote_query_service/core/redaction.py) — applies regex redaction to returned lines.
- [src/remote_query_service/core/audit.py](src/remote_query_service/core/audit.py) — writes audit events as JSON Lines.
- [src/remote_query_service/remote/ssh.py](src/remote_query_service/remote/ssh.py) — SSH transport, per-host connection pool, retry logic, and remote helper implementation.

### Request flow

1. On startup, the lifespan handler validates the policy file and API key configuration; the process exits immediately on bad config.
2. FastAPI route receives the request.
3. `get_actor()` authenticates the caller.
4. `get_service()` returns the singleton service (built once, shared across requests).
5. `RemoteQueryService` validates host, path, query name, and query arguments.
6. `SSHRemoteLogClient` acquires a connection from the per-host pool (opening a new one if none is available or the cached one has expired or closed).
7. Approved queries are executed directly over SSH on the target host.
8. POSIX log operations use a small Python helper executed remotely through `python3 -c`.
9. On `ConnectionLost` or `DisconnectError`, the pool entry is evicted and the call is retried up to twice before failing.
10. The service redacts output, persists session state if needed, records an audit event, and returns the HTTP response.

## Configuration

Environment variables are loaded from `.env` or the process environment. The `REMOTE_QUERY_` prefix is used for service settings. Plain variable names (e.g. `SSH_USER`) are used for values referenced inside `policy.json` via `${...}` substitution.

### Service settings

| Variable | Default | Purpose |
|---|---|---|
| `REMOTE_QUERY_POLICY_PATH` | `config/policy.json` | Policy file location. |
| `REMOTE_QUERY_SESSION_TTL_SECONDS` | `1800` | Session lifetime in seconds. |
| `REMOTE_QUERY_MAX_CHUNK_BYTES` | `65536` | Max bytes fetched per SSH read chunk (initial/tail reads). Does not affect search. |
| `REMOTE_QUERY_DEFAULT_LINES` | `200` | Default line count returned per read. |
| `REMOTE_QUERY_REDACT_PATTERNS` | empty | `\|\|`-delimited regex patterns replaced with `[REDACTED]` in all output. |
| `REMOTE_QUERY_REDIS_URL` | empty | Enables Redis-backed session storage when set. |
| `REMOTE_QUERY_API_KEYS` | empty | Comma-separated `token:subject` pairs. Empty = anonymous access. |
| `REMOTE_QUERY_ERROR_LOG_PATH` | `var/error.log` | Rotating error log for unhandled exceptions and remote execution failures. |
| `REMOTE_QUERY_AUDIT_LOG_PATH` | `var/audit.log` | JSONL audit log path. |

### SSH defaults

These are applied to any host policy entry that omits the corresponding field. They are also available as `${REMOTE_QUERY_SSH_DEFAULT_USER}` etc. inside `policy.json`.

| Variable | Purpose |
|---|---|
| `REMOTE_QUERY_SSH_DEFAULT_USER` | Default SSH username for hosts that don't specify one. |
| `REMOTE_QUERY_SSH_DEFAULT_KEY_PATH` | Default private key path for hosts that don't specify one. |
| `REMOTE_QUERY_SSH_DEFAULT_KNOWN_HOSTS` | Default known-hosts file for hosts that don't specify one. |

### Example `.env`

```dotenv
# Service settings
REMOTE_QUERY_POLICY_PATH=config/policy.json
REMOTE_QUERY_SESSION_TTL_SECONDS=1800
REMOTE_QUERY_MAX_CHUNK_BYTES=65536
REMOTE_QUERY_DEFAULT_LINES=200
REMOTE_QUERY_REDACT_PATTERNS=(?i)authorization:\s*bearer\s+\S+||(?i)api[_-]?key['"]?\s*[:=]\s*['"]?[A-Za-z0-9_\-]+
REMOTE_QUERY_REDIS_URL=
REMOTE_QUERY_API_KEYS=secret-token:ops
REMOTE_QUERY_ERROR_LOG_PATH=var/error.log
REMOTE_QUERY_AUDIT_LOG_PATH=var/audit.log

# SSH values — expanded into ${SSH_USER}, ${SSH_KEY_PATH}, etc. inside policy.json
SSH_USER=alex
SSH_KEY_PATH=C:/Users/alexr/.ssh/id_rsa
WIN_HOME_USER=Alex
```

## Policy Model

[`config/policy.json`](config/policy.json) is the main authorization boundary for remote operations. A portable generic template is provided at [`config/policy.template.json`](config/policy.template.json).

### Environment variable substitution

Before the policy file is parsed, every `${NAME}` token is replaced with the value of the corresponding environment variable. If the variable is not set, the token is left as-is. This allows the policy to use placeholders like `${SSH_USER}` and `${SSH_KEY_PATH}` rather than hardcoding user-specific values:

```json
"username": "${SSH_USER}",
"private_key_path": "${SSH_KEY_PATH}",
"allowed_paths": ["/home/${SSH_USER}/app/logs/*.log"]
```

### Policy structure

The policy file has two layers:

- Root-level `query_services` — reusable query groups such as network, process, filesystem, or application-specific diagnostics.
- Per-host `hosts` — connection details, allowed log paths, and the list of shared services enabled for that host.

### Host policy fields

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Logical API-facing host name. |
| `address` | yes | SSH destination hostname or IP. Supports `${VAR}`. |
| `os_family` | no | `posix` (default) or `windows`. `posix` uses the Python log helper; `windows` enables Windows-safe query execution and rejects log operations. |
| `port` | no | SSH port (default `22`). |
| `username` | no | SSH username. Falls back to `REMOTE_QUERY_SSH_DEFAULT_USER` if omitted. Supports `${VAR}`. |
| `private_key_path` | no | SSH private key path. Falls back to `REMOTE_QUERY_SSH_DEFAULT_KEY_PATH` if omitted. Supports `${VAR}`. If neither is set, the SSH agent or default key is used. |
| `known_hosts_path` | no | Path to a known-hosts file. `null` disables host-key verification (default). `"UNSAFE_DISABLE"` is an explicit sentinel with the same effect. Any other string is treated as a file path. |
| `allowed_paths` | yes | Shell-style glob patterns checked with `fnmatch`. Supports `${VAR}`. |
| `query_services` | no | Names of root-level query service groups to attach to this host. |
| `allowed_queries` | no | Host-specific query catalog, merged on top of `query_services`. Can override shared queries by name. |

### Query policy fields

| Field | Purpose |
|---|---|
| `command` | String or argv list. Strings are tokenized with `shlex.split` at execution time. |
| `args` | Static or templated args such as `"{process_name}"`. |
| `description` | Returned by `/v1/hosts/{host}/queries`. |
| `arg_policies` | List of allowed runtime parameters — each with `name`, `pattern` (full-match regex), and `required`. |

### Policy enforcement

- Path authorization is glob-based (`fnmatch`). There is no path canonicalization.
- Query argument validation rejects missing required args, extra undeclared args, and values that do not fully match the configured pattern.
- Unknown `query_services` references in a host policy fail at startup.
- Duplicate query names from multiple attached services fail at startup.
- Unknown hosts → HTTP 404. Unknown queries → HTTP 404. Forbidden paths → HTTP 403. Bad arguments → HTTP 400. Remote failures → HTTP 502.

## Current Policy: `config/policy.json`

The live policy defines six reusable query service groups and eight hosts. All user-specific paths use `${SSH_USER}` (resolved from `.env`).

### Shared query service groups

| Service | Purpose | Representative queries |
|---|---|---|
| `host_identity` | Basic host naming | `hostname_short`, `hostname_fqdn` |
| `process_observability` | Process inspection | `ps_named` |
| `network_diagnostics` | Network and firewall | `ss_listen`, `ip_addr`, `ip_route`, `ping_host`, `tcp_connect_check`, `getent_hosts`, `getent_ahostsv4`, `nmcli_device_status`, `firewalld_*`, `iptables_input`, `nft_ruleset` |
| `filesystem_read` | System-path file access | `alloy_config` (reads `/etc/alloy/config.alloy` via sudo) |
| `geode_diagnostics` | Geode-specific checks | `curl_geode_ping`, `ss_geode` |
| `neovim_introspection` | Read-only Neovim and Mason installation/config inspection | `nvim_version`, `nvim_stdpaths`, `nvim_pack_get`, `nvim_dap_python_probe`, `nvim_dap_runtime_probe`, `nvim_dap_logs`, `nvim_config_files`, `nvim_lua_dirs`, `nvim_lua_files`, `nvim_read_lua_file`, `nvim_read_init_lua`, `nvim_read_init_vim`, `nvim_read_pack_lock`, `mason_package_dirs`, `mason_bin_links`, `mason_registry_dirs` |

### Hosts

#### `Apache_Geode`

| Field | Value |
|---|---|
| SSH target | `Antman:22` |
| Allowed paths | `/var/log/app/*.log`, `/var/log/nginx/access.log`, `/home/${SSH_USER}/geode_cluster/*.properties`, `/home/${SSH_USER}/geode_cluster/server1/*.log`, `/home/${SSH_USER}/geode_cluster/locator1/*.log` |
| Query services | `host_identity`, `process_observability`, `network_diagnostics`, `filesystem_read`, `geode_diagnostics` |

#### `Apache_Geode_Hulk`

| Field | Value |
|---|---|
| SSH target | `Hulk:22` |
| Allowed paths | `/var/log/app/*.log`, `/var/log/nginx/access.log`, `/home/${SSH_USER}/geode_cluster/server2/*.log`, `/home/${SSH_USER}/geode_cluster/locator2/*.log`, `/home/${SSH_USER}/geode/scripts/*.sh`, `/home/${SSH_USER}/.config/nvim/lua/*`, `/home/${SSH_USER}/.config/nvim/lua/**`, `/etc/alloy/config.alloy`, `/home/${SSH_USER}/Work/stress-test/logs/*.log` |
| Query services | `host_identity`, `process_observability`, `network_diagnostics`, `filesystem_read`, `geode_diagnostics`, `neovim_introspection` |

#### `Blackwidow`

| Field | Value |
|---|---|
| SSH target | `Blackwidow:22` |
| Allowed paths | `/home/${SSH_USER}/observability-lgtm/**` (alloy, grafana, loki, mimir, tempo, docker-compose.yml) |
| Query services | `filesystem_read` |
| Host-specific queries | `alloy_config`, `alloy_dir_list`, `docker_ps`, `docker_inspect_{grafana,loki,mimir,tempo,alloy}`, `find_lgtm_all`, `read_docker_compose`, `read_grafana_datasources`, `read_mimir_config` |

#### `Vision`

| Field | Value |
|---|---|
| SSH target | `Vision:22` |
| Allowed paths | `/home/${SSH_USER}/geode/scripts/*.sh`, `/home/${SSH_USER}/geode_cluster_b/serverB1/*.log`, `/home/${SSH_USER}/geode_cluster_b/locatorB/*.log` |
| Query services | `filesystem_read`, `host_identity`, `process_observability`, `network_diagnostics`, `geode_diagnostics` |

#### `Warmachine`

| Field | Value |
|---|---|
| SSH target | `Warmachine:22` |
| Allowed paths | `/home/${SSH_USER}/geode/scripts/*.sh`, `/home/${SSH_USER}/geode_cluster_b/serverB2/*.log` |
| Query services | `filesystem_read`, `host_identity`, `process_observability`, `network_diagnostics`, `geode_diagnostics` |

#### `Thor`

| Field | Value |
|---|---|
| SSH target | `Thor:22` |
| `os_family` | `windows` (log operations not supported) |
| Allowed paths | `C:/Users/${WIN_HOME_USER}/.ssh/*` |
| Host-specific queries | `hostname_short`, `portproxy_show_all`, `openssh_service`, `ssh_listeners`, `relay_processes`, `firewall_ssh_rules`, `wsl_status`, `wsl_list`, `vision_loopback_ssh_banner`, `warmachine_loopback_ssh_banner`, `vision_wsl_sshd_state`, `vision_wsl_listeners`, `warmachine_wsl_sshd_state`, `warmachine_wsl_listeners` |

`WIN_HOME_USER` is separate from `SSH_USER` because the Windows home directory path capitalizes the username (`Alex`) while the SSH login uses lowercase (`alex`).

## API Surface

All routes except `/healthz` require authentication when `REMOTE_QUERY_API_KEYS` is configured.

### `GET /healthz`

Health probe. Does not require authentication.

```json
{"status": "ok", "version": "0.1.0", "host_count": 8}
```

### `GET /v1/hosts`

Returns all configured hosts.

```json
[
  {
    "name": "Apache_Geode",
    "address": "Antman",
    "port": 22,
    "allowed_paths": ["/var/log/app/*.log", "..."]
  }
]
```

### `GET /v1/hosts/{host_name}/queries`

Returns the merged query catalog for one host.

```json
[
  {
    "name": "ps_named",
    "description": "List processes whose full command line matches a pattern",
    "command": "pgrep",
    "arg_names": ["process_name"]
  }
]
```

List-valued commands such as `["sudo", "firewall-cmd"]` are flattened to a space-separated string in the response.

### `POST /v1/sessions/open`

Opens a log session and returns the initial chunk.

Request:

```json
{
  "host": "Apache_Geode",
  "path": "/home/alex/geode_cluster/server1/server.log",
  "start": "end",
  "lines": 200
}
```

Response:

```json
{
  "session_id": "uuid",
  "host": "Apache_Geode",
  "path": "/home/alex/geode_cluster/server1/server.log",
  "cursor": 12345,
  "line_count": 20,
  "rotated": false,
  "lines": ["..."]
}
```

- `start="end"` (default) seeks to `max(file_size - max_chunk_bytes, 0)` and returns the last `lines` lines.
- `start="beginning"` reads from offset 0 and returns the first `lines` lines within `max_chunk_bytes`.
- The cursor is a byte offset, not a line number.

### `POST /v1/sessions/read`

Reads more lines from an existing session starting at its stored cursor.

Request:

```json
{"session_id": "uuid", "max_lines": 200}
```

If the remote inode has changed since the session was opened, `rotated=true` is set and reading restarts from offset 0.

### `POST /v1/sessions/close`

Deletes a session. Returns HTTP 204.

```json
{"session_id": "uuid"}
```

### `POST /v1/logs/search`

Searches an approved log file with a regex. The full file is scanned line-by-line using a memory-efficient streaming approach; there is no size cap on what can be matched.

Request:

```json
{
  "host": "Apache_Geode",
  "path": "/home/alex/geode_cluster/server1/server.log",
  "pattern": "ERROR",
  "max_matches": 20,
  "before": 2,
  "after": 2
}
```

Response:

```json
{
  "host": "Apache_Geode",
  "path": "/home/alex/geode_cluster/server1/server.log",
  "pattern": "ERROR",
  "match_count": 1,
  "matches": [
    {"line_number": 42, "lines": ["before line", "ERROR line", "after line"]}
  ]
}
```

Field limits: `max_matches` 1–200, `before`/`after` 0–50.

### `POST /v1/queries/run`

Runs a named approved query on a host.

Request:

```json
{
  "host": "Apache_Geode",
  "query_name": "tcp_connect_check",
  "arguments": {"name": "Vision", "port": "7070"},
  "max_lines": 200
}
```

Response:

```json
{
  "host": "Apache_Geode",
  "query_name": "tcp_connect_check",
  "command": ["nc", "-zv", "-w", "3", "Vision", "7070"],
  "line_count": 2,
  "lines": ["..."]
}
```

- Template args (e.g. `{name}`) are substituted server-side after argument validation.
- `stderr` lines are appended after `stdout` lines when they are not duplicates.
- Output is truncated first by `max_lines`, then by `max_chunk_bytes`.

## Authentication

- If `REMOTE_QUERY_API_KEYS` is empty, every request is treated as actor `anonymous` — suitable only for local development.
- If set, the service requires `Authorization: Bearer <token>` on every request except `/healthz`.
- Tokens map to audit subject names via `token:subject` pairs.

```dotenv
REMOTE_QUERY_API_KEYS=secret-token:ops,readonly-token:sre
```

## Redaction

All lines returned from log reads, searches, and query output pass through `Redactor` before the HTTP response is built.

- Patterns are split on `||` in `REMOTE_QUERY_REDACT_PATTERNS`.
- Each match is replaced with the literal string `[REDACTED]`.
- Patterns are compiled once at startup.

Default patterns from `.env.example` cover Bearer tokens in headers and `api_key=...` / `api-key:...` assignments.

## Session Storage

### In-memory (default)

Used when `REMOTE_QUERY_REDIS_URL` is empty. Session lifetime is enforced at fetch time. Suitable for single-process development only; sessions are lost on restart.

### Redis

Used when `REMOTE_QUERY_REDIS_URL` is set. Sessions are stored as JSON with a Redis TTL derived from `expires_at`, so rewriting a session preserves the original expiry window rather than extending it.

## Auditing

Each API action emits an `AuditEvent` to the JSONL sink:

`list_hosts` · `list_queries` · `open_session` · `read_session` · `close_session` · `search_logs` · `run_query`

Each line contains actor, action, host/path/query metadata, line counts, cursor position when applicable, rotation flag, and UTC timestamp.

## Error Logging

Unhandled exceptions and Uvicorn error events are written to a rotating logfile at `REMOTE_QUERY_ERROR_LOG_PATH` (default `var/error.log`). This is separate from the audit log.

| File | Content |
|---|---|
| `var/error.log` | Runtime failures, stack traces, remote execution errors. |
| `var/audit.log` | Structured actor/action events for all API activity. |

## Remote Execution Details

### SSH transport

[ssh.py](src/remote_query_service/remote/ssh.py) connects with `asyncssh` using the host's `username`, `private_key_path` (both optional — falls back to SSH agent/defaults if absent), and `known_hosts` configuration.

SSH keepalives are sent every 60 seconds on pooled connections. Connections are evicted from the pool after five minutes or when a disconnect is detected; the next request opens a fresh connection transparently.

`ConnectionLost` and `DisconnectError` trigger up to two retries with 0.5 s / 1.0 s backoff. `PermissionDenied` and `ProcessError` are not retried.

### Known-hosts handling

| `known_hosts_path` value | Behaviour |
|---|---|
| `null` (default) | Host-key verification disabled. |
| `"UNSAFE_DISABLE"` | Explicit opt-out; identical effect to `null`, but self-documenting in policy. |
| Any other string | Treated as a path to a known-hosts file and passed to `asyncssh.read_known_hosts`. |

### Remote helper

For POSIX log reads and searches, the service encodes a Python helper as base64 and executes it on the remote host via `python3 -c "..."`. No files are uploaded.

| Mode | Purpose |
|---|---|
| `initial` | Read the initial chunk for a new session (from start or end of file). |
| `read` | Read from a byte offset; detect inode-based log rotation. |
| `search` | Regex search using a streaming line iterator and a rolling context buffer — scans the entire file without a size cap. |

Approved queries bypass the helper entirely and are executed directly as argv on the remote host.

### Error mapping

All SSH and remote execution failures are normalized to `RemoteExecutionError` and surfaced to API callers as HTTP 502.

## Security Characteristics

### Positive controls

- No arbitrary shell command execution through the HTTP API.
- Query args are strict full-match regex validated; extra args are rejected.
- Log access is path allowlist only (glob via `fnmatch`).
- Output redaction is centralized and applied before every response.
- Audit logging is built in and covers all API operations.
- Bad configuration (invalid policy JSON, malformed API keys) terminates the process at startup.

### Operational caveats

- Path checks use `fnmatch` against the raw requested path string without canonicalization.
- POSIX log access requires `python3` to be available on the target host.
- Windows hosts support approved queries only; log session and log search operations are rejected.
- Several policy queries use `sudo` and depend on the remote sudoers configuration for the SSH user.
- Host-key verification is disabled by default (`known_hosts_path: null`). Set a known-hosts path per host or configure `REMOTE_QUERY_SSH_DEFAULT_KNOWN_HOSTS` to enable it across all hosts.

## Running the Service

### Development launch (Windows)

Use [`runme.cmd`](runme.cmd), which resolves all paths relative to its own location:

```cmd
runme.cmd
```

Equivalent manual invocation:

```powershell
$env:PYTHONPATH = "D:\Alex\Work\Tools\Observability\src"
$env:REMOTE_QUERY_POLICY_PATH = "D:\Alex\Work\Tools\Observability\config\policy.json"
python -m uvicorn remote_query_service.main:app --app-dir "$env:PYTHONPATH"
```

The service starts on `http://127.0.0.1:8000` by default. Pass `--host 0.0.0.0 --port 8080` to bind on a different interface or port.

On startup you will see a log line confirming the policy was loaded and how many hosts were registered:

```
startup host_count=8 version=0.1.0
```

If the policy file is invalid or `REMOTE_QUERY_API_KEYS` is malformed, the process exits immediately with a descriptive error.

### Policy changes require a restart

The policy file is read once at startup. There is no hot-reload endpoint. After editing `config/policy.json` (e.g. adding a new allowed path or host), stop the running process and relaunch:

```cmd
:: Stop the current uvicorn process (Ctrl-C in its terminal, or kill the process)
:: Then relaunch:
cd D:\Alex\Work\Tools\Observability
runme.cmd
```

Do not attempt to restart the service programmatically — ask the user to do it manually.

## API Usage Examples

### Health check

```powershell
curl.exe http://127.0.0.1:8000/healthz
```

### List hosts

```powershell
curl.exe -H "Authorization: Bearer secret-token" http://127.0.0.1:8000/v1/hosts
```

### List queries for a host

```powershell
curl.exe -H "Authorization: Bearer secret-token" http://127.0.0.1:8000/v1/hosts/Apache_Geode/queries
```

### Open a log session

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/sessions/open `
  -H "Authorization: Bearer secret-token" `
  -H "Content-Type: application/json" `
  -d '{"host":"Apache_Geode","path":"/home/alex/geode_cluster/server1/server.log","start":"end","lines":100}'
```

### Search a log file

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/logs/search `
  -H "Authorization: Bearer secret-token" `
  -H "Content-Type: application/json" `
  -d '{"host":"Apache_Geode_Hulk","path":"/home/alex/geode_cluster/server2/server.log","pattern":"ERROR","max_matches":10,"before":2,"after":2}'
```

### Run an approved query

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/queries/run `
  -H "Authorization: Bearer secret-token" `
  -H "Content-Type: application/json" `
  -d '{"host":"Apache_Geode","query_name":"ps_named","arguments":{"process_name":"java"},"max_lines":50}'
```

### Run a Windows query on Thor

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/queries/run `
  -H "Authorization: Bearer secret-token" `
  -H "Content-Type: application/json" `
  -d '{"host":"Thor","query_name":"wsl_list","max_lines":20}'
```

## Test Coverage

`tests/test_service.py` verifies:

- Open, read, and close session flow.
- Redaction behavior.
- Search behavior and auditing.
- Query execution and argument validation.
- Authentication enforcement.
- HTTP endpoint wiring for search, list queries, and run query.
- Mapping remote errors to HTTP 502.

```powershell
python -m pytest
```
