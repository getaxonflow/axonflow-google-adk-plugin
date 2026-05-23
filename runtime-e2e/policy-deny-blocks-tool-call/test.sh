#!/usr/bin/env bash
# test.sh — Verify that a deny policy blocks a tool call and records
# a denied decision in audit_logs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== policy-deny-blocks-tool-call ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# SETUP: insert a deny policy into static_policies
echo "  inserting deny policy..."
psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c "
INSERT INTO static_policies (policy_id, name, category, pattern, severity, action, enabled, tenant_id, org_id)
VALUES ('e2e-deny-tool', 'E2E deny test', 'dangerous_queries', 'disburse_payment', 'high', 'block', true, 'e2e-test', 'e2e-test')
ON CONFLICT (policy_id) DO NOTHING;
"

cleanup() {
  echo "  cleaning up deny policy..."
  psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c \
    "DELETE FROM static_policies WHERE policy_id = 'e2e-deny-tool';" 2>/dev/null || true
}
trap cleanup EXIT

# RUN: execute the agent test (attempts to use the blocked tool)
cd "$E2E_DIR"
python_exit=0
python "$SCRIPT_DIR/test_agent.py" > /tmp/policy-deny-output.log 2>&1 || python_exit=$?
cat /tmp/policy-deny-output.log

if [ "$python_exit" -ne 0 ]; then
  echo "FAIL: policy-deny-blocks-tool-call — test_agent.py exited $python_exit"
  exit 1
fi

# ASSERT: Python output contains [AxonFlow] denial text
if ! grep -qi '\[AxonFlow\]' /tmp/policy-deny-output.log && ! grep -qi 'denied' /tmp/policy-deny-output.log; then
  echo "FAIL: no denial signal found in test output"
  exit 1
fi
echo "  denial signal found in output"

# ASSERT: query audit_logs for a denied decision
"$LIB_DIR/verify-db.sh" audit-log-denied "e2e-test"

echo "PASS: policy-deny-blocks-tool-call"
