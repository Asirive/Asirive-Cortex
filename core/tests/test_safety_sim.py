"""Safety against the simulated walker (tests/safety_sim.py): a quick gate over 10 seeds, fitted and unfitted (about 25 s).
The full tables (100 seeds, fitted and unfitted) are in docs/measurements/2026-11-safety-sim.md; rerun with
  python -m tests.safety_sim --seeds 100 [--unfitted]
Bars are set from the 100-seed run so a regression shows: must-warn scenes 100 % except the two whose detection
range is physics-limited (sunlight, dark sign), quiet scenes allowed one miss in ten (100 seeds: 94-97 %)."""
import pytest

from tests import safety_sim as S

PHYSICS_LIMITED = {"branch in sunlight", "dark sign"}
NEVER_FALSE = {"open path, looking around", "ceiling 2.3 m", "stairs up", "looking at the phone",
               "branch beside the path", "parked car beside", "canopy 2.4 m", "glass wall (sensor can't see glass)"}


@pytest.fixture(scope="module", params=[True, False], ids=["fitted", "unfitted"])
def sweep(request):
    return S.sweep(10, fitted=request.param)


def test_every_scenario_ran(sweep):
    kinds = {r["kind"] for r in sweep["rows"].values()}
    assert kinds == {"warn", "appear", "quiet", "stand"} and len(sweep["rows"]) >= 26


def test_must_warn_scenes_warn_in_time_on_the_right_side_once(sweep):
    for name, r in sweep["rows"].items():
        if r["kind"] not in ("warn", "appear"):
            continue
        need = 0.6 if name in PHYSICS_LIMITED else 1.0
        assert r["ok"] >= need * r["n"], (name, r["fails"])
        assert not any("scene error" in w for _, w in r["fails"]), name


def test_quiet_scenes_stay_quiet(sweep):
    for name, r in sweep["rows"].items():
        if r["kind"] == "quiet":
            need = 1.0 if name in NEVER_FALSE else 0.9
            assert r["ok"] >= need * r["n"], (name, r["fails"])


def test_standing_and_scanning_does_not_spam(sweep):
    r = sweep["rows"]["standing 0.6 m from a branch, scanning"]
    assert r["ok"] == r["n"], r["fails"]


def test_processing_is_far_inside_the_frame(sweep):
    p = sorted(sweep["proc_ms"])
    assert p[int(len(p) * 0.99)] < 5.0 and p[-1] < 30.0  # frame period 66 ms; the box is ~5x slower than this machine
