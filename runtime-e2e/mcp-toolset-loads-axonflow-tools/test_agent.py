# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that axonflow_mcp_toolset() integrates into a real Runner.

This test constructs an MCP toolset via `axonflow_mcp_toolset()` and
registers it as a tool on an LlmAgent, then runs that agent through
`Runner.run_async(...)` with `AxonFlowPlugin`.

The community stack may not have MCP connectors configured, so the
toolset's MCP connection may fail at runtime. The test verifies:

  1. `axonflow_mcp_toolset()` constructs without error.
  2. The toolset integrates into an LlmAgent without import issues.
  3. Runner.run_async completes (the plugin fails-open if MCP is down).
  4. The agent produces events (even if the MCP tools are unavailable).

This replaces the construction-only test that never called Runner.run_async.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from axonflow_adk import AxonFlowPlugin, axonflow_mcp_toolset
from axonflow_adk.plugin import AxonFlowPluginConfig
from _lib.stub_model import TextOnlyStubModel


def _connection_params(toolset: object) -> object:
    """The params the REAL toolset holds.

    ADK's `McpToolset` stores them as `_connection_params` (2.0.0 and 2.8.0
    alike). The earlier read of a public `connection_params` returned None on
    the real class, so the URL and auth assertions below never ran. Neither
    attribute present is a FAIL, not a skip.
    """
    for attr in ("_connection_params", "connection_params"):
        params = getattr(toolset, attr, None)
        if params is not None:
            return params
    raise AssertionError("toolset exposes neither _connection_params nor connection_params")


async def main() -> int:
    endpoint = os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080")

    # Step 1: construct the MCP toolset
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

    print(f"  toolset created: {type(toolset).__module__}.{type(toolset).__name__}")

    # Step 2: verify connection params
    try:
        conn_params = _connection_params(toolset)
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        return 1
    url = getattr(conn_params, "url", None)
    expected_url = endpoint.rstrip("/") + "/mcp/"
    if url != expected_url:
        print(f"FAIL: URL mismatch: {url} != {expected_url}")
        return 1
    print(f"  URL: {url}")
    headers = getattr(conn_params, "headers", None) or {}
    auth = headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        print(f"FAIL: expected Basic auth header, got: {auth[:20]}...")
        return 1
    print("  auth: Basic ***")

    # Step 3: create agent with toolset and run through Runner.run_async.
    # Use TextOnlyStubModel since we don't know what MCP tools are available
    # and can't issue a targeted tool call.
    plugin = AxonFlowPlugin(
        endpoint=endpoint,
        client_id="e2e-test",
        client_secret="",
        config=AxonFlowPluginConfig(
            call_timeout_seconds=10.0,
            default_user_token="e2e-user",
            enable_hitl_polling=False,
            breaker_failure_threshold=50,
        ),
    )

    model = TextOnlyStubModel(text="I can see the AxonFlow MCP tools.")

    agent = LlmAgent(
        model=model,
        name="e2e_mcp_agent",
        instruction="You have access to AxonFlow MCP tools.",
        tools=[toolset],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_mcp_toolset_test",
        plugins=[plugin],
    )

    session = await runner.session_service.create_session(
        app_name="e2e_mcp_toolset_test",
        user_id="e2e-user",
    )

    events = []
    async for event in runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message=genai_types.Content(
            role="user",
            parts=[genai_types.Part(text="What tools do you have?")],
        ),
    ):
        events.append(event)
        print(f"  event: {event}")

    await plugin.aclose()

    if not events:
        print("FAIL: no events received from runner")
        return 1

    # Verify text output exists (agent completed)
    has_text = False
    for event in events:
        content = getattr(event, "content", None)
        if content is None:
            continue
        parts = getattr(content, "parts", None) or []
        for part in parts:
            text = getattr(part, "text", None)
            if text and len(text) > 0:
                has_text = True
                print(f"  model output: {text[:200]}")

    if not has_text:
        print("FAIL: no text output from model")
        return 1

    # Step 4: verify bearer token path constructs correctly
    try:
        toolset_bearer = axonflow_mcp_toolset(
            endpoint=endpoint,
            bearer_token="test-bearer-token",
        )
        cp = _connection_params(toolset_bearer)
        auth = (getattr(cp, "headers", None) or {}).get("Authorization", "")
        if not auth.startswith("Bearer "):
            print(f"FAIL: expected Bearer auth, got: {auth[:20]}...")
            return 1
        print("  bearer path: OK")
    except Exception as exc:
        print(f"FAIL: bearer path construction failed: {exc}")
        return 1

    # Step 5: verify anonymous path
    try:
        axonflow_mcp_toolset(endpoint=endpoint)
        print("  anonymous path: OK")
    except Exception as exc:
        print(f"FAIL: anonymous construction failed: {exc}")
        return 1

    print("PASS: mcp-toolset-loads-axonflow-tools")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
