"""Memory: item list, the scan prompt and its parser, the SQLite store, the scan policy and recall."""
import sqlite3
import threading

import pytest

from cortex_core.memory import items as I
from cortex_core.memory import look as L
from cortex_core.memory.memory import Memory, ago
from cortex_core.memory.store import Store

DAY = 86400.0


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def view(fid, skipped=False):
    return {"type": "view", "frame_id": fid, "skipped": skipped}


# ---------------------------------------------------------------- items
def test_builtin_items_and_matching(tmp_path):
    s = Store(tmp_path / "m.db")
    cat = I.catalogue(s)
    names = [i.name for i in cat]
    assert names[:6] == ["keys", "wallet", "phone", "glasses", "bag", "cane"]
    for said, want in [("my keys", "keys"), ("Key", "keys"), ("the house keys", "keys"), ("purse", "wallet"),
                       ("handphone", "phone"), ("my backpack", "bag"), ("white cane", "cane"),
                       ("spectacles", "glasses"), ("umbrella", None), ("", None)]:
        assert I.match(cat, said) == (want and next(i for i in cat if i.name == want)), said


def test_user_items_add_remove_limits(tmp_path):
    s = Store(tmp_path / "m.db")
    s.add_item("Water bottle", details="blue metal, dented", aliases=["bottle", "flask"])
    cat = I.catalogue(s)
    bottle = I.match(cat, "my flask")
    assert bottle.name == "water bottle" and bottle.details == "blue metal, dented" and not bottle.builtin
    assert I.match(cat, "water bottles").name == "water bottle"
    with pytest.raises(ValueError):
        s.add_item("keys")  # a built-in
    with pytest.raises(ValueError):
        s.add_item("WATER bottle")  # already there
    with pytest.raises(ValueError):
        s.add_item("x" * 41)
    with pytest.raises(ValueError):
        s.add_item("ok", details="d" * 121)
    with pytest.raises(ValueError):
        s.add_item("  ")
    with pytest.raises(ValueError):
        s.remove_item("keys")
    s.remove_item("water bottle")
    assert I.match(I.catalogue(s), "flask") is None
    for k in range(I.MAX_USER_ITEMS):
        s.add_item(f"thing {k}")
    with pytest.raises(ValueError):
        s.add_item("one too many")


# ---------------------------------------------------------------- the scan prompt and parser
def test_prompt_lists_items_with_details(tmp_path):
    s = Store(tmp_path / "m.db")
    s.add_item("water bottle", details="blue metal")
    p = L.prompt(I.catalogue(s))
    for n in ("keys", "wallet", "phone", "glasses", "bag", "cane", "water bottle (blue metal)"):
        assert n in p
    assert "none" in p and "|" in p


def test_parse_keeps_listed_clear_sightings_only(tmp_path):
    cat = I.catalogue(Store(tmp_path / "m.db"))
    out = L.parse(cat, """<think></think>
- keys | silver, two keys on a red ring | on the kitchen table, left of the kettle
2. Wallet | black leather | maybe on the chair
phone | | in the user's hand
umbrella | red | by the door
keys | again | twice
bag: brown backpack
""")
    assert [(o.item, o.looks, o.spot) for o in out] == [
        ("keys", "silver, two keys on a red ring", "on the kitchen table, left of the kettle"),
        ("phone", "", "in the user's hand"),
    ]


@pytest.mark.parametrize("text", ["none", "None.", "", "I can't see any of those items.", "garbage ||| ||",
                                  "keys | not visible | -", "cane | I cannot see it clearly | ?"])
def test_parse_nothing(tmp_path, text):
    assert L.parse(I.catalogue(Store(tmp_path / "m.db")), text) == []


def test_parse_cuts_long_text(tmp_path):
    out = L.parse(I.catalogue(Store(tmp_path / "m.db")), "keys | " + "a" * 300 + " | " + "b" * 300)
    assert len(out[0].looks) == L.MAX_TEXT and len(out[0].spot) == L.MAX_TEXT


# ---------------------------------------------------------------- store
def test_record_merges_same_place_soon_and_keeps_20(tmp_path):
    s = Store(tmp_path / "m.db")
    t = 1_000_000.0
    s.record("keys", t, "silver", "on the table", "Home", 1.35, 103.8, 5)
    s.record("keys", t + 300, "silver ring", "", "Home", 1.35, 103.8, 5)  # merged: newer time and looks, spot kept
    rows = s.sightings("keys")
    assert len(rows) == 1 and rows[0]["t"] == t + 300 and rows[0]["looks"] == "silver ring" \
        and rows[0]["spot"] == "on the table"
    s.record("keys", t + 300 + 601, "silver", "on the sofa", "Home", 1.35, 103.8, 5)  # 10 min later: new row
    s.record("keys", t + 2000, "silver", "in the bag", "Northpoint", 1.42, 103.83, 8)  # another place: new row
    assert [r["spot"] for r in s.sightings("keys")] == ["in the bag", "on the sofa", "on the table"]
    for k in range(30):
        s.record("keys", t + 10_000 + k * 1000, "", f"spot {k}", None, None, None, None)
    assert len(s.sightings("keys", limit=100)) == Store.KEEP_PER_ITEM


def test_purge_clears_coordinates_after_30_days_keeps_words(tmp_path):
    s = Store(tmp_path / "m.db")
    now = 1_800_000_000.0
    s.record("wallet", now - 31 * DAY, "black", "on the desk", "Home", 1.35, 103.8, 5)
    s.record("phone", now - 29 * DAY, "", "in the bag", "Home", 1.35, 103.8, 5)
    s.purge(now)
    w, p = s.sightings("wallet")[0], s.sightings("phone")[0]
    assert (w["lat"], w["lon"], w["acc"]) == (None, None, None) and w["place"] == "Home" and w["spot"] == "on the desk"
    assert p["lat"] == 1.35
    raw = sqlite3.connect(tmp_path / "m.db").execute("SELECT lat FROM sightings WHERE item='wallet'").fetchone()
    assert raw == (None,)


def test_forget_and_remove_drop_sightings(tmp_path):
    s = Store(tmp_path / "m.db")
    s.add_item("umbrella")
    for it in ("keys", "wallet", "umbrella"):
        s.record(it, 1.0, "", "here", None, None, None, None)
    s.forget("keys")
    assert s.sightings("keys") == [] and s.sightings("wallet")
    s.remove_item("umbrella")
    assert s.sightings("umbrella") == []
    s.forget()
    assert s.sightings("wallet") == []


def test_two_processes_share_the_file(tmp_path):
    a, b = Store(tmp_path / "m.db"), Store(tmp_path / "m.db")  # the link adds, the brain sees it at once
    a.add_item("umbrella", details="red")
    assert I.match(I.catalogue(b), "umbrella").details == "red"
    b.record("umbrella", 5.0, "red", "by the door", None, None, None, None)
    assert a.sightings("umbrella")[0]["spot"] == "by the door"


# ---------------------------------------------------------------- scan policy
class Looker:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt, max_tokens):
        self.prompts.append((prompt, max_tokens))
        return self.answers.pop(0) if self.answers else "none"


def mem(tmp_path, answers=(), where=None, clock=None):
    clock = clock or Clock()
    return Memory(Store(tmp_path / "m.db"), Looker(answers), where=where, clock=clock), clock


def test_wants_scan_rules(tmp_path):
    m, clk = mem(tmp_path)
    assert not m.wants_scan(view(1, skipped=True), idle=True)  # same scene as before
    assert not m.wants_scan(view(1), idle=False)               # the user is busy
    assert not m.wants_scan({"type": "error", "what": "x"}, idle=True)
    assert m.wants_scan(view(1), idle=True)
    m.scan(view(1))
    clk.t += 60
    assert not m.wants_scan(view(1), idle=True)                # already scanned
    clk.t -= 45
    assert not m.wants_scan(view(2), idle=True)                # 15 s after the last scan
    clk.t += 15
    assert m.wants_scan(view(2), idle=True)
    assert not Memory(Store(tmp_path / "n.db"), None).wants_scan(view(1), idle=True)  # engine cannot peek


def test_budget_caps_scans_per_window(tmp_path):
    m, clk = mem(tmp_path)
    n = 0
    for fid in range(1, 20):  # 19 views 31 s apart: all inside one 10 min window
        clk.t += 31
        if m.wants_scan(view(fid), idle=True):
            m.scan(view(fid))
            n += 1
    assert n == Memory.BUDGET_N
    clk.t += Memory.BUDGET_S
    assert m.wants_scan(view(99), idle=True)


def test_scan_records_with_place_and_cancelled_scan_stores_nothing(tmp_path):
    where = lambda: {"name": "Home", "lat": 1.35, "lon": 103.8, "acc_m": 6.0}
    m, clk = mem(tmp_path, ["keys | silver | on the kitchen table", None], where=where)
    got = m.scan(view(1))
    assert [g.item for g in got] == ["keys"]
    r = m.store.sightings("keys")[0]
    assert (r["place"], r["spot"], r["lat"], r["t"]) == ("Home", "on the kitchen table", 1.35, clk.t)
    clk.t += 40
    assert m.scan(view(2)) == [] and len(m.store.sightings("keys")) == 1
    assert m.looker.prompts[0][1] == Memory.MAX_TOKENS


def test_scan_without_place_or_with_failing_where(tmp_path):
    def broken():
        raise RuntimeError("nav down")
    m, _ = mem(tmp_path, ["wallet | black | on the desk"], where=broken)
    m.scan(view(1))
    r = m.store.sightings("wallet")[0]
    assert r["place"] is None and r["spot"] == "on the desk"


@pytest.mark.parametrize("dt,words", [(20, "just now"), (90, "about 2 minutes ago"), (59 * 60, "about 59 minutes ago"),
                                      (3 * 3600 + 100, "about 3 hours ago"), (DAY + 5, "about a day ago"),
                                      (4 * DAY, "4 days ago")])
def test_ago(dt, words):
    assert ago(dt) == words


def test_search(tmp_path):
    m, clk = mem(tmp_path)
    s = m.store
    s.record("keys", clk.t - 3 * 3600, "silver", "in the bag", "Northpoint", None, None, None)
    s.record("keys", clk.t - 20 * 60, "silver, red ring", "on the kitchen table", "Home", None, None, None)
    data, say = m.search("my keys")
    assert say is None
    assert data == {"item": "keys", "seen": True, "spot": "on the kitchen table", "place": "Home",
                    "ago": "about 20 minutes ago", "looks": "silver, red ring",
                    "before": {"spot": "in the bag", "place": "Northpoint", "ago": "about 3 hours ago"}}
    assert m.search("wallet")[0] == {"item": "wallet", "seen": False}
    err = m.search("umbrella")[0]["error"]
    assert "keys" in err and "app" in err
    s.add_item("umbrella", aliases=["brolly"])
    assert m.search("brolly")[0] == {"item": "umbrella", "seen": False}


def test_scan_and_search_from_threads(tmp_path):
    m, clk = mem(tmp_path, ["keys | a | b"] * 50)
    errs = []

    def scans():
        try:
            for fid in range(50):
                m.scan(view(fid))
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    th = threading.Thread(target=scans)
    th.start()
    for _ in range(50):
        m.search("keys")
    th.join()
    assert not errs
