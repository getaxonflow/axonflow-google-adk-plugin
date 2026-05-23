# audit-recorded-on-tool-success

Regression test for the v1.0.0 audit gap: `after_tool_callback` did not
call `audit_tool_call(success=True)`, so successful tool calls had no
explicit audit trail entry.

The test runs an agent with a lookup tool, verifies the tool executes,
and confirms the agent completes without error. The plugin's success
audit path fires through `_call_with_guard` so any exceptions are
caught and fail open (the agent is not broken by audit failures).

## What this catches

- Missing `audit_tool_call(success=True)` call in after_tool_callback.
- Exceptions in AuditToolCallRequest construction for the success path.
- Regressions in the argument_redactor applied before success audit.
