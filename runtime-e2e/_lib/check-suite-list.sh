#!/usr/bin/env bash
# check-suite-list.sh — the runtime-e2e suite list, checked against the suite directories.
#
# Prints run-all.sh's ALL_TESTS, one per line, when it names exactly the
# directories that hold a test.sh. Otherwise it prints the difference to stderr
# and exits 1. The release workflow runs the suites this prints, so a suite
# directory that is not listed, a listed suite with no test.sh, or a name listed
# twice fails the job instead of silently not running.
set -euo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$E2E_DIR"

listed="$(bash run-all.sh --list | sort)"
present="$(for f in */test.sh; do [ -f "$f" ] && printf '%s\n' "${f%/test.sh}"; done | grep -v '^_lib$' | sort || true)"

if [ -z "$listed" ]; then
  echo "check-suite-list: run-all.sh --list printed no suites" >&2
  exit 1
fi
if [ "$listed" != "$present" ]; then
  echo "check-suite-list: run-all.sh ALL_TESTS and the suite directories differ ('<' listed only, '>' directory only):" >&2
  diff <(printf '%s\n' "$listed") <(printf '%s\n' "$present") >&2 || true
  exit 1
fi
printf '%s\n' "$listed"
