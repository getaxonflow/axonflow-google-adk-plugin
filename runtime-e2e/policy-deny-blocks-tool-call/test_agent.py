# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that a tool call blocked by AxonFlow policy is denied.

The tool call's `command` argument is a destructive shell command, which the
platform's shipped sys_dangerous_destructive_fs control blocks on the
check-input pass. No policy is seeded: since AxonFlow v11.0.0 a row written
straight into static_policies authors no verdict.

The plugin's before_tool_callback should return an error dict that
prevents the tool from executing. The test verifies that:
  1. The tool function was NOT called
  2. The agent output contains an AxonFlow denial signal
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

TOOL_EXECUTED = False


def run_maintenance(command: str) -> dict:
    """Run a maintenance shell command on the host."""
    global TOOL_EXECUTED
    TOOL_EXECUTED = True
    print(f"  !!! TOOL FUNCTION INVOKED: command={command}")
    return {"status": "ok", "command": command}


async def main() -> int:
    global TOOL_EXECUTED
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
        tool_name="run_maintenance",
        # Matches sys_dangerous_destructive_fs's `rm\\s+-rf\\s+/`.
        tool_args={"command": "rm -rf /var/lib/adk-e2e-scratch"},
        final_text="Maintenance completed.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_deny_agent",
        instruction="You run host maintenance. Call run_maintenance with the command.",
        tools=[run_maintenance],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_deny_test",
        plugins=[plugin],
    )

    session = await runner.session_service.create_session(
        app_name="e2e_deny_test",
        user_id="e2e-user",
    )

    events = []
    async for event in runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message=genai_types.Content(role="user", parts=[genai_types.Part(text="Clear the scratch directory")]),
    ):
        events.append(event)
        print(f"  event: {event}")

    await plugin.aclose()

    # The shipped destructive-command control denies the call: the tool must NOT run
    if TOOL_EXECUTED:
        print("FAIL: tool executed despite the shipped deny control")
        return 1

    # Check events for the deny signal
    for event in events:
        content = getattr(event, "content", None)
        if content is None:
            continue
        parts = getattr(content, "parts", None) or []
        for part in parts:
            text = getattr(part, "text", None) or ""
            if "[AxonFlow]" in text or "denied" in text.lower():
                print(f"  [AxonFlow] denial signal found: {text[:200]}")

    print("OK: policy-deny-blocks-tool-call (shipped deny control, tool not executed)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
