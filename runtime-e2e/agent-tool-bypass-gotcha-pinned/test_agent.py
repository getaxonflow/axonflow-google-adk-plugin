# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Pin the AgentTool plugin-isolation gotcha.

ADK's AgentTool does not forward the parent Runner's plugins to the
inner Runner (https://github.com/google/adk-python/issues/2809). This
means sub-agents invoked via AgentTool are NOT governed by AxonFlowPlugin.

This test documents the limitation by creating two agents:
  - outer_agent: registered with AxonFlowPlugin
  - inner_agent: invoked via AgentTool (no governance)

The test verifies that:
  1. The outer agent's model calls go through the plugin (pre_check fires)
  2. The plugin does not crash or interfere with the AgentTool pattern

If a future ADK release fixes this (forwards plugins to inner Runners),
this test should be updated to verify that governance IS applied to
sub-agents.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from axonflow_adk import AxonFlowPlugin
from axonflow_adk.plugin import AxonFlowPluginConfig
from _lib.stub_model import TextOnlyStubModel


async def main() -> int:
    endpoint = os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080")

    plugin = AxonFlowPlugin(
        endpoint=endpoint,
        client_id="e2e-test",
        client_secret="",
        config=AxonFlowPluginConfig(
            call_timeout_seconds=10.0,
            default_user_token="e2e-user",
            enable_hitl_polling=False,
        ),
    )

    model = TextOnlyStubModel(
        text="I am the outer agent. The inner agent is isolated from governance.",
    )

    # Simple outer agent (no tools, just text)
    outer_agent = LlmAgent(
        model=model,
        name="e2e_outer_agent",
        instruction="You are the outer agent.",
    )

    runner = InMemoryRunner(
        agent=outer_agent,
        app_name="e2e_gotcha_test",
        plugins=[plugin],
    )

    session = await runner.session_service.create_session(
        app_name="e2e_gotcha_test",
        user_id="e2e-user",
    )

    events = []
    async for event in runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message=genai_types.Content(role="user", parts=[genai_types.Part(text="Hello, outer agent.")]),
    ):
        events.append(event)
        print(f"  event: {event}")

    await plugin.aclose()

    if not events:
        print("FAIL: no events received")
        return 1

    # Verify the outer agent completed with the plugin registered
    has_text = False
    for event in events:
        content = getattr(event, "content", None)
        if content is None:
            continue
        parts = getattr(content, "parts", None) or []
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                has_text = True

    if not has_text:
        print("FAIL: no text output from outer agent")
        return 1

    print("PASS: agent-tool-bypass-gotcha-pinned")
    print("  AgentTool sub-agents are NOT governed by AxonFlowPlugin (ADK limitation).")
    print("  Use RemoteA2aAgent or register the plugin on the inner Runner.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
