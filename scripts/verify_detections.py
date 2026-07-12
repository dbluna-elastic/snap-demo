#!/usr/bin/env python3
"""Verify all 7 ES|QL fraud detections return seeded entities."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ES_URL = os.environ["ES_URL"]
API_KEY = os.environ["ES_API_KEY"]
HEADERS = {"Authorization": f"ApiKey {API_KEY}", "Content-Type": "application/json"}

QUERIES = {
    "same_cent": (
        "FROM snap-transactions "
        "| STATS total = COUNT(*), same_cent = COUNT(*) WHERE cents == 0 BY store_id "
        "| EVAL pct_round = same_cent::double / total "
        "| WHERE total > 50 AND pct_round > 0.6 "
        "| SORT pct_round DESC"
    ),
    "rapid_baskets": (
        "FROM snap-transactions "
        "| WHERE @timestamp > NOW() - 7 days "
        "| STATS tx_count = COUNT(*), total_amt = SUM(amount) "
        "BY household_id, store_id, bucket = DATE_TRUNC(10 minutes, @timestamp) "
        "| WHERE tx_count >= 3 AND total_amt > 100 "
        "| SORT total_amt DESC"
    ),
    "balance_drains": (
        "FROM snap-transactions "
        "| WHERE balance_after < 1.0 "
        "| STATS drains = COUNT(*), last_seen = MAX(@timestamp) BY household_id, store_id "
        "| WHERE drains >= 2 "
        "| SORT drains DESC"
    ),
    "manual_entry": (
        'FROM snap-transactions '
        '| STATS total = COUNT(*), manual = COUNT(*) WHERE entry_method == "manual" BY store_id '
        "| EVAL pct_manual = manual::double / total "
        "| WHERE total > 50 AND pct_manual > 0.3 "
        "| SORT pct_manual DESC"
    ),
    "large_baskets": (
        "FROM snap-transactions "
        "| LOOKUP JOIN snap-stores ON store_id "
        '| WHERE category == "convenience" AND amount > 30 '
        "| STATS big_baskets = COUNT(*), avg_amt = AVG(amount) BY store_id, name "
        "| WHERE big_baskets > 20 "
        "| SORT avg_amt DESC "
        "| LIMIT 3"
    ),
    "cross_state": (
        "FROM snap-households "
        "| STATS states = COUNT_DISTINCT(state), state_list = VALUES(state) BY ssn_hash "
        "| WHERE states > 1"
    ),
    "deceased": (
        "FROM snap-transactions "
        "| LOOKUP JOIN snap-households ON household_id "
        '| WHERE status == "deceased" '
        "| STATS tx_after_death = COUNT(*), total = SUM(amount) BY household_id "
        "| SORT total DESC"
    ),
}

EXPECTED = {
    "same_cent": {"store_id": "4471"},
    "rapid_baskets": {"household_id": "hh_basket_demo_001", "store_id": "7701"},
    "balance_drains": {"store_id": "7701"},
    "manual_entry": {"store_id": "5102"},
    "large_baskets": {"store_id": "6123"},
    "cross_state": {"ssn_hash": "ssn_hash_cross_state_demo_001"},
    "deceased": {"household_id": "hh_deceased_demo_001"},
}


def run_query(query: str) -> list[dict]:
    resp = requests.post(f"{ES_URL}/_query", headers=HEADERS, json={"query": query}, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    cols = [c["name"] for c in body["columns"]]
    return [dict(zip(cols, row)) for row in body.get("values", [])]


def main() -> None:
    failed = 0
    for name, query in QUERIES.items():
        rows = run_query(query)
        exp = EXPECTED[name]
        hit = any(all(row.get(k) == v for k, v in exp.items()) for row in rows)
        status = "PASS" if hit and rows else "FAIL"
        if status == "FAIL":
            failed += 1
        top = rows[0] if rows else {}
        print(f"[{status}] {name}: {len(rows)} hits — top: {top}")

    if failed:
        print(f"\n{failed} detection(s) failed.", file=sys.stderr)
        sys.exit(1)
    print("\nAll 7 detections verified.")


if __name__ == "__main__":
    main()
