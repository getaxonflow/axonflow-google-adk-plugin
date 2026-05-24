# breaker-opens-on-stack-down

Verifies fail-open behavior when the AxonFlow stack is unreachable.

Points the plugin at a non-existent endpoint (`127.0.0.1:19999`) and
runs the agent through `Runner.run_async(...)`. The plugin should
fail-open on every governance hook and the agent should complete
normally with the tool executing. After enough failures, the circuit
breaker should open.

## What this catches

- Plugin blocking or crashing when AxonFlow is down.
- Fail-open not working (tool should still execute).
- Circuit breaker not opening after threshold failures.
- Connection timeout handling bugs.
