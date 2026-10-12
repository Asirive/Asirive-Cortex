# infra/ — AGENTS.md

**Domain:** cloud infrastructure (control plane, contracts, data).
**Owner:** cloud-infrastructure domain agent. Languages: Python today (seeds),
Go for the fleet gateway (greenfield), TypeScript for the web dashboard.
**RULE: every new file, module, schema or behavior change in infra/ MUST
update this AGENTS.md in the same change. No exceptions. This file is the
first thing the domain agent reads and the last thing it writes.**

Reference architecture: `docs/architecture/V4-ECOSYSTEM.md`.

---

## What lives here today (V3 seeds)

| Path | Role |
|:---|:---|
| `api/protocol.py` | THE message contract: `BaseMessage`, `MessageType` (VIDEO_FRAME, METRICS, DETECTIONS, STATUS, COMMAND, GPS_IMU, SAFETY_ALERT, LAYER1_QUERY, ...) |
| `api/base_client.py` | Client base used by the device link |
| `api/base_server.py` | Server base (used by the legacy laptop dashboard) |
| `api/exceptions.py` | Protocol exceptions |
| `config/__init__.py` | Shared config loader (note: hardcodes a default client host) |
| `config/schema.json` | Config schema |
| `supabase/migrations/001_initial_schema.sql` | 7 tables (detections, queries, memories, adaptive_prompts, system_logs, device_status, device_commands) + heartbeat RPC + RLS + realtime |
| `video_streamer.py`, `fastapi_client.py`, `websocket_client.py` | Device-side links (moved here from the old rpi5 package) |

Legacy consumers: `core/` (device links, hybrid memory sync),
`apps/laptop_dashboard/` (deprecated, message-shape reference only).

## V4 target (greenfield)

1. **Fleet gateway (Go).** Device registry, persistent device/app channels,
   end-to-end envelope encryption (device keys at provisioning). Go, not
   Python: long-lived connections, single static binary, low memory.
2. **OTA service.** Signed artifacts, update rings (ALPHA: dev team decides,
   BETA: opt-in users, STABLE: everyone), staged rollout, rollback. The chain
   covers the compute module firmware/models AND the glasses ESP32-S3 MCU
   (infra -> app -> USB -> compute -> USB -> MCU).
3. **Web dashboard** (React/Svelte against the Go API): fleet view, update
   rings, feedback tab.
4. **Contracts first.** One contracts source of truth (protobuf/OpenAPI) with
   codegen per language (Python, Dart, Go). Schemas change before code. The
   agent tool registry (function-calling schemas shared by the Gemini brain
   and the local brain) lives in the contract set.

## Privacy and safety laws (product-level, non-negotiable)

- Images and video are NEVER stored. Zero retention, including on our own
  infrastructure. Ephemeral relay only.
- Location: retained 30 days, shared per companion with explicit user consent.
- Call records, transit data, activity logs: stored.
- Feedback attachments: trimmed logs only, never media.
- Shipped devices are provisionable and updatable but NEVER remotely
  breakable. Remote command execution exists for the alpha bench only.
- Production firmware signing uses real PKI (alpha uses the team key).

## Legacy ports (V3, being replaced)

WebSocket 8765 (device link), ZMQ 5555 (video), HTTPS 8766 (phone GPS).

## How to run and check

```bash
py -3 -m compileall infra          # syntax gate after changes
psql -f supabase/migrations/001_initial_schema.sql   # schema apply (reference)
```

## Change log (append one line per meaningful change)

- 2026-10-12: AGENTS.md created. Directory holds V3 seeds; Go gateway to be
  created here per V4-ECOSYSTEM.md section 6.
