# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that 5 sequential Runner.run_async calls complete with breaker closed.

Reuses the same Runner and AxonFlowPlugin instance across 5 sequential
invocations. Each run triggers a tool call (get_balance), exercising the
full pre_check + check_tool_input + check_tool_output + audit cycle.

The test verifies that:
  1. All 5 runs complete successfully.
  2. The circuit breaker stays closed (no spurious failures).
  3. The plugin handles repeated use without state leakage.
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
from axonflow_adk.plugin import AxonFlowPluginConfig, _BreakerState
from _lib.stub_model import StubModel

TOOL_CALL_COUNT = 0


def get_balance(account_id: str) -> dict:
    """Look up account balance."""
    global TOOL_CALL_COUNT
    TOOL_CALL_COUNT += 1
    return {"balance": 1000.0 + TOOL_CALL_COUNT, "currency": "USD", "account_id": account_id}


async def main() -> int:
    global TOOL_CALL_COUNT
    endpoint = os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080")
    num_runs = 5

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
        tool_name="get_balance",
        tool_args={"account_id": "ACC-SEQ"},
        final_text="Balance retrieved.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_sequential_agent",
        instruction="You check balances. Call get_balance.",
        tools=[get_balance],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_sequential_test",
        plugins=[plugin],
    )

    for run_idx in range(1, num_runs + 1):
        # Reset the stub model's call counter for each run so it
        # produces the tool-call -> text sequence again.
        model._call_count = 0

        session = await runner.session_service.create_session(
            app_name="e2e_sequential_test",
            user_id="e2e-user",
        )

        events = []
        async for event in runner.run_async(
            user_id="e2e-user",
            session_id=session.id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=f"Check balance (run {run_idx})")],
            ),
        ):
            events.append(event)

        if not events:
            print(f"FAIL: run {run_idx}/{num_runs} produced no events")
            return 1

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
            print(f"FAIL: run {run_idx}/{num_runs} produced no text output")
            return 1

        print(f"  run {run_idx}/{num_runs}: OK ({len(events)} events)")

    # Verify breaker is still closed
    breaker_state = plugin._breaker.state
    if breaker_state is not _BreakerState.CLOSED:
        print(f"FAIL: circuit breaker state is {breaker_state.value} (expected closed)")
        return 1
    print(f"  circuit breaker: {breaker_state.value}")

    # Verify the tool was actually called across all runs
    if TOOL_CALL_COUNT < num_runs:
        print(f"FAIL: tool called {TOOL_CALL_COUNT} times (expected >= {num_runs})")
        return 1
    print(f"  tool called {TOOL_CALL_COUNT} time(s) across {num_runs} runs")

    await plugin.aclose()
    print("PASS: sequential-runs-breaker-stable")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
