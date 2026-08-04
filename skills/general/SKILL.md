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

**Corrected 2026-08-04**: this reference previously described Thor as running WSL2 in NAT mode and Vision/Warmachine as sharing a single private WSL2 IP (`172.22.79.100`). That was migrated away months earlier (see GEODE.md/MONITORING.md in the LGTM-Geode project) — Vision and Warmachine have been real bridged-LAN VMs on Thor since that migration, and were further migrated from VMware Workstation to Oracle VirtualBox 7.2 on 2026-08-03/04 (Thor is unchanged as the physical host; only the hypervisor changed). Falcon and Wasp, previously missing from this list, are added below.

- `Ironman`
  - IP: `192.168.0.53`
  - OS: `Windows 11`
  - Role: Primary Windows host running VMware Workstation 17 Pro for the lab VMs (Antman, Hulk, BlackWidow).
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
  - Role: Secondary Windows host; VirtualBox host for Vision, Warmachine, and Wasp (real bridged-LAN VMs, not WSL2 guests; migrated from VMware Workstation to Oracle VirtualBox 7.2 on 2026-08-03/04).
- `Hawkeye`
  - IP: `192.168.0.154`
  - OS: `Rocky Linux 9`
  - Role: Splunk; Kafka (KRaft mode, `192.168.0.154:9092`); GitLab CE (see `D:\Alex\Work\Installs\GitLab-CE\PROJECT-PLAN.md`). VM migrated from VMware to Oracle VirtualBox 7.2 on 2026-08-03/04.
- `Falcon`
  - IP: `192.168.0.155`
  - OS: `Rocky Linux 9`
  - Role: FIX Engine host; GitLab Runner (shell executor).
- `Vision`
  - IP: `192.168.0.156`
  - OS: `Ubuntu 24.04`
  - Role: Cluster B Geode locatorB, serverB1, GatewayReceiver; PostgreSQL. VM on Thor, migrated from VMware to Oracle VirtualBox 7.2 on 2026-08-03/04.
- `Warmachine`
  - IP: `192.168.0.157`
  - OS: `RHEL 8`
  - Role: Cluster B Geode `serverB2`. VM on Thor, migrated from VMware to Oracle VirtualBox 7.2 on 2026-08-03/04.
- `Wasp`
  - IP: `192.168.0.158`
  - OS: `Rocky Linux 9.7`
  - Role: k3s single-node Kubernetes, deployment target for the GitLab CI/CD lab pipeline (see `D:\Alex\Work\Installs\GitLab-CE\PROJECT-PLAN.md`). VM on Thor, migrated from VMware to Oracle VirtualBox 7.2 on 2026-08-04.

## Notes

- Prefer host names and addresses exactly as the live service or policy exposes them.
- If the live API response conflicts with an assumption, trust the live API response.
