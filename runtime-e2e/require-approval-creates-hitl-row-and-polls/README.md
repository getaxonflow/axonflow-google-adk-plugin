# require-approval-creates-hitl-row-and-polls

Exercises the 4-step HITL approval flow:

1. `pre_check` / `check_tool_input` returns `block_reason="require_approval"`
2. Plugin calls `create_hitl_request` to enqueue a queue row
3. Plugin polls `get_hitl_request` until terminal status
4. On approval, tool proceeds; on rejection/timeout, tool is denied

In community mode (no require_approval policy available), the test
verifies the deny-fast path: `enable_hitl_polling=False` causes the
plugin to deny immediately without creating a queue row.

## What this catches

- HITL row creation failures (missing fields, SDK shape drift).
- Polling loop hangs or incorrect terminal-status detection.
- Deny-fast mode not short-circuiting correctly.
