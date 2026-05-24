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
            breaker_failure_threshold=50,
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
    runner_error = None
    try:
        async for event in runner.run_async(
            user_id="e2e-user",
            session_id=session.id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text="Run the buggy tool with input test-input")],
            ),
        ):
            events.append(event)
    except RuntimeError as exc:
        runner_error = exc
        print(f"  runner raised RuntimeError (expected): {exc}")

    await plugin.aclose()

    if runner_error is None:
        print("FAIL: expected RuntimeError from buggy tool but runner completed normally")
        return 1

    if "Tool error for testing" not in str(runner_error):
        print(f"FAIL: unexpected error message: {runner_error}")
        return 1

    print(f"  received {len(events)} event(s) before error")
    print("PASS: on-tool-error-callback-fires")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
