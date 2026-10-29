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
