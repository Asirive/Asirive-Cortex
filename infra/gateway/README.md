# Cortex gateway + fleet console

Go gateway (device WebSocket, dashboard API, tier enforcement) and the embedded
Asirive fleet console (`web/index.html`).

```bash
export CORTEX_DEV_TOKEN=changeme
go run ./cmd/gateway -addr :8080          # console at http://localhost:8080
go run ./cmd/simdevice                    # fake alpha/beta/stable devices
```

| Endpoint | Purpose |
|:---|:---|
| `WS /ws/device` | Device link. Device dials out, first message `Hello`. |
| `GET /api/summary`, `/api/devices`, `/api/devices/{id}` | Fleet state. Beta/stable detail never includes the full log feed. |
| `POST /api/devices/{id}/command` | Alpha bench debug commands. Refused for non-alpha devices, audited. |
| `GET /api/audit` | Audit trail. |

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
