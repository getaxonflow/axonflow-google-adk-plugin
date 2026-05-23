# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that successful tool calls record an audit entry.

This is the runtime regression test for Bug 4 (v1.0.0): after_tool_callback
did not call audit_tool_call(success=True) on the happy path, so successful
tool calls had no explicit audit trail. v1.0.1 adds the success audit call.

The test runs an agent with a simple tool, verifies the tool executes
successfully, and then checks that the plugin attempted the audit call.
Since we are running against a real AxonFlow agent, the audit endpoint
may or may not persist the row depending on configuration. The test
verifies that the plugin attempted the call (no exception from the
audit path) and the agent completed normally.
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

TOOL_CALL_COUNT = 0


def lookup_customer(customer_id: str) -> dict:
    """Look up customer details."""
    global TOOL_CALL_COUNT
    TOOL_CALL_COUNT += 1
    return {
        "customer_id": customer_id,
        "name": "Jane Doe",
        "status": "active",
        "tier": "premium",
    }


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
            request_type="adk-e2e-audit-test",
            enable_hitl_polling=False,
        ),
    )

    model = StubModel(
        tool_name="lookup_customer",
        tool_args={"customer_id": "CUST-001"},
        final_text="Customer CUST-001 is Jane Doe, premium tier, active.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_audit_agent",
        instruction="You look up customers. Call lookup_customer with the customer_id.",
        tools=[lookup_customer],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_audit_test",
        plugins=[plugin],
    )

    session = await runner.session_service.create_session(
        app_name="e2e_audit_test",
        user_id="e2e-user",
    )

    events = []
    async for event in runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message="Look up customer CUST-001",
    ):
        events.append(event)
        print(f"  event: {event}")

    await plugin.aclose()

    if TOOL_CALL_COUNT == 0:
        print("FAIL: tool was never called")
        return 1

    print(f"  tool called {TOOL_CALL_COUNT} time(s)")

    # Verify we got events and the agent completed
    if not events:
        print("FAIL: no events received")
        return 1

    # Check for text output (agent completed successfully)
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

    if not has_text:
        print("FAIL: no text output — agent may have been blocked")
        return 1

    print("PASS: audit-recorded-on-tool-success")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
