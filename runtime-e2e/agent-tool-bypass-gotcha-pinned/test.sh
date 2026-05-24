#!/usr/bin/env bash
# test.sh — Verify AgentTool sub-agent governance through Runner.run_async.
# The outer agent delegates to an inner agent via AgentTool, both governed
# by AxonFlowPlugin.
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

# RUN: execute the agent test (outer agent + AgentTool inner agent)
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify audit row exists for the tool call chain
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: agent-tool-bypass-gotcha-pinned"
