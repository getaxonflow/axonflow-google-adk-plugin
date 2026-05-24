#!/usr/bin/env bash
# test.sh — Verify the HITL queue API creates a row.
# REQUIRES: enterprise agent (HITL endpoint is enterprise-only).
# In community mode, this test exits 1 with an explicit message.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== require-approval-creates-hitl-row-and-polls ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# PRE-CHECK: verify the HITL endpoint exists (enterprise-only)
HITL_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
  -X POST "$AXONFLOW_ENDPOINT/api/v1/hitl/queue" \
  -H "Content-Type: application/json" \
  -d '{"client_id":"probe","original_query":"probe","request_type":"probe","triggered_policy_id":"probe","triggered_policy_name":"probe","trigger_reason":"probe","severity":"low"}' 2>/dev/null || echo "000")

if [ "$HITL_CODE" = "404" ]; then
  echo "FAIL: HITL endpoint returned 404 — this test requires enterprise agent"
  echo "  The community agent does not expose /api/v1/hitl/queue."
  echo "  Run this test against an enterprise stack."
  exit 1
fi

cleanup() {
  echo "  cleaning up HITL rows..."
  psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c \
    "DELETE FROM hitl_approval_queue WHERE client_id = 'e2e-test';" 2>/dev/null || true
}
trap cleanup EXIT

# RUN: create a HITL row via the SDK's create_hitl_request API
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify a hitl_approval_queue row exists for client_id='e2e-test'
"$LIB_DIR/verify-db.sh" hitl-exists "e2e-test"

echo "PASS: require-approval-creates-hitl-row-and-polls"
