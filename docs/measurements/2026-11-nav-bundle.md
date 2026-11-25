# Offline Singapore nav bundle: build and query times (2026-11-26)

Measured on the **home server** (i5-12400, 7 GB RAM, Python 3.13, pyosmium 4.3.2). The bundle has **not** run on
the box yet: the Q8B was unreachable (it reset twice under load). Re-measure RSS and route times there before
relying on these numbers.

## Build (`infra/navbundle/build.py`)

Input: Geofabrik `malaysia-singapore-brunei-latest.osm.pbf`, clipped to Singapore. Headways: defaults (no LTA
BusServices JSON on the server yet).

| | |
|:---|:---|
| Wall time | 50 s (one pass with area assembly: 41 s reading, 9 s assembling and writing) |
| Peak RSS | 1.13 GB |
| Output | 52.1 MB, 41 files (`.npy` + `manifest.json` with SHA-256 per file) |
| Walking graph | 831,641 nodes, 1,874,608 directed edges |
| Stops | 5,553 (5,450 bus; MRT/LRT stations, all on the walking graph within 400 m) |
| Patterns | 882 (bus 849, MRT 21, LRT 12), 27,940 stop calls |
| Transfers | 18,074 |
| Places | 100,015 (malls, stations, hospitals, HDB blocks with postal codes, ...) |

Lines found (longest pattern, stops): NSL 27, EWL 33 (+ Changi branch 3), NEL 17, CCL 31, DTL 35, TEL 27, JRL 12,
SKLRT 10, PGLRT 9, BPLRT 19, Sentosa Express 4. 180 stations are on a line; names are clean (no line codes, no
duplicates).

What it took to get there (all in the builder, each covered by `core/tests/test_navbundle_build.py`):
- Stations are mapped as nodes, as areas (Sengkang, Punggol) and only as stop positions, so the builder reads all
  three. Stop positions join the station with the same name, so "Sengkang - West Loop Clockwise" is no longer a
  station of its own.
- Punggol LRT, Bukit Panjang LRT and Sentosa Express are `route=monorail` (the airport Skytrain is excluded).
- A station any MRT line calls at counts as MRT, even when it is tagged `light_rail`.
- VivoCity is a multipolygon, so places come from osmium areas, not only closed ways.
- A place is reached by its outline plus its mapped entrances, and a route ends at whichever is quickest.
  - Northpoint City has only 2 mapped entrances and Causeway Point only 1.
  - Using entrances alone sent routes round the building: Yishun MRT to Northpoint took 4 min, where the real
    link bridge takes 1 min.
- Unit numbers (`#01-03`) are not addresses.

## Queries (`core/cortex_core/nav`, bundle memory-mapped)

| | |
|:---|:---|
| Open bundle | 4 ms (58 ms with SHA-256 verify) |
| `search_places` | median 14 ms, max 37 ms (12 queries); names are built on a thread at start, so the first search is 9 ms, not 311 ms |
| `plan_trip` | median 68 ms, max 113 ms (10 trips) |
| Process RSS with bundle loaded and searched | 180 MB |

Example trips (frequency-based, 9 am headways; these are the answers the LM will see):

| From → to | Plan | ms |
|:---|:---|---:|
| Yishun MRT → Northpoint City | Walk 1 min | 68 |
| Khatib MRT → Northpoint City | NSL 1 stop, walk 1 min; about 8 min | 68 |
| Ang Mo Kio Hub → Northpoint City | walk 4, NSL 3 stops, walk 1; about 23 min | 93 |
| Bishan MRT → Causeway Point | NSL 8 stops, walk 3; about 36 min | 113 |
| Changi Airport MRT → Sengkang MRT | EWL 2 (change at Tanah Merah), EWL 4, CCL 4, NEL 4; about 56 min | 43 |
| Punggol MRT → HarbourFront MRT | NEL 15 stops; about 39 min | 66 |
| KTPH → Ang Mo Kio Hub | walk 5, bus 853 2 stops, walk 3, NSL 2, walk 3; about 36 min | 97 |
| Jurong Point → VivoCity | walk 6, EWL 10, walk 2, bus 123M 8 stops, walk 2; about 62 min | 98 |

## Known gaps (honest)

- **No live data yet.**
  - Waits are half the default headway. LTA DataMall headways and live arrivals need the fetch job and the
    gateway proxy, which are not built.
  - Times are estimates; they are not timetables.
- **Jurong Point → VivoCity** picks EWL + bus 123M. A person would likely take EWL → Outram Park → NEL or
  EWL → Buona Vista → CCL.
  - With equal rides and similar estimated times, the planner has no reason to prefer rail.
  - Revisit once real headways are in.
- **Punggol MRT → Waterway Point** says "You are there". The station node sits inside the mall, which is true on the
  ground, but the walk from the platform is not modelled.
- **Indoor routes inside stations** (platform to exit) are not modelled; INDOOR_NAV mode relies on vision for that.
