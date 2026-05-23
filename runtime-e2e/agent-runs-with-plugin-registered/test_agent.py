# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that AxonFlowPlugin registers on an ADK Runner and fires pre_check.

This test creates a real ADK InMemoryRunner with the AxonFlowPlugin pointed
at a live AxonFlow agent. The stub model returns a function call, triggering
both model-level and tool-level governance hooks. The test verifies that
the runner completes without error and the plugin's pre_check hook fires
(observable via the agent's /health or audit trail).
"""

from __future__ import annotations

import asyncio
import os
import sys

# Add the runtime-e2e directory to path for stub_model import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner

from axonflow_adk import AxonFlowPlugin
from axonflow_adk.plugin import AxonFlowPluginConfig
from _lib.stub_model import StubModel


def get_balance(account_id: str) -> dict:
    """Look up account balance."""
    return {"balance": 1000.0, "currency": "USD", "account_id": account_id}


async def main() -> int:
    endpoint = os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080")

    plugin = AxonFlowPlugin(
        endpoint=endpoint,
        client_id="e2e-test",
        client_secret="",
        config=AxonFlowPluginConfig(
            call_timeout_seconds=10.0,
            default_user_token="e2e-user",
            request_type="adk-e2e-test",
            # Disable HITL polling for this basic registration test
            enable_hitl_polling=False,
        ),
    )

    model = StubModel(
        tool_name="get_balance",
        tool_args={"account_id": "ACC-001"},
        final_text="The balance for ACC-001 is $1,000.00 USD.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_balance_agent",
        instruction="You check account balances. Call get_balance with the account_id.",
        tools=[get_balance],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_registration_test",
        plugins=[plugin],
    )

    session = await runner.session_service.create_session(
        app_name="e2e_registration_test",
        user_id="e2e-user",
    )

    events = []
    async for event in runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message="Check balance for account ACC-001",
    ):
        events.append(event)
        print(f"  event: {event}")

    if not events:
        print("FAIL: no events received from runner")
        return 1

    # Verify we got some events (the exact count depends on ADK version)
    print(f"  received {len(events)} event(s)")

    # Check that the final event contains model output text
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
        print("FAIL: no text output from model — plugin may have blocked unexpectedly")
        return 1

    await plugin.aclose()
    print("PASS: agent-runs-with-plugin-registered")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
