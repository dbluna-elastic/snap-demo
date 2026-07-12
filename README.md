# SNAP Fraud Detection Demo

Synthetic SNAP/EBT fraud detection demo for **Elasticsearch 9.4+** with Agent Builder and Workflows. All data is fake — no real PII.

**Live cluster:** [Kibana](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com) · [Agent Chat](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/agent_builder/chat/snap-fraud-investigator)

## What's deployed

| Step | Status | Details |
|------|--------|---------|
| 1. Indices + mappings | Done | 4 indices, lookup mode on stores/households |
| 2. Ingest pipeline | Done | `snap-tx-enrich` derives `cents` from `amount` |
| 3. Synthetic data | Done | 300k txs, 5k households, 500 stores, 200 reference |
| 4. ES\|QL detections | Done | All 7 queries verified |
| 6. Agent Builder | Done | 7 tools + `snap-fraud-investigator` agent |
| 5. ML jobs | Done | 3 jobs running on `snap-transactions` |
| 7. Workflows | Done | Alert-triggered case workflow + nightly sweep |
| 8. Dashboard | Done | [Investigator dashboard](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dashboards#/view/130b4789-10ed-400f-890f-23086f5b76e8) |
| 9. Demo page | Done | `demo/index.html` |

## Seeded fraud entities

| Scenario | Entity | Signal |
|----------|--------|--------|
| Same-cent trafficking | Store `4471` | 93% transactions end in `.00` |
| Rapid drains | `hh_drain_demo_*` at store `7701` | Balance drained to &lt;$1 |
| Broken-up baskets | `hh_basket_demo_001` at `7701` | 5 txs / $180 in 4 min |
| Manual entry | Store `5102` | ~49% `entry_method: manual` |
| Volume spike (ML) | Store `3890` | 10× daily tx count last 3 days |
| Large baskets | Store `6123` | $30+ txs at convenience store |
| Cross-state ID | `ssn_hash_cross_state_demo_001` | Enrolled TX + FL |
| Deceased transacting | `hh_deceased_demo_001` | 25 txs after death record |

## Quick start (from scratch)

```bash
cp .env.example .env   # add your ES_URL + ES_API_KEY
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Steps 1-4: indices, pipeline, data, verify
bash scripts/setup_cluster.sh

# Step 6: Agent Builder tools + agent
.venv/bin/python scripts/setup_agent_builder.py

# Steps 5, 7, 8: ML jobs, workflows, dashboard
.venv/bin/python scripts/setup_kibana_extras.py
```

## Project layout

```
scripts/
  generate_data.py       # Synthetic data with 7 fraud signatures
  bulk_load.py           # NDJSON bulk loader
  verify_detections.py   # Assert all ES|QL queries hit seeded fraud
  setup_cluster.sh       # One-shot Steps 1-4
  setup_agent_builder.py # Create tools + agent via Kibana API
setup/
  setup.http             # Dev Tools commands (copy-paste)
demo/
  index.html             # Phase 3 landing page
data/                    # Generated NDJSON (gitignored)
```

## Deployed resources

| Resource | Link / ID |
|----------|-----------|
| Investigator dashboard | [Open dashboard](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/dashboards#/view/130b4789-10ed-400f-890f-23086f5b76e8) |
| Agent chat | [snap-fraud-investigator](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/agent_builder/chat/snap-fraud-investigator) |
| Alerting rule | `SNAP Same-Cent Trafficking` (every 5m) |
| Case workflow | `snap-trafficking-case` (alert-triggered) |
| Nightly sweep | `snap-nightly-fraud-sweep` (daily 06:00 UTC) |
| ML jobs | `snap-store-volume-spike`, `snap-store-basket-value`, `snap-household-spend-rate` |

Cases are created automatically when the trafficking rule fires and invokes the workflow (typically within 5 minutes of setup, or on the next new alert). Check [Observability Cases](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/observability/cases).

## Step 5 — ML anomaly jobs (automated)

Created via `scripts/setup_kibana_extras.py`:

| Job | Function | Partition | Bucket |
|-----|----------|-----------|--------|
| `snap-store-volume-spike` | `high_count` | `store_id` | 1h |
| `snap-store-basket-value` | `high_mean` on `amount` | `store_id` | 1h |
| `snap-household-spend-rate` | `high_sum` on `amount` | `household_id` | 1d |

- **Data view / index:** `snap-transactions`
- **Time field:** `@timestamp`
- **Demo target:** store `3890` — verified with 16 high-score anomalies (max ~100) on `snap-store-volume-spike`

Talking point: *"No thresholds hand-tuned — Elastic learned normal for every store and household."*

## Step 7 — Workflows (automated)

Deployed via `scripts/setup_kibana_extras.py`.

### 7a. Detection rule

ES|QL rule **SNAP Same-Cent Trafficking** (`.es-query`, every 5m) using query 4a. Linked to workflow action on `query matched`.

### 7b. Alert-triggered workflow

Workflow `snap-trafficking-case` creates an Observability case, attaches the alert, enriches store/recipients via ES|QL, and adds a comment.

### 7c. Scheduled sweep

Workflow `snap-nightly-fraud-sweep` runs detections 4a/4b/4f/4g daily at 06:00 UTC.

## Step 8 — Kibana dashboard (automated)

Dashboard **SNAP Fraud Investigator** includes:

1. **Filters** — state and entry method controls
2. **Metrics** — flagged stores, cross-state IDs, deceased accounts
3. **Ranked bars** — same-cent stores, manual-entry stores, drain households
4. **ML swimlane** — anomaly scores for store `3890` on `snap-store-volume-spike`
5. **State breakdown** — flagged stores by state (add a map panel in the UI if desired; the Dashboards API does not yet support `map` type)

## Agent test prompts

Open [Agent Chat](https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com/app/agent_builder/chat/snap-fraud-investigator):

- "Which stores show signs of trafficking this week?"
- "Why is store 4471 suspicious?"
- "Is anyone enrolled in two states?"
- "Show me accounts being drained to zero."

## Live-demo checklist

- [x] All 4 indices created + mapped
- [x] Ingest pipeline deriving `cents`
- [x] Synthetic data loaded, 7 fraud signatures verified
- [x] Each ES|QL detection returns seeded fraud
- [x] 3 ML jobs run and flag store `3890`
- [x] 7 Agent Builder tools + agent created
- [x] Detection rule + workflow wired (cases appear on next alert fire)
- [x] Dashboard renders metrics, ranked tables, ML swimlane, and filters
- [ ] 10-minute storyline rehearsed

## Regenerate data

```bash
SNAP_TX_COUNT=500000 .venv/bin/python scripts/generate_data.py
.venv/bin/python scripts/bulk_load.py
.venv/bin/python scripts/verify_detections.py
```
