"""A/B slot state machine with crash-safe persistence.

Flow: stage (write inactive slot) -> switch (mark pending, N trial boots) ->
boot_select (bootloader view, burns a trial) -> confirm after the safety
self-test (commit) | trials exhausted (automatic rollback).

Every durable change is an atomic write (temp file, fsync, rename). The state
file is the single commit point, so a power cut at any step leaves the previous
slot bootable. `fault(point)` is a test hook that may raise to simulate a cut.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Optional

from cortex_core.ota.verify import BadArtifact

TRIAL_BOOTS = 3


def _noop(point: str) -> None: ...


class Slots:
    def __init__(self, root: Path, fault: Callable[[str], None] = _noop, trial_boots: int = TRIAL_BOOTS):
        self.root, self.fault, self.trials = Path(root), fault, trial_boots
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "ota-state.json"
        self.s = self._load()

    # ---- persistence ----
    def _load(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (FileNotFoundError, ValueError):
            return {"active": "A", "counter": 0, "pending": None,
                    "slots": {"A": {"version": "", "sha256": ""}, "B": {"version": "", "sha256": ""}}}

    def _atomic(self, path: Path, data: bytes, point: str) -> None:
        tmp = path.with_name(path.name + ".tmp")
        self.fault(point + ":before")
        with open(tmp, "wb") as f:
            f.write(data[: len(data) // 2])  # a cut here leaves a torn temp file
            self.fault(point + ":torn")
            f.write(data[len(data) // 2:])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        self.fault(point + ":after")

    def _save(self, point: str) -> None:
        self._atomic(self.state_path, json.dumps(self.s).encode(), point)

    def image(self, slot: str) -> Path:
        return self.root / f"{slot}.img"

    # ---- queries ----
    @property
    def active(self) -> str:
        return self.s["active"]

    @property
    def inactive(self) -> str:
        return "B" if self.active == "A" else "A"

    @property
    def counter(self) -> int:
        return self.s["counter"]

    def _intact(self, slot: str) -> bool:
        want = self.s["slots"][slot]["sha256"]
        p = self.image(slot)
        return bool(want) and p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == want

    # ---- update steps ----
    def stage(self, version: str, counter: int, release_id: str, data: bytes, sha256: bytes) -> str:
        """Write the image to the inactive slot. Never touches the active slot."""
        if hashlib.sha256(data).digest() != sha256:
            raise BadArtifact("artifact hash mismatch")
        if self.s["pending"]:
            raise RuntimeError("an update is already pending")
        slot = self.inactive
        self.s["slots"][slot] = {"version": "", "sha256": ""}  # invalidate first: a torn image must never look valid
        self._save("stage-invalidate")
        self._atomic(self.image(slot), data, "stage-image")
        self.s["slots"][slot] = {"version": version, "sha256": sha256.hex()}
        self._save("stage-record")
        return slot

    def switch(self, release_id: str, counter: int) -> None:
        """Commit point of the update: next boot tries the new slot."""
        slot = self.inactive
        if not self._intact(slot):
            raise BadArtifact("staged image missing or corrupt")
        self.s["pending"] = {"slot": slot, "release_id": release_id, "counter": counter, "trials_left": self.trials}
        self._save("switch")

    def boot_select(self) -> str:
        """What the bootloader does at power-on. Returns the slot to boot."""
        p = self.s["pending"]
        if p:
            if p["trials_left"] > 0 and self._intact(p["slot"]):
                p["trials_left"] -= 1
                self._save("trial-burn")
                return p["slot"]
            self.s["pending"] = None  # trials exhausted or image bad: automatic rollback
            self.s["rolled_back"] = p["release_id"]
            self._save("rollback")
        if self._intact(self.active):
            return self.active
        other = "B" if self.active == "A" else "A"
        if self._intact(other):  # last resort: active image damaged, fall back to the other good one
            return other
        return self.active  # factory image / recovery handled by the bootloader

    def confirm(self, release_id: str) -> bool:
        """Called by the new slot after its safety self-test passes. Commits the update."""
        p = self.s["pending"]
        if not p or p["release_id"] != release_id:
            return False
        self.s["active"], self.s["counter"], self.s["pending"] = p["slot"], max(self.counter, p["counter"]), None
        self._save("confirm")
        return True

    def take_rollback(self) -> Optional[str]:
        """Release id of an automatic rollback not yet reported, so the OTA agent can tell the gateway."""
        r = self.s.pop("rolled_back", None)
        if r:
            self._save("rollback-ack")
        return r
