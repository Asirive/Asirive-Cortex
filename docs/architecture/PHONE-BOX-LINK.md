# Phone to box link

Status: built on both sides (2026-10-30), tested against each other with fakes only. Not yet run
with real hardware or a real phone.

## Idea

The USB-C cable already carries the phone's internet (tethering). So the cable is also a small
private network: the box is a client on the phone's hotspot subnet. The app talks to the box over
that network. No custom USB driver, no Apple MFi accessory chip, same code on iPhone and Android.

## Finding the box

The box broadcasts `{"cortex":1,"port":8765}` over UDP port 8766 every 2 seconds. No secrets. The
app listens for about 4 seconds and takes the sender's address. iOS asks for the Local Network
permission once (text in `Info.plist`). Nothing found means "cable out" in the app.

## Messages

WebSocket text frames, JSON, on `ws://<box>:8765`. The box sends first:

    {"hello": {"v":1, "nonce":"<b64>", "paired":false, "public_key":"<b64 DER>", "box_tail":"4TXD"}}

The app sends `{"id":N,"op":"...","args":{...},"mac":"<b64>"}`, the box answers `{"id":N,"ok":bool,"error"?,...}`.

| op | args | answer | needs mac |
|:---|:---|:---|:---|
| `provision` | `reply` (the whole `/v1/claim` reply), `link_secret` (b64, 32+ bytes), `gateway_ws_url`, `claim_code` (the code printed for this box) | ok | no, and only while unpaired (the same secret may be sent again) |
| `status` | none | `paused`, `internet` | yes |
| `pause` | `confirmed:true` | `ok`, `paused` | yes |
| `resume` | none | `ok` | yes |
| `internet` | none | `internet` | yes |
| `test` | `kind`: sound, vibrate, voice | `ok` | yes |
| `install` | `manifest` | `ok` | yes |

`mac` = base64 HMAC-SHA256 with the link secret over `nonce|id|op|canonical(args)`; canonical JSON has
sorted keys, no spaces, raw UTF-8. `id` must rise within a connection. The nonce is new per
connection, so a captured request cannot be replayed.

## Pairing order (the app)

1. `hello`: read `public_key` and `box_tail` (the owner confirms the tail by ear).
2. `POST /v1/claim` with `device_public_key` = the box's key.
3. `provision` with the claim reply and a fresh random link secret. The box stores the cloud reply and
   the secret (0600), and refuses any later `provision`. The app keeps the secret in secure storage.
   The box also checks the claim code against the one stored for it, and that the certificate in the reply is for its own key, so a stranger on the hotspot cannot plant one. The app keeps the secret before sending it, so a lost answer can be retried; the box accepts the same secret twice. Set `CORTEX_TETHER_IFACE` to pin the beacon to the cable's interface if the box has other networks.

Factory reset on the box clears the secret, which allows pairing again.

## Trust and limits

- The hotspot can be joined by other phones. Before pairing, anyone on it could try to claim the box,
  but they would also need the one-time claim code printed on the box. After pairing, every command
  needs the secret.
- Pause goes through `OwnerControl`: it refuses unconfirmed requests and has no way to touch safety.
- Replacing a lost phone needs a box reset, by design.
- `test` and `install` answer false on the box until the audio/haptic service and the OTA agent are
  connected to the link (`RuntimeHooks` in `core/cortex_core/link/phone_link.py`). The app shows that
  as "could not reach the box" and does not pretend.

Code: box `core/cortex_core/link/phone_link.py`, app `apps/mobile/lib/box_link.dart`. Both test files
share the signature vectors; change them together.
