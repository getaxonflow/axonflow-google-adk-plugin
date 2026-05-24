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
VALUES ('e2e-deny-tool', 'E2E deny test', 'security-dangerous', '.*disburse_payment.*', 'high', 'block', true, 'global', '')
ON CONFLICT (policy_id) DO NOTHING;
"

# The policy engine caches policies at startup — restart the agent
# so the new policy is loaded into the engine's in-memory cache.
echo "  restarting agent to pick up new policy..."
docker restart adk-e2e-agent > /dev/null 2>&1
for i in $(seq 1 30); do
  if curl -sf -o /dev/null --max-time 2 "$AXONFLOW_ENDPOINT/health" 2>/dev/null; then
    echo "  agent restarted (${i}s)"
    break
  fi
  if [ "$i" -eq 30 ]; then echo "FAIL: agent not healthy after restart"; exit 1; fi
  sleep 1
done

cleanup() {
  echo "  cleaning up deny policy..."
  psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c \
    "DELETE FROM static_policies WHERE policy_id = 'e2e-deny-tool';" 2>/dev/null || true
}
trap cleanup EXIT

# RUN: execute the agent test (attempts to use the blocked tool)
cd "$E2E_DIR"
python_exit=0
python3 "$SCRIPT_DIR/test_agent.py" > /tmp/policy-deny-output.log 2>&1 || python_exit=$?
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
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: policy-deny-blocks-tool-call"
