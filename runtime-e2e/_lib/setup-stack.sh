#!/usr/bin/env bash
# setup-stack.sh — Bring up the AxonFlow stack and wait for health.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { echo "$(date -u +%H:%M:%S) [setup-stack] $*"; }

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

log "Starting E2E stack..."
docker compose -f "$COMPOSE_DIR/docker-compose.yml" up -d 2>&1

AGENT_URL="${AGENT_URL:-http://localhost:18080}"
wait_for_health "$AGENT_URL" "axonflow-agent" 90

log "Stack ready"
