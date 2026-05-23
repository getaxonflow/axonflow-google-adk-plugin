#!/usr/bin/env bash
# test.sh — Verify that successful tool calls record an audit entry.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"

echo "=== audit-recorded-on-tool-success ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

cd "$E2E_DIR"
python "$SCRIPT_DIR/test_agent.py"
exit_code=$?

if [ "$exit_code" -ne 0 ]; then
  echo "FAIL: audit-recorded-on-tool-success (exit=$exit_code)"
  exit 1
fi

echo "PASS: audit-recorded-on-tool-success"
