# mcp-toolset-loads-axonflow-tools

Verifies that `axonflow_mcp_toolset()` integrates into a real
`Runner.run_async(...)` with `AxonFlowPlugin` registered.

The test constructs a toolset, registers it on an LlmAgent, and runs
the agent through the Runner. Since the community stack may not have
MCP connectors configured, the test uses a TextOnlyStubModel (no tool
calls issued). The toolset construction + Runner integration is the
primary verification.

Also tests three auth paths:
1. Basic auth (client_id + client_secret)
2. Bearer token
3. Anonymous (community mode)

## What this catches

- Import errors in the mcp_helper module.
- URL construction bugs (double slashes, missing path).
- Auth header encoding errors (Base64, Bearer prefix).
- McpToolset incompatibility with Runner plugin registration.
