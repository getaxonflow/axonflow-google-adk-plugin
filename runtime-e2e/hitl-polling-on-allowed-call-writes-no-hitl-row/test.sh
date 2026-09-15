#!/usr/bin/env bash
# test.sh — Verify that HITL polling holds nothing on an allowed call against a
# v11 platform, through Runner.run_async.
#
# It writes no policy: since AxonFlow v11.0.0 a row written into static_policies
# authors no verdict, and none of the platform's shipped controls gives an
# approval verdict for this tool call. The call is allowed. The test proves the
# hook chain ran with HITL polling on, the hold was never entered, and no HITL
# row was written. The approval refusal itself is proven through the stub
# channel in platform-error-posture (scenario D).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/../_lib"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export PGPASSWORD="${DB_PASSWORD:-localdev123}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"

echo "=== hitl-polling-on-allowed-call-writes-no-hitl-row ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# RUN: execute the agent test through Runner.run_async
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# ASSERT: the governance hooks fired (an adk-tool row in mcp_query_audits)
"$LIB_DIR/verify-db.sh" mcp-audit-exists "adk-tool"

# ASSERT: no HITL row for this suite's client id (test_agent.py CLIENT_ID)
"$LIB_DIR/verify-db.sh" hitl-absent "e2e-hitl-polling"

echo "PASS: hitl-polling-on-allowed-call-writes-no-hitl-row"
