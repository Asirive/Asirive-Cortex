# Memory (V4): automatic object memory

Approved by Haziq on 2026-11-26. The detector is LFM3, which looks only when the brain is idle. "Where" is the scene
words plus a named place. This builds on spec 6.9 of `2026-11-24-v4-core-design.md`. No V3 code or design is used:
V3 memory did not work.

## What it does

The user asks: "Where are my keys?"

Cortex answers: "On the kitchen table at Home, about 20 minutes ago. Silver, on a red ring."

Memory only remembers items on its list:

- **Built-in items:** keys, wallet, phone, glasses, bag, cane.
- **The user's own items:** added from the app, each with optional details such as "blue metal bottle" and other
  names it goes by.

Anything else is never stored. Images are never stored either; a sighting is text only.

## How an item gets noticed

Memory never turns on the camera and never takes a frame of its own. It looks only at the view the engine has
already read. In IDLE that view exists only while the user is talking.

A scan runs when all of these are true:

1. A new view has arrived that is not a scene skip (a skipped view has nothing new) and has not been scanned already.
2. The brain is idle:
   - no turn is running;
   - the user is not talking;
   - no cue is waiting to be spoken.
3. At least 30 s have passed since the last scan.
4. Fewer than 10 scans have started in the last 10 minutes. This load budget keeps the extra LM work to roughly
   10 s in every 10 minutes. The box shuts down under sustained load, so this number must be measured on the box
   before it is raised.

A scan asks the LM one silent question about the current view: the item list (each item with its details), and one
line back per item it can clearly see, in the form `item | what it looks like | where in the scene`, or `none`.

The scan is cut short as soon as the user does anything:

- the user starts talking;
- the user types;
- an urgent cue arrives.

A scan that was cut stores nothing.

The parser trusts the model's answer only within limits:

- **Kept:** items on the list only, one sighting per item, text cut to 80 characters.
- **Dropped:** hedged lines ("maybe", "possibly", "might", "not sure", "can't see" and the like).

## Engine: `ce_peek` (NOT built yet: needs the box)

```
int ce_peek(void* h, const char* text, int max_tokens);
```

`ce_peek` is a silent question about the current view. It is not part of the conversation.

1. It copies the view slot into a scratch sequence and reads the question there.
2. It samples greedily, text only: no speech, no tool calls, no sound.
3. It emits token events and then a done event with `"kind":"peek"`.
4. It drops the scratch sequence.

It returns -1 (busy) while any of these runs:

- an ask, a tool result or a say;
- another peek;
- the user talking.

These end it early with `cancelled: true`:

- speech start;
- `ce_ask`;
- `ce_cancel`.

In the big-core gate it ranks below an ask.

The Python binding `Engine.peek()` exists, and `Engine.can_peek` is False until the library exports `ce_peek`. Without
it, memory recall works but nothing new is learned, and the host logs why.

## Where it was seen

Each sighting records:

- **Scene words**, from the LM: "on the kitchen table".
- **A named place**, from the newest GPS fix less than 30 s old:
  - first choice: a saved place within max(40 m, fix accuracy);
  - otherwise: the nearest named place within 75 m, leaving out bus stops, postcodes and bare addresses.
- **The time.**

GPS coordinates are kept for 30 days and then cleared. The words, the place name and the time stay.

## Store

SQLite in WAL mode at `/var/lib/cortex/memory/memory.db`. It lives on the box only and is never in git.

| Table | Columns | Notes |
|:--|:--|:--|
| `items` | name, aliases, details, added | the user's own items only (built-in items live in code) |
| `sightings` | item, t, looks, spot, place, lat, lon, acc | see the rules below |

`items` limits: at most 30 items, names up to 40 characters, details up to 120.

`sightings` rules:

- **Merging:** a new sighting of the same item at the same place within 10 minutes updates the last row instead of
  adding a new one.
- **Keeping:** the last 20 sightings per item are kept.

Two processes use the store:

- **The brain** owns the scans and recall.
- **The link** writes the user's own items from the app (phone-link op `memory`).

They share the file. WAL mode lets them read and write at the same time.

## Recall

The tool is `search_memory(item)`. It is spoken by the LM, which turns the result into a sentence. It answers in one
of three ways:

| Case | Result |
|:--|:--|
| A known item that has been seen | `{item, seen: true, spot, place, ago, looks, before?}`. `before` is the previous different place, when there is one. |
| A known item that has not been seen | `{item, seen: false}` |
| Not a known item | An error that lists the items memory knows, and says that more can be added in the app. |

## Phone-link op `memory` (owner-signed)

The `action` field picks what it does:

| `action` | What it does |
|:--|:--|
| `list` | Returns all items: built-in and the user's own. |
| `add` | Adds an item: `name`, plus optional `details` and `aliases`. |
| `remove` | Removes one of the user's own items, with its sightings. |
| `forget` | Clears the sightings: all of them, or one item's. |

The app screen for this is not built.
