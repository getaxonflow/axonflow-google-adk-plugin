#!/usr/bin/env bash
# test.sh — Verify require_approval policy path through Runner.run_async.
#
# In community mode, require_approval policies auto-approve. This test
# verifies the full governance hook chain fires through the customer
# entry point with AxonFlowPlugin + enable_hitl_polling=True configured.
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

# SETUP: insert a require_approval policy
echo "  inserting require_approval policy..."
psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c "
INSERT INTO static_policies (policy_id, name, category, pattern, severity, action, enabled, tenant_id, org_id)
VALUES ('e2e-hitl-approval', 'E2E HITL approval test', 'security-dangerous', '.*disburse_funds.*', 'critical', 'require_approval', true, 'global', '')
ON CONFLICT (policy_id) DO NOTHING;
"

# The policy engine caches policies at startup — restart the agent
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
  echo "  cleaning up require_approval policy..."
  psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -c \
    "DELETE FROM static_policies WHERE policy_id = 'e2e-hitl-approval';" 2>/dev/null || true
}
trap cleanup EXIT

# RUN: execute the agent test through Runner.run_async
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify audit row exists (governance hooks fired)
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: require-approval-creates-hitl-row-and-polls"
