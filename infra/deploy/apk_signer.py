#!/usr/bin/env python3
"""Signs the app with the permanent Cortex key on the gateway server, so the key never leaves it.

CI (.github/workflows/app.yml) publishes a throwaway-signed build as cortex-ci.apk on the app-beta pre-release. This
script (run every few minutes by cortex-apk-signer.timer) takes a new build only if this repo's CI uploaded it,
re-signs it with ~/.config/cortex/android/cortex-release.jks, checks the signature, and swaps it in atomically at
<out>/cortex.apk with <out>/version.json. Caddy serves that folder at https://infra.asirive.com/app/.

It also refuses a build signed by a different certificate than the one already served, so phones never get an update
they would reject. Standard library only; needs Java and apksigner (Android build-tools).

    python3 apk_signer.py --out ~/cortex-infra/app
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = "Asirive/Asirive-Cortex"
TAG = "app-beta"
ASSET = "cortex-ci.apk"
CI_UPLOADER = "github-actions[bot]"
MAX_APK = 300 << 20
HOME = os.path.expanduser("~")
KEYSTORE = os.path.join(HOME, ".config/cortex/android/cortex-release.jks")
PASSFILE = os.path.join(HOME, ".config/cortex/android/keystore.pass")
ALIAS = "cortex"
APKSIGNER = os.path.join(HOME, ".local/android-sdk/build-tools/36.0.0/apksigner")


class SignError(Exception):
    pass


def update(out: str, get_json, download, sign, repo: str = REPO, tag: str = TAG) -> str:
    """One pass. Returns what it did; raises SignError and leaves the served APK as it was on any problem."""
    rel = get_json(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
    asset = next((a for a in rel.get("assets", []) if a.get("name") == ASSET), None)
    if asset is None:
        raise SignError(f"no {ASSET} on the {tag} release")
    if (asset.get("uploader") or {}).get("login") != CI_UPLOADER:
        raise SignError(f"{ASSET} was not uploaded by CI")
    if not 0 < asset.get("size", 0) <= MAX_APK:
        raise SignError(f"{ASSET} is empty or too big")
    m = re.search(r"build (\d+)", rel.get("name", ""))
    build = int(m.group(1)) if m else 0
    vpath = os.path.join(out, "version.json")
    old = {}
    if os.path.exists(vpath):
        with open(vpath) as f:
            old = json.load(f)
    if old.get("asset_id") == asset["id"]:
        return f"up to date (build {old.get('build')})"

    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".sign-", dir=out)
    try:
        raw, signed = os.path.join(tmp, "ci.apk"), os.path.join(tmp, "cortex.apk")
        download(asset["browser_download_url"], raw, MAX_APK)
        with open(raw, "rb") as f:
            if f.read(4) != b"PK\x03\x04":
                raise SignError("download is not an APK")
        cert = sign(raw, signed)
        if old.get("cert_sha256") and old["cert_sha256"] != cert:
            raise SignError("signing certificate changed: phones would refuse the update")
        h = hashlib.sha256()
        with open(signed, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        os.chmod(signed, 0o644)
        os.replace(signed, os.path.join(out, "cortex.apk"))
        info = {"build": build, "asset_id": asset["id"], "commit": rel.get("target_commitish", "")[:7],
                "sha256": h.hexdigest(), "cert_sha256": cert, "signed_at": int(time.time())}
        vtmp = os.path.join(tmp, "version.json")
        with open(vtmp, "w") as f:
            json.dump(info, f)
        os.chmod(vtmp, 0o644)
        os.replace(vtmp, vpath)
        return f"signed build {build}"
    finally:
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


# ---- the real network and apksigner

def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "cortex-apk-signer"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def download(url: str, dest: str, limit: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "cortex-apk-signer"})
    n = 0
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            n += len(chunk)
            if n > limit:
                raise SignError("download over the size limit")
            f.write(chunk)


def make_signer(apksigner: str = APKSIGNER, keystore: str = KEYSTORE, passfile: str = PASSFILE, alias: str = ALIAS):
    def sign(src: str, dest: str) -> str:
        # apksigner drops CI's throwaway signature and signs v1-v3 with ours. The password is passed as a file path,
        # never on the command line.
        r = subprocess.run([apksigner, "sign", "--ks", keystore, "--ks-key-alias", alias, "--ks-pass", f"file:{passfile}",
                            "--out", dest, src], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise SignError(f"apksigner sign failed: {r.stderr.strip()[-300:]}")
        r = subprocess.run([apksigner, "verify", "--print-certs", dest], capture_output=True, text=True, timeout=300)
        certs = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-f]{64})", r.stdout)
        if r.returncode != 0 or len(certs) != 1:
            raise SignError("signed APK does not verify with exactly one signer")
        return certs[0]
    return sign


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=os.path.join(HOME, "cortex-infra/app"))
    p.add_argument("--apksigner", default=APKSIGNER)
    a = p.parse_args(argv)
    try:
        print(update(a.out, get_json, download, make_signer(a.apksigner)))
        return 0
    except (SignError, OSError) as e:
        print(f"apk signer: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
