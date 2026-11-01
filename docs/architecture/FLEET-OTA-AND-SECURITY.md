# Fleet OTA, Security and Coverage

**Status:** design + partial skeleton (2026-10-29). Companion to V4-ECOSYSTEM.md section 6.
Read the gap table before trusting any part of the gateway with a real device.

## 1. How updates roll out

**Can we ship from GitHub?** GitHub can store the files. It cannot be the update
system. Releases and Actions have no staged rollout, no per-ring gating, no
health-based halt or rollback, no device targeting, no visibility into which
device runs what, and a private repo would need a token on every device. A
GitHub outage or rate limit would also block every update.

**What we build:** a small control plane (`infra/gateway/internal/ota`) that decides
who gets which release and when. Artifact bytes can sit on any dumb storage
(GitHub Releases for alpha, object storage or the self-host server later). The
device does not trust the storage or the gateway; it trusts a signature.

```
CI build -> cortex-sign (offline key) -> signed manifest
        -> POST /api/releases (gateway verifies, cannot forge)
        -> ALPHA 100% -> soak -> BETA 20% -> BETA 100% -> STABLE 10% -> 50% -> 100%
        -> each stage needs a clean soak and a healthy-commit fraction, else HALT
device: verify signature + ring + anti-rollback counter -> download -> check sha256
        -> write inactive slot -> reboot -> health + safety self-test -> commit or roll back
```

Trust rules (implemented and unit-tested in `internal/ota`):
- Signing key is never on the gateway. Gateway holds only the public key.
- `max_ring` in the signed manifest: a beta build can never reach stable.
- `version_counter` anti-rollback: device refuses a lower counter than it has.
- Any tamper, wrong key, or unsigned manifest is rejected.
- A rollback or rejection below the stage threshold halts the whole rollout.
- Devices already on the release are never re-offered.

Chain for the glasses: infra -> app -> USB -> compute module -> USB -> ESP32-S3.
Each hop verifies the same signed manifest; no hop is trusted to relay unverified bytes.

## 2. Is the current implementation secure?

No. It is a working skeleton with dev-grade security. Use it on a closed network
with simulated or bench devices only.

| Area | Today | Needed before real devices |
|---|---|---|
| Device identity | per-device token issued at claim, revocable, tier from registry (done, tested). Shared dev token only behind `-dev-shared-device-token` | **mTLS built 2026-10-30** (device CA, 90-day certs, renewal, revocation at handshake). Still needed: hardware-backed key (secure element/TPM), CA key custody off the box |
| Transport | TLS 1.3 + client certificate on a dedicated device listener (`-device-addr`); public API stays behind the HTTPS proxy | pin the server certificate on the device |
| Payload privacy | unsealed protobuf | device terminates its own mTLS stream through the phone tunnel, so the relay sees only ciphertext (needs the phone-side TCP tunnel, not built). Separate sealing not needed unless a proxy ever terminates device TLS |
| Operator auth | one shared token, one actor name | per-user accounts, MFA, roles (viewer/operator/admin), short-lived sessions |
| Commands | audited, tier-gated, **signed** (device id, 60 s expiry, nonce); device verifier written and cross-checked with the gateway | wire the verifier into the alpha debug handler; operator-held key so a compromised gateway cannot sign |
| OTA | signed manifests, rings, halt, anti-rollback (done, tested) | real key custody (HSM/offline), device-side verifier, storage hosting, A/B slot client |
| Replay protection | seq + clock window checked | persist seq across gateway restarts |
| Persistence | in memory; restart loses state | Postgres wiring (schema exists in 002_fleet.sql) |
| Audit | in memory | append-only store, tamper evidence |
| Console | token in sessionStorage | HttpOnly session cookie, CSRF protection, CSP |
| Rate limits / abuse | none | per-device and per-IP limits, connection caps |
| Camera relay / dataset | message types only | consent flow, access control, never-persist (camera), separate store (dataset) |

## 3. Does it cover what fleet infrastructure does?

Covered in the skeleton: device registry (in memory), heartbeat/health, online
state, tiers, alpha debug commands with audit, logs and events, staged OTA control
plane, fleet console.

Not yet built (a complete fleet platform also needs):
- Identity lifecycle beyond claim/revoke (key rotation, decommission, transfer to a new owner)
- App-facing API: only /v1/claim exists; the rest is drafted in contracts/openapi/app.yaml
- Durable storage, backups, retention jobs, and multi-instance gateway scaling
- Alerting and on-call (offline ratio, safety fault, failed rollout) to email/chat
- Metrics and tracing (Prometheus/Grafana), uptime history, SLOs
- Config management and feature flags per ring/device
- Crash and log pipeline with retention limits; feedback inbox
- Device groups and tagging, search, bulk actions
- Disaster recovery: restoring the fleet after a gateway loss; kill switch to halt all rollouts
- Compliance: data inventory, consent records, deletion on request (dataset consents)
- Load and soak tests, chaos tests (gateway down, flaky tether)

## 4. Next steps in order

1. Postgres store behind the fleet and release APIs (restart-safe).
2. (Done 2026-10-30: mTLS, roles, signed commands.) Remaining: hardware-backed device key, CA key custody, server-cert pinning.
3. Device-side OTA verifier + A/B client (core `ota` service) using the same `internal/ota` rules.
4. Alerting + metrics; rollout halt notifications.
5. Dataset and camera pipelines with consent enforcement.
6. External security review before any non-bench device connects.

## 5. Operator QA pass (2026-10-29)

An agent acting as the operator tested the console and gateway in a real browser and
found 21 bugs, 15 UX problems and many gaps. Fixed and covered by tests or browser
checks: auto-refresh wiping inputs and focus, keyboard-unreachable rows, rollbacks not
counted, re-posting a release resetting a halt (now 409 plus explicit Resume), versions
not following updates, incidents vanishing when a device drops, heartbeat interval trust
(clamped 2-60 s), duplicate connections marking a live device offline, silently dropped
feedback, blank/bench/over-long labels, error text, command allowlist and audited args,
revoke and halt on unknown ids, rollout advancing with nobody tested, rolled-back devices
re-offered, `not_before` ignored, stalled stages, ID collisions, operator token guessing,
security headers and server timeouts. Added: release panel with halt/resume, claim QR,
feedback tab, label column and search.

Still open from that pass: Postgres persistence (a restart loses registrations, tokens and
releases), per-user operator accounts and roles, signed commands, claim endpoint requires an
authenticated app account, alerting, uptime history, device notes/groups/export, offline
fonts, artifact hosting and key custody, and everything in the app API that is only planned.
