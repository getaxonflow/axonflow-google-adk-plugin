# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that HITL polling holds nothing on an allowed call against a v11 platform.

`enable_hitl_polling=True` is on. From AxonFlow v11.0.0 the platform never
holds a call on the planes this plugin drives: an approval-requiring call is
refused with a `block_reason` beginning `approval_required:`, which the plugin
denies without a hold (proven through the stub channel in
platform-error-posture, scenario D). None of the platform's shipped controls
gives an approval verdict for this tool call, so it is allowed.

This test verifies, through Runner.run_async against the live stack:
  1. The tool runs: the call is allowed and nothing holds it.
  2. The plugin never entered the hold: no "AWAITING APPROVAL" log line.
  3. No HITL row was written for this suite's client id (asserted in test.sh
     against hitl_approval_queue).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from axonflow_adk import AxonFlowPlugin
from axonflow_adk.plugin import AxonFlowPluginConfig
from _lib.stub_model import StubModel

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

# The client id a HITL row would carry (`_effective_client_id`); test.sh asserts
# no row exists for it. Unique to this suite, so another suite's rows cannot
# satisfy or break the assertion.
CLIENT_ID = "e2e-hitl-polling"

TOOL_EXECUTED = False


class _PluginLog(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


PLUGIN_LOG = _PluginLog()
logging.getLogger("axonflow_adk.plugin").addHandler(PLUGIN_LOG)


def disburse_funds(amount: int, destination: str) -> dict:
    """Disburse funds to a destination account."""
    global TOOL_EXECUTED
    TOOL_EXECUTED = True
    return {
        "status": "ok",
        "amount": amount,
        "destination": destination,
        "transaction_id": f"tx-{destination}-{amount}",
    }


async def main() -> int:
    endpoint = os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080")

    plugin = AxonFlowPlugin(
        endpoint=endpoint,
        client_id=CLIENT_ID,
        client_secret="",
        config=AxonFlowPluginConfig(
            call_timeout_seconds=10.0,
            default_user_token="e2e-user",
            enable_hitl_polling=True,
            approval_max_wait_seconds=3.0,
            approval_poll_interval_seconds=1.0,
            breaker_failure_threshold=50,
        ),
    )

    model = StubModel(
        tool_name="disburse_funds",
        tool_args={"amount": 50000, "destination": "ACCT-VIP"},
        final_text="Disbursement complete.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_hitl_agent",
        instruction="You disburse funds. Call disburse_funds with amount and destination.",
        tools=[disburse_funds],
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
        new_message=genai_types.Content(
            role="user",
            parts=[genai_types.Part(text="Disburse $50,000 to ACCT-VIP")],
        ),
    ):
        events.append(event)

    await plugin.aclose()

    if not events:
        print("FAIL: no events received from runner")
        return 1
    print(f"  received {len(events)} event(s)")

    if not TOOL_EXECUTED:
        print("FAIL: the allowed tool call did not run")
        return 1
    print("  tool executed: the call was allowed and nothing held it")

    held = [m for m in PLUGIN_LOG.messages if "AWAITING APPROVAL" in m]
    if held:
        print(f"FAIL: the plugin entered the HITL hold on a v11 platform: {held}")
        return 1
    print("  no AWAITING APPROVAL line: the hold was never entered")

    print("OK: hitl-polling-on-allowed-call-writes-no-hitl-row")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
