# agent-tool-bypass-gotcha-pinned

Documents the `AgentTool` plugin-isolation limitation
(https://github.com/google/adk-python/issues/2809).

Sub-agents invoked via `AgentTool` construct an inner Runner with
`plugins=[]`, so the parent's `AxonFlowPlugin` is NOT forwarded. This
means sub-agent model and tool calls are ungoverned.

The test verifies that:
1. The outer agent works correctly with the plugin registered.
2. The plugin does not interfere with the AgentTool pattern.

## Workaround

Use `RemoteA2aAgent` instead of `AgentTool`, or register the plugin on
the inner Runner as well.

## What this catches

- Plugin crashes when used alongside AgentTool patterns.
- Future ADK fixes that forward plugins to inner Runners (test would
  need updating to verify governance applies to sub-agents).
