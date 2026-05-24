# on-tool-error-callback-fires

Verifies that the `on_tool_error_callback` fires through
`Runner.run_async(...)` when a tool raises an exception.

A buggy tool raises `RuntimeError`. ADK catches the exception and
invokes the plugin's error callback, which calls `audit_tool_call`
with `success=False`. The test verifies the Runner completes and an
audit row is created.

## What this catches

- Plugin's error callback crashing the agent on tool exceptions.
- Missing audit trail for failed tool calls.
- Regression in ADK's tool-error-to-callback dispatch.
