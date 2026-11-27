"""Tests for apk_signer.py (run: python3 -m pytest infra/deploy/test_apk_signer.py). No network, no real key: the
GitHub API, the download and apksigner are fakes."""
import json
import os

import pytest

import apk_signer as A

APK = b"PK\x03\x04" + b"\0" * 64


def release(asset_id=7, uploader="github-actions[bot]", name=A.ASSET, size=len(APK), title="Cortex app (beta build 12)"):
    return {"name": title, "target_commitish": "abc1234def", "assets": [
        {"id": asset_id, "name": name, "size": size, "browser_download_url": f"https://example/{asset_id}",
         "uploader": {"login": uploader}}]}


class Fakes:
    def __init__(self, rel, body=APK, sign_ok=True, cert="ab" * 32):
        self.rel, self.body, self.sign_ok, self.cert = rel, body, sign_ok, cert
        self.downloads, self.signed = 0, []

    def get_json(self, url):
        return self.rel

    def download(self, url, dest, limit):
        self.downloads += 1
        with open(dest, "wb") as f:
            f.write(self.body)

    def sign(self, src, dest):
        if not self.sign_ok:
            raise A.SignError("apksigner failed")
        self.signed.append(src)
        with open(src, "rb") as i, open(dest, "wb") as o:
            o.write(i.read() + b"SIGNED")
        return self.cert


def run(tmp_path, f):
    return A.update(str(tmp_path), f.get_json, f.download, f.sign)


def test_signs_the_new_build_and_serves_it(tmp_path):
    f = Fakes(release())
    assert run(tmp_path, f) == "signed build 12"
    assert (tmp_path / "cortex.apk").read_bytes() == APK + b"SIGNED"
    v = json.loads((tmp_path / "version.json").read_text())
    assert v["build"] == 12 and v["asset_id"] == 7 and v["commit"] == "abc1234" and v["cert_sha256"] == "ab" * 32
    assert len(v["sha256"]) == 64
    assert sorted(os.listdir(tmp_path)) == ["cortex.apk", "version.json"]  # no temp files left behind


def test_the_same_build_is_not_signed_twice(tmp_path):
    f = Fakes(release())
    run(tmp_path, f)
    assert run(tmp_path, f) == "up to date (build 12)"
    assert f.downloads == 1


def test_a_newer_build_replaces_the_old_one(tmp_path):
    run(tmp_path, Fakes(release()))
    assert run(tmp_path, Fakes(release(asset_id=8, title="Cortex app (beta build 13)"), body=APK + b"new")) == "signed build 13"
    assert (tmp_path / "cortex.apk").read_bytes() == APK + b"new" + b"SIGNED"


@pytest.mark.parametrize("rel,why", [
    (release(uploader="someone"), "not uploaded by CI"),
    (release(name="other.apk"), "no cortex-ci.apk"),
    (release(size=A.MAX_APK + 1), "too big"),
])
def test_refuses_what_ci_did_not_make(tmp_path, rel, why):
    f = Fakes(rel)
    with pytest.raises(A.SignError, match=why):
        run(tmp_path, f)
    assert f.downloads == 0 and not f.signed and os.listdir(tmp_path) == []


def test_refuses_a_download_that_is_not_an_apk(tmp_path):
    with pytest.raises(A.SignError, match="not an APK"):
        run(tmp_path, Fakes(release(), body=b"<html>"))
    assert os.listdir(tmp_path) == []


def test_a_failed_signing_keeps_the_served_apk(tmp_path):
    run(tmp_path, Fakes(release()))
    before = (tmp_path / "cortex.apk").read_bytes()
    with pytest.raises(A.SignError):
        run(tmp_path, Fakes(release(asset_id=8, title="Cortex app (beta build 13)"), sign_ok=False))
    assert (tmp_path / "cortex.apk").read_bytes() == before
    assert json.loads((tmp_path / "version.json").read_text())["build"] == 12
    assert sorted(os.listdir(tmp_path)) == ["cortex.apk", "version.json"]


def test_a_different_signing_cert_is_refused(tmp_path):
    run(tmp_path, Fakes(release()))
    with pytest.raises(A.SignError, match="certificate changed"):
        run(tmp_path, Fakes(release(asset_id=8, title="Cortex app (beta build 13)"), cert="cd" * 32))
