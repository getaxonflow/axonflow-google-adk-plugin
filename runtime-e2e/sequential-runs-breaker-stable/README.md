# sequential-runs-breaker-stable

Verifies that 5 sequential `Runner.run_async(...)` calls complete
successfully with the circuit breaker staying in CLOSED state.

Reuses the same Runner and AxonFlowPlugin instance across all 5 runs.
Each run triggers a tool call (get_balance), exercising the full
pre_check + check_tool_input + check_tool_output + audit cycle.

## What this catches

- State leakage between sequential runs on the same Runner.
- Circuit breaker drifting to OPEN on transient timing issues.
- Plugin client re-initialization bugs across invocations.
- Session isolation failures.
