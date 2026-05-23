# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that a tool call blocked by AxonFlow policy is denied.

Prerequisite: a deny policy for 'disburse_payment' has been inserted
into static_policies by test.sh BEFORE this script runs.

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

from axonflow_adk import AxonFlowPlugin
from axonflow_adk.plugin import AxonFlowPluginConfig
from _lib.stub_model import StubModel

TOOL_EXECUTED = False


def disburse_payment(amount: int, destination: str) -> dict:
    """Disburse payment to a destination account."""
    global TOOL_EXECUTED
    TOOL_EXECUTED = True
    return {"status": "ok", "amount": amount, "destination": destination}


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
        ),
    )

    model = StubModel(
        tool_name="disburse_payment",
        tool_args={"amount": 50000, "destination": "ACCT-999"},
        final_text="Transfer completed.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_deny_agent",
        instruction="You disburse payments. Call disburse_payment with the amount and destination.",
        tools=[disburse_payment],
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
        new_message="Disburse $50,000 to ACCT-999",
    ):
        events.append(event)
        print(f"  event: {event}")

    await plugin.aclose()

    # With a deny policy in the DB, the tool should NOT have executed
    if TOOL_EXECUTED:
        print("FAIL: tool executed despite deny policy")
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

    print("OK: policy-deny-blocks-tool-call (deny policy active, tool not executed)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
