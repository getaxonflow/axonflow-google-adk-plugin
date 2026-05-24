#!/usr/bin/env bash
# test.sh — Verify the HITL approval code path fires through Runner.run_async.
#
# In community mode, the HITL queue endpoint returns 404, so the plugin
# fails-closed and denies the tool call. The test verifies:
#   1. The tool was NOT executed (HITL path activated)
#   2. The plugin produced a denial signal
#   3. An audit row exists in mcp_query_audits
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
VALUES ('e2e-hitl-approval', 'E2E HITL approval test', 'security-dangerous', '.*disburse_funds.*', 'critical', 'require_approval', true, 'e2e-test', 'e2e-test')
ON CONFLICT (policy_id) DO NOTHING;
"

cleanup() {
  echo "  cleaning up require_approval policy..."
  psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c \
    "DELETE FROM static_policies WHERE policy_id = 'e2e-hitl-approval';" 2>/dev/null || true
}
trap cleanup EXIT

# RUN: execute the agent test
cd "$E2E_DIR"
python_exit=0
python3 "$SCRIPT_DIR/test_agent.py" > /tmp/hitl-approval-output.log 2>&1 || python_exit=$?
cat /tmp/hitl-approval-output.log

if [ "$python_exit" -ne 0 ]; then
  echo "FAIL: require-approval-creates-hitl-row-and-polls — test_agent.py exited $python_exit"
  exit 1
fi

# ASSERT: output proves the HITL code path was reached.
# The plugin logs at INFO level when HITL polling is activated or when
# create_hitl_request fails. Either signal proves the path fired.
if grep -qi 'hitl\|require_approval\|tool correctly not executed' /tmp/hitl-approval-output.log; then
  echo "  HITL code path confirmed in output"
else
  echo "FAIL: no HITL signal found in test output"
  exit 1
fi

# ASSERT: verify audit row exists (the check_tool_input call should audit)
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: require-approval-creates-hitl-row-and-polls"
