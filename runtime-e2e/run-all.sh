#!/usr/bin/env bash
# run-all.sh — ADK Plugin runtime E2E orchestrator.
#
# Brings up the AxonFlow stack, runs all test scenarios, tears down.
# Exit non-zero on any failure.
#
# Usage:
#   cd runtime-e2e
#   ./run-all.sh              # full lifecycle (up -> test -> down)
#   ./run-all.sh --no-down    # leave stack running for debugging
#   TESTS="agent-runs-with-plugin-registered" ./run-all.sh  # run specific test

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Configuration ---
AGENT_URL="${AGENT_URL:-http://localhost:18080}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"
DB_NAME="${DB_NAME:-axonflow}"
DB_USER="${DB_USER:-axonflow}"
DB_PASSWORD="${DB_PASSWORD:-localdev123}"

TEAR_DOWN=true
ALL_TESTS="agent-runs-with-plugin-registered policy-deny-blocks-tool-call audit-recorded-on-tool-success require-approval-creates-hitl-row-and-polls mcp-toolset-loads-axonflow-tools agent-tool-bypass-gotcha-pinned on-tool-error-callback-fires sequential-runs-breaker-stable breaker-opens-on-stack-down on-user-message-callback-fires"
SELECTED_TESTS="${TESTS:-$ALL_TESTS}"

for arg in "$@"; do
  case "$arg" in
    --no-down) TEAR_DOWN=false ;;
    *) echo "Unknown arg: $arg"; exit 2 ;;
  esac
done

export AGENT_URL DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD
export PGPASSWORD="$DB_PASSWORD"

WORK="/tmp/adk-plugin-e2e-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$WORK"
export WORK

# --- Results tracking ---
PASS=0
FAIL=0
SKIP=0
RESULTS=()

record() {
  local test_name="$1" status="$2" detail="${3:-}"
  RESULTS+=("$status $test_name $detail")
  case "$status" in
    PASS) PASS=$((PASS + 1)) ;;
    FAIL) FAIL=$((FAIL + 1)) ;;
    SKIP) SKIP=$((SKIP + 1)) ;;
  esac
}

# --- Helpers ---
log() { echo "$(date -u +%H:%M:%S) [run-all] $*"; }

wait_for_health() {
  local url="$1" name="$2" timeout="${3:-90}"
  log "Waiting for $name at $url/health (timeout ${timeout}s)..."
  for i in $(seq 1 "$timeout"); do
    if curl -sf -o /dev/null --max-time 2 "$url/health" 2>/dev/null; then
      log "$name healthy after ${i}s"
      return 0
    fi
    sleep 1
  done
  log "FATAL: $name not healthy after ${timeout}s"
  return 1
}

# --- Stack lifecycle ---
stack_up() {
  log "=== Starting E2E stack ==="
  docker compose -f docker-compose.yml up -d 2>&1 | tee "$WORK/stack-up.log"
  wait_for_health "$AGENT_URL" "axonflow-agent" 90
  log "Stack ready"
}

stack_down() {
  if [ "$TEAR_DOWN" = "true" ]; then
    log "=== Tearing down E2E stack ==="
    docker compose -f docker-compose.yml down -v 2>&1 | tee "$WORK/stack-down.log"
  else
    log "=== Leaving stack up (--no-down) ==="
  fi
}

# --- Test runner ---
run_test() {
  local test_name="$1"

  if ! echo "$SELECTED_TESTS" | grep -qw "$test_name"; then
    record "$test_name" SKIP "not selected"
    return 0
  fi

  log "--- Test: $test_name ---"

  if [ ! -d "$test_name" ]; then
    log "SKIP: $test_name/ not found"
    record "$test_name" SKIP "dir not found"
    return 0
  fi

  local test_script="$test_name/test.sh"
  if [ ! -f "$test_script" ]; then
    log "SKIP: no test.sh in $test_name/"
    record "$test_name" SKIP "no test.sh"
    return 0
  fi

  chmod +x "$test_script"
  local test_log="$WORK/${test_name}.log"
  local test_exit=0
  bash "$test_script" > "$test_log" 2>&1 || test_exit=$?
  cat "$test_log"
  if [ "$test_exit" -eq 0 ]; then
    record "$test_name" PASS
  else
    record "$test_name" FAIL "exit=$test_exit see $test_log"
  fi
}

# --- Main ---
main() {
  log "============================================"
  log "AxonFlow ADK Plugin — Runtime E2E Harness"
  log "============================================"
  log "Workspace: $WORK"
  log "Selected tests: $SELECTED_TESTS"
  log ""

  trap stack_down EXIT

  stack_up

  # Install the plugin from local checkout
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  log "Installing axonflow-google-adk-plugin from $REPO_ROOT..."
  pip install -e "$REPO_ROOT" --quiet 2>&1 | tail -3

  for test_name in $ALL_TESTS; do
    run_test "$test_name"
  done

  # --- Summary ---
  log ""
  log "============================================"
  log "RESULTS SUMMARY"
  log "============================================"
  for r in "${RESULTS[@]}"; do
    status="${r%% *}"
    rest="${r#* }"
    case "$status" in
      PASS) echo "  [PASS] $rest" ;;
      FAIL) echo "  [FAIL] $rest" ;;
      SKIP) echo "  [SKIP] $rest" ;;
    esac
  done
  log ""
  log "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
  log "Artifacts: $WORK"

  if [ "$FAIL" -gt 0 ]; then
    log "EXIT 1 — $FAIL test(s) failed"
    exit 1
  fi

  log "EXIT 0 — all tests passed"
  exit 0
}

main
