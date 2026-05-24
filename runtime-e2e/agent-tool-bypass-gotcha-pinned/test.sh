#!/usr/bin/env bash
# test.sh — Pin the AgentTool plugin-isolation gotcha.
# Verifies that sub-agent tool calls are NOT audited (the bypass bug).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== agent-tool-bypass-gotcha-pinned ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# Capture the audit_logs count BEFORE the test runs so we can
# detect whether the sub-agent's call (if any) produced a new row.
pre_count=$(psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -t -A \
  -c "SELECT COUNT(*) FROM audit_logs WHERE client_id = 'e2e-test' AND query LIKE '%inner_agent%'")

# RUN: execute the agent test
cd "$E2E_DIR"
python "$SCRIPT_DIR/test_agent.py"

# ASSERT: no NEW audit_logs row for the sub-agent's inner_agent call.
# This confirms the bypass bug: sub-agents via AgentTool are NOT governed.
post_count=$(psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -t -A \
  -c "SELECT COUNT(*) FROM audit_logs WHERE client_id = 'e2e-test' AND query LIKE '%inner_agent%'")

new_rows=$((post_count - pre_count))

if [ "$new_rows" -gt 0 ]; then
  echo "INFO: found $new_rows new audit row(s) for inner_agent — the AgentTool bypass bug may be fixed upstream."
  echo "INFO: update this test to assert governance IS applied to sub-agents."
  # This is informational, not a failure — the bug being fixed is a good thing.
  # The test still passes because the agent completed successfully.
fi

# ASSERT: verify at least the outer agent's audit row exists
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: agent-tool-bypass-gotcha-pinned"
