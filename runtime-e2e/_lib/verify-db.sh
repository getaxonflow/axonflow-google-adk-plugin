#!/usr/bin/env bash
# verify-db.sh — Assertion queries against the AxonFlow platform DB.
#
# Usage:
#   ./verify-db.sh audit-row-exists <table> <column> <value>
#   ./verify-db.sh audit-row-count <table> <minimum>
#   ./verify-db.sh hitl-row <request_id>
#   ./verify-db.sh hitl-field <request_id> <field> <expected>
#   ./verify-db.sh table-row-count <table> <minimum>
#
# Environment:
#   DB_HOST (default: localhost)
#   DB_PORT (default: 15432)
#   DB_NAME (default: axonflow)
#   DB_USER (default: axonflow)
#   DB_PASSWORD (default: localdev123)

set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-15432}"
DB_NAME="${DB_NAME:-axonflow}"
DB_USER="${DB_USER:-axonflow}"
DB_PASSWORD="${DB_PASSWORD:-localdev123}"

export PGPASSWORD="$DB_PASSWORD"

validate_identifier() {
  local val="$1" label="$2"
  if ! [[ "$val" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
    echo "ABORT: invalid $label '$val' — must be [a-zA-Z_][a-zA-Z0-9_]*" >&2
    exit 2
  fi
}

validate_safe_string() {
  local val="$1" label="$2"
  if [[ "$val" =~ [\'] ]] || [[ "$val" =~ \; ]] || [[ "$val" =~ -- ]]; then
    echo "ABORT: invalid $label — contains disallowed characters" >&2
    exit 2
  fi
}

psql_param() {
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -A "$@"
}

case "${1:-}" in
  audit-row-exists)
    table="${2:?usage: verify-db.sh audit-row-exists <table> <column> <value>}"
    column="${3:?}"
    value="${4:?}"
    validate_identifier "$table" "table"
    validate_identifier "$column" "column"
    validate_safe_string "$value" "value"
    count=$(psql_param -c "SELECT COUNT(*) FROM $table WHERE $column = '$value'")
    if [ "$count" -eq 0 ]; then
      echo "FAIL: no row in $table where $column='$value'"
      exit 1
    fi
    echo "OK: found $count row(s) in $table where $column='$value'"
    exit 0
    ;;

  audit-row-count)
    table="${2:?usage: verify-db.sh audit-row-count <table> <minimum>}"
    minimum="${3:?}"
    validate_identifier "$table" "table"
    if ! [[ "$minimum" =~ ^[0-9]+$ ]]; then
      echo "ABORT: minimum must be a number" >&2
      exit 2
    fi
    count=$(psql_param -c "SELECT COUNT(*) FROM $table")
    if [ "$count" -lt "$minimum" ]; then
      echo "FAIL: $table has $count rows (expected >= $minimum)"
      exit 1
    fi
    echo "OK: $table has $count rows (>= $minimum)"
    exit 0
    ;;

  hitl-row)
    request_id="${2:?usage: verify-db.sh hitl-row <request_id>}"
    validate_safe_string "$request_id" "request_id"
    row=$(psql_param -c "SELECT row_to_json(t) FROM (
      SELECT request_id, client_id, user_id, original_query,
             request_type, triggered_policy_id, trigger_reason, status
      FROM hitl_approval_queue WHERE request_id = '$request_id'
    ) t")
    if [ -z "$row" ]; then
      echo "FAIL: no row found for request_id=$request_id"
      exit 1
    fi
    echo "$row"
    exit 0
    ;;

  hitl-field)
    request_id="${2:?usage: verify-db.sh hitl-field <request_id> <field> <expected>}"
    field="${3:?}"
    expected="${4:?}"
    validate_safe_string "$request_id" "request_id"
    validate_identifier "$field" "field"
    validate_safe_string "$expected" "expected"
    actual=$(psql_param -c "SELECT $field FROM hitl_approval_queue WHERE request_id = '$request_id'")
    if [ "$actual" != "$expected" ]; then
      echo "FAIL: $field='$actual' (expected '$expected') for request_id=$request_id"
      exit 1
    fi
    echo "OK: $field='$actual' matches expected"
    exit 0
    ;;

  table-row-count)
    table="${2:?usage: verify-db.sh table-row-count <table> <minimum>}"
    minimum="${3:?}"
    validate_identifier "$table" "table"
    if ! [[ "$minimum" =~ ^[0-9]+$ ]]; then
      echo "ABORT: minimum must be a number" >&2
      exit 2
    fi
    count=$(psql_param -c "SELECT COUNT(*) FROM $table")
    if [ "$count" -lt "$minimum" ]; then
      echo "FAIL: $table has $count rows (expected >= $minimum)"
      exit 1
    fi
    echo "OK: $table has $count rows (>= $minimum)"
    exit 0
    ;;

  *)
    echo "Usage: $0 {audit-row-exists|audit-row-count|hitl-row|hitl-field|table-row-count} ..."
    exit 2
    ;;
esac
