# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify the no-answer posture when the AxonFlow stack is unreachable.

Points the plugin at a non-existent endpoint (port 19999) and runs the
agent through Runner.run_async. No answer arrives, so with the default
`fail_open=True` every governed hook (pre_check, check_tool_input,
check_tool_output) lets the call proceed UNGOVERNED and says so in a
WARNING notice, and the agent completes normally. After enough connection
failures the circuit breaker opens.

This test verifies:
  1. Agent completes despite AxonFlow being unreachable.
  2. Tool executes (fail_open=True proceeds on no answer).
  3. Circuit breaker opens after threshold connection failures.
  4. Every governed hook logged a WARNING notice that it ran ungoverned,
     including a call the open breaker skipped.
  5. With fail_open=False the same outage denies: the tool does not run,
     and the model call is denied with the no-answer reason.
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
from axonflow_adk.plugin import AxonFlowPluginConfig, _BreakerState
from _lib.stub_model import StubModel

TOOL_EXECUTED = False


class _Notices(logging.Handler):
    """Collects the plugin's WARNING records: the notices a user sees."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


NOTICES = _Notices()
logging.getLogger("axonflow_adk.plugin").addHandler(NOTICES)


def get_balance(account_id: str) -> dict:
    """Look up account balance."""
    global TOOL_EXECUTED
    TOOL_EXECUTED = True
    return {"balance": 42.0, "currency": "USD", "account_id": account_id}


async def main() -> int:
    global TOOL_EXECUTED

    # Point at a port where nothing is listening — simulates stack-down.
    unreachable_endpoint = "http://127.0.0.1:19999"

    plugin = AxonFlowPlugin(
        endpoint=unreachable_endpoint,
        client_id="e2e-test",
        client_secret="",
        config=AxonFlowPluginConfig(
            call_timeout_seconds=2.0,
            default_user_token="e2e-user",
            enable_hitl_polling=False,
            # Low threshold so breaker opens quickly
            breaker_failure_threshold=3,
            breaker_recovery_seconds=60.0,
        ),
    )

    model = StubModel(
        tool_name="get_balance",
        tool_args={"account_id": "ACC-BREAKER"},
        final_text="Balance retrieved despite AxonFlow being down.",
    )

    agent = LlmAgent(
        model=model,
        name="e2e_breaker_agent",
        instruction="You check balances. Call get_balance.",
        tools=[get_balance],
    )

    runner = InMemoryRunner(
        agent=agent,
        app_name="e2e_breaker_test",
        plugins=[plugin],
    )

    # Run the agent multiple times to trip the breaker.
    # Each run triggers pre_check + check_tool_input + check_tool_output +
    # audit_tool_call — all of which will fail and increment the counter.
    num_runs = 3
    for run_idx in range(1, num_runs + 1):
        model._call_count = 0
        TOOL_EXECUTED = False

        session = await runner.session_service.create_session(
            app_name="e2e_breaker_test",
            user_id="e2e-user",
        )

        events = []
        async for event in runner.run_async(
            user_id="e2e-user",
            session_id=session.id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=f"Check balance (breaker run {run_idx})")],
            ),
        ):
            events.append(event)

        if not events:
            print(f"FAIL: run {run_idx} produced no events (agent should complete even with AxonFlow down)")
            return 1

        # The tool SHOULD execute because the plugin fails-open
        if not TOOL_EXECUTED:
            print(f"FAIL: run {run_idx} did not execute tool (plugin should fail-open)")
            return 1

        print(f"  run {run_idx}/{num_runs}: OK — tool executed, agent completed ({len(events)} events)")

    # After 3 runs of connection failures the breaker must be open: only a
    # call that got no answer counts toward it, and every call here got none.
    breaker_state = plugin._breaker.state
    consecutive = plugin._breaker.consecutive_failures
    print(f"  breaker state: {breaker_state.value} (consecutive failures: {consecutive})")
    if breaker_state is not _BreakerState.OPEN:
        print(f"FAIL: breaker is {breaker_state.value} after {consecutive} connection failures (expected open)")
        return 1
    print("  breaker correctly opened after threshold failures")

    # Proceeding ungoverned is never silent: every governed hook logged a
    # WARNING notice naming itself, including the calls the open breaker
    # skipped.
    for op in ("pre_check", "check_tool_input", "check_tool_output"):
        if not any(f"AxonFlow {op} got no answer" in m and "UNGOVERNED" in m for m in NOTICES.messages):
            print(f"FAIL: no WARNING notice that {op} ran UNGOVERNED: {NOTICES.messages}")
            return 1
    if not any("circuit breaker open after repeated connection failures" in m for m in NOTICES.messages):
        print(f"FAIL: no WARNING notice for a call skipped by the open breaker: {NOTICES.messages}")
        return 1
    print(f"  {len(NOTICES.messages)} WARNING notice(s) logged, one per ungoverned call")
    await plugin.aclose()

    # The switch: the same outage with fail_open=False denies instead.
    TOOL_EXECUTED = False
    closed_plugin = AxonFlowPlugin(
        endpoint=unreachable_endpoint,
        client_id="e2e-test",
        client_secret="",
        config=AxonFlowPluginConfig(
            call_timeout_seconds=2.0,
            default_user_token="e2e-user",
            enable_hitl_polling=False,
            breaker_failure_threshold=3,
            breaker_recovery_seconds=60.0,
            fail_open=False,
        ),
    )
    closed_runner = InMemoryRunner(agent=agent, app_name="e2e_breaker_test", plugins=[closed_plugin])
    model._call_count = 0
    session = await closed_runner.session_service.create_session(app_name="e2e_breaker_test", user_id="e2e-user")
    texts: list[str] = []
    async for event in closed_runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message=genai_types.Content(role="user", parts=[genai_types.Part(text="Check balance (fail_open=False)")]),
    ):
        for part in getattr(getattr(event, "content", None), "parts", None) or []:
            if getattr(part, "text", None):
                texts.append(part.text)
    await closed_plugin.aclose()
    if TOOL_EXECUTED:
        print("FAIL: fail_open=False still executed the tool with AxonFlow down")
        return 1
    if not any(t.startswith("[AxonFlow policy denial] pre_check got no answer from AxonFlow (") for t in texts):
        print(f"FAIL: fail_open=False did not deny the model call with the no-answer reason: {texts}")
        return 1
    print("  fail_open=False: tool not executed, model call denied with the no-answer reason")

    print("PASS: breaker-opens-on-stack-down")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
