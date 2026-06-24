# Antman Example Outputs

Use this reference when you need concrete examples of what the API has returned from `Antman` during successful checks.

## Health

Endpoint:

```text
GET /healthz
```

Example response:

```json
{"status":"ok"}
```

## Registered host

Endpoint:

```text
GET /v1/hosts
```

Example response excerpt:

```json
[
  {
    "name": "Apache_Geode",
    "address": "Antman",
    "port": 22,
    "allowed_paths": [
      "/var/log/app/*.log",
      "/var/log/nginx/access.log",
      "/home/alex/geode_cluster/server1/*.log",
      "/home/alex/geode_cluster/locator1/*.log"
    ]
  }
]
```

## Server log session

Endpoint:

```text
POST /v1/sessions/open
```

Request body:

```json
{
  "host": "Apache_Geode",
  "path": "/home/alex/geode_cluster/server1/server1.log",
  "start": "end",
  "lines": 20
}
```

Example response excerpt:

```json
{
  "host": "Apache_Geode",
  "path": "/home/alex/geode_cluster/server1/server1.log",
  "line_count": 20,
  "rotated": false,
  "lines": [
    "[info 2026/03/26 08:29:43.991 EDT server1 <main> tid=0x1] Completed initialization in 3054 ms",
    "[info 2026/03/26 08:29:44.048 EDT server1 <main> tid=0x1] Cache server connection listener bound to address Antman-0.0.0.0/0.0.0.0:40404 with backlog 1280.",
    "[warn 2026/03/26 08:29:44.059 EDT server1 <main> tid=0x1] Handshaker max Pool size: 4",
    "[info 2026/03/26 08:29:44.106 EDT server1 <main> tid=0x1] Server server1 startup completed in 12451 ms"
  ]
}
```

## Server log search

Endpoint:

```text
POST /v1/logs/search
```

Request body:

```json
{
  "host": "Apache_Geode",
  "path": "/home/alex/geode_cluster/server1/server1.log",
  "pattern": "(?i)warn|error",
  "max_matches": 5,
  "before": 1,
  "after": 1
}
```

Example response excerpt:

```json
{
  "match_count": 2,
  "matches": [
    {
      "line_number": 432,
      "lines": [
        "",
        "[warn 2026/03/21 17:36:43.950 EDT server1 <main> tid=0x1] Handshaker max Pool size: 4",
        ""
      ]
    }
  ]
}
```

## Process query

Endpoint:

```text
POST /v1/queries/run
```

Request body:

```json
{
  "host": "Apache_Geode",
  "query_name": "ps_named",
  "arguments": {
    "process_name": "geode"
  },
  "max_lines": 20
}
```

Example response excerpt:

```json
{
  "command": ["pgrep", "-a", "-f", "geode"],
  "line_count": 2,
  "lines": [
    "2436 ... LocatorLauncher start locator1 --port=10334",
    "2586 ... ServerLauncher start server1 --server-port=40404"
  ]
}
```

## Socket query

Endpoint:

```text
POST /v1/queries/run
```

Request body:

```json
{
  "host": "Apache_Geode",
  "query_name": "ss_listen",
  "arguments": {},
  "max_lines": 30
}
```

## Connectivity checks from Hulk to Antman

### Ping

Endpoint:

```text
POST /v1/queries/run
```

Request body:

```json
{
  "host": "Apache_Geode_Hulk",
  "query_name": "ping_host",
  "arguments": {
    "name": "Antman"
  },
  "max_lines": 20
}
```

Example response excerpt:

```json
{
  "command": ["ping", "-c", "2", "-W", "2", "Antman"],
  "lines": [
    "PING Antman (192.168.0.150) 56(84) bytes of data.",
    "64 bytes from Antman (192.168.0.150): icmp_seq=1 ttl=64 time=0.742 ms",
    "64 bytes from Antman (192.168.0.150): icmp_seq=2 ttl=64 time=0.321 ms"
  ]
}
```

### TCP connect check

Endpoint:

```text
POST /v1/queries/run
```

Request body:

```json
{
  "host": "Apache_Geode_Hulk",
  "query_name": "tcp_connect_check",
  "arguments": {
    "name": "Antman",
    "port": "10334"
  },
  "max_lines": 20
}
```

Example response excerpt:

```json
{
  "command": ["nc", "-zv", "-w", "3", "Antman", "10334"],
  "lines": [
    "Ncat: Version 7.92 ( https://nmap.org/ncat )",
    "Ncat: Connected to 192.168.0.150:10334.",
    "Ncat: 0 bytes sent, 0 bytes received in 0.01 seconds."
  ]
}
```

### Geode REST ping

Endpoint:

```text
POST /v1/queries/run
```

Request body:

```json
{
  "host": "Apache_Geode_Hulk",
  "query_name": "curl_geode_ping",
  "arguments": {
    "name": "Antman",
    "port": "7071"
  },
  "max_lines": 20
}
```

Example response excerpt:

```json
{
  "command": ["curl", "-i", "-s", "http://Antman:7071/geode/v1/ping"],
  "lines": [
    "HTTP/1.1 200 OK",
    "Server: Jetty(9.4.57.v20241219)"
  ]
}
```

Example response excerpt:

```json
{
  "command": ["ss", "-ltnp"],
  "lines": [
    "LISTEN ... *:1099 ... users:((\"java\",pid=2436,fd=107))",
    "LISTEN ... *:40404 ... users:((\"java\",pid=2586,fd=214))",
    "LISTEN ... *:7070 ... users:((\"java\",pid=2436,fd=125))",
    "LISTEN ... *:9404 ... users:((\"java\",pid=2586,fd=101))"
  ]
}
```
