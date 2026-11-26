"""The silent question a memory scan asks the LM about the current view, and the parser for its answer.

The answer is trusted only as far as the list: unknown items, hedged lines ("maybe", "can't see") and repeats are
dropped, and text is cut to MAX_TEXT characters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from cortex_core.memory.items import Item, match

MAX_TEXT = 80
_HEDGE = re.compile(r"\b(maybe|possibly|might|probably|perhaps|unclear|unsure|not sure|can'?t see|cannot see|"
                    r"can not see|not visible|hard to tell|could be|no sign)\b")
_THINK = re.compile(r"<think>.*?</think>", re.S)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_EMPTY = {"", "-", "?", "n/a", "none", "unknown"}


@dataclass(frozen=True)
class Seen:
    item: str
    looks: str
    spot: str


def _label(it: Item) -> str:
    return f"{it.name} ({it.details})" if it.details else it.name


def prompt(cat: list[Item]) -> str:
    return ("Memory check. Look only at the current camera view. Items: " + "; ".join(_label(i) for i in cat) + ".\n"
            "For each item you can clearly see, write one line: item | what it looks like | where it is in the "
            "scene. Write nothing else. If you see none of them, write: none")


def _text(s: str) -> str:
    s = s.strip().strip(".").strip()
    return "" if s.lower() in _EMPTY else s[:MAX_TEXT]


def parse(cat: list[Item], text: str) -> list[Seen]:
    out: list[Seen] = []
    seen: set[str] = set()
    for line in _THINK.sub("", text or "").splitlines():
        if "|" not in line or _HEDGE.search(line.lower()):
            continue
        parts = [p.strip() for p in _BULLET.sub("", line).split("|")]
        it = match(cat, parts[0])
        if it is None or it.name in seen:
            continue
        seen.add(it.name)
        looks = _text(parts[1]) if len(parts) > 1 else ""
        spot = _text(" | ".join(p for p in parts[2:] if p)) if len(parts) > 2 else ""
        out.append(Seen(it.name, looks, spot))
    return out
