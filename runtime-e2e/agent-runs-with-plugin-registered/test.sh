#!/usr/bin/env bash
# test.sh — Verify AxonFlowPlugin registers on an ADK Runner and creates
# an audit_logs row proving the pre_check hook fired against the real stack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== agent-runs-with-plugin-registered ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# RUN: execute the agent test
cd "$E2E_DIR"
python "$SCRIPT_DIR/test_agent.py"

# ASSERT: verify an audit_logs row exists for client_id='e2e-test'
"$LIB_DIR/verify-db.sh" audit-log-exists "e2e-test"

echo "PASS: agent-runs-with-plugin-registered"
