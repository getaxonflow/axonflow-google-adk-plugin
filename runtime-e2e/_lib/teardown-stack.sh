#!/usr/bin/env bash
# teardown-stack.sh — Bring down the AxonFlow stack and remove volumes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { echo "$(date -u +%H:%M:%S) [teardown-stack] $*"; }

log "Tearing down E2E stack..."
docker compose -f "$COMPOSE_DIR/docker-compose.yml" down -v 2>&1
log "Stack torn down"
