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

Legacy consumers: `v3_core/` (device links, hybrid memory sync),
`apps/laptop_dashboard/` (deprecated, message-shape reference only).

## V4 build status (2026-10-29)

- `contracts/` (repo root): protobuf contracts + buf config. Lints and generates Go.
- `gateway/`: Go gateway skeleton. Device WebSocket, heartbeat/log/event/OTA
  status handling, tier enforcement, dashboard API, audit, embedded Asirive
  fleet console (`gateway/web/index.html`), `cmd/simdevice` fake devices. Dev
  token auth and in-memory state only. See `gateway/README.md`.
- `supabase/migrations/002_fleet.sql`: V4 Postgres schema (not applied anywhere yet).
- `gateway/internal/ota` + `cmd/cortex-sign`: signed manifests (ed25519, offline key),
  ring/anti-rollback checks, staged rollout engine with halt. Unit-tested and
  run end to end against simulated devices.
- `gateway/internal/registry`: register -> claim -> revoke, one-time claim codes, per-device tokens, tier from registry. `contracts/openapi/app.yaml`: draft app API (only /claim live).
- Not built: mTLS/PKI, sealed envelope, roles, Postgres wiring, device-side OTA
  verifier/A-B client, camera relay, dataset pipeline, Python/Dart codegen. Gap
  table: docs/architecture/FLEET-OTA-AND-SECURITY.md.

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

- 2026-10-29: Added contracts/, gateway skeleton, fleet console, 002_fleet.sql. Tiered access and dataset-capture policy documented in V4-ECOSYSTEM.md 6.1 and 9.1.
- 2026-10-12: AGENTS.md created. Directory holds V3 seeds; Go gateway to be
  created here per V4-ECOSYSTEM.md section 6.
- 2026-10-29: Added OTA control plane (internal/ota), cortex-sign, release API, FLEET-OTA-AND-SECURITY.md.
- 2026-10-29: Added device registry (register/claim/revoke), console registration UI, app API draft.
- 2026-10-29: QA-pass fixes: console rewrite (state-preserving render, keyboard, mobile sheet, releases panel, feedback tab), rollout engine hardening, registry id/claim fixes, command allowlist, security headers, claim QR. contracts: local.proto (owner stop over the local link only), app.yaml auth/deletion/opt-in decisions.
- 2026-10-29: Durable gateway state: registrations (credential hashes), releases (re-verified on load) and audit saved atomically to --state file (0600) every 3 s and on SIGTERM; a restart no longer locks claimed devices out. Bad state file refuses to start. Postgres (002_fleet.sql) remains the planned multi-node store; the file is the single-node self-host store.
- 2026-10-29: Per-user operators with viewer/operator/release/admin roles, personal tokens (hashed, persisted), real actor in audit, whoami badge in console.
- 2026-10-29: App accounts in the gateway: email+password (argon2id), Resend verification/reset mail, sessions, login lockout, delete account (releases devices), beta opt-in with consent record, authenticated /v1/claim, /v1/me/devices. Sign in with Apple dropped for now.
