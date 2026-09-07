#!/usr/bin/env bash
# test.sh — Verify axonflow_mcp_toolset() integrates into Runner.run_async.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== mcp-toolset-loads-axonflow-tools ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# No side-install of `mcp` here. The wheel under test declares
# `google-adk[mcp]`, so the installed environment is the customer's; an
# unpinned `pip install mcp` on top of it once resolved `mcp` 2.x, which
# google-adk does not support, and took McpToolset out of the release run.

# RUN: execute the agent test through Runner.run_async
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify DB connectivity and audit row
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: mcp-toolset-loads-axonflow-tools"
