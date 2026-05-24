#!/usr/bin/env bash
# test.sh — Verify 5 sequential Runner.run_async calls complete
# with the circuit breaker staying closed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== sequential-runs-breaker-stable ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# RUN: execute 5 sequential runs through the same Runner
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify audit rows exist from all runs
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

echo "PASS: sequential-runs-breaker-stable"
