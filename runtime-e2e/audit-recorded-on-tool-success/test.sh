#!/usr/bin/env bash
# test.sh — Verify that successful tool calls record an audit entry
# in the database (Bug 4 regression test).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== audit-recorded-on-tool-success ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# RUN: execute the agent test
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify audit_logs row exists for client_id='e2e-test'
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: audit-recorded-on-tool-success"
