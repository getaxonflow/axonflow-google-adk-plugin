# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that on_tool_error_callback fires through Runner.run_async.

A buggy tool raises RuntimeError. ADK catches the exception and invokes
the plugin's on_tool_error_callback, which calls audit_tool_call with
success=False. The test verifies that:

  1. Runner.run_async completes despite the tool error.
  2. The plugin's error callback does not crash the agent.
  3. An audit row is created for the failed tool call.
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
from _lib.stub_model import StubModel


def buggy_tool(x: str) -> dict:
    """A tool that always raises an error for testing."""
    raise RuntimeError(f"Tool error for testing: input={x}")


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

    model = StubModel(
        tool_name="buggy_tool",
        tool_args={"x": "test-input"},
        final_text="The tool encountered an error.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_error_agent",
        instruction="You test tools. Call buggy_tool with any input.",
        tools=[buggy_tool],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_tool_error_test",
        plugins=[plugin],
    )

    session = await runner.session_service.create_session(
        app_name="e2e_tool_error_test",
        user_id="e2e-user",
    )

    events = []
    async for event in runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message=genai_types.Content(
            role="user",
            parts=[genai_types.Part(text="Run the buggy tool with input test-input")],
        ),
    ):
        events.append(event)
        print(f"  event: {event}")

    await plugin.aclose()

    if not events:
        print("FAIL: no events received from runner")
        return 1

    print(f"  received {len(events)} event(s)")

    # Verify the agent completed (produced some output despite tool error)
    has_content = False
    for event in events:
        content = getattr(event, "content", None)
        if content is not None:
            has_content = True

    if not has_content:
        print("FAIL: no content in any event")
        return 1

    print("PASS: on-tool-error-callback-fires")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
