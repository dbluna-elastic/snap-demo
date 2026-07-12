#!/usr/bin/env python3
"""Create Agent Builder ES|QL tools and SNAP fraud investigation agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

KB_URL = os.environ.get("KB_URL", "https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com")
API_KEY = os.environ["ES_API_KEY"]
HEADERS = {
    "Authorization": f"ApiKey {API_KEY}",
    "kbn-xsrf": "true",
    "Content-Type": "application/json",
}

TOOLS = [
    {
        "id": "snap.fraud.find_same_cent_stores",
        "description": (
            "Stores with a suspicious share of same-cent transactions (trafficking signal). "
            "Returns store_id, total transactions, same-cent count, and percentage rounded to .00."
        ),
        "query": (
            "FROM snap-transactions "
            "| STATS total = COUNT(*), same_cent = COUNT(*) WHERE cents == 0 BY store_id "
            "| EVAL pct_round = same_cent::double / total "
            "| WHERE total > 50 AND pct_round > 0.6 "
            "| SORT pct_round DESC "
            "| LIMIT 20"
        ),
    },
    {
        "id": "snap.fraud.find_rapid_transactions",
        "description": (
            "Households making multiple rapid transactions summing over $100 at one store "
            "(broken-up baskets / structuring). Groups by 10-minute buckets."
        ),
        "query": (
            "FROM snap-transactions "
            "| WHERE @timestamp > NOW() - 7 days "
            "| STATS tx_count = COUNT(*), total_amt = SUM(amount) "
            "BY household_id, store_id, bucket = DATE_TRUNC(10 minutes, @timestamp) "
            "| WHERE tx_count >= 3 AND total_amt > 100 "
            "| SORT total_amt DESC "
            "| LIMIT 20"
        ),
    },
    {
        "id": "snap.fraud.find_balance_drains",
        "description": (
            "Households whose SNAP benefits are drained to near zero (balance_after < $1) "
            "multiple times at the same store."
        ),
        "query": (
            "FROM snap-transactions "
            "| WHERE balance_after < 1.0 "
            "| STATS drains = COUNT(*), last_seen = MAX(@timestamp) BY household_id, store_id "
            "| WHERE drains >= 2 "
            "| SORT drains DESC "
            "| LIMIT 20"
        ),
    },
    {
        "id": "snap.fraud.find_manual_entry_stores",
        "description": (
            "Stores with excessive card-not-present manual entries — possible trafficking "
            "or unauthorized card use."
        ),
        "query": (
            "FROM snap-transactions "
            '| STATS total = COUNT(*), manual = COUNT(*) WHERE entry_method == "manual" BY store_id '
            "| EVAL pct_manual = manual::double / total "
            "| WHERE total > 50 AND pct_manual > 0.3 "
            "| SORT pct_manual DESC "
            "| LIMIT 20"
        ),
    },
    {
        "id": "snap.fraud.find_large_baskets_small_stores",
        "description": (
            "Large basket transactions (>$30) at convenience stores — inconsistent with "
            "expected store type and average basket size."
        ),
        "query": (
            "FROM snap-transactions "
            "| LOOKUP JOIN snap-stores ON store_id "
            '| WHERE category == "convenience" AND amount > 30 '
            "| STATS big_baskets = COUNT(*), avg_amt = AVG(amount) BY store_id, name "
            "| WHERE big_baskets > 20 "
            "| SORT avg_amt DESC "
            "| LIMIT 20"
        ),
    },
    {
        "id": "snap.fraud.find_cross_state_identities",
        "description": (
            "Identities (ssn_hash) enrolled in more than one state — possible duplicate "
            "benefits or identity fraud."
        ),
        "query": (
            "FROM snap-households "
            "| STATS states = COUNT_DISTINCT(state), state_list = VALUES(state) BY ssn_hash "
            "| WHERE states > 1 "
            "| LIMIT 20"
        ),
    },
    {
        "id": "snap.fraud.find_deceased_transactions",
        "description": (
            "Transactions on accounts flagged as deceased — benefits may still be active "
            "or being trafficked after death."
        ),
        "query": (
            "FROM snap-transactions "
            "| LOOKUP JOIN snap-households ON household_id "
            '| WHERE status == "deceased" '
            "| STATS tx_after_death = COUNT(*), total = SUM(amount) BY household_id "
            "| SORT total DESC "
            "| LIMIT 20"
        ),
    },
]

AGENT = {
    "id": "snap-fraud-investigator",
    "name": "SNAP Fraud Investigator",
    "description": (
        "Hi! I'm your SNAP fraud investigation assistant. Ask me about suspicious stores, "
        "trafficking patterns, duplicate enrollments, or accounts being drained."
    ),
    "labels": ["snap", "fraud", "benefits", "demo"],
    "avatar_color": "#D4E157",
    "avatar_symbol": "🔍",
    "configuration": {
        "instructions": (
            "You are a SNAP fraud investigation assistant for a state benefits agency. "
            "When asked about suspicious activity, choose the appropriate detection tool, "
            "run it, and explain findings in plain language for a non-technical investigator. "
            "Always cite the store or household IDs, the pattern that triggered, and dollar amounts. "
            "Known demo entities: store 4471 (same-cent trafficking), store 5102 (manual entry), "
            "store 3890 (volume spike), store 6123 (large baskets), store 7701 (rapid drains/baskets), "
            "household hh_deceased_demo_001 (deceased still transacting), "
            "ssn_hash_cross_state_demo_001 (enrolled in TX and FL). "
            "Offer to open a case when a strong signal is found."
        ),
        "tools": [
            {
                "tool_ids": [t["id"] for t in TOOLS]
                + [
                    "platform.core.search",
                    "platform.core.get_document_by_id",
                ]
            }
        ],
    },
}


def upsert(method: str, path: str, payload: dict) -> dict:
    resp = requests.request(
        method,
        f"{KB_URL}{path}",
        headers=HEADERS,
        json=payload,
        timeout=60,
    )
    if resp.status_code >= 400:
        print(f"  ERROR {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()


def main() -> None:
    print("Creating Agent Builder tools...")
    for tool in TOOLS:
        body = {
            "id": tool["id"],
            "type": "esql",
            "description": tool["description"],
            "configuration": {"query": tool["query"], "params": {}},
        }
        # Try create; update if exists
        resp = requests.post(f"{KB_URL}/api/agent_builder/tools", headers=HEADERS, json=body, timeout=60)
        if resp.status_code == 409:
            upsert("PUT", f"/api/agent_builder/tools/{tool['id']}", body)
            print(f"  updated {tool['id']}")
        else:
            resp.raise_for_status()
            print(f"  created {tool['id']}")

    print("Creating agent...")
    resp = requests.post(f"{KB_URL}/api/agent_builder/agents", headers=HEADERS, json=AGENT, timeout=60)
    if resp.status_code == 409:
        upsert("PUT", f"/api/agent_builder/agents/{AGENT['id']}", AGENT)
        print(f"  updated {AGENT['id']}")
    else:
        resp.raise_for_status()
        print(f"  created {AGENT['id']}")

    print(f"\nAgent ready: {KB_URL}/app/agent_builder/chat/snap-fraud-investigator")
    print("Test prompts:")
    print('  - "Which stores show signs of trafficking this week?"')
    print('  - "Why is store 4471 suspicious?"')
    print('  - "Is anyone enrolled in two states?"')
    print('  - "Show me accounts being drained to zero."')


if __name__ == "__main__":
    main()
