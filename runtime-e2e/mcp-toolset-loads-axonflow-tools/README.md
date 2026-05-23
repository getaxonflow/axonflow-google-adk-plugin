# mcp-toolset-loads-axonflow-tools

Verifies that `axonflow_mcp_toolset()` constructs a valid `McpToolset`
pointed at the AxonFlow agent's MCP server endpoint (`/mcp/`).

Tests three auth paths:
1. Basic auth (client_id + client_secret)
2. Bearer token
3. Anonymous (community mode)

Does not run a full agent with MCP tools (the MCP endpoint may not have
connectors configured in community mode). Verifies construction,
connection params, and auth header generation.

## What this catches

- Import errors in the mcp_helper module.
- URL construction bugs (double slashes, missing path).
- Auth header encoding errors (Base64, Bearer prefix).
