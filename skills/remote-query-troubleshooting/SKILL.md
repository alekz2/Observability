---
name: remote-query-troubleshooting
description: Use when troubleshooting network reachability, service connectivity, process state, or log output on lab hosts through the local Remote Query Service API. Covers the common workflow for Antman, Hulk, and any other host exposed by the live policy.
---

# Remote Query Troubleshooting

Use this skill when the task is to troubleshoot a remote host through the local API service at `http://127.0.0.1:8000`.

This skill is the default for:

- network and connectivity checks
- process discovery
- listening-port inspection
- log inspection and log search
- Geode troubleshooting which needs correlation across logs, processes, and sockets

## Scope

- Verify the API is reachable
- Inspect configured hosts and approved queries
- Run process, socket, DNS, ICMP, and TCP checks through the API
- Read and search approved log files
- Correlate log findings with running processes and listener ports

Use the API first. Only use direct SSH when the user explicitly asks for it.

## Known environment

- API base URL: `http://127.0.0.1:8000`
- Common Geode host names in the API:
  - `Apache_Geode` for `Antman`
  - `Apache_Geode_Hulk` for `Hulk`
  - `WSL2_Vision` for `Vision` when configured

Known Geode log paths currently used in this lab:

- `Antman` server log: `/home/alex/geode_cluster/server1/server1.log`
- `Antman` locator logs: `/home/alex/geode_cluster/locator1/*.log`
- `Hulk` server log: `/home/alex/geode_cluster/server2/server2.log`
- `Hulk` locator logs: `/home/alex/geode_cluster/locator2/*.log`

If `/v1/hosts` exposes different hosts, paths, or queries than expected, trust the live API response over repo assumptions.

## Default workflow

1. Check service health:

```powershell
curl http://127.0.0.1:8000/healthz
```

2. Confirm the host is registered and inspect allowed paths:

```powershell
curl http://127.0.0.1:8000/v1/hosts
```

3. List approved queries for the target host:

```powershell
curl http://127.0.0.1:8000/v1/hosts/Apache_Geode/queries
```

4. Check the target process:

```powershell
curl -X POST http://127.0.0.1:8000/v1/queries/run `
  -H "Content-Type: application/json" `
  -d "{\"host\":\"Apache_Geode\",\"query_name\":\"ps_named\",\"arguments\":{\"process_name\":\"geode\"},\"max_lines\":20}"
```

5. Check listening ports:

```powershell
curl -X POST http://127.0.0.1:8000/v1/queries/run `
  -H "Content-Type: application/json" `
  -d "{\"host\":\"Apache_Geode\",\"query_name\":\"ss_listen\",\"arguments\":{},\"max_lines\":30}"
```

6. Read the latest log lines from an approved path:

```powershell
curl -X POST http://127.0.0.1:8000/v1/sessions/open `
  -H "Content-Type: application/json" `
  -d "{\"host\":\"Apache_Geode\",\"path\":\"/home/alex/geode_cluster/server1/server1.log\",\"start\":\"end\",\"lines\":20}"
```

7. Search the log for warnings or errors:

```powershell
curl -X POST http://127.0.0.1:8000/v1/logs/search `
  -H "Content-Type: application/json" `
  -d "{\"host\":\"Apache_Geode\",\"path\":\"/home/alex/geode_cluster/server1/server1.log\",\"pattern\":\"(?i)warn|error\",\"max_matches\":10,\"before\":1,\"after\":1}"
```

8. If connectivity is relevant, run DNS, ICMP, and TCP checks from the source host:

```powershell
curl -X POST http://127.0.0.1:8000/v1/queries/run `
  -H "Content-Type: application/json" `
  -d "{\"host\":\"Apache_Geode_Hulk\",\"query_name\":\"getent_hosts\",\"arguments\":{\"name\":\"Antman\"},\"max_lines\":20}"
```

```powershell
curl -X POST http://127.0.0.1:8000/v1/queries/run `
  -H "Content-Type: application/json" `
  -d "{\"host\":\"Apache_Geode_Hulk\",\"query_name\":\"ping_host\",\"arguments\":{\"name\":\"Antman\"},\"max_lines\":20}"
```

```powershell
curl -X POST http://127.0.0.1:8000/v1/queries/run `
  -H "Content-Type: application/json" `
  -d "{\"host\":\"Apache_Geode_Hulk\",\"query_name\":\"tcp_connect_check\",\"arguments\":{\"name\":\"Antman\",\"port\":\"10334\"},\"max_lines\":20}"
```

## Troubleshooting patterns

### Network and connectivity

- Use `getent_hosts` to verify name resolution from the remote host.
- Use `ping_host` when ICMP reachability matters.
- Use `tcp_connect_check` to confirm the target listener is reachable.
- Use service-specific checks such as `curl_geode_ping` when a protocol-level response matters more than raw port reachability.

### Process inspection

- Use `ps_named` for a targeted process search.
- Match PIDs from `ps_named` with `ss_listen` output to prove which process owns which listener.
- For Geode, distinguish locator and server JVMs explicitly.

### Log inspection

- Use `/v1/sessions/open` for tail-style inspection.
- Use `/v1/sessions/read` only after a session is open and you want appended lines.
- Use `/v1/logs/search` for focused error or warning searches.
- Always keep the log path inside the host allowlist returned by `/v1/hosts`.

## Geode-specific signals

- Locator command lines usually include `LocatorLauncher start locator1 --port=10334`
- Server command lines may include:
  - `ServerLauncher start server1 --server-port=40404`
  - `ServerLauncher start server2 --server-port=40405`
- Common listener ports in this lab:
  - `10334` locator
  - `1099` JMX manager
  - `7070` or `7071` HTTP service
  - `40404` `server1`
  - `40405` `server2`
  - `9404` exporter

## Interpreting failures

- `500` usually means the API encountered an internal execution failure. Check the service log.
- `502` usually means the API reached the remote execution layer but the remote command or SSH path failed.
- `404` for host or query names means the live policy does not expose the requested object.
- `403` on log access means the path is outside the configured allowlist.
- Empty `/v1/sessions/read` results usually mean no new lines were appended after the session opened.

## Reporting guidance

- State the exact endpoint used.
- Include the host, query name, log path, and any important PID, port, or peer hostname.
- Correlate findings across:
  - logs
  - `ps_named`
  - `ss_listen`
  - connectivity checks such as `getent_hosts`, `ping_host`, `tcp_connect_check`, and `curl_geode_ping`

## Reference data

When you need concrete examples of successful API output from `Antman`, read:

- `references/antman-example-outputs.md`
