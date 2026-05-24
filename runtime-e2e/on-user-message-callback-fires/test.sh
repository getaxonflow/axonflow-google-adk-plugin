#!/usr/bin/env bash
# test.sh — Verify on_user_message_callback fires without breaking
# multi-turn conversations through Runner.run_async.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== on-user-message-callback-fires ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# RUN: execute the multi-turn agent test
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify audit rows exist from all turns
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: on-user-message-callback-fires"
