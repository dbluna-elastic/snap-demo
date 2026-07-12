#!/usr/bin/env python3
"""
Generate synthetic SNAP fraud detection demo data.

Produces NDJSON bulk files in data/ for:
  snap-stores, snap-households, snap-reference, snap-transactions

Seven seeded fraud signatures are buried in realistic noise.
"""

from __future__ import annotations

import json
import math
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

STATES = ["TX", "FL", "CA", "NY", "OH", "GA", "MI", "PA", "IL", "NC"]
CATEGORIES = ["convenience", "grocery", "supermarket"]
ENTRY_METHODS = ["chip", "swipe", "manual", "keyed"]

# --- Seeded fraud entity IDs (stable for demo queries) ---
FRAUD_SAME_CENT_STORE = "4471"
FRAUD_MANUAL_STORE = "5102"
FRAUD_VOLUME_SPIKE_STORE = "3890"
FRAUD_LARGE_BASKET_STORE = "6123"
FRAUD_DRAIN_STORE = "7701"
FRAUD_BASKET_STORE = "7701"  # same store for broken-up baskets demo
FRAUD_CROSS_SSN = "ssn_hash_cross_state_demo_001"
FRAUD_DECEASED_HH = "hh_deceased_demo_001"
FRAUD_DRAIN_HHS = ["hh_drain_demo_001", "hh_drain_demo_002", "hh_drain_demo_003"]
FRAUD_BASKET_HH = "hh_basket_demo_001"

GUILTY_STORE_IDS = {
    FRAUD_SAME_CENT_STORE,
    FRAUD_MANUAL_STORE,
    FRAUD_VOLUME_SPIKE_STORE,
    FRAUD_LARGE_BASKET_STORE,
    FRAUD_DRAIN_STORE,
    "8200",
    "9301",
    "1044",
}
FRAUD_HOUSEHOLD_IDS = {
    FRAUD_DECEASED_HH,
    FRAUD_BASKET_HH,
    *FRAUD_DRAIN_HHS,
    "hh_cross_tx",
    "hh_cross_fl",
}

NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = NOW - timedelta(days=45)
SPIKE_START = NOW - timedelta(days=3)

TX_COUNT_TARGET = int(os.environ.get("SNAP_TX_COUNT", "300000"))


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def geo_for_state(state: str) -> dict:
    centers = {
        "TX": (31.0, -99.0),
        "FL": (28.5, -81.5),
        "CA": (36.5, -119.5),
        "NY": (43.0, -75.5),
        "OH": (40.3, -82.8),
        "GA": (32.6, -83.5),
        "MI": (44.3, -85.4),
        "PA": (40.9, -77.8),
        "IL": (40.0, -89.2),
        "NC": (35.5, -79.4),
    }
    lat, lon = centers.get(state, (39.0, -98.0))
    return {"lat": lat + random.uniform(-2, 2), "lon": lon + random.uniform(-2, 2)}


def write_ndjson(path: Path, index: str, docs: list[dict]) -> None:
    with path.open("w") as f:
        for doc in docs:
            f.write(json.dumps({"index": {"_index": index}}) + "\n")
            f.write(json.dumps(doc) + "\n")
    print(f"  wrote {len(docs):,} docs -> {path}")


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

def generate_stores() -> list[dict]:
    stores: list[dict] = []
    guilty_ids = {
        FRAUD_SAME_CENT_STORE: ("QuickMart #4471", "convenience", "TX"),
        FRAUD_MANUAL_STORE: ("Corner Stop 5102", "convenience", "FL"),
        FRAUD_VOLUME_SPIKE_STORE: ("Neighborhood Groc 3890", "grocery", "OH"),
        FRAUD_LARGE_BASKET_STORE: ("Mini Mart 6123", "convenience", "GA"),
        FRAUD_DRAIN_STORE: ("Family Foods 7701", "grocery", "MI"),
        "8200": ("Sunrise Market 8200", "convenience", "PA"),
        "9301": ("Value Foods 9301", "supermarket", "IL"),
        "1044": ("Metro Groc 1044", "grocery", "NC"),
    }

    for store_id, (name, category, state) in guilty_ids.items():
        stores.append(
            {
                "store_id": store_id,
                "name": name,
                "category": category,
                "geo": geo_for_state(state),
                "authorized_date": iso(START - timedelta(days=random.randint(180, 900))),
                "expected_avg_basket": round(random.uniform(12, 28), 2),
                "state": state,
            }
        )

    for i in range(500 - len(guilty_ids)):
        state = random.choice(STATES)
        category = random.choices(CATEGORIES, weights=[0.35, 0.4, 0.25])[0]
        stores.append(
            {
                "store_id": f"store_{i:04d}",
                "name": fake.company(),
                "category": category,
                "geo": geo_for_state(state),
                "authorized_date": iso(START - timedelta(days=random.randint(30, 1000))),
                "expected_avg_basket": round(
                    {"convenience": 18, "grocery": 35, "supermarket": 55}[category]
                    + random.uniform(-8, 8),
                    2,
                ),
                "state": state,
            }
        )

    return stores


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------

def generate_households() -> list[dict]:
    households: list[dict] = []

    # Cross-state duplicate identity
    for state in ["TX", "FL"]:
        households.append(
            {
                "household_id": f"hh_cross_{state.lower()}",
                "ssn_hash": FRAUD_CROSS_SSN,
                "state": state,
                "enrollment_date": iso(START - timedelta(days=random.randint(200, 500))),
                "monthly_benefit": round(random.uniform(400, 800), 2),
                "reported_income": round(random.uniform(0, 1200), 2),
                "household_size": random.randint(1, 5),
                "status": "active",
            }
        )

    # Deceased recipient still transacting
    households.append(
        {
            "household_id": FRAUD_DECEASED_HH,
            "ssn_hash": "ssn_hash_deceased_demo_001",
            "state": "NY",
            "enrollment_date": iso(START - timedelta(days=800)),
            "monthly_benefit": 650.0,
            "reported_income": 0.0,
            "household_size": 2,
            "status": "deceased",
        }
    )

    # Rapid-drain households
    for hh_id in FRAUD_DRAIN_HHS:
        households.append(
            {
                "household_id": hh_id,
                "ssn_hash": f"ssn_{hh_id}",
                "state": "MI",
                "enrollment_date": iso(START - timedelta(days=300)),
                "monthly_benefit": round(random.uniform(500, 750), 2),
                "reported_income": round(random.uniform(0, 500), 2),
                "household_size": random.randint(2, 4),
                "status": "active",
            }
        )

    # Broken-up basket household
    households.append(
        {
            "household_id": FRAUD_BASKET_HH,
            "ssn_hash": "ssn_hash_basket_demo_001",
            "state": "MI",
            "enrollment_date": iso(START - timedelta(days=400)),
            "monthly_benefit": 700.0,
            "reported_income": 200.0,
            "household_size": 3,
            "status": "active",
        }
    )

    seen_ssn = {h["ssn_hash"] for h in households}
    for i in range(5000 - len(households)):
        state = random.choice(STATES)
        ssn = f"ssn_{uuid.uuid4().hex[:16]}"
        while ssn in seen_ssn:
            ssn = f"ssn_{uuid.uuid4().hex[:16]}"
        seen_ssn.add(ssn)
        status = random.choices(["active", "closed", "deceased"], weights=[0.88, 0.08, 0.04])[0]
        households.append(
            {
                "household_id": f"hh_{i:05d}",
                "ssn_hash": ssn,
                "state": state,
                "enrollment_date": iso(START - timedelta(days=random.randint(30, 900))),
                "monthly_benefit": round(random.uniform(200, 900), 2),
                "reported_income": round(random.uniform(0, 2500), 2),
                "household_size": random.randint(1, 6),
                "status": status,
            }
        )

    return households


# ---------------------------------------------------------------------------
# Reference (death index + cross-state)
# ---------------------------------------------------------------------------

def generate_reference() -> list[dict]:
    refs: list[dict] = []

    refs.append(
        {
            "ssn_hash": "ssn_hash_deceased_demo_001",
            "source": "death_index",
            "state": "NY",
            "record_date": iso(NOW - timedelta(days=14)),
        }
    )

    refs.append(
        {
            "ssn_hash": FRAUD_CROSS_SSN,
            "source": "cross_state_enrollment",
            "state": "TX",
            "record_date": iso(NOW - timedelta(days=30)),
        }
    )
    refs.append(
        {
            "ssn_hash": FRAUD_CROSS_SSN,
            "source": "cross_state_enrollment",
            "state": "FL",
            "record_date": iso(NOW - timedelta(days=25)),
        }
    )

    for i in range(200 - len(refs)):
        refs.append(
            {
                "ssn_hash": f"ssn_ref_{i:04d}",
                "source": random.choice(["death_index", "cross_state_enrollment"]),
                "state": random.choice(STATES),
                "record_date": iso(START + timedelta(days=random.randint(0, 40))),
            }
        )

    return refs


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def make_tx(
    *,
    ts: datetime,
    household_id: str,
    store_id: str,
    amount: float,
    entry_method: str,
    balance_after: float,
    state: str,
    geo: dict,
    card_id: str | None = None,
) -> dict:
    return {
        "transaction_id": f"tx_{uuid.uuid4().hex[:12]}",
        "@timestamp": iso(ts),
        "card_id": card_id or f"card_{household_id[-8:]}",
        "household_id": household_id,
        "store_id": store_id,
        "amount": round(amount, 2),
        "entry_method": entry_method,
        "balance_after": round(balance_after, 2),
        "state": state,
        "geo": geo,
    }


def random_background_tx(
    stores_by_id: dict,
    households: list[dict],
    ts: datetime,
) -> dict:
    eligible_hh = [
        h
        for h in households
        if h["status"] == "active" and h["household_id"] not in FRAUD_HOUSEHOLD_IDS
    ]
    eligible_stores = [
        s for s in stores_by_id.values() if s["store_id"] not in GUILTY_STORE_IDS
    ]
    hh = random.choice(eligible_hh)
    store = random.choice(eligible_stores)
    base = store["expected_avg_basket"]
    amount = max(1.0, round(random.gauss(base, base * 0.35), 2))
    # Natural cent distribution
    if random.random() < 0.15:
        amount = math.floor(amount) + random.choice([0.0, 0.25, 0.50, 0.75, 0.99])

    entry = random.choices(ENTRY_METHODS, weights=[0.55, 0.30, 0.08, 0.07])[0]
    benefit = hh["monthly_benefit"]
    balance = round(random.uniform(0, benefit), 2)

    return make_tx(
        ts=ts,
        household_id=hh["household_id"],
        store_id=store["store_id"],
        amount=amount,
        entry_method=entry,
        balance_after=balance,
        state=hh["state"],
        geo=store["geo"],
    )


def inject_fraud_transactions(
    stores_by_id: dict,
    households_by_id: dict,
) -> list[dict]:
    fraud_txs: list[dict] = []

    # 1. Same-cent trafficking at store 4471 (~90% round dollars)
    same_cent_store = stores_by_id[FRAUD_SAME_CENT_STORE]
    for i in range(900):
        ts = START + timedelta(
            seconds=random.randint(0, int((NOW - START).total_seconds()))
        )
        amount = float(random.randint(5, 45))  # whole dollars -> cents == 0
        if random.random() < 0.08:
            amount += random.choice([0.01, 0.05, 0.09, 0.25, 0.50])
        hh = random.choice(
            [h for h in households_by_id.values() if h["status"] == "active"]
        )
        fraud_txs.append(
            make_tx(
                ts=ts,
                household_id=hh["household_id"],
                store_id=FRAUD_SAME_CENT_STORE,
                amount=float(amount),
                entry_method=random.choice(["swipe", "chip"]),
                balance_after=random.uniform(10, 400),
                state=same_cent_store["state"],
                geo=same_cent_store["geo"],
            )
        )

    # 2. Rapid-drain households at store 7701
    drain_store = stores_by_id[FRAUD_DRAIN_STORE]
    for hh_id in FRAUD_DRAIN_HHS:
        hh = households_by_id[hh_id]
        benefit = hh["monthly_benefit"]
        base_ts = NOW - timedelta(days=random.randint(1, 5), hours=random.randint(8, 18))
        balance = benefit
        tx_count = 5
        for j in range(tx_count):
            amt = round(balance * random.uniform(0.22, 0.32), 2)
            balance = max(0, round(balance - amt, 2))
            if j >= tx_count - 2:
                balance_after = round(random.uniform(0, 0.45), 2)
            else:
                balance_after = balance
            fraud_txs.append(
                make_tx(
                    ts=base_ts + timedelta(minutes=j * 2),
                    household_id=hh_id,
                    store_id=FRAUD_DRAIN_STORE,
                    amount=amt,
                    entry_method="swipe",
                    balance_after=balance_after,
                    state=drain_store["state"],
                    geo=drain_store["geo"],
                )
            )

    # 3. Broken-up baskets — 5 txs within 4 minutes summing ~$180
    basket_store = stores_by_id[FRAUD_BASKET_STORE]
    basket_ts = NOW - timedelta(days=2, hours=14, minutes=2)
    parts = [38.50, 42.25, 35.00, 33.75, 30.50]  # sums to 180
    running_bal = 700.0
    for j, amt in enumerate(parts):
        running_bal -= amt
        fraud_txs.append(
            make_tx(
                ts=basket_ts + timedelta(minutes=j),  # all within one 10-min bucket
                household_id=FRAUD_BASKET_HH,
                store_id=FRAUD_BASKET_STORE,
                amount=amt,
                entry_method="chip",
                balance_after=running_bal,
                state=basket_store["state"],
                geo=basket_store["geo"],
            )
        )

    # 4. Manual-entry store 5102 (~50% manual)
    manual_store = stores_by_id[FRAUD_MANUAL_STORE]
    for i in range(700):
        ts = START + timedelta(
            seconds=random.randint(0, int((NOW - START).total_seconds()))
        )
        hh = random.choice(
            [h for h in households_by_id.values() if h["status"] == "active"]
        )
        fraud_txs.append(
            make_tx(
                ts=ts,
                household_id=hh["household_id"],
                store_id=FRAUD_MANUAL_STORE,
                amount=round(random.uniform(8, 55), 2),
                entry_method="manual" if random.random() < 0.50 else random.choice(["chip", "swipe"]),
                balance_after=random.uniform(20, 500),
                state=manual_store["state"],
                geo=manual_store["geo"],
            )
        )

    # 5. Volume-spike store 3890 — baseline + 10x spike last 3 days
    spike_store = stores_by_id[FRAUD_VOLUME_SPIKE_STORE]
    # Baseline: ~15/day for 42 days
    for day in range(42):
        day_start = START + timedelta(days=day)
        for _ in range(random.randint(10, 20)):
            ts = day_start + timedelta(
                hours=random.randint(7, 21), minutes=random.randint(0, 59)
            )
            hh = random.choice(
                [h for h in households_by_id.values() if h["status"] == "active"]
            )
            fraud_txs.append(
                make_tx(
                    ts=ts,
                    household_id=hh["household_id"],
                    store_id=FRAUD_VOLUME_SPIKE_STORE,
                    amount=round(random.uniform(10, 40), 2),
                    entry_method=random.choice(["chip", "swipe"]),
                    balance_after=random.uniform(50, 400),
                    state=spike_store["state"],
                    geo=spike_store["geo"],
                )
            )

    # Spike: ~180/day for last 3 days (10x)
    for day in range(3):
        day_start = SPIKE_START + timedelta(days=day)
        for _ in range(random.randint(160, 200)):
            ts = day_start + timedelta(
                hours=random.randint(6, 22), minutes=random.randint(0, 59)
            )
            hh = random.choice(
                [h for h in households_by_id.values() if h["status"] == "active"]
            )
            fraud_txs.append(
                make_tx(
                    ts=ts,
                    household_id=hh["household_id"],
                    store_id=FRAUD_VOLUME_SPIKE_STORE,
                    amount=round(random.uniform(12, 45), 2),
                    entry_method=random.choice(["chip", "swipe"]),
                    balance_after=random.uniform(30, 350),
                    state=spike_store["state"],
                    geo=spike_store["geo"],
                )
            )

    # 6. Large baskets at convenience store 6123
    large_store = stores_by_id[FRAUD_LARGE_BASKET_STORE]
    for i in range(120):
        ts = START + timedelta(
            seconds=random.randint(0, int((NOW - START).total_seconds()))
        )
        hh = random.choice(
            [h for h in households_by_id.values() if h["status"] == "active"]
        )
        fraud_txs.append(
            make_tx(
                ts=ts,
                household_id=hh["household_id"],
                store_id=FRAUD_LARGE_BASKET_STORE,
                amount=round(random.uniform(32, 85), 2),
                entry_method=random.choice(["chip", "swipe"]),
                balance_after=random.uniform(10, 300),
                state=large_store["state"],
                geo=large_store["geo"],
            )
        )

    # 7. Deceased household still transacting (post death record)
    deceased_hh = households_by_id[FRAUD_DECEASED_HH]
    death_date = NOW - timedelta(days=14)
    for i in range(25):
        ts = death_date + timedelta(days=random.randint(1, 10), hours=random.randint(9, 20))
        store = random.choice(list(stores_by_id.values()))
        fraud_txs.append(
            make_tx(
                ts=ts,
                household_id=FRAUD_DECEASED_HH,
                store_id=store["store_id"],
                amount=round(random.uniform(15, 60), 2),
                entry_method="swipe",
                balance_after=random.uniform(100, 500),
                state=deceased_hh["state"],
                geo=store["geo"],
            )
        )

    return fraud_txs


def generate_transactions(
    stores: list[dict],
    households: list[dict],
) -> list[dict]:
    stores_by_id = {s["store_id"]: s for s in stores}
    households_by_id = {h["household_id"]: h for h in households}

    fraud_txs = inject_fraud_transactions(stores_by_id, households_by_id)
    background_count = max(0, TX_COUNT_TARGET - len(fraud_txs))

    print(f"  fraud injections: {len(fraud_txs):,}")
    print(f"  background target: {background_count:,}")

    txs: list[dict] = list(fraud_txs)
    total_seconds = int((NOW - START).total_seconds())

    for i in range(background_count):
        ts = START + timedelta(seconds=random.randint(0, total_seconds))
        txs.append(random_background_tx(stores_by_id, households, ts))
        if (i + 1) % 50000 == 0:
            print(f"    ... {i + 1:,} background txs")

    txs.sort(key=lambda t: t["@timestamp"])
    return txs


def main() -> None:
    print("Generating SNAP demo data...")
    print(f"  time window: {iso(START)} -> {iso(NOW)}")
    print(f"  tx target:   {TX_COUNT_TARGET:,}")

    stores = generate_stores()
    households = generate_households()
    reference = generate_reference()
    transactions = generate_transactions(stores, households)

    write_ndjson(DATA_DIR / "snap-stores.ndjson", "snap-stores", stores)
    write_ndjson(DATA_DIR / "snap-households.ndjson", "snap-households", households)
    write_ndjson(DATA_DIR / "snap-reference.ndjson", "snap-reference", reference)
    write_ndjson(DATA_DIR / "snap-transactions.ndjson", "snap-transactions", transactions)

    print("\nSeeded fraud entities:")
    print(f"  same-cent store:     {FRAUD_SAME_CENT_STORE}")
    print(f"  manual-entry store:  {FRAUD_MANUAL_STORE}")
    print(f"  volume-spike store:  {FRAUD_VOLUME_SPIKE_STORE}")
    print(f"  large-basket store:  {FRAUD_LARGE_BASKET_STORE}")
    print(f"  drain/basket store:  {FRAUD_DRAIN_STORE}")
    print(f"  cross-state ssn:     {FRAUD_CROSS_SSN}")
    print(f"  deceased household:  {FRAUD_DECEASED_HH}")
    print(f"  drain households:    {', '.join(FRAUD_DRAIN_HHS)}")
    print(f"  basket household:    {FRAUD_BASKET_HH}")
    print("\nDone.")


if __name__ == "__main__":
    main()
