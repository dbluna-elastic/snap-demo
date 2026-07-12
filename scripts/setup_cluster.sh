#!/usr/bin/env bash
# One-shot cluster setup for SNAP Fraud Detection Demo (Steps 1-4)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

: "${ES_URL:?Set ES_URL in .env}"
: "${ES_API_KEY:?Set ES_API_KEY in .env}"

AUTH="Authorization: ApiKey ${ES_API_KEY}"
HDR=(-H "$AUTH" -H "Content-Type: application/json")

echo "==> Elasticsearch $(curl -sf -H "$AUTH" "${ES_URL}/" | python3 -c "import json,sys; print(json.load(sys.stdin)['version']['number'])")"

echo "==> Step 1: Create indices"
for idx in snap-transactions snap-stores snap-households snap-reference; do
  curl -sf -X DELETE -H "$AUTH" "${ES_URL}/${idx}" >/dev/null 2>&1 || true
done

curl -sf -X PUT "${HDR[@]}" "${ES_URL}/snap-transactions" -d '{
  "settings": { "index.default_pipeline": "snap-tx-enrich" },
  "mappings": {
    "properties": {
      "transaction_id":  { "type": "keyword" },
      "@timestamp":      { "type": "date" },
      "card_id":         { "type": "keyword" },
      "household_id":    { "type": "keyword" },
      "store_id":        { "type": "keyword" },
      "amount":          { "type": "double" },
      "cents":           { "type": "integer" },
      "entry_method":    { "type": "keyword" },
      "balance_after":   { "type": "double" },
      "state":           { "type": "keyword" },
      "geo":             { "type": "geo_point" }
    }
  }
}' >/dev/null && echo "  snap-transactions"

curl -sf -X PUT "${HDR[@]}" "${ES_URL}/snap-stores" -d '{
  "settings": { "index.mode": "lookup" },
  "mappings": {
    "properties": {
      "store_id": { "type": "keyword" }, "name": { "type": "text" },
      "category": { "type": "keyword" }, "geo": { "type": "geo_point" },
      "authorized_date": { "type": "date" }, "expected_avg_basket": { "type": "double" },
      "state": { "type": "keyword" }
    }
  }
}' >/dev/null && echo "  snap-stores (lookup)"

curl -sf -X PUT "${HDR[@]}" "${ES_URL}/snap-households" -d '{
  "settings": { "index.mode": "lookup" },
  "mappings": {
    "properties": {
      "household_id": { "type": "keyword" }, "ssn_hash": { "type": "keyword" },
      "state": { "type": "keyword" }, "enrollment_date": { "type": "date" },
      "monthly_benefit": { "type": "double" }, "reported_income": { "type": "double" },
      "household_size": { "type": "integer" }, "status": { "type": "keyword" }
    }
  }
}' >/dev/null && echo "  snap-households (lookup)"

curl -sf -X PUT "${HDR[@]}" "${ES_URL}/snap-reference" -d '{
  "mappings": {
    "properties": {
      "ssn_hash": { "type": "keyword" }, "source": { "type": "keyword" },
      "state": { "type": "keyword" }, "record_date": { "type": "date" }
    }
  }
}' >/dev/null && echo "  snap-reference"

echo "==> Step 2: Ingest pipeline"
curl -sf -X PUT "${HDR[@]}" "${ES_URL}/_ingest/pipeline/snap-tx-enrich" -d '{
  "description": "Derive cents from amount for SNAP transactions",
  "processors": [{
    "script": {
      "source": "ctx.cents = (int)(Math.round((ctx.amount - Math.floor(ctx.amount)) * 100));"
    }
  }]
}' >/dev/null && echo "  snap-tx-enrich"

echo "==> Step 3: Generate & load synthetic data"
cd "$ROOT_DIR"
python3 -m venv .venv 2>/dev/null || true
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python scripts/generate_data.py
.venv/bin/python scripts/bulk_load.py

echo "==> Step 4: Verify detections"
.venv/bin/python scripts/verify_detections.py

echo ""
echo "Cluster setup complete. Continue in Kibana:"
echo "  ${KB_URL:-https://gawdzilla-0d3e9e.kb.us-east-2.aws.elastic-cloud.com}"
echo "  Steps 5-9: see README.md (run scripts/setup_kibana_extras.py)"
