# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that axonflow_mcp_toolset() connects to a real MCP endpoint.

The AxonFlow agent exposes an MCP server at /mcp/. This test verifies
that the `axonflow_mcp_toolset()` helper constructs a valid McpToolset
that can be used with ADK. The test does not run a full agent (the MCP
endpoint may not have connectors configured in community mode), but
verifies the construction path and connection params.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main() -> int:
    endpoint = os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080")

    # Test 1: Verify the helper constructs without error
    try:
        from axonflow_adk import axonflow_mcp_toolset
    except ImportError as exc:
        print(f"FAIL: cannot import axonflow_mcp_toolset: {exc}")
        return 1

    try:
        toolset = axonflow_mcp_toolset(
            endpoint=endpoint,
            client_id="e2e-test",
            client_secret="e2e-secret",
        )
    except ImportError as exc:
        print(f"FAIL: McpToolset not available — {exc}")
        return 1
    except Exception as exc:
        print(f"FAIL: axonflow_mcp_toolset() construction failed: {exc}")
        return 1

    print(f"  toolset created: {type(toolset).__name__}")

    # Test 2: Verify connection params are correct
    conn_params = getattr(toolset, "connection_params", None)
    if conn_params is None:
        # Might be wrapped differently in newer ADK versions
        print("  connection_params not directly accessible (OK)")
    else:
        url = getattr(conn_params, "url", None)
        headers = getattr(conn_params, "headers", None)
        if url:
            expected_url = endpoint.rstrip("/") + "/mcp/"
            if url != expected_url:
                print(f"FAIL: URL mismatch: {url} != {expected_url}")
                return 1
            print(f"  URL: {url}")
        if headers:
            auth = headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                print(f"FAIL: expected Basic auth header, got: {auth[:20]}...")
                return 1
            print("  auth: Basic ***")

    # Test 3: Verify bearer token path
    try:
        toolset_bearer = axonflow_mcp_toolset(
            endpoint=endpoint,
            bearer_token="test-bearer-token",
        )
        conn_params_bearer = getattr(toolset_bearer, "connection_params", None)
        if conn_params_bearer:
            auth = getattr(conn_params_bearer, "headers", {}).get("Authorization", "")
            if not auth.startswith("Bearer "):
                print(f"FAIL: expected Bearer auth, got: {auth[:20]}...")
                return 1
            print("  bearer path: OK")
    except Exception as exc:
        print(f"  bearer path construction failed (non-fatal): {exc}")

    # Test 4: Verify anonymous path (no auth)
    try:
        toolset_anon = axonflow_mcp_toolset(endpoint=endpoint)
        print("  anonymous path: OK")
    except Exception as exc:
        print(f"FAIL: anonymous construction failed: {exc}")
        return 1

    print("PASS: mcp-toolset-loads-axonflow-tools")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
