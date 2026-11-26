"""The items memory knows: the built-in list plus the user's own (from the app, kept in the store).

Nothing outside this list is ever remembered (spec 6.9). match() turns what the user or the LM said ("my house keys",
"the flask") into an item: lower case, "my/the/a" dropped, plurals folded, names and other names both tried.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_USER_ITEMS = 30
MAX_NAME = 40
MAX_DETAILS = 120


@dataclass(frozen=True)
class Item:
    name: str
    aliases: tuple[str, ...] = ()
    details: str = ""
    builtin: bool = False


BUILTIN = (
    Item("keys", ("key", "house keys", "car keys", "keychain", "key ring"), builtin=True),
    Item("wallet", ("purse", "card holder"), builtin=True),
    Item("phone", ("handphone", "mobile", "mobile phone", "smartphone", "iphone", "cellphone"), builtin=True),
    Item("glasses", ("spectacles", "specs", "reading glasses", "sunglasses"), builtin=True),
    Item("bag", ("backpack", "handbag", "sling bag", "tote"), builtin=True),
    Item("cane", ("white cane", "walking stick", "stick"), builtin=True),
)
_LEAD = {"my", "the", "a", "an", "your", "his", "her", "their", "our"}


def _word(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def canon(s: str) -> str:
    """Lower case words, leading my/the/a dropped, plurals folded: "My House Keys" -> "house key"."""
    words = re.findall(r"[a-z0-9]+", str(s).lower())
    while words and words[0] in _LEAD:
        words.pop(0)
    return " ".join(_word(w) for w in words)


def clean_name(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9'\-]+", str(s).lower()))


def catalogue(store) -> list[Item]:
    """The built-in items, then the user's own (read from the store each time: the app may have changed them)."""
    return list(BUILTIN) + store.user_items()


def match(cat: list[Item], said: str) -> Item | None:
    c = canon(said)
    if not c:
        return None
    for it in cat:
        if c == canon(it.name) or any(c == canon(a) for a in it.aliases):
            return it
    return None
