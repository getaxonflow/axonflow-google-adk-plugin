#!/usr/bin/env bash
# test.sh — Verify that a deny policy blocks a tool call.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"

echo "=== policy-deny-blocks-tool-call ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

cd "$E2E_DIR"
python "$SCRIPT_DIR/test_agent.py"
exit_code=$?

if [ "$exit_code" -ne 0 ]; then
  echo "FAIL: policy-deny-blocks-tool-call (exit=$exit_code)"
  exit 1
fi

echo "PASS: policy-deny-blocks-tool-call"
