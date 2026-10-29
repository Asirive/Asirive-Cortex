# Cortex gateway + fleet console

Go gateway (device WebSocket, dashboard API, tier enforcement) and the embedded
Asirive fleet console (`web/index.html`).

```bash
export CORTEX_DEV_TOKEN=changeme
go run ./cmd/gateway -addr :8080 -dev-shared-device-token   # console at http://localhost:8080
go run ./cmd/simdevice                    # fake alpha/beta/stable devices (needs the dev flag above)
```

| Endpoint | Purpose |
|:---|:---|
| `WS /ws/device` | Device link. Device dials out, first message `Hello`. |
| `GET /api/summary`, `/api/devices`, `/api/devices/{id}` | Fleet state. Beta/stable detail never includes the full log feed. |
| `POST /api/devices/{id}/command` | Alpha bench debug commands. Refused for non-alpha devices, audited. |
| `GET /api/audit` | Audit trail. |
| `POST /api/registrations`, `GET /api/registrations`, `POST /api/registrations/{id}/revoke` | Register a device (returns a one-time claim code), list, revoke. Operator token. |
| `GET/POST /api/releases`, `POST /api/releases/{id}/halt`, `/resume` | Release list, add a signed manifest (409 on a duplicate id), halt, explicit resume. |
| `GET /api/feedback` | Feedback received from devices. |
| `POST /v1/claim` | Called by the phone app. Code + device public key in, per-device credential out (shown once). Rate limited per source. |

## OTA
```bash
go build -o cortex-sign ./cmd/cortex-sign
./cortex-sign keygen -out ota.key                 # keep ota.key OFF the gateway; prints the public key
export CORTEX_OTA_PUBKEY=<printed public key>      # gateway enables OTA with this
./cortex-sign sign -key ota.key -release r-2026.10.30 -counter 12 -max-ring stable \
    -artifact compute:4.0.1:./compute.img:https://dl.example/compute.img -out r.manifest
curl -H "Authorization: Bearer $CORTEX_DEV_TOKEN" --data-binary @r.manifest localhost:8080/api/releases
```
Rollout engine, gating and halt rules: `docs/architecture/FLEET-OTA-AND-SECURITY.md`.
`go test ./...` covers sign/verify, anti-rollback, ring limits and staged halt.

**Dev-only parts:** auth is one shared token, state is in memory. Production adds
mTLS with per-device certificates, the sealed end-to-end envelope, per-user roles,
Postgres (`infra/supabase/migrations/002_fleet.sql`), signed OTA manifests and the
camera relay / dataset pipeline (message types exist, handlers are stubs).

## Registering a device
1. Console: Register device -> label, tier, bench flag -> you get a claim code (shown once, valid 7 days, single use).
2. App: Add device -> scan the QR (or type the code) -> USB-connect the glasses. The app calls `/v1/claim` and passes the returned device token to the device over USB.
3. Device connects to `/ws/device` with `Authorization: Bearer <device token>` and `X-Device-Id`. Its tier, ring and bench flag come from the registry, not from what the device says.
4. Lost or stolen: Revoke in the console. The live connection drops and the device cannot reconnect.
Tests: `go test ./...` covers claim, expiry, rate limit, tier override, revoke.

## Durable state

`-state cortex-state.json` (default) holds registrations (claim/token **hashes**, public keys), releases with
rollout progress and halts, and the audit log. It is written atomically every 3 s and on SIGTERM, mode 0600,
and read at start; an unreadable file stops the gateway rather than starting empty. Back it up, and keep it
on the same disk encryption as any secret store. Releases are re-verified against `CORTEX_OTA_PUBKEY` on load.
Live device telemetry is not persisted; it repopulates as devices reconnect. Single node only: the multi-node
store is Postgres (`infra/supabase/migrations/002_fleet.sql`), not yet wired.

## Operators and roles

The `CORTEX_DEV_TOKEN` is the **bootstrap** admin. Use it once to create named operators, then stop sharing it.

```bash
curl -XPOST :8080/api/operators -H "Authorization: Bearer $CORTEX_DEV_TOKEN" -d '{"name":"omar","role":"operator"}'
# -> {"token":"op_..."}  shown once; only its hash is stored
curl -XPOST :8080/api/operators/omar/revoke -H "Authorization: Bearer ..."
```

| Role | Can |
|---|---|
| viewer | read fleet, audit, feedback, releases |
| operator | + register/revoke devices, alpha debug commands |
| release | + register, halt and resume OTA releases |
| admin | + create and revoke operators |

Every audit line now carries the real operator name (`bootstrap` for the shared token). Operators persist in the state file.
No password login yet: tokens are personal bearer secrets; SSO is not built.

## App accounts (email + password)

App users are separate from console operators: different token type (`ses_...`), different routes, and a session
cannot call `/api/*`. Endpoints (all under `/v1`): `auth/register`, `auth/verify`, `auth/resend`, `auth/login`,
`auth/logout`, `auth/reset-request`, `auth/reset`, `GET /me`, `DELETE /me` (password required), `PUT /me/beta`
(needs the current consent version), `GET /me/devices`, and `POST /claim` (needs a session).

- Passwords: argon2id; min 10 chars. Sessions last 30 days; a password reset signs out every session.
- Registration, resend and reset answer identically whether or not the email exists. Login locks for 15 min after 10 failures per email or per IP.
- Deleting an account revokes its devices; an operator must register the hardware again before a new owner can claim it.
- Beta toggle moves the owner's STABLE/BETA devices between channels; ALPHA devices are never touched.

Email goes out through Resend:

```bash
export RESEND_API_KEY=re_...                       # from resend.com
export CORTEX_MAIL_FROM='Asirive <no-reply@asirive.com>'   # a sender on your verified domain
export CORTEX_APP_LINK_BASE='asirive://'           # deep links in emails: asirive://verify?token=...
```

Without `RESEND_API_KEY` mail is printed to the gateway log (dev only: it exposes links). Not built: Sign in with Apple, email change, per-device session list, companions/location/calls.
