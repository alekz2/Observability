---
name: general
description: General repository guidance for this lab environment. Use when working on installations, troubleshooting, or Query Service API tasks tied to the Ironman, Antman, Hulk, BlackWidow, Thor, Vision, and Warmachine topology, or when the user wants step-by-step interactive troubleshooting instead of autonomous execution.
---

# General Guidance

Follow these instructions when this skill is active.

## Step-By-Step Interactive Mode

When the user asks to switch to step-by-step troubleshooting:

1. Tell the user the exact command to execute to gather information.
2. Wait for the command output.
3. Use that output to decide the next single task.
4. Do not proceed to the next step unless the current result is successful or expected.

## Query Service API Rule

When using the Query Service API:

- If a call fails, stop immediately.
- Highlight the failure clearly.
- Do not fix the failure in the same flow unless the user explicitly changes the instruction.

## Topology Reference

Use this topology when reasoning about installations and troubleshooting.

- `Ironman`
  - IP: `192.168.0.53`
  - OS: `Windows 11`
  - Role: Primary Windows host running VMware Workstation 17 Pro for the lab VMs.
- `Antman`
  - IP: `192.168.0.150`
  - OS: `Rocky Linux 8.0`
  - Role: Cluster A Geode locator and `server1`.
- `Hulk`
  - IP: `192.168.0.151`
  - OS: `RHEL 8`
  - Role: Kafka, Splunk Forwarder, and Geode `server2`.
- `BlackWidow`
  - IP: `192.168.0.153`
  - OS: `Ubuntu 24.04`
  - Role: Main observability hub running the LGTM stack.
- `Thor`
  - IP: `192.168.0.14`
  - OS: `Windows 11`
  - Role: Secondary Windows host running WSL2 in NAT mode.
- `Hawkeye: `192.168.0.154
  - IP: `192.168.0.154`
  - OS: `Rocky Linux 9`
  - Role: `Splunk Enterprise`
- `Vision`
  - Private IP: `172.22.79.100`
  - OS: `Ubuntu 24.04`
  - Role: Cluster B Geode main node and PostgreSQL server.
- `Warmachine`
  - Private IP: `172.22.79.100`
  - OS: `RHEL 8`
  - Role: Cluster B Geode member.

## Notes

- Prefer host names and addresses exactly as the live service or policy exposes them.
- If the live API response conflicts with an assumption, trust the live API response.
