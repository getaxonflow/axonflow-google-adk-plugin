#!/usr/bin/env bash
# test.sh — a tool result reaches the model with the platform's redaction
# applied, and the tool-call audit's user id is never the user token.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export AXONFLOW_ENDPOINT="${AGENT_URL:-http://localhost:18080}"
export AXONFLOW_TELEMETRY="${AXONFLOW_TELEMETRY:-off}"
PYTHON="${PYTHON:-python3}"

echo "=== tool-result-redaction ==="
echo "  endpoint: $AXONFLOW_ENDPOINT"
echo "  plugin:   $("$PYTHON" -c 'import axonflow_adk, os; print(axonflow_adk.__version__, os.path.dirname(axonflow_adk.__file__))')"

cd "$SCRIPT_DIR/.."
"$PYTHON" "$SCRIPT_DIR/test_agent.py"
