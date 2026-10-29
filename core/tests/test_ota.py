import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from cortex_core.contracts import common_pb2 as c, ota_pb2 as o
from cortex_core.ota.agent import OtaAgent
from cortex_core.ota.slots import Slots
from cortex_core.ota.verify import (BadArtifact, BadSignature, RingNotAllowed, Rollback, TooEarly,
                                    signing_bytes, verify_artifact, verify_manifest)

OLD, NEW = b"old-firmware-image" * 50, b"new-firmware-image" * 50
NOW = 1_800_000_000_000


def keypair():
    k = Ed25519PrivateKey.generate()
    return k, k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def manifest(k, counter=5, max_ring=c.RING_STABLE, data=NEW, **kw):
    m = o.Manifest(release_id=f"r{counter}", version_counter=counter, max_ring=max_ring, **kw)
    m.artifacts.add(kind=o.ARTIFACT_KIND_COMPUTE_FIRMWARE, version=f"4.0.{counter}", url="https://x",
                    size_bytes=len(data), sha256=hashlib.sha256(data).digest())
    m.manifest_signature = k.sign(signing_bytes(m))
    return m


# ---- verifier ----
def test_valid_manifest_and_every_rejection():
    k, pub = keypair()
    m = manifest(k)
    verify_manifest(m, pub, c.RING_ALPHA, 4, NOW)
    verify_manifest(m, pub, c.RING_ALPHA, 5, NOW)  # same counter allowed (re-verify), install path requires >
    with pytest.raises(Rollback):
        verify_manifest(m, pub, c.RING_ALPHA, 6, NOW)
    with pytest.raises(RingNotAllowed):
        verify_manifest(manifest(k, max_ring=c.RING_BETA), pub, c.RING_STABLE, 0, NOW)
    with pytest.raises(RingNotAllowed):
        verify_manifest(manifest(k, max_ring=c.RING_UNSPECIFIED), pub, c.RING_ALPHA, 0, NOW)
    with pytest.raises(TooEarly):
        verify_manifest(manifest(k, not_before_ms=NOW + 1), pub, c.RING_ALPHA, 0, NOW)
    m.artifacts[0].version = "evil"
    with pytest.raises(BadSignature):
        verify_manifest(m, pub, c.RING_ALPHA, 0, NOW)
    with pytest.raises(BadSignature):
        verify_manifest(manifest(k), keypair()[1], c.RING_ALPHA, 0, NOW)
    with pytest.raises(BadSignature):
        verify_manifest(manifest(k), b"short", c.RING_ALPHA, 0, NOW)


def test_artifact_checks():
    k, _ = keypair()
    a = manifest(k).artifacts[0]
    verify_artifact(a, NEW)
    for bad in (NEW + b"x", NEW[:-1], b"y" * len(NEW)):
        with pytest.raises(BadArtifact):
            verify_artifact(a, bad)


@pytest.mark.skipif(not shutil.which("go"), reason="go toolchain not available")
def test_go_signed_manifest_verifies_in_python(tmp_path):
    """Cross-check: a manifest produced by the gateway's cortex-sign verifies here (same signing bytes)."""
    gw = Path(__file__).resolve().parents[2] / "infra" / "gateway"
    art = tmp_path / "compute.img"
    art.write_bytes(NEW)
    run = lambda *a: subprocess.run(["go", "run", "./cmd/cortex-sign", *a], cwd=gw, capture_output=True, text=True, check=True)
    pubhex = run("keygen", "-out", str(tmp_path / "k")).stdout.split(":")[1].strip()
    run("sign", "-key", str(tmp_path / "k"), "-release", "rgo", "-counter", "7", "-max-ring", "beta",
        "-artifact", f"compute:4.0.7:{art}:https://x", "-out", str(tmp_path / "m"))
    m = o.Manifest.FromString((tmp_path / "m").read_bytes())
    pub = bytes.fromhex(pubhex)
    verify_manifest(m, pub, c.RING_BETA, 6, NOW)
    verify_artifact(m.artifacts[0], NEW)
    assert m.version_counter == 7
    with pytest.raises(RingNotAllowed):
        verify_manifest(m, pub, c.RING_STABLE, 0, NOW)


# ---- slots ----
def seeded(tmp_path, fault=lambda p: None, trials=3):
    """Device with OLD committed in slot A."""
    s = Slots(tmp_path, trial_boots=trials)
    s.s["slots"]["A"] = {"version": "4.0.1", "sha256": hashlib.sha256(OLD).hexdigest()}
    s.s["counter"] = 1
    s.image("A").write_bytes(OLD)
    s._save("seed")
    return Slots(tmp_path, fault=fault, trial_boots=trials)


def full_update(s, boot=True):
    sha = hashlib.sha256(NEW).digest()
    s.stage("4.0.5", 5, "r5", NEW, sha)
    s.switch("r5", 5)
    if boot:
        assert s.boot_select() == "B"
        assert s.confirm("r5")


def test_happy_path_commits_and_raises_counter(tmp_path):
    s = seeded(tmp_path)
    full_update(s)
    assert (s.active, s.counter) == ("B", 5)
    assert Slots(tmp_path).active == "B"  # survives restart


def test_trials_exhausted_rolls_back_to_old_slot(tmp_path):
    s = seeded(tmp_path, trials=2)
    full_update(s, boot=False)
    assert s.boot_select() == "B" and s.boot_select() == "B"  # two trial boots, never confirmed
    assert s.boot_select() == "A"  # third power-on: automatic rollback
    assert (s.active, s.counter) == ("A", 1)
    assert s.take_rollback() == "r5" and s.take_rollback() is None


def test_failed_self_test_does_not_commit(tmp_path):
    k, pub = keypair()
    s = seeded(tmp_path, trials=1)
    agent = OtaAgent(s, pub, c.RING_STABLE, self_test=lambda: False, clock=lambda: NOW / 1000)
    assert agent.apply(manifest(k), lambda a: NEW).detail.startswith("staged")
    assert s.boot_select() == "B"
    assert agent.after_boot("r5").outcome == o.OTA_OUTCOME_ROLLED_BACK
    assert s.boot_select() == "A" and s.counter == 1


def test_agent_rejects_bad_updates_before_touching_slots(tmp_path):
    k, pub = keypair()
    s = seeded(tmp_path)
    agent = OtaAgent(s, pub, c.RING_BETA, self_test=lambda: True, clock=lambda: NOW / 1000)
    fetched = []
    fetch = lambda a: fetched.append(a) or NEW
    bad_sig = manifest(k); bad_sig.release_id = "tampered"
    for m, why in [(bad_sig, "signature"), (manifest(k, counter=0), "below device counter"), (manifest(k, counter=1), "already"),
                   (manifest(keypair()[0]), "signature")]:
        r = agent.apply(m, fetch)
        assert r.outcome == o.OTA_OUTCOME_REJECTED and why in r.detail, (why, r.detail)
    assert agent.apply(manifest(k, data=b"other"), fetch).outcome == o.OTA_OUTCOME_REJECTED  # artifact hash mismatch vs served bytes
    assert s.s["pending"] is None and s.active == "A" and not s.image("B").exists()
    assert len(fetched) == 1  # nothing was downloaded for the signature/rollback rejections


def test_cannot_switch_to_corrupt_staged_image(tmp_path):
    s = seeded(tmp_path)
    s.stage("4.0.5", 5, "r5", NEW, hashlib.sha256(NEW).digest())
    s.image("B").write_bytes(b"bitrot")
    with pytest.raises(BadArtifact):
        s.switch("r5", 5)


class Crash(Exception): ...


def trace_points(tmp_path):
    pts = []
    s = seeded(tmp_path, fault=pts.append)
    full_update(s)
    return pts


def test_power_loss_at_every_step_leaves_a_bootable_slot(tmp_path):
    points = trace_points(tmp_path / "trace")
    assert len(points) > 15
    new_sha, old_sha = hashlib.sha256(NEW).hexdigest(), hashlib.sha256(OLD).hexdigest()
    for i in range(len(points)):
        root = tmp_path / f"cut{i}"
        n = [0]

        def cut(p, i=i):
            if n[0] == i:
                n[0] += 1
                raise Crash(p)
            n[0] += 1

        s = seeded(root, fault=cut)
        try:
            full_update(s)
        except Crash:
            pass
        # power back on: fresh process, only the disk survives
        s2 = Slots(root)
        slot = s2.boot_select()
        img = s2.image(slot).read_bytes()
        assert hashlib.sha256(img).hexdigest() in (old_sha, new_sha), f"cut at {points[i]} booted a torn image"
        assert s2._intact(slot), f"cut at {points[i]}: booted slot fails its recorded hash"
        # and the device can still finish (or retry) an update from here
        if s2.s["pending"] is None and s2.counter < 5:
            full_update(s2)
            assert s2.counter == 5
        # the anti-rollback counter never goes down
        assert s2.counter >= 1


def test_corrupt_active_image_falls_back_to_other_good_slot(tmp_path):
    s = seeded(tmp_path)
    full_update(s)
    s.image("B").write_bytes(b"flash wear")
    assert Slots(tmp_path).boot_select() == "A"
