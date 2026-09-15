#!/usr/bin/env bash
# test.sh — Verify the no-answer posture when AxonFlow is unreachable.
# Points the plugin at a dead port: with fail_open=True the agent completes
# ungoverned with a WARNING notice per governed call and the breaker opens;
# with fail_open=False the same outage denies.
# Does NOT assert DB state (the stack is intentionally unreachable).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== breaker-opens-on-stack-down ==="
echo "  (points plugin at unreachable endpoint — no stack interaction)"

# RUN: execute the agent test (plugin pointed at port 19999)
cd "$E2E_DIR"
python3 "$SCRIPT_DIR/test_agent.py"

# No DB assertion — the test intentionally avoids the real stack.
# The Python test verifies tool execution + breaker state internally.

echo "PASS: breaker-opens-on-stack-down"
