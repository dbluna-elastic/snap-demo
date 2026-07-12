#!/usr/bin/env python3
"""Deploy Steps 5, 7, and 8: ML jobs, Workflows/Alerting, and Dashboard."""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ES_URL = os.environ["ES_URL"]
KB_URL = os.environ.get("KB_URL", "https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com")
API_KEY = os.environ["ES_API_KEY"]
ES_HEADERS = {"Authorization": f"ApiKey {API_KEY}", "Content-Type": "application/json"}
KB_HEADERS = {**ES_HEADERS, "kbn-xsrf": "true"}

DATA_VIEW_ID = None  # resolved at runtime
RULE_ID = "3c77ca91-d945-4cad-9d8d-f6c95a42f100"
DASHBOARD_ID = "snap-fraud-investigator-home"

ML_JOBS = [
    {
        "job_id": "snap-store-volume-spike",
        "description": "SNAP demo: store transaction volume spike",
        "bucket_span": "1h",
        "function": "high_count",
        "field_name": None,
        "partition_field_name": "store_id",
    },
    {
        "job_id": "snap-store-basket-value",
        "description": "SNAP demo: store average basket value spike",
        "bucket_span": "1h",
        "function": "high_mean",
        "field_name": "amount",
        "partition_field_name": "store_id",
    },
    {
        "job_id": "snap-household-spend-rate",
        "description": "SNAP demo: household daily spend rate",
        "bucket_span": "1d",
        "function": "high_sum",
        "field_name": "amount",
        "partition_field_name": "household_id",
    },
]

TRAFFICKING_ESQL = (
    "FROM snap-transactions "
    "| STATS total = COUNT(*), same_cent = COUNT(*) WHERE cents == 0 BY store_id "
    "| EVAL pct_round = same_cent::double / total "
    "| WHERE total > 50 AND pct_round > 0.6 "
    "| SORT pct_round DESC"
)

TRAFFICKING_WORKFLOW_YAML = textwrap.dedent(
    """
    version: "1"
    name: SNAP Trafficking Case
    description: Auto-create and enrich SNAP trafficking cases from same-cent alerts
    enabled: true
    triggers:
      - type: alert
    steps:
      - name: create_case
        type: cases.createCase
        with:
          title: "Possible SNAP trafficking — store {{ event.alerts[0].kibana.alert.grouping.store_id }}"
          description: "Auto-generated from same-cent trafficking detection rule."
          owner: observability
          severity: high
          tags:
            - snap
            - trafficking
      - name: attach_alert
        type: cases.addAlerts
        with:
          case_id: "{{ steps.create_case.output.case.id }}"
          alerts:
            - alertId: "{{ event.alerts[0]._id }}"
              index: "{{ event.alerts[0]._index }}"
      - name: enrich_store
        type: elasticsearch.esql.query
        with:
          format: json
          query: |
            FROM snap-stores
            | WHERE store_id == "{{ event.alerts[0].kibana.alert.grouping.store_id }}"
            | LIMIT 1
      - name: enrich_recipients
        type: elasticsearch.esql.query
        with:
          format: json
          query: |
            FROM snap-transactions
            | WHERE store_id == "{{ event.alerts[0].kibana.alert.grouping.store_id }}"
            | STATS tx = COUNT(*), total = SUM(amount) BY household_id
            | SORT total DESC
            | LIMIT 10
      - name: add_enrichment
        type: cases.addComment
        with:
          case_id: "{{ steps.create_case.output.case.id }}"
          comment: |
            **Store enrichment**
            {{ steps.enrich_store.output | json }}

            **Top recipients**
            {{ steps.enrich_recipients.output | json }}
    """
).strip()

NIGHTLY_SWEEP_YAML = textwrap.dedent(
    """
    version: "1"
    name: SNAP Nightly Fraud Sweep
    description: Run the full SNAP detection suite and emit a summary for investigators
    enabled: true
    triggers:
      - type: scheduled
        with:
          rrule:
            dtstart: "2026-07-12T06:00:00Z"
            freq: DAILY
            interval: 1
    steps:
      - name: same_cent
        type: elasticsearch.esql.query
        with:
          format: json
          query: |
            FROM snap-transactions
            | STATS total = COUNT(*), same_cent = COUNT(*) WHERE cents == 0 BY store_id
            | EVAL pct_round = same_cent::double / total
            | WHERE total > 50 AND pct_round > 0.6
            | SORT pct_round DESC
            | LIMIT 10
      - name: rapid_tx
        type: elasticsearch.esql.query
        with:
          format: json
          query: |
            FROM snap-transactions
            | WHERE @timestamp > NOW() - 7 days
            | STATS tx_count = COUNT(*), total_amt = SUM(amount)
                BY household_id, store_id, bucket = DATE_TRUNC(10 minutes, @timestamp)
            | WHERE tx_count >= 3 AND total_amt > 100
            | SORT total_amt DESC
            | LIMIT 10
      - name: cross_state
        type: elasticsearch.esql.query
        with:
          format: json
          query: |
            FROM snap-households
            | STATS states = COUNT_DISTINCT(state), state_list = VALUES(state) BY ssn_hash
            | WHERE states > 1
            | LIMIT 10
      - name: deceased
        type: elasticsearch.esql.query
        with:
          format: json
          query: |
            FROM snap-transactions
            | LOOKUP JOIN snap-households ON household_id
            | WHERE status == "deceased"
            | STATS tx_after_death = COUNT(*), total = SUM(amount) BY household_id
            | SORT total DESC
            | LIMIT 10
      - name: log_summary
        type: console
        with:
          message: |
            SNAP nightly sweep complete.
            Same-cent stores: {{ steps.same_cent.output | json }}
            Rapid transactions: {{ steps.rapid_tx.output | json }}
            Cross-state IDs: {{ steps.cross_state.output | json }}
            Deceased transacting: {{ steps.deceased.output | json }}
    """
).strip()


def esql_bar_panel(
    *,
    title: str,
    query: str,
    x_col: str,
    y_col: str,
    x: int,
    y: int,
    w: int = 24,
    h: int = 10,
) -> dict:
    return {
        "grid": {"x": x, "y": y, "w": w, "h": h},
        "type": "vis",
        "config": {
            "type": "xy",
            "title": title,
            "layers": [
                {
                    "type": "bar_horizontal",
                    "data_source": {"type": "esql", "query": query},
                    "x": {"column": x_col},
                    "y": [{"column": y_col}],
                }
            ],
        },
    }


def esql_metric_panel(title: str, query: str, column: str, x: int, y: int, w: int = 12, h: int = 5) -> dict:
    return {
        "grid": {"x": x, "y": y, "w": w, "h": h},
        "type": "vis",
        "config": {
            "type": "metric",
            "title": title,
            "data_source": {"type": "esql", "query": query},
            "metrics": [{"type": "primary", "column": column}],
        },
    }


def build_dashboard() -> dict:
    return {
        "title": "SNAP Fraud Investigator",
        "description": "Investigator home base — suspicious stores, households, ML anomalies, and filters.",
        "time_range": {"from": "now-45d", "to": "now"},
        "panels": [
            {
                "grid": {"x": 0, "y": 0, "w": 12, "h": 4},
                "type": "options_list_control",
                "config": {
                    "data_view_id": DATA_VIEW_ID,
                    "field_name": "state",
                    "title": "State",
                },
            },
            {
                "grid": {"x": 12, "y": 0, "w": 12, "h": 4},
                "type": "options_list_control",
                "config": {
                    "data_view_id": DATA_VIEW_ID,
                    "field_name": "entry_method",
                    "title": "Entry method",
                },
            },
            {
                "grid": {"x": 24, "y": 0, "w": 24, "h": 4},
                "type": "markdown",
                "config": {
                    "content": (
                        "### SNAP Fraud Investigator\n"
                        "[Agent Chat](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/agent_builder/chat/snap-fraud-investigator) · "
                        "[Cases](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/observability/cases) · "
                        "Seeded: **4471**, **5102**, **3890**, **7701**"
                    )
                },
            },
            esql_metric_panel(
                "Same-cent flagged stores",
                "FROM snap-transactions | STATS total = COUNT(*), same_cent = COUNT(*) WHERE cents == 0 BY store_id "
                "| EVAL pct_round = same_cent::double / total | WHERE total > 50 AND pct_round > 0.6 | STATS flagged = COUNT(*)",
                "flagged",
                0,
                4,
                12,
            ),
            esql_metric_panel(
                "Manual-entry flagged stores",
                'FROM snap-transactions | STATS total = COUNT(*), manual = COUNT(*) WHERE entry_method == "manual" BY store_id '
                "| EVAL pct_manual = manual::double / total | WHERE total > 50 AND pct_manual > 0.3 | STATS flagged = COUNT(*)",
                "flagged",
                12,
                4,
                12,
            ),
            esql_metric_panel(
                "Cross-state identities",
                "FROM snap-households | STATS states = COUNT_DISTINCT(state) BY ssn_hash | WHERE states > 1 | STATS flagged = COUNT(*)",
                "flagged",
                24,
                4,
                12,
            ),
            esql_metric_panel(
                "Deceased still transacting",
                "FROM snap-transactions | LOOKUP JOIN snap-households ON household_id | WHERE status == \"deceased\" "
                "| STATS flagged = COUNT_DISTINCT(household_id)",
                "flagged",
                36,
                4,
                12,
            ),
            esql_bar_panel(
                title="Top same-cent stores (trafficking signal)",
                query=(
                    "FROM snap-transactions | STATS total = COUNT(*), same_cent = COUNT(*) WHERE cents == 0 BY store_id "
                    "| EVAL pct_round = same_cent::double / total | WHERE total > 50 AND pct_round > 0.6 "
                    "| SORT pct_round DESC | LIMIT 10"
                ),
                x_col="pct_round",
                y_col="store_id",
                x=0,
                y=9,
            ),
            esql_bar_panel(
                title="Top manual-entry stores",
                query=(
                    'FROM snap-transactions | STATS total = COUNT(*), manual = COUNT(*) WHERE entry_method == "manual" BY store_id '
                    "| EVAL pct_manual = manual::double / total | WHERE total > 50 AND pct_manual > 0.3 "
                    "| SORT pct_manual DESC | LIMIT 10"
                ),
                x_col="pct_manual",
                y_col="store_id",
                x=24,
                y=9,
            ),
            esql_bar_panel(
                title="Top drain households (balance < $1)",
                query=(
                    "FROM snap-transactions | WHERE balance_after < 1.0 "
                    "| STATS drains = COUNT(*) BY household_id, store_id | WHERE drains >= 2 "
                    "| SORT drains DESC | LIMIT 10"
                ),
                x_col="drains",
                y_col="household_id",
                x=0,
                y=19,
            ),
            {
                "grid": {"x": 24, "y": 19, "w": 24, "h": 10},
                "type": "vis",
                "config": {
                    "type": "xy",
                    "title": "ML anomaly score — store 3890 volume (snap-store-volume-spike)",
                    "layers": [
                        {
                            "type": "line",
                            "data_source": {
                                "type": "esql",
                                "query": (
                                    "FROM .ml-anomalies-shared-000001 "
                                    '| WHERE job_id == "snap-store-volume-spike" AND partition_field_value == "3890" '
                                    "| STATS max_score = MAX(record_score) BY bucket = DATE_TRUNC(1 hour, timestamp) "
                                    "| SORT bucket ASC"
                                ),
                            },
                            "x": {"column": "bucket"},
                            "y": [{"column": "max_score"}],
                        }
                    ],
                },
            },
            esql_bar_panel(
                title="Flagged store locations (avg basket)",
                query=(
                    "FROM snap-transactions "
                    "| STATS total = COUNT(*), same_cent = COUNT(*) WHERE cents == 0 BY store_id "
                    "| EVAL pct_round = same_cent::double / total "
                    "| WHERE total > 50 AND pct_round > 0.6 "
                    "| LOOKUP JOIN snap-stores ON store_id "
                    "| STATS stores = COUNT(*), avg_basket = AVG(expected_avg_basket) BY state "
                    "| SORT stores DESC"
                ),
                x_col="avg_basket",
                y_col="state",
                x=0,
                y=29,
                w=48,
                h=8,
            ),
        ],
    }


def upsert_ml_jobs() -> None:
    print("Step 5: ML anomaly detection jobs")
    for job in ML_JOBS:
        detector = {
            "detector_description": job["description"],
            "function": job["function"],
            "partition_field_name": job["partition_field_name"],
        }
        if job["field_name"]:
            detector["field_name"] = job["field_name"]

        body = {
            "description": job["description"],
            "groups": ["snap", "fraud-demo"],
            "analysis_config": {
                "bucket_span": job["bucket_span"],
                "detectors": [detector],
            },
            "data_description": {"time_field": "@timestamp"},
            "datafeed_config": {
                "indices": ["snap-transactions"],
                "query": {"match_all": {}},
            },
        }
        job_id = job["job_id"]
        resp = requests.put(
            f"{ES_URL}/_ml/anomaly_detectors/{job_id}",
            headers=ES_HEADERS,
            json=body,
            timeout=60,
        )
        if resp.status_code == 400 and "resource_already_exists" in resp.text:
            print(f"  {job_id} already exists")
        else:
            resp.raise_for_status()
        requests.post(f"{ES_URL}/_ml/anomaly_detectors/{job_id}/_open", headers=ES_HEADERS, timeout=60)
        start = requests.post(
            f"{ES_URL}/_ml/datafeeds/{job_id}/_start",
            headers=ES_HEADERS,
            params={"start": "2026-05-28T00:00:00Z"},
            timeout=60,
        )
        if start.status_code >= 400 and "datafeed_started" not in start.text:
            print(f"  warn {job_id} datafeed: {start.text[:200]}", file=sys.stderr)
        print(f"  {job_id} ready")

    print("  waiting for initial ML processing...")
    time.sleep(20)
    stats = requests.get(f"{ES_URL}/_ml/anomaly_detectors/snap-*/_stats", headers=ES_HEADERS, timeout=60).json()
    for j in stats.get("jobs", []):
        processed = j["data_counts"].get("processed_record_count", 0)
        print(f"    {j['job_id']}: {j['state']} ({processed:,} records)")


def upsert_workflows_and_rule() -> None:
    print("Step 7: Workflows + alerting rule")

    # Trafficking case workflow
    resp = requests.put(
        f"{KB_URL}/api/workflows/workflow/snap-trafficking-case",
        headers=KB_HEADERS,
        json={"yaml": TRAFFICKING_WORKFLOW_YAML, "enabled": True},
        timeout=60,
    )
    resp.raise_for_status()
    print("  workflow snap-trafficking-case updated")

    # Nightly sweep
    resp = requests.post(
        f"{KB_URL}/api/workflows/workflow",
        headers=KB_HEADERS,
        json={"id": "snap-nightly-fraud-sweep", "yaml": NIGHTLY_SWEEP_YAML},
        timeout=60,
    )
    if resp.status_code == 409:
        requests.put(
            f"{KB_URL}/api/workflows/workflow/snap-nightly-fraud-sweep",
            headers=KB_HEADERS,
            json={"yaml": NIGHTLY_SWEEP_YAML, "enabled": True},
            timeout=60,
        ).raise_for_status()
        print("  workflow snap-nightly-fraud-sweep updated")
    else:
        resp.raise_for_status()
        print("  workflow snap-nightly-fraud-sweep created")

    # Alerting rule with workflow action
    rule_body = {
        "name": "SNAP Same-Cent Trafficking",
        "tags": ["snap", "fraud", "demo"],
        "schedule": {"interval": "5m"},
        "params": {
            "searchType": "esqlQuery",
            "timeWindowSize": 7,
            "timeWindowUnit": "d",
            "threshold": [0],
            "thresholdComparator": ">",
            "size": 100,
            "esqlQuery": {"esql": TRAFFICKING_ESQL},
            "aggType": "count",
            "groupBy": "row",
            "termSize": 10,
            "timeField": "@timestamp",
            "excludeHitsFromPreviousRun": True,
        },
        "actions": [
            {
                "group": "query matched",
                "id": "system-connector-.workflows",
                "params": {
                    "subAction": "run",
                    "subActionParams": {"workflowId": "snap-trafficking-case"},
                },
                "frequency": {
                    "summary": False,
                    "notify_when": "onActiveAlert",
                    "throttle": None,
                },
            }
        ],
        "notify_when": "onActionGroupChange",
        "throttle": None,
    }
    resp = requests.put(
        f"{KB_URL}/api/alerting/rule/{RULE_ID}",
        headers=KB_HEADERS,
        json=rule_body,
        timeout=60,
    )
    resp.raise_for_status()
    print(f"  alerting rule SNAP Same-Cent Trafficking ({RULE_ID}) linked to workflow")


def upsert_dashboard() -> str:
    print("Step 8: Investigator dashboard")
    payload = build_dashboard()

    existing = requests.get(f"{KB_URL}/api/dashboards", headers=KB_HEADERS, params={"query": "SNAP Fraud Investigator"}, timeout=60)
    dashboard_id = None
    if existing.ok:
        for item in existing.json().get("dashboards", []):
            if item.get("data", {}).get("title") == "SNAP Fraud Investigator":
                dashboard_id = item["id"]
                break

    if dashboard_id:
        resp = requests.put(f"{KB_URL}/api/dashboards/{dashboard_id}", headers=KB_HEADERS, json=payload, timeout=60)
        resp.raise_for_status()
        print(f"  dashboard updated: {dashboard_id}")
        return dashboard_id

    resp = requests.post(f"{KB_URL}/api/dashboards", headers=KB_HEADERS, json=payload, timeout=60)
    resp.raise_for_status()
    dashboard_id = resp.json()["id"]
    print(f"  dashboard created: {dashboard_id}")
    return dashboard_id


def ensure_data_view() -> str:
    global DATA_VIEW_ID
    resp = requests.get(f"{KB_URL}/api/data_views", headers=KB_HEADERS, timeout=60)
    resp.raise_for_status()
    for dv in resp.json().get("data_view", []):
        if dv.get("title") == "snap-*":
            DATA_VIEW_ID = dv["id"]
            return DATA_VIEW_ID
    created = requests.post(
        f"{KB_URL}/api/data_views/data_view",
        headers=KB_HEADERS,
        json={"data_view": {"title": "snap-*", "name": "SNAP Demo", "timeFieldName": "@timestamp"}},
        timeout=60,
    )
    created.raise_for_status()
    DATA_VIEW_ID = created.json()["data_view"]["id"]
    print(f"  data view snap-* created ({DATA_VIEW_ID})")
    return DATA_VIEW_ID


def main() -> None:
    ensure_data_view()
    upsert_ml_jobs()
    upsert_workflows_and_rule()
    dashboard_id = upsert_dashboard()

    print("\nDone.")
    print(f"  Dashboard: {KB_URL}/app/dashboards#/view/{dashboard_id}")
    print(f"  Cases:     {KB_URL}/app/observability/cases")
    print(f"  Workflows: {KB_URL}/app/workflows")


if __name__ == "__main__":
    main()
