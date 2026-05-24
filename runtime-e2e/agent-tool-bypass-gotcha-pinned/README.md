# agent-tool-bypass-gotcha-pinned

Verifies that `AgentTool` sub-agent governance works through
`Runner.run_async(...)` with `AxonFlowPlugin` registered.

ADK's `AgentTool` now supports `include_plugins=True` (the default),
which propagates parent Runner plugins to the inner agent. This test
creates an outer agent that delegates to an inner agent via AgentTool,
both governed by the plugin.

## What this catches

- Plugin crashes when used alongside AgentTool patterns.
- AgentTool not propagating plugins to inner agents.
- Regression in `include_plugins` default behavior.
- Inner agent tool calls not triggering governance hooks.
