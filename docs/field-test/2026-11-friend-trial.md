# Friend trial: Cortex used by a blind person, nobody managing it

The bar (Haziq, 2026-11-26): a friend plays the blind user. The box boots on its own, the app is the only thing
anyone touches, and nobody SSHes in or watches a screen.

## Must be true before the trial

| # | Gate | State on 2026-11-26 |
| --- | --- | --- |
| 1 | The box survives an hour of engine load without hard-shutting | **Fails.** It has shut down under NPU/LM load and needs the wall socket cycled. Power supply / thermal first. |
| 2 | Cold boot to "Cortex ready." with nobody logged in | Software built (`cortex-brain.service`), never run on the box. |
| 3 | A button the user can find without looking | Glasses firmware is not built on hardware. Until it is: the app's talk button (`button` op built; the on-screen button is not). |
| 4 | Camera, mic and speaker that go with the user | Today: USB webcam + USB mic + headphone jack on the box. |
| 5 | The app pairs with the box and sends GPS | Built and tested against the real box code on the server; never run on a phone. |
| 6 | Internet for bus times and the Gemini second opinion | Gateway works with the real LTA and Gemini keys from the server; the box needs a claimed identity and a route to it. |
| 7 | A sighted helper walks one step behind, the whole time | Required. Safety (ToF warnings) has only been tested in simulation. |

## Bring-up, once gates 1–2 pass (Haziq at the box)

1. Install: `deploy/cortex-brain.service` and the other units, `systemctl enable cortex.target`, copy the newest
   nav bundle to `/var/lib/cortex/nav/bundles/` (`~/cortex-data/navbundle/20261126-1525` has real LTA headways).
2. Power-cycle the box. Pass: "Cortex ready." within 60 s with no keyboard, no SSH and no screen.
3. Unplug the mic and reboot. Pass: Cortex says it can't hear. Same for the camera.
4. Kill the brain process. Pass: it comes back and says "Cortex ready." again (systemd restart).

## The trial (indoors first, then a short outdoor route)

Friend wears the camera and headphones (blindfolded if sighted). Helper watches, never touches the box.

| Task | Pass |
| --- | --- |
| Tap, "what's in front of me?" | A correct, short answer, no colour-only description |
| Tap, "where are my keys?" after they were seen | The place and how long ago (memory learns only with `ce_peek`, not built: expected to fail) |
| "Take me home" (saved place) | Walk instructions that match the street |
| At a bus stop: "when is the next 858?" | Live minutes from LTA |
| A question it can't answer well (a sign, a bus far away) | It says "not sure", or the Gemini answer with the right bus and side |
| Pause from the app, then tap | Cortex says it paused; the button does nothing until resumed |

Record per task: pass/fail, seconds from end of question to first sound, what was said wrong. No video or
photos of the friend are kept.
