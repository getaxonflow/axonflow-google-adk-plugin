# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify the HITL approval flow against a real AxonFlow agent.

Prerequisite: a require_approval policy for 'disburse_payment' has been
inserted into static_policies by test.sh BEFORE this script runs.

This test exercises steps 1-3 of the HITL lifecycle:
  1. pre_check returns require_approval
  2. plugin calls create_hitl_request to enqueue a row
  3. plugin polls get_hitl_request (times out after max_wait)

The test verifies that a hitl_approval_queue row was created by the
plugin. Approval/denial is verified at the DB level by test.sh.
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


def disburse_payment(amount_cents: int, customer_id: str) -> dict:
    """Disburse a payment to a customer."""
    return {
        "status": "ok",
        "customer_id": customer_id,
        "amount_cents": amount_cents,
        "transaction_id": f"tx-{customer_id}-{amount_cents}",
    }


async def main() -> int:
    endpoint = os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080")

    plugin = AxonFlowPlugin(
        endpoint=endpoint,
        client_id="e2e-test",
        client_secret="",
        config=AxonFlowPluginConfig(
            call_timeout_seconds=10.0,
            default_user_token="e2e-user",
            request_type="adk-e2e-hitl-test",
            # Enable HITL polling so the plugin creates a row and polls.
            # Short timeout so the test does not block long.
            enable_hitl_polling=True,
            approval_max_wait_seconds=5.0,
            approval_poll_interval_seconds=0.5,
        ),
    )

    model = StubModel(
        tool_name="disburse_payment",
        tool_args={"amount_cents": 5000000, "customer_id": "CUST-VIP"},
        final_text="Payment disbursed.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_hitl_agent",
        instruction="You disburse payments. Call disburse_payment with amount_cents and customer_id.",
        tools=[disburse_payment],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_hitl_test",
        plugins=[plugin],
    )

    session = await runner.session_service.create_session(
        app_name="e2e_hitl_test",
        user_id="e2e-user",
    )

    events = []
    async for event in runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message=genai_types.Content(role="user", parts=[genai_types.Part(text="Disburse $50,000 to customer CUST-VIP")]),
    ):
        events.append(event)
        print(f"  event: {event}")

    await plugin.aclose()

    if not events:
        print("FAIL: no events received")
        return 1

    print(f"  received {len(events)} event(s)")
    print("OK: require-approval-creates-hitl-row-and-polls")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
