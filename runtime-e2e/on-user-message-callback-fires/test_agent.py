# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify on_user_message_callback fires without breaking multi-turn agents.

The plugin's on_user_message_callback is a no-op (returns None), which
means the user message passes through unmodified. This test verifies
that the no-op callback does not interfere with a multi-turn
conversation through Runner.run_async.

The test sends 3 sequential messages to the same session, each
triggering a tool call. This exercises:
  1. The on_user_message_callback fires on each turn (no crash).
  2. The before_model_callback + tool callbacks fire each turn.
  3. Session state persists across turns (same session_id).
  4. Audit rows accumulate from all turns.
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

TOOL_CALL_COUNT = 0


def get_balance(account_id: str) -> dict:
    """Look up account balance."""
    global TOOL_CALL_COUNT
    TOOL_CALL_COUNT += 1
    return {"balance": 1000.0 * TOOL_CALL_COUNT, "currency": "USD", "account_id": account_id}


async def main() -> int:
    global TOOL_CALL_COUNT
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
        tool_name="get_balance",
        tool_args={"account_id": "ACC-MULTI"},
        final_text="Balance checked.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_multiturn_agent",
        instruction="You check balances. Call get_balance with the account_id.",
        tools=[get_balance],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_multiturn_test",
        plugins=[plugin],
    )

    # Create a single session for multi-turn conversation
    session = await runner.session_service.create_session(
        app_name="e2e_multiturn_test",
        user_id="e2e-user",
    )

    messages = [
        "Check balance for ACC-MULTI (turn 1)",
        "Check again (turn 2)",
        "One more time (turn 3)",
    ]

    total_events = 0
    for turn, msg in enumerate(messages, 1):
        # Reset model call counter for each turn
        model._call_count = 0

        events = []
        async for event in runner.run_async(
            user_id="e2e-user",
            session_id=session.id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=msg)],
            ),
        ):
            events.append(event)

        if not events:
            print(f"FAIL: turn {turn} produced no events")
            return 1

        total_events += len(events)
        print(f"  turn {turn}: {len(events)} events")

    # Verify the tool was called across all turns
    if TOOL_CALL_COUNT < len(messages):
        print(f"FAIL: tool called {TOOL_CALL_COUNT} times (expected >= {len(messages)})")
        return 1
    print(f"  tool called {TOOL_CALL_COUNT} time(s) across {len(messages)} turns")
    print(f"  total events: {total_events}")

    await plugin.aclose()
    print("PASS: on-user-message-callback-fires")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
