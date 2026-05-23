# agent-runs-with-plugin-registered

Verifies that `AxonFlowPlugin` registers on a real ADK `InMemoryRunner`
and that the full model+tool call cycle completes without error.

The stub model returns a function call to `get_balance`, which triggers
both `before_model_callback` (pre_check) and `before_tool_callback`
(check_tool_input) on the plugin. The test asserts that the runner
produces events and the model output contains text (i.e., the plugin
did not erroneously block the call).

## What this catches

- Import errors in the plugin module under a real ADK installation.
- Hook signature mismatches between the plugin and ADK's BasePlugin.
- Failures in the lazy client construction path.
- Circuit breaker tripping on the first call (AxonFlow unreachable).
