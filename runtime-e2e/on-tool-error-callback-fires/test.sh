#!/usr/bin/env bash
# test.sh — Verify that on_tool_error_callback fires and audits
# through Runner.run_async when a tool raises an exception.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== on-tool-error-callback-fires ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# RUN: execute the agent test (tool will raise RuntimeError)
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify audit row exists (error audit should fire)
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: on-tool-error-callback-fires"
