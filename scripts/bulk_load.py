#!/usr/bin/env python3
"""Bulk-load NDJSON files into Elasticsearch."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ES_URL = os.environ["ES_URL"]
API_KEY = os.environ["ES_API_KEY"]
HEADERS = {
    "Authorization": f"ApiKey {API_KEY}",
    "Content-Type": "application/x-ndjson",
}

DATA_DIR = Path(__file__).parent.parent / "data"
BATCH_SIZE = 5000

FILES = [
    "snap-stores.ndjson",
    "snap-households.ndjson",
    "snap-reference.ndjson",
    "snap-transactions.ndjson",
]


def bulk_load(path: Path) -> tuple[int, int]:
    lines = path.read_text().splitlines()
    # NDJSON bulk: pairs of action + doc
    pairs = len(lines) // 2
    ok, err = 0, 0

    for start in range(0, len(lines), BATCH_SIZE * 2):
        batch = "\n".join(lines[start : start + BATCH_SIZE * 2]) + "\n"
        resp = requests.post(
            f"{ES_URL}/_bulk",
            headers=HEADERS,
            data=batch,
            params={"refresh": "false"},
            timeout=120,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            for item in body["items"]:
                action = item.get("index") or item.get("create") or {}
                if action.get("error"):
                    err += 1
                    if err <= 5:
                        print(f"  ERROR: {action['error']}", file=sys.stderr)
                else:
                    ok += 1
        else:
            ok += len(body["items"])

        done = min(start // 2 + BATCH_SIZE, pairs)
        print(f"  {path.name}: {done:,}/{pairs:,}")

    return ok, err


def main() -> None:
    for fname in FILES:
        path = DATA_DIR / fname
        if not path.exists():
            print(f"Missing {path} — run generate_data.py first", file=sys.stderr)
            sys.exit(1)
        print(f"Loading {fname}...")
        ok, err = bulk_load(path)
        print(f"  done: {ok:,} ok, {err:,} errors")

    print("Refreshing indices...")
    requests.post(
        f"{ES_URL}/snap-*/_refresh",
        headers={"Authorization": f"ApiKey {API_KEY}"},
        timeout=60,
    ).raise_for_status()
    print("Bulk load complete.")


if __name__ == "__main__":
    main()
