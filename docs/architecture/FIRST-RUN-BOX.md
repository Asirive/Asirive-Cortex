# First run: phone and box (Compute Module)

For the first day with the pocket box. It covers the phone-to-box link only, not the glasses.
Nothing here has been run on hardware yet, so treat each step as "check", not "known good".

## Before you start
- Box running the `cortex-link` service (`core/deploy/cortex-link.service`). It needs `cortex-safety` up first.
- The claim code printed for this box must be in `/var/lib/cortex/identity/claim_code` (one line, like `K7Q2-4TXD`).
  The link refuses to pair without it. If nothing puts it there yet, create it by hand and make it readable by user `cortex`.
- The gateway reachable from the box. Set `CORTEX_GATEWAY_WS=wss://<gateway host>/ws/device` in the service
  environment (or the app sends it). It must start with `wss://`.
- Phone: sign in to the app, USB tethering switched on (iPhone: Personal Hotspot, then plug in the cable).
  Allow "Local Network" when iOS asks.

## Steps
1. Plug the box into the phone with the cable. Wait about 10 seconds for the box to get an address.
2. On the box: `systemctl status cortex-link` should say active. `journalctl -u cortex-link -f` shows the log.
3. App, Setup: the screen should show "connected" and the last 4 characters of the code. If it says cable out, see below.
4. Type the code. The app reads the box's key, claims the code with the gateway, then hands the result to the box.
5. On the box, check `/var/lib/cortex/identity/` now has `device.json`, `device.crt`, `link.secret` (mode 600).
6. App: Pause then Resume the assistant (confirm Pause). Check "internet" shows the right state with and without the box's network.
7. Unplug and replug the cable: the app should say cable out, then connected again without re-pairing.

## If the app says "cable out"
- Does the phone give the box an address? On the box: `ip addr` (look for the tether interface, often `usb0` or `eth1`).
- Is the beacon leaving on that interface? `tcpdump -i usb0 udp port 8766` should print a packet every 2 seconds.
  If the box has Wi-Fi or Ethernet too, set `CORTEX_TETHER_IFACE=usb0` (your interface name) in the service and restart it.
- Does the phone's hotspot pass broadcasts to the box's subnet? Some phones do not. Fallback to try next: find the box's
  address by hand (`ip addr`) and test `websocat ws://<box ip>:8765` from a laptop on the same network. If that works and only
  the beacon fails, the fix is discovery, not the link.
- iOS may block receiving broadcast without a "multicast networking" entitlement from Apple. If the beacon is seen by
  `tcpdump` on the box but never by the app on an iPhone, that is the likely cause. Android should not need it.

## If pairing fails
| App message or box log | Meaning |
|---|---|
| "Could not read the box" | The app could not get the box key. Nothing was spent. Check cable and service. |
| `wrong claim code` | The code in `claim_code` differs from the one typed. |
| `this box has no claim code` | `claim_code` file missing or empty. |
| `certificate is not for this box` | The gateway signed a different key than the box's. Re-claim after checking the key the app sent. |
| `already paired` | The box already has a secret that is not this phone's. To start over: stop `cortex-link`, delete `device.json`, `device.crt`, `link.secret` in the identity folder, start it. |
| `bad signature` after a reinstall | The phone lost its secret (stored in the app). Reset the box as above and pair again. |

## What you should expect not to work yet
- Sound / touch / voice test and "install update" report failure: the audio/haptic service and OTA agent are not connected.
- Calls ringing with the app closed (needs the Firebase and Apple setup in `apps/mobile/README.md`, and no full-screen ring yet).

## Please write down
What the phone model and OS were, whether the beacon arrived, how long pairing took, and any line from the log
that looked wrong. That tells us what to fix first.
