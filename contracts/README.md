# contracts/

Single source of truth for every message between the device, the app and the cloud.
Schemas change first; generated code follows. Never hand-edit generated code.

```
contracts/proto/cortex/v1/
  common.proto     Tier, Ring, Header, PayloadType, Envelope
  session.proto    Hello, HelloAck, Heartbeat, Ack, Goodbye, ClaimRequest/Result
  ota.proto        Manifest, Artifact, OtaOffer, OtaProgress, OtaResult
  telemetry.proto  LogBatch, Event, Feedback (text only, no media fields)
  alpha.proto      ALPHA-ONLY: DebugCommand, CameraControl/Frame, DatasetControl/Chunk
```

## Rules
1. Every message rides in an `Envelope` (header + typed payload + tag). Production
   seals the payload end to end; the phone relay and proxies see ciphertext only.
2. `schema_version` bumps on any breaking change. `buf breaking` runs in CI.
3. Replay protection: `(device_id, seq)` strictly increasing per session, `ts_ms`
   inside a 5 minute window.
4. `alpha.proto` handlers are compiled into alpha device builds only. The gateway
   also rejects those payload types from any device that is not ALPHA + bench.
5. No telemetry message has a media field. Camera frames and dataset chunks are
   separate alpha-only messages with their own storage rules (V4-ECOSYSTEM.md s9).

## Codegen
```bash
go install github.com/bufbuild/buf/cmd/buf@v1.47.2
go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.1
cd contracts && buf lint && buf generate     # Go -> infra/gateway/internal/gen
```
Python (device) and Dart (app) plugins are added to `buf.gen.yaml` when those
domains start consuming the contracts.
