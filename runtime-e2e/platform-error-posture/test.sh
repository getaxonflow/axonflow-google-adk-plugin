#!/usr/bin/env bash
# test.sh — Verify the plugin's failure posture for each platform answer,
# through Runner.run_async, the real plugin and the real axonflow SDK.
#
# STUB CHANNEL: the platform is a local stub HTTP server started by
# test_agent.py, because the runtime stack cannot be made to answer these on
# demand (a community agent answers 200 for a missing or wrong credential, and
# nothing makes it answer a 429 or a 5xx). It does not touch the stack or its
# database. The live legs are policy-deny-blocks-tool-call (the platform's own
# deny) and breaker-opens-on-stack-down (no answer).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== platform-error-posture ==="
echo "  (stub channel: a local HTTP server answers 401 / 429 / 500 / 503 / 502-html / approval_required / slow; nothing listens for the no-answer leg)"

cd "$E2E_DIR"
output_file="$(mktemp)"
trap 'rm -f "$output_file"' EXIT
python_exit=0
python3 "$SCRIPT_DIR/test_agent.py" > "$output_file" 2>&1 || python_exit=$?
cat "$output_file"

if [ "$python_exit" -ne 0 ]; then
  echo "FAIL: platform-error-posture — test_agent.py exited $python_exit"
  exit 1
fi

# A run that asserted nothing is not a pass: every scenario prints a PASS line
# per assertion, and a crash before the first one prints none.
pass_lines="$(grep -c '^PASS: ' "$output_file" || true)"
if [ "$pass_lines" -eq 0 ]; then
  echo "FAIL: platform-error-posture — no assertion ran"
  exit 1
fi
if grep -q '^FAIL: ' "$output_file"; then
  echo "FAIL: platform-error-posture — an assertion failed"
  exit 1
fi

echo "  $pass_lines assertion(s) passed"
echo "PASS: platform-error-posture"
