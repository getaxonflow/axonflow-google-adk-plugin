#!/usr/bin/env bash
# test.sh — Verify the HITL approval flow creates a row in
# hitl_approval_queue when a require_approval policy is active.
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

# SETUP: insert a require_approval policy into static_policies
echo "  inserting require_approval policy..."
psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c "
INSERT INTO static_policies (policy_id, name, category, pattern, severity, action, enabled, tenant_id, org_id)
VALUES ('e2e-approval-test', 'E2E approval test', 'admin_access', 'disburse_payment', 'critical', 'require_approval', true, 'e2e-test', 'e2e-test')
ON CONFLICT (policy_id) DO NOTHING;
"

cleanup() {
  echo "  cleaning up approval policy and HITL rows..."
  psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c \
    "DELETE FROM hitl_approval_queue WHERE client_id = 'e2e-test';" 2>/dev/null || true
  psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c \
    "DELETE FROM static_policies WHERE policy_id = 'e2e-approval-test';" 2>/dev/null || true
}
trap cleanup EXIT

# RUN: execute the agent test (triggers HITL flow)
cd "$E2E_DIR"
python "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify a hitl_approval_queue row exists for client_id='e2e-test'
"$LIB_DIR/verify-db.sh" hitl-exists "e2e-test"

echo "PASS: require-approval-creates-hitl-row-and-polls"
