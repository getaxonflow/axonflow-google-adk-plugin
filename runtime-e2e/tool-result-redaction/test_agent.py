# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify that a tool result reaches the model with the platform's redaction
applied, and that the tool-call audit's user id is never the user token.

Runs a real ADK InMemoryRunner with AxonFlowPlugin against a live AxonFlow
stack. A tool returns a customer record with an email address and a card
number; the platform's output check answers `allowed: true` with the masked
record. The stub model records the function_response it receives on its
second call, which is exactly what ADK hands the model.

A pass-through proxy around the SDK client (the SDK's client does not accept
attribute assignment) forwards every call to the real client unchanged and
notes the audit request's `user_id` on the way through.

Two states run in one invocation: `default` (no capability handshake) and
`handshake` (AXONFLOW_PEP_AUDIENCE set, so the response path declares
field_redact@1). Each assertion prints PASS or FAIL with its name, so two
runs of this leg (one per plugin version) compare line by line.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, AsyncGenerator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from axonflow_adk import AxonFlowPlugin
from axonflow_adk.plugin import AxonFlowPluginConfig

EMAIL = "jane.doe@example.com"
CARD = "4111 1111 1111 1111"
RECORD = f"Customer c-100: name Jane Doe, email {EMAIL}, card {CARD}, tier gold"
ADK_USER = "w3y-e2e-user"
CANARY_TOKEN = "w3y-canary-user-token"

TOOL_CALLS = 0


def lookup_customer_record(customer_id: str) -> dict:
    """Look up a customer's record."""
    global TOOL_CALLS
    TOOL_CALLS += 1
    return {"record": RECORD}


class AuditRecorder:
    """A pass-through proxy around the real SDK client.

    Every attribute and call is forwarded to the real client, so every request
    still reaches the platform; `audit_tool_call` also notes the request's
    `user_id` before forwarding it.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.user_ids: list[Any] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def audit_tool_call(self, *args: Any, **kwargs: Any) -> Any:
        request = kwargs.get("request", args[0] if args else None)
        self.user_ids.append(getattr(request, "user_id", None))
        return await self._inner.audit_tool_call(*args, **kwargs)


class RecordingModel(BaseLlm):
    """Calls the tool once, then records the function_response it is given."""

    _calls: int = 0
    _received: list[Any] = []

    def __init__(self) -> None:
        super().__init__(model="recording-stub-model")
        self._calls = 0
        self._received = []

    async def generate_content_async(
        self, llm_request: Any = None, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self._calls += 1
        if self._calls == 1:
            yield LlmResponse(
                content=genai_types.Content(
                    role="model",
                    parts=[
                        genai_types.Part(
                            function_call=genai_types.FunctionCall(
                                name="lookup_customer_record", args={"customer_id": "c-100"}
                            )
                        )
                    ],
                )
            )
            return
        for content in getattr(llm_request, "contents", None) or []:
            for part in getattr(content, "parts", None) or []:
                fr = getattr(part, "function_response", None)
                if fr is not None:
                    self._received.append(fr.response)
        yield LlmResponse(
            content=genai_types.Content(role="model", parts=[genai_types.Part(text="Done.")])
        )


async def run_state(state: str) -> int:
    global TOOL_CALLS
    TOOL_CALLS = 0
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"{'PASS' if ok else 'FAIL'}: [{state}] {name}" + (f": {detail}" if detail else ""))
        if not ok:
            failures += 1

    plugin = AxonFlowPlugin(
        endpoint=os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080"),
        client_id=os.environ.get("AXONFLOW_E2E_CLIENT_ID", "w3y-e2e"),
        client_secret=os.environ.get("AXONFLOW_E2E_CLIENT_SECRET", ""),
        config=AxonFlowPluginConfig(
            call_timeout_seconds=10.0,
            request_type="adk-e2e-tool-result-redaction",
            enable_hitl_polling=False,
            breaker_failure_threshold=50,
            pep_audience="w3y-e2e-audience" if state == "handshake" else None,
        ),
    )

    # The pass-through proxy becomes the plugin's client; the real client
    # still sends every request to the platform.
    recorder = AuditRecorder(await plugin._get_client())
    plugin._client = recorder
    audit_user_ids = recorder.user_ids

    model = RecordingModel()
    agent = LlmAgent(
        model=model,
        name="w3y_redaction_agent",
        instruction="Look up customer records with lookup_customer_record.",
        tools=[lookup_customer_record],
    )
    runner = InMemoryRunner(agent=agent, app_name="w3y_redaction", plugins=[plugin])
    session = await runner.session_service.create_session(
        app_name="w3y_redaction", user_id=ADK_USER, state={"axonflow_user_token": CANARY_TOKEN}
    )
    async for _ in runner.run_async(
        user_id=ADK_USER,
        session_id=session.id,
        new_message=genai_types.Content(role="user", parts=[genai_types.Part(text="Look up c-100")]),
    ):
        pass
    await plugin.aclose()

    received = json.dumps(model._received, default=str)
    print(f"OBSERVED: [{state}] the model received: {received[:400]}")
    print(f"OBSERVED: [{state}] the tool-call audit user_id values: {audit_user_ids}")

    check("the tool ran", TOOL_CALLS >= 1, f"{TOOL_CALLS} call(s)")
    check("the model received the tool result", bool(model._received))
    check(
        "the model's input carries no raw email or card number",
        bool(model._received) and EMAIL not in received and CARD not in received and CARD.replace(" ", "") not in received,
    )
    check(
        "the model's input is the platform's masked result",
        any(isinstance(r, dict) and r.get("_axonflow_redacted") is True for r in model._received),
    )
    check(
        "the tool-call audit's user_id is the ADK user, not the user token",
        bool(audit_user_ids) and all(u == ADK_USER for u in audit_user_ids) and CANARY_TOKEN not in audit_user_ids,
        f"{audit_user_ids}",
    )
    return failures


async def main() -> int:
    failures = 0
    for state in ("default", "handshake"):
        failures += await run_state(state)
    print(f"=== tool-result-redaction: {'PASS' if failures == 0 else 'FAIL'} ({failures} failed) ===")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
