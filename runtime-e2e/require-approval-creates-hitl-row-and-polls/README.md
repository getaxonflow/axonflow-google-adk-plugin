# require-approval-creates-hitl-row-and-polls

Verifies that the HITL approval code path fires through
`Runner.run_async(...)` with `AxonFlowPlugin` registered.

A `require_approval` policy is inserted into `static_policies` via
psql before the test runs. When the stub model triggers a tool call,
`before_tool_callback` hits `check_tool_input`, which returns
`require_approval`. The plugin then attempts `create_hitl_request`,
which returns 404 in community mode. The plugin fails-closed and
denies the tool call.

## What this catches

- HITL polling code path not reached when `enable_hitl_polling=True`.
- Plugin silently allowing a `require_approval` verdict (should fail-closed).
- `create_hitl_request` error handling (404 in community mode).
- Regression in the 4-step HITL flow: gate -> create -> poll -> deny.
