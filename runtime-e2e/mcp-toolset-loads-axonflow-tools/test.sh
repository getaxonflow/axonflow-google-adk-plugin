#!/usr/bin/env bash
# test.sh — Verify axonflow_mcp_toolset() constructs correctly.
# No skip paths — McpToolset must be available or the test fails.
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

# SETUP: ensure mcp package is installed (required by McpToolset)
pip install mcp --quiet 2>/dev/null || true

# RUN: execute the test (must not skip — exit 1 if McpToolset unavailable)
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify the agent health endpoint is reachable (the test
# validates toolset construction + connection params in Python; we
# confirm the stack is live via a simple psql connectivity check)
psql -h "$DB_HOST" -p "$DB_PORT" -U axonflow -d axonflow -t -A -c "SELECT 1" | grep -q 1
if [ $? -ne 0 ]; then
  echo "FAIL: cannot reach Postgres — stack may be down"
  exit 1
fi
echo "  DB connectivity confirmed"

echo "PASS: mcp-toolset-loads-axonflow-tools"
