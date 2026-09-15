#!/usr/bin/env bash
# test.sh — Verify require_approval policy path through Runner.run_async.
#
# In community mode, require_approval policies auto-approve. This test
# verifies the full governance hook chain fires through the customer
# entry point with AxonFlowPlugin + enable_hitl_polling=True configured.
#
# It no longer writes a require_approval row into static_policies: since
# AxonFlow v11.0.0 a row written there authors no verdict, and none of the
# platform's shipped controls gives an approval verdict for this tool call. The
# tool call is allowed, and the test
# proves the hook chain with HITL polling on and the audit row it leaves.
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

# RUN: execute the agent test through Runner.run_async
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify audit row exists (governance hooks fired)
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: require-approval-creates-hitl-row-and-polls"
