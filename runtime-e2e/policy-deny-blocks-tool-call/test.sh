#!/usr/bin/env bash
# test.sh — Verify that a policy deny blocks a tool call and records the
# check in mcp_query_audits.
#
# The deny comes from a control the platform ships: sys_dangerous_destructive_fs
# (migration core/059) blocks `rm -rf /`-shaped commands, and the check-input
# pass reads the tool call's parameters as well as its name. Since AxonFlow
# v11.0.0 the anchored engine decides check-input, and a row written straight
# into static_policies authors no verdict, so this test no longer seeds one.
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

# RUN: execute the agent test (its tool call carries a destructive command)
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
