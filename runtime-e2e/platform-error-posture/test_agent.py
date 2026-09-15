# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify the plugin's failure posture through Runner.run_async, one platform answer at a time.

Channel: a local stub HTTP server stands in for the platform, in front of the
real axonflow SDK client, the real AxonFlowPlugin and a real google-adk
InMemoryRunner driven by the repo's StubModel. The runtime stack cannot be made
to give these answers on demand: a community agent answers 200 for a missing or
wrong credential, and nothing makes it answer a 429 or a 5xx. The live stack
proves the other legs (policy-deny-blocks-tool-call, breaker-opens-on-stack-down).

The stub answers each route on its own, so each governed hook's refusal is
proven in isolation:

  A. check-input answers a refusal -> the tool does NOT run, and the model
     receives the deny.
  B. check-output answers a refusal -> the tool ran, but the model receives the
     deny, never the original result.
  C. pre-check answers a refusal -> the model call is denied, and no tool is
     requested.
  D. check-input answers v11's approval_required refusal -> a deny; no HITL
     row is requested.
  E. nothing listens -> fail_open=True runs the tool with a WARNING notice per
     governed call; fail_open=False denies.
  F. check-input answers after the timeout -> the same split as E.
  G. check-input answers 401 for six runs with a breaker threshold of 1 ->
     every run denied, the breaker closed after each, and every run reaches
     the platform.

Refusals: 401, the platform's full Free-tier daily-quota 429, 500, 503, and a
502 with an HTML body. A-C run with fail_open True and False: an answer that
did not allow denies either way.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

from axonflow_adk import AxonFlowPlugin  # noqa: E402
from axonflow_adk.plugin import AxonFlowPluginConfig, _BreakerState  # noqa: E402
from _lib.stub_model import StubModel  # noqa: E402

PRE_CHECK = "/api/policy/pre-check"
CHECK_INPUT = "/api/v1/mcp/check-input"
CHECK_OUTPUT = "/api/v1/mcp/check-output"
HITL_QUEUE = "/api/v1/hitl/queue"

SECRET = "secret-original-tool-output-7f3a"
COMMAND = "rm -rf / --no-preserve-root"

QUOTA_429 = {
    "error": "Daily request limit reached. Resets at midnight UTC.",
    "limit_type": "daily_quota",
    "tier": "free",
    "limit": 500,
    "remaining": 0,
    "window": "daily_utc",
    "resets_at": "2026-09-16T00:00:00Z",
    "upgrade": {"tier": "Pro", "wording": "Upgrade to Pro.", "compare_url": "https://getaxonflow.com/pricing", "buy_url": "https://getaxonflow.com/pricing"},
}

# name -> (status, content type, body, text the tool-path deny carries, text the model-path deny carries)
REFUSALS: dict[str, tuple[int, str, str, str, str]] = {
    "401": (401, "application/json", json.dumps({"error": "Invalid credentials"}), "ConnectorError: Invalid credentials", "AuthenticationError: Invalid credentials"),
    "429": (429, "application/json", json.dumps(QUOTA_429), "ConnectorError: Daily request limit reached", 'AxonFlowError: HTTP 429: {"error": "Daily request limit reached'),
    "500": (500, "application/json", json.dumps({"error": "internal error"}), "ConnectorError: internal error", "AxonFlowError: HTTP 500"),
    "503": (503, "application/json", json.dumps({"error": "service unavailable"}), "ConnectorError: service unavailable", "AxonFlowError: HTTP 503"),
    "502-html": (502, "text/html", "<html><body>502 Bad Gateway</body></html>", "JSONDecodeError", "AxonFlowError: HTTP 502"),
}

APPROVAL_REFUSAL = (
    "approval_required: the policy engine requires an approval, and the mcp:request plane has no "
    "approval hold, so it is refused rather than held (PRD v11 §1.13)"
)

ALLOW: dict[str, tuple[int, str, str]] = {
    PRE_CHECK: (200, "application/json", json.dumps({"context_id": "ctx-stub", "approved": True, "expires_at": "2026-09-16T00:00:00Z", "policies": []})),
    CHECK_INPUT: (200, "application/json", json.dumps({"allowed": True, "policies_evaluated": 1})),
    CHECK_OUTPUT: (200, "application/json", json.dumps({"allowed": True, "policies_evaluated": 1})),
}


class Stub:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, str, str]] = {}
        self.delay: dict[str, float] = {}
        self.hits: list[str] = []

    def reset(self, **overrides: tuple[int, str, str]) -> None:
        self.routes = dict(ALLOW)
        self.routes.update(overrides)
        self.delay = {}
        self.hits = []


STUB = Stub()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        STUB.hits.append(self.path)
        if STUB.delay.get(self.path):
            time.sleep(STUB.delay[self.path])
        status, ctype, body = STUB.routes.get(self.path, (200, "application/json", "{}"))
        raw = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST  # noqa: N815

    def log_message(self, *args: Any) -> None:
        return


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


from _lib.notices import capture_plugin_log  # noqa: E402

# The plugin's WARNING records: the notices a user sees.
NOTICES = capture_plugin_log(logging.WARNING)

FAILURES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + ("" if ok else f" -- {detail}"))
    if not ok:
        FAILURES += 1


def dead_endpoint() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"


def new_plugin(endpoint: str, **config: Any) -> AxonFlowPlugin:
    cfg: dict[str, Any] = {"call_timeout_seconds": 2.0, "default_user_token": "e2e-user", "enable_hitl_polling": True, "breaker_failure_threshold": 50}
    cfg.update(config)
    return AxonFlowPlugin(endpoint=endpoint, client_id="e2e-stub", client_secret="e2e-secret", config=AxonFlowPluginConfig(**cfg))


async def run_once(plugin: AxonFlowPlugin, label: str) -> dict[str, Any]:
    """One user turn through the Runner. Returns what ran and what the model got."""
    executed: list[str] = []

    def run_maintenance(command: str) -> dict:
        """Run a maintenance shell command on the host."""
        executed.append(command)
        return {"status": "ok", "ran": command, "record": SECRET}

    model = StubModel(tool_name="run_maintenance", tool_args={"command": COMMAND}, final_text="maintenance done")
    agent = LlmAgent(model=model, name="e2e_posture_agent", instruction="Run maintenance.", tools=[run_maintenance])
    runner = InMemoryRunner(agent=agent, app_name="e2e_posture", plugins=[plugin])
    session = await runner.session_service.create_session(app_name="e2e_posture", user_id="e2e-user")
    tool_responses: list[str] = []
    texts: list[str] = []
    async for event in runner.run_async(
        user_id="e2e-user",
        session_id=session.id,
        new_message=genai_types.Content(role="user", parts=[genai_types.Part(text=f"clean the host ({label})")]),
    ):
        content = getattr(event, "content", None)
        for part in getattr(content, "parts", None) or []:
            fr = getattr(part, "function_response", None)
            if fr is not None:
                tool_responses.append(json.dumps(fr.response, default=str))
            if getattr(part, "text", None):
                texts.append(part.text)
    return {"executed": executed, "tool_responses": tool_responses, "texts": texts}


async def scenario_refusals(url: str) -> None:
    for name, (status, ctype, body, tool_text, model_text) in REFUSALS.items():
        for fail_open in (True, False):
            tag = f"{name} fail_open={fail_open}"

            STUB.reset(**{CHECK_INPUT: (status, ctype, body)})
            plugin = new_plugin(url, fail_open=fail_open)
            out = await run_once(plugin, f"A {tag}")
            await plugin.aclose()
            check(f"A [{tag}] check-input refusal: the tool did not run", not out["executed"], str(out))
            check(
                f"A [{tag}] the model received the check_tool_input deny with the platform's text",
                any("[AxonFlow] check_tool_input did not complete with an allow: " in r and tool_text in r for r in out["tool_responses"]),
                str(out["tool_responses"]),
            )

            STUB.reset(**{CHECK_OUTPUT: (status, ctype, body)})
            plugin = new_plugin(url, fail_open=fail_open)
            out = await run_once(plugin, f"B {tag}")
            await plugin.aclose()
            check(f"B [{tag}] check-output refusal: the tool ran (the output check follows it)", out["executed"] == [COMMAND], str(out))
            check(
                f"B [{tag}] the model received the check_tool_output deny, not the original result",
                any("[AxonFlow] check_tool_output did not complete with an allow: " in r and tool_text in r for r in out["tool_responses"])
                and not any(SECRET in r for r in out["tool_responses"]),
                str(out["tool_responses"]),
            )

            STUB.reset(**{PRE_CHECK: (status, ctype, body)})
            plugin = new_plugin(url, fail_open=fail_open)
            out = await run_once(plugin, f"C {tag}")
            await plugin.aclose()
            check(f"C [{tag}] pre-check refusal: no tool ran", not out["executed"], str(out))
            check(
                f"C [{tag}] the model call was denied with the platform's text",
                any(t.startswith("[AxonFlow policy denial] pre_check did not complete with an allow: ") and model_text in t for t in out["texts"]),
                str(out["texts"]),
            )
            check(f"C [{tag}] no tool check was sent", CHECK_INPUT not in STUB.hits, str(STUB.hits))


async def scenario_approval(url: str) -> None:
    STUB.reset(**{CHECK_INPUT: (403, "application/json", json.dumps({"allowed": False, "block_reason": APPROVAL_REFUSAL, "policies_evaluated": 1}))})
    plugin = new_plugin(url, enable_hitl_polling=True)
    out = await run_once(plugin, "D approval")
    await plugin.aclose()
    check("D approval_required refusal: the tool did not run", not out["executed"], str(out))
    check("D the model received the approval_required text verbatim", any(f"[AxonFlow] {APPROVAL_REFUSAL}" in json.loads(r).get("error", "") for r in out["tool_responses"]), str(out["tool_responses"]))
    check("D no HITL row was requested (refused, not held)", not any(h.startswith(HITL_QUEUE) for h in STUB.hits), str(STUB.hits))


async def scenario_no_answer() -> None:
    endpoint = dead_endpoint()
    NOTICES.messages.clear()
    plugin = new_plugin(endpoint, fail_open=True)
    out = await run_once(plugin, "E fail_open=True")
    await plugin.aclose()
    check("E [fail_open=True] nothing listening: the tool ran", out["executed"] == [COMMAND], str(out))
    for op in ("pre_check", "check_tool_input", "check_tool_output"):
        check(
            f"E [fail_open=True] a WARNING notice says {op} ran UNGOVERNED",
            any(f"AxonFlow {op} got no answer" in m and "UNGOVERNED" in m for m in NOTICES.messages),
            str(NOTICES.messages),
        )

    plugin = new_plugin(endpoint, fail_open=False)
    out = await run_once(plugin, "E fail_open=False")
    await plugin.aclose()
    check("E [fail_open=False] nothing listening: no tool ran", not out["executed"], str(out))
    check(
        "E [fail_open=False] the model call was denied: no answer and fail_open is False",
        any(t.startswith("[AxonFlow policy denial] pre_check got no answer from AxonFlow (") and t.endswith("and fail_open is False") for t in out["texts"]),
        str(out["texts"]),
    )


async def scenario_timeout(url: str) -> None:
    for fail_open in (True, False):
        STUB.reset()
        STUB.delay[CHECK_INPUT] = 1.5
        NOTICES.messages.clear()
        plugin = new_plugin(url, fail_open=fail_open, call_timeout_seconds=0.3)
        out = await run_once(plugin, f"F fail_open={fail_open}")
        await plugin.aclose()
        if fail_open:
            check("F [fail_open=True] check-input timed out: the tool ran", out["executed"] == [COMMAND], str(out))
            check(
                "F [fail_open=True] a WARNING notice names the timeout",
                any("AxonFlow check_tool_input got no answer (timed out after 0.3s)" in m and "UNGOVERNED" in m for m in NOTICES.messages),
                str(NOTICES.messages),
            )
        else:
            check("F [fail_open=False] check-input timed out: the tool did not run", not out["executed"], str(out))
            check(
                "F [fail_open=False] the model received the no-answer deny",
                any("[AxonFlow] check_tool_input got no answer from AxonFlow (timed out after 0.3s)" in r for r in out["tool_responses"]),
                str(out["tool_responses"]),
            )


async def scenario_refusals_never_open_the_breaker(url: str) -> None:
    # Threshold 1: through the Runner the allowed pre-check between refusals
    # resets the failure count, so only a threshold of 1 lets a refusal that
    # WRONGLY counted open the breaker. Opened, it would make the next run's
    # governed calls no-answer outcomes, and fail_open=True would run the tool.
    status, ctype, body, tool_text, _ = REFUSALS["401"]
    STUB.reset(**{CHECK_INPUT: (status, ctype, body)})
    plugin = new_plugin(url, fail_open=True, breaker_failure_threshold=1, breaker_recovery_seconds=60.0)
    for run in range(1, 7):
        out = await run_once(plugin, f"G run {run}")
        check(f"G 401 run {run}/6: the tool did not run", not out["executed"], str(out))
        check(f"G 401 run {run}/6: the model received the 401 deny", any(tool_text in r for r in out["tool_responses"]), str(out["tool_responses"]))
        check(f"G 401 run {run}/6: the breaker is CLOSED", plugin._breaker.state is _BreakerState.CLOSED, plugin._breaker.state.value)
    check("G all six runs reached check-input (the breaker never skipped the platform)", STUB.hits.count(CHECK_INPUT) == 6, str(STUB.hits))
    await plugin.aclose()


async def main() -> int:
    server = QuietServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        await scenario_refusals(url)
        await scenario_approval(url)
        await scenario_no_answer()
        await scenario_timeout(url)
        await scenario_refusals_never_open_the_breaker(url)
    finally:
        server.shutdown()
        server.server_close()
    print(f"=== platform-error-posture: {'PASS' if FAILURES == 0 else 'FAIL'} ({FAILURES} failed) ===")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
