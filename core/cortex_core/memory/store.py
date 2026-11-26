"""Memory's SQLite store (box only: /var/lib/cortex/memory/memory.db, never in git). Text only, never images.

items      the user's own items (built-in ones live in code)
sightings  item, t, looks, spot (scene words), place (named place), lat/lon/acc (cleared after 30 days)

WAL mode: the brain (scans, recall) and the link (the app's item edits) open the same file at once.
A new sighting of an item at the same place within MERGE_S updates the last row; KEEP_PER_ITEM rows are kept.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from cortex_core.memory import items as I

DEFAULT_PATH = "/var/lib/cortex/memory/memory.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (name TEXT PRIMARY KEY, aliases TEXT NOT NULL DEFAULT '[]',
                                  details TEXT NOT NULL DEFAULT '', added REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sightings (id INTEGER PRIMARY KEY, item TEXT NOT NULL, t REAL NOT NULL,
                                      looks TEXT NOT NULL DEFAULT '', spot TEXT NOT NULL DEFAULT '', place TEXT,
                                      lat REAL, lon REAL, acc REAL);
CREATE INDEX IF NOT EXISTS sightings_item_t ON sightings (item, t);
"""


class Store:
    MERGE_S = 600.0
    KEEP_PER_ITEM = 20
    COORDS_DAYS = 30

    def __init__(self, path: str | Path = DEFAULT_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)

    # ---- the user's own items
    def user_items(self) -> list[I.Item]:
        with self._lock:
            rows = self._db.execute("SELECT name, aliases, details FROM items ORDER BY added").fetchall()
        return [I.Item(r["name"], tuple(json.loads(r["aliases"])), r["details"]) for r in rows]

    def add_item(self, name: str, details: str = "", aliases: list[str] | None = None) -> I.Item:
        n = I.clean_name(name)
        details = " ".join(str(details or "").split())
        al = tuple(dict.fromkeys(a for a in (I.clean_name(x) for x in (aliases or [])) if a and a != n))
        if not n:
            raise ValueError("an item needs a name")
        if len(n) > I.MAX_NAME:
            raise ValueError(f"item names are at most {I.MAX_NAME} characters")
        if len(details) > I.MAX_DETAILS:
            raise ValueError(f"details are at most {I.MAX_DETAILS} characters")
        cat = I.catalogue(self)
        for word in (n, *al):
            hit = I.match(cat, word)
            if hit is not None:
                raise ValueError(f"'{word}' is already an item ({hit.name})")
        with self._lock:
            if self._db.execute("SELECT COUNT(*) FROM items").fetchone()[0] >= I.MAX_USER_ITEMS:
                raise ValueError(f"at most {I.MAX_USER_ITEMS} items of your own")
            self._db.execute("INSERT INTO items (name, aliases, details, added) VALUES (?, ?, ?, ?)",
                             (n, json.dumps(list(al)), details, time.time()))
        return I.Item(n, al, details)

    def remove_item(self, name: str) -> None:
        hit = I.match(I.catalogue(self), name)
        if hit is None:
            raise ValueError(f"no item called '{name}'")
        if hit.builtin:
            raise ValueError(f"'{hit.name}' is built in and cannot be removed")
        with self._lock:
            self._db.execute("DELETE FROM items WHERE name = ?", (hit.name,))
            self._db.execute("DELETE FROM sightings WHERE item = ?", (hit.name,))

    # ---- sightings
    def record(self, item: str, t: float, looks: str, spot: str, place: str | None,
               lat: float | None, lon: float | None, acc: float | None) -> None:
        with self._lock:
            last = self._db.execute("SELECT id, t, place FROM sightings WHERE item = ? ORDER BY t DESC LIMIT 1",
                                    (item,)).fetchone()
            if last is not None and last["place"] == place and 0 <= t - last["t"] <= self.MERGE_S:
                self._db.execute(
                    "UPDATE sightings SET t = ?, looks = CASE WHEN ? = '' THEN looks ELSE ? END, "
                    "spot = CASE WHEN ? = '' THEN spot ELSE ? END, lat = COALESCE(?, lat), lon = COALESCE(?, lon), "
                    "acc = COALESCE(?, acc) WHERE id = ?",
                    (t, looks, looks, spot, spot, lat, lon, acc, last["id"]))
                return
            self._db.execute("INSERT INTO sightings (item, t, looks, spot, place, lat, lon, acc) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (item, t, looks, spot, place, lat, lon, acc))
            self._db.execute("DELETE FROM sightings WHERE item = ? AND id NOT IN "
                             "(SELECT id FROM sightings WHERE item = ? ORDER BY t DESC LIMIT ?)",
                             (item, item, self.KEEP_PER_ITEM))

    def sightings(self, item: str, limit: int = KEEP_PER_ITEM) -> list[dict]:
        """Newest first."""
        with self._lock:
            rows = self._db.execute("SELECT item, t, looks, spot, place, lat, lon, acc FROM sightings "
                                    "WHERE item = ? ORDER BY t DESC LIMIT ?", (item, limit)).fetchall()
        return [dict(r) for r in rows]

    def purge(self, now: float | None = None) -> None:
        """Clears GPS coordinates older than COORDS_DAYS (the words, place name and time stay)."""
        cut = (time.time() if now is None else now) - self.COORDS_DAYS * 86400.0
        with self._lock:
            self._db.execute("UPDATE sightings SET lat = NULL, lon = NULL, acc = NULL "
                             "WHERE t < ? AND (lat IS NOT NULL OR lon IS NOT NULL OR acc IS NOT NULL)", (cut,))

    def forget(self, item: str | None = None) -> None:
        """Clears the sightings: all, or one item's."""
        with self._lock:
            if item is None:
                self._db.execute("DELETE FROM sightings")
            else:
                self._db.execute("DELETE FROM sightings WHERE item = ?", (item,))

    def close(self) -> None:
        with self._lock:
            self._db.close()
