#!/usr/bin/env bash
# test.sh — Verify AxonFlowPlugin registers on an ADK Runner.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"

echo "=== agent-runs-with-plugin-registered ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"

# Run the test agent
cd "$E2E_DIR"
python "$SCRIPT_DIR/test_agent.py"
exit_code=$?

if [ "$exit_code" -ne 0 ]; then
  echo "FAIL: agent-runs-with-plugin-registered (exit=$exit_code)"
  exit 1
fi

echo "PASS: agent-runs-with-plugin-registered"
