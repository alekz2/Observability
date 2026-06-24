# Thor WSL SSH Connectivity Postmortem

Date: April 18, 2026
Status: Resolved
Scope: Ironman to Thor-hosted WSL SSH forwarding for Vision and Warmachine

## Summary

SSH connectivity from `Ironman` (`192.168.0.53`) to the WSL-hosted Linux distributions on `Thor` (`192.168.0.14`) was failing on the externally exposed ports:

- `50022` for `Vision`
- `60022` for `Warmachine`

Local checks on `Thor` showed that both backend SSH relays were healthy on loopback, but remote TCP connectivity from `Ironman` failed. The root cause was a bad Windows `portproxy` binding strategy on `Thor`: the SSH forward rules were bound to `listenaddress=192.168.0.14`, which did not work for the loopback-backed `wslrelay.exe` listeners. Rebinding those rules to `listenaddress=0.0.0.0` restored both TCP reachability and end-to-end SSH access.

In parallel, the local Query Service policy in this repository was incomplete for the Cluster B side. It exposed `WSL2_Vision:50022` but did not expose `Warmachine`, `Thor`, or the `60022` path. The policy was updated and the live Query Service process was restarted so the API could use the repaired SSH path.

## Impact

- `Ironman` could not reach `Vision` over `192.168.0.14:50022`.
- `Ironman` could not reach `Warmachine` over `192.168.0.14:60022`.
- The live Query Service could not execute SSH-backed queries against Cluster B WSL targets after policy expansion, because the underlying TCP path was refusing connections.
- Any automation or troubleshooting workflow depending on Query Service access to `Vision` and `Warmachine` was blocked.

## Environment

- `Ironman`
  - IP: `192.168.0.53`
  - Role: Primary Windows 11 lab host
- `Thor`
  - IP: `192.168.0.14`
  - Role: Windows 11 host running WSL2
- `Vision`
  - Access path: `Thor:50022`
  - Role: Ubuntu 24.04 WSL distro
- `Warmachine`
  - Access path: `Thor:60022`
  - Role: RHEL8 WSL distro

## Initial Symptoms

Observed from `Ironman`:

```text
Test-NetConnection 192.168.0.14 -Port 50022 => TcpTestSucceeded : False
Test-NetConnection 192.168.0.14 -Port 60022 => TcpTestSucceeded : False
```

Observed from `Thor`:

- `localhost:50022` succeeded
- `localhost:60022` succeeded
- Both listeners were owned by `wslrelay.exe`

This immediately suggested that the backend WSL relay process was healthy and the failure existed between LAN-facing Windows networking and the loopback-backed relay path.

## Problem Statement

The WSL SSH relay listeners on `Thor` were reachable only on loopback. The intended Windows `portproxy` rules that should have made those services reachable over the LAN were present, but remote and self-referential LAN tests to `192.168.0.14:50022` and `192.168.0.14:60022` still failed.

At the same time, the Query Service policy did not fully model the actual Cluster B access topology, which prevented direct API-based troubleshooting of `Warmachine` until the policy was expanded.

## Investigation Timeline

### 1. Verified Query Service state and policy gap

The live Query Service at `http://127.0.0.1:8000` was healthy, but `GET /v1/hosts` showed:

- `WSL2_Vision` on `50022`
- no `Warmachine`
- no `Thor`

The checked-in policy was then updated to add:

- `Warmachine` on `60022`
- `Thor` on `22`

The shipped-policy test was also updated to validate those new entries.

### 2. Confirmed the issue was not a Query Service-only problem

An API retry against `WSL2_Vision` after policy updates failed with an internal error which, once inspected, mapped to:

```text
ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
```

That confirmed the failure was in the underlying network or forwarding path, not in the API request shape.

### 3. Switched to step-by-step troubleshooting on Thor

Direct operator checks on `Thor` showed:

- `Get-NetTCPConnection` reported listeners on:
  - `127.0.0.1:50022`
  - `::1:50022`
  - `127.0.0.1:60022`
  - `::1:60022`
- all owned by `wslrelay.exe`

This proved:

- the WSL-side SSH service exposure existed
- only loopback listeners were present

### 4. Inspected Windows portproxy configuration

`netsh interface portproxy show all` showed:

- `192.168.0.14:50022 -> 127.0.0.1:50022`
- `192.168.0.14:60022 -> 127.0.0.1:60022`

These rules looked correct at first glance, but LAN tests still failed.

### 5. Ruled out Windows Firewall as the blocker

Checks on `Thor` showed:

- active Wi-Fi network category: `Private`
- inbound allow rules present for:
  - `Vision SSH 50022`
  - `Warmachine SSH 60022`

So the failure was not caused by missing firewall exceptions on those ports.

### 6. Proved the failure was specific to the SSH portproxy bindings

Additional control tests on `Thor` showed:

- direct backend connectivity to `172.22.79.100:5432` succeeded
- a known-good `portproxy` path on `192.168.0.14:6432` succeeded
- loopback access to `127.0.0.1:50022` and `127.0.0.1:60022` succeeded
- LAN access to `192.168.0.14:50022` and `192.168.0.14:60022` failed

This narrowed the problem to the specific SSH `portproxy` rules rather than:

- Windows networking in general
- `iphlpsvc`
- all portproxy behavior
- the backend WSL services

### 7. Tested an alternate listen binding

A temporary control rule was added:

```text
0.0.0.0:65022 -> 127.0.0.1:50022
```

Then:

```text
Test-NetConnection 192.168.0.14 -Port 65022 => TcpTestSucceeded : True
```

That was the decisive test. It proved:

- `portproxy` could forward traffic to `127.0.0.1:50022`
- the problem was not the loopback `connectaddress`
- the problem was the original `listenaddress=192.168.0.14`

### 8. Applied the fix

The broken rules were removed and recreated as:

```text
0.0.0.0:50022 -> 127.0.0.1:50022
0.0.0.0:60022 -> 127.0.0.1:60022
```

After the change, tests on `Thor` succeeded:

- `Test-NetConnection 192.168.0.14 -Port 50022 => True`
- `Test-NetConnection 192.168.0.14 -Port 60022 => True`

### 9. Validated from Ironman

From `Ironman`, both ports became reachable:

- `192.168.0.14:50022 => True`
- `192.168.0.14:60022 => True`

SSH validation also succeeded:

- `ssh -p 50022 alex@192.168.0.14 hostname => Vision`
- `ssh -p 60022 alex@192.168.0.14 hostname => Warmachine`

### 10. Restored live Query Service validation

The Query Service process was restarted so it would reload the updated policy. After restart:

- `GET /v1/hosts` included `Warmachine` and `Thor`
- live Query Service calls succeeded:
  - `WSL2_Vision` `hostname_short => Vision`
  - `Warmachine` `hostname_short => Warmachine`

## Root Cause

The immediate root cause was an incompatible `portproxy` listen binding on `Thor`.

The SSH proxy rules were configured as:

```text
192.168.0.14:50022 -> 127.0.0.1:50022
192.168.0.14:60022 -> 127.0.0.1:60022
```

Although those rules were present, they did not successfully accept or forward LAN traffic for the loopback-backed `wslrelay.exe` listeners. Replacing the listen address with `0.0.0.0` fixed the issue immediately:

```text
0.0.0.0:50022 -> 127.0.0.1:50022
0.0.0.0:60022 -> 127.0.0.1:60022
```

### Why `0.0.0.0` worked and `192.168.0.14` did not

Microsoft documents `listenaddress` as the local IPv4 address on which `portproxy` listens. Microsoft also documents that, in Windows socket binding semantics, `0.0.0.0` is the wildcard address (`INADDR_ANY`), which means "use any appropriate network address" on a multihomed host.

In this incident, that distinction mattered:

- `0.0.0.0:50022 -> 127.0.0.1:50022`
- `0.0.0.0:60022 -> 127.0.0.1:60022`

worked because the wildcard listener allowed Windows to accept connections arriving on any local IPv4 address on `Thor`, including `192.168.0.14`, and then open the separate proxied connection to the loopback-backed `wslrelay.exe` listener.

By contrast:

- `192.168.0.14:50022 -> 127.0.0.1:50022`
- `192.168.0.14:60022 -> 127.0.0.1:60022`

restricted the listener to that one specific local address. In this lab, that specific-address binding did not successfully accept or forward the LAN traffic for the loopback-backed WSL SSH relays.

The supporting evidence was:

- `127.0.0.1:50022` and `127.0.0.1:60022` worked on `Thor`
- firewall rules for `50022` and `60022` were present
- another `portproxy` rule on `192.168.0.14:6432` worked
- a temporary wildcard control rule `0.0.0.0:65022 -> 127.0.0.1:50022` worked immediately

That combination proved the failure was not the loopback `connectaddress`, not Windows Firewall, and not all `portproxy` usage in general. It was isolated to the specific `listenaddress=192.168.0.14` binding for this Windows-to-loopback WSL relay path.

This last point is an inference from observed behavior in this lab. Microsoft documentation explains wildcard versus specific local bind semantics, but it does not explicitly document this exact `portproxy` edge case with `wslrelay.exe` and loopback-backed WSL SSH listeners.

## Contributing Factors

### 1. Misleading partial health signals

- `localhost:50022` and `localhost:60022` succeeded on `Thor`
- the `portproxy` rules existed
- firewall rules existed

Those signals made the forwarding configuration look healthy even though the LAN path was broken.

### 2. Incomplete Query Service policy

The repository policy initially modeled only:

- `WSL2_Vision:50022`

It did not model:

- `Warmachine:60022`
- `Thor:22`

That prevented full API-based access to Cluster B and forced policy work in parallel with the connectivity investigation.

### 3. Query Service policy caching

The running service cached the loaded policy. After editing `config/policy.json`, the live process still served the old host set until it was restarted.

### 4. Thor is a Windows hop to WSL loopback listeners

This topology is more fragile than a direct LAN listener because it combines:

- Windows LAN-facing networking
- Windows `portproxy`
- loopback-bound relay listeners
- WSL backend processes

Each layer can succeed locally while the full path still fails.

## Resolution

### Configuration changes

Updated `config/policy.json` to add:

- `Warmachine`
- `Thor`

Updated `tests/test_service.py` to validate those shipped-policy entries.

### Operational fix on Thor

Removed:

```text
192.168.0.14:50022 -> 127.0.0.1:50022
192.168.0.14:60022 -> 127.0.0.1:60022
```

Added:

```text
0.0.0.0:50022 -> 127.0.0.1:50022
0.0.0.0:60022 -> 127.0.0.1:60022
```

### Service recovery

Restarted the live Query Service process so it would load the updated policy from `config/policy.json`.

## Validation

### Network validation

- `Ironman -> Thor:50022` reachable
- `Ironman -> Thor:60022` reachable

### SSH validation

- `ssh -p 50022 alex@192.168.0.14 hostname` returned `Vision`
- `ssh -p 60022 alex@192.168.0.14 hostname` returned `Warmachine`

### Query Service validation

- `GET /v1/hosts` included `WSL2_Vision`, `Warmachine`, and `Thor`
- live Query Service `hostname_short` queries succeeded for:
  - `WSL2_Vision`
  - `Warmachine`

## What Went Well

- The layered troubleshooting approach isolated the failure cleanly.
- A control `portproxy` rule on `65022` provided a fast, low-risk way to test the listen-binding hypothesis.
- Firewall was ruled out quickly with explicit evidence instead of assumption.
- The Query Service policy and test coverage were improved as part of the same incident.

## What Did Not Go Well

- The initial live Query Service policy did not reflect the actual Cluster B access topology.
- The running Query Service retained stale policy state until restart, which can be easy to miss during live troubleshooting.
- The original `portproxy` configuration appeared valid on inspection but failed functionally, which increased time to isolate the true root cause.

## Preventive Actions

### Recommended operational checks

- Add a standard post-change validation checklist for Thor portproxy rules:
  - `Test-NetConnection 127.0.0.1 -Port <port>`
  - `Test-NetConnection 192.168.0.14 -Port <port>` from Thor
  - `Test-NetConnection 192.168.0.14 -Port <port>` from Ironman
  - `ssh -p <port> alex@192.168.0.14 hostname`

### Recommended configuration standards

- Standardize WSL SSH portproxy rules on `listenaddress=0.0.0.0` when the service must be reachable from other hosts on the lab LAN.
- Keep Query Service host policy aligned with the actual topology whenever new forwarded access paths are introduced.

### Recommended service improvements

- Consider documenting that Query Service host policy changes require a service restart.
- Consider adding an explicit service endpoint or operator note for current policy revision or last reload time.
- Consider adding a lightweight connectivity smoke test to validate all configured SSH hosts at startup or on demand.

## Final State

As of April 18, 2026:

- `Vision` SSH access through `Thor:50022` is working
- `Warmachine` SSH access through `Thor:60022` is working
- the live Query Service can query both WSL hosts successfully
- the repository policy and tests now reflect the Cluster B forwarding topology
