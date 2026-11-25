"""Fetches LTA DataMall static bus data for the nav bundle builder (run on the home server, e.g. weekly by cron).

    python infra/navbundle/lta_fetch.py --out ~/cortex-data/lta        # then build.py --lta-dir ~/cortex-data/lta

The AccountKey is read from LTA_ACCOUNT_KEY or a key file (default ~/.config/cortex/lta_key, must not be readable
by group/others). It never enters this repo, the output files or the logs. Each dataset is paged ($skip by 500 until
a short page) and written atomically as {"value": [...], "fetched": "<UTC time>"}; a failed fetch leaves the
previous file in place, so the builder falls back to the last good data (or its defaults).
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://datamall2.mytransport.sg/ltaodataservice/"
DATASETS = ("BusServices", "BusRoutes", "BusStops")
PAGE = 500
KEY_FILE = Path.home() / ".config" / "cortex" / "lta_key"


class FetchError(RuntimeError):
    pass


def load_key(path: Path = KEY_FILE, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    k = (env.get("LTA_ACCOUNT_KEY") or "").strip()
    if k:
        return k
    if not path.is_file():
        raise FetchError(f"no LTA key: set LTA_ACCOUNT_KEY or put it in {path} (chmod 600)")
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise FetchError(f"{path} is readable by others: chmod 600 it")
    k = path.read_text().strip()
    if not k:
        raise FetchError(f"{path} is empty")
    return k


def fetch_all(name: str, key: str, base: str = BASE, timeout: float = 30.0, max_pages: int = 200,
              pause_s: float = 0.0) -> list[dict]:
    rows: list[dict] = []
    for page in range(max_pages):
        url = f"{base}{name}?$skip={page * PAGE}"
        req = urllib.request.Request(url, headers={"AccountKey": key, "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise FetchError(f"{name}: HTTP {e.code}") from None  # never echo the request (it has the key)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise FetchError(f"{name}: {type(e).__name__}") from None
        value = body.get("value") if isinstance(body, dict) else None
        if not isinstance(value, list):
            raise FetchError(f"{name}: no 'value' list in the answer")
        rows.extend(value)
        if len(value) < PAGE:
            return rows
        if pause_s:
            time.sleep(pause_s)
    raise FetchError(f"{name}: more than {max_pages} pages")


def write_atomic(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"value": rows, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    os.replace(tmp, path)


def main(argv=None, base: str = BASE) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--key-file", type=Path, default=KEY_FILE)
    ap.add_argument("--datasets", default=",".join(DATASETS))
    a = ap.parse_args(argv)
    try:
        key = load_key(a.key_file)
    except FetchError as e:
        print(f"lta_fetch: {e}", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name in [d for d in a.datasets.split(",") if d]:
        try:
            rows = fetch_all(name, key, base=base, pause_s=0.1)
        except FetchError as e:
            print(f"lta_fetch: {e} (kept the previous file)", file=sys.stderr)
            failed += 1
            continue
        write_atomic(a.out / f"{name}.json", rows)
        print(f"{name}: {len(rows)} rows", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
