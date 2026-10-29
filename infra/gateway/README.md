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

## Companions, location, calls, feedback, updates (app)

- **Companions:** the owner creates an invite (`POST /v1/companions`, 8-char code or `asirive://companion?code=`; 48 h, single use, max 5 open). The companion accepts it and then sees **nothing** until the owner sets grants (`location`, `call`) per companion. Either side can end the link, which ends open calls and stops location reads.
- **Location:** `PUT /v1/me/location`. Latest point plus history at 5-minute granularity, 30-day TTL (swept every 10 min), wipeable by the owner. Timestamp is the gateway's clock. A companion with no grant and a user with no data get the same 404. No camera, no media, ever.
- **Calls:** WebRTC signalling by polling (offer, answer, ICE) between linked accounts with the `call` grant; one call at a time per person; ringing times out at 60 s; SDP/ICE are wiped when the call ends; metadata kept 30 days. **No push notification yet**: the callee's app must poll `/v1/calls/inbox` (APNs/FCM wake-up is not built). No TURN server yet, so calls across strict NATs can fail.
- **Feedback:** `POST /v1/feedback` text plus a clipped log excerpt, attached to the user's device; appears in the console Feedback tab.
- **Updates:** `GET /v1/me/devices/{id}/update?counter=N` returns the signed manifest for the device's ring (204 if none); `POST` reports `committed | rolled_back | rejected`. Only the owner of the device can ask.
- **Deleting an account** also removes its links, location, call records and device feedback.

## Push wake-up and TURN (calls)

- `PUT /v1/me/push {platform: ios|android, token}` registers a phone (max 5 per account; a token moves to the newest account that registers it). `DELETE /v1/me/push` clears.
- Starting a call sends the callee a **generic** push ("Incoming call", opaque call id; no name, no email). Dead tokens are dropped automatically. Failures never fail the call.
- Providers: FCM HTTP v1 (`CORTEX_FCM_SERVICE_ACCOUNT` = Firebase service-account JSON) and APNs token auth (`CORTEX_APNS_KEY` `.p8`, `_KEY_ID`, `_TEAM_ID`, `_TOPIC`). Unset = push is logged, not sent.
- **iOS caveat:** this sends a normal time-sensitive alert push, which shows a banner. A full-screen ringing call UI on iOS needs PushKit VoIP pushes + CallKit in the app (separate VoIP token and `.voip` topic). Not built; tell the app team.
- `GET /v1/calls/ice-servers` returns TURN URLs with 1-hour HMAC credentials (coturn `use-auth-secret`). The secret must match `static-auth-secret` on coturn.
- `infra/deploy/` has a docker-compose (gateway + Caddy TLS + coturn). Written but **not run**: it was not tested in the dev container.
- Tested against fake FCM/APNs servers only; never against the real providers.

## Alerts and signed commands

- **Alerts:** set `CORTEX_ALERT_EMAILS=a@x.com,b@x.com`. A live device needing attention (offline, safety fault/degraded, low battery) for 3 minutes emails once, repeats every 6 h while unresolved, and sends one all-clear. Releases that halt automatically email immediately. Uses the same Resend mailer. Pending and revoked devices never alert.
- **Signed debug commands:** every alpha command carries `device_id`, issue/expiry (60 s), a random nonce, the operator's name and an ed25519 signature (`internal/cmdsign`, field list in `alpha.proto`). The device must check all of them and remember the last 256 nonces. The public key is returned by `/v1/claim` and `GET /api/command-key`; the private key is generated on first start and kept in the state file. **Limit:** the key is on the gateway, so this stops replay, misdirection and stale/tampered commands, not a compromised gateway. An operator-held key (WebAuthn) would be needed for that.

## Postgres state store (failover)

Set `CORTEX_PG_DSN=postgres://user:pass@host/db?sslmode=require`. The state document is stored in one table
(`cortex_state`, created automatically) and a Postgres advisory lock makes one gateway the leader; others wait as
**warm standbys** and take over within ~5 s when the leader's session ends (crash or network loss). A leader that
loses the lock exits, so run the gateway under a restarter (compose `restart: unless-stopped` does this).
Verified against a local Postgres 16 (`CORTEX_TEST_PG=... go test ./internal/server`), including killing the leader.
This is **failover, not scaling**: one writer at a time, whole-document saves every 3 s (so a hard crash loses up to
3 s of changes). A per-table schema for active-active is not built; `supabase/migrations/002_fleet.sql` is still reference only.
