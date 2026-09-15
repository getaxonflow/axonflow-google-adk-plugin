# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Real-SDK contract for the plugin's failure posture (issue #7).

The plugin's governed hooks run through the REAL ``axonflow`` SDK client
against a local stub HTTP server that answers each status the platform can
send. Nothing inside the SDK or the plugin is replaced. Which exception the SDK
raises for an answer is the SDK's own choice, and `_classify_failure` has to
read it correctly.

Why a stub server and not a monkeypatched exception: on the tool path the SDK
raises one untyped ``ConnectorError`` for a 401, a 429 and a 5xx alike, a
``json.JSONDecodeError`` for a non-JSON answer, and a raw ``httpx.ConnectError``
when nothing listens. A test that raised ``AuthenticationError`` into a hook
would pass against a wire that never produces one.

The posture under test, on all three governed hooks:
- an ANSWER that did not allow (401, 429, 5xx, a non-JSON answer) denies, with
  ``fail_open`` True or False;
- NO ANSWER (nothing listening, a timeout, the breaker open) proceeds with a
  WARNING notice when ``fail_open`` is True, and denies when it is False;
- a refusal never opens the breaker;
- an ``approval_required`` refusal is a deny, and no HITL row is requested.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import types
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

# The platform's Free-tier daily-quota 429 (platform/agent/
# community_saas_ratelimit_response.go writeRateLimitError), with every key it
# writes.
_QUOTA_429 = {
    "error": "Daily request limit reached. Resets at midnight UTC.",
    "limit_type": "daily_quota",
    "tier": "free",
    "limit": 500,
    "remaining": 0,
    "window": "daily_utc",
    "resets_at": "2026-09-16T00:00:00Z",
    "upgrade": {
        "tier": "Pro",
        "wording": "Upgrade to Pro for a higher daily limit.",
        "compare_url": "https://getaxonflow.com/pricing",
        "buy_url": "https://getaxonflow.com/pricing",
    },
}

# (status, content type, body, text the tool-path deny carries, text the
# model-path deny carries). The two texts differ because the SDK raises
# differently on the two paths: `ConnectorError(<body error>)` on the tool path,
# `AuthenticationError("Invalid credentials")` / `AxonFlowError("HTTP <n>: ...")`
# on pre_check.
_REFUSALS = {
    "401": (401, "application/json", json.dumps({"error": "Invalid credentials"}), "ConnectorError: Invalid credentials", "AuthenticationError: Invalid credentials"),
    "429": (429, "application/json", json.dumps(_QUOTA_429), "ConnectorError: Daily request limit reached", "AxonFlowError: HTTP 429"),
    "500": (500, "application/json", json.dumps({"error": "internal error"}), "ConnectorError: internal error", "AxonFlowError: HTTP 500"),
    "503": (503, "application/json", json.dumps({"error": "service unavailable"}), "ConnectorError: service unavailable", "AxonFlowError: HTTP 503"),
    "502-html": (502, "text/html", "<html><body>502 Bad Gateway</body></html>", "JSONDecodeError", "AxonFlowError: HTTP 502"),
}

_APPROVAL_REFUSAL = (
    "approval_required: the policy engine requires an approval, and the mcp:request plane has no "
    "approval hold, so it is refused rather than held (PRD v11 §1.13)"
)

_TOOL_RESULT = {"record": "secret-original-tool-output"}


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


class _Stub:
    """A platform stand-in: one configurable answer for every route, and a hit log."""

    def __init__(self) -> None:
        self.status = 200
        self.content_type = "application/json"
        self.body = "{}"
        self.delay_seconds = 0.0
        self.hits: list[str] = []
        self.url = ""

    def answer(self, status: int, content_type: str, body: str) -> None:
        self.status, self.content_type, self.body = status, content_type, body


@pytest.fixture
def stub() -> Iterator[_Stub]:
    state = _Stub()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server's name
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            state.hits.append(self.path)
            if state.delay_seconds:
                time.sleep(state.delay_seconds)
            raw = state.body.encode()
            self.send_response(state.status)
            self.send_header("Content-Type", state.content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST  # noqa: N815 - http.server's name

        def log_message(self, *args: Any) -> None:
            return

    server = _QuietServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


@pytest.fixture
def dead_endpoint() -> str:
    """An endpoint nothing listens on: bind a port, then release it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"


def _plugin(endpoint: str, **config: Any) -> Any:
    from axonflow_adk.plugin import AxonFlowPlugin, AxonFlowPluginConfig

    cfg = {"call_timeout_seconds": 2.0, "default_user_token": "wire-user", "breaker_failure_threshold": 50}
    cfg.update(config)
    return AxonFlowPlugin(endpoint=endpoint, client_id="wire", client_secret="wire-secret", config=AxonFlowPluginConfig(**cfg))


def _ctx() -> Any:
    return types.SimpleNamespace(state={}, user_id="", invocation_id="inv-wire", agent_name="wire_agent")


def _tool() -> Any:
    return types.SimpleNamespace(name="run_maintenance")


def _llm_request() -> Any:
    from google.genai.types import Content, Part

    return types.SimpleNamespace(contents=[Content(role="user", parts=[Part(text="clean the host")])], model="stub-model")


async def _before_tool(plugin: Any) -> Any:
    return await plugin.before_tool_callback(tool=_tool(), tool_args={"command": "rm -rf / --no-preserve-root"}, tool_context=_ctx())


async def _after_tool(plugin: Any) -> Any:
    return await plugin.after_tool_callback(tool=_tool(), tool_args={"command": "ls"}, tool_context=_ctx(), result=dict(_TOOL_RESULT))


async def _before_model(plugin: Any) -> Any:
    return await plugin.before_model_callback(callback_context=_ctx(), llm_request=_llm_request())


def _model_text(response: Any) -> str:
    return " ".join(p.text or "" for p in response.content.parts)


# ---------------------------------------------------------------------------
# An answer that did not allow: denied, whatever fail_open says
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fail_open", [True, False])
@pytest.mark.parametrize("answer", sorted(_REFUSALS))
async def test_check_tool_input_refusal_denies_the_tool_call(stub: _Stub, answer: str, fail_open: bool) -> None:
    status, ctype, body, tool_text, _ = _REFUSALS[answer]
    stub.answer(status, ctype, body)
    plugin = _plugin(stub.url, fail_open=fail_open)

    result = await _before_tool(plugin)

    assert isinstance(result, dict), f"a {answer} answer let the tool call run (hook returned {result!r})"
    assert result["error"].startswith("[AxonFlow] check_tool_input did not complete with an allow: "), result
    assert tool_text in result["error"], result
    assert stub.hits == ["/api/v1/mcp/check-input"]
    await plugin.aclose()


@pytest.mark.parametrize("fail_open", [True, False])
@pytest.mark.parametrize("answer", sorted(_REFUSALS))
async def test_check_tool_output_refusal_withholds_the_tool_result(stub: _Stub, answer: str, fail_open: bool) -> None:
    status, ctype, body, tool_text, _ = _REFUSALS[answer]
    stub.answer(status, ctype, body)
    plugin = _plugin(stub.url, fail_open=fail_open)

    result = await _after_tool(plugin)

    assert isinstance(result, dict) and "error" in result, f"a {answer} answer passed the original tool result to the model ({result!r})"
    assert result["error"].startswith("[AxonFlow] check_tool_output did not complete with an allow: "), result
    assert tool_text in result["error"], result
    assert _TOOL_RESULT["record"] not in json.dumps(result)
    await plugin.aclose()


@pytest.mark.parametrize("fail_open", [True, False])
@pytest.mark.parametrize("answer", sorted(_REFUSALS))
async def test_pre_check_refusal_denies_the_model_call(stub: _Stub, answer: str, fail_open: bool) -> None:
    status, ctype, body, _, model_text = _REFUSALS[answer]
    stub.answer(status, ctype, body)
    plugin = _plugin(stub.url, fail_open=fail_open)

    result = await _before_model(plugin)

    assert result is not None, f"a {answer} answer let the model call run"
    text = _model_text(result)
    assert text.startswith("[AxonFlow policy denial] pre_check did not complete with an allow: "), text
    assert model_text in text, text
    assert stub.hits == ["/api/policy/pre-check"]
    await plugin.aclose()


async def test_a_refusal_never_opens_the_breaker(stub: _Stub) -> None:
    """Five 401s against a breaker that opens after three failures: every call
    is denied, the breaker stays CLOSED, and the sixth call still reaches the
    platform and is still denied. An open breaker is a no-answer outcome, so a
    refusal that opened it would turn the platform's refusals into
    allow-with-notice."""
    from axonflow_adk.plugin import _BreakerState

    status, ctype, body, tool_text, _ = _REFUSALS["401"]
    stub.answer(status, ctype, body)
    plugin = _plugin(stub.url, breaker_failure_threshold=3, fail_open=True)

    for attempt in range(1, 6):
        result = await _before_tool(plugin)
        assert isinstance(result, dict) and tool_text in result["error"], f"401 number {attempt} was not denied: {result!r}"
    assert plugin._breaker.state is _BreakerState.CLOSED
    assert plugin._breaker.consecutive_failures == 0

    sixth = await _before_tool(plugin)
    assert isinstance(sixth, dict) and tool_text in sixth["error"], f"the sixth call after five 401s was not denied: {sixth!r}"
    assert len(stub.hits) == 6, "the breaker skipped the platform after refusals"
    await plugin.aclose()


# ---------------------------------------------------------------------------
# The platform's own deny, and the v11 approval refusal
# ---------------------------------------------------------------------------


async def test_approval_required_refusal_is_a_deny_and_requests_no_hitl_row(stub: _Stub) -> None:
    stub.answer(403, "application/json", json.dumps({"allowed": False, "block_reason": _APPROVAL_REFUSAL, "policies_evaluated": 1}))
    plugin = _plugin(stub.url, enable_hitl_polling=True)

    result = await _before_tool(plugin)

    assert result == {"error": f"[AxonFlow] {_APPROVAL_REFUSAL}"}
    assert stub.hits == ["/api/v1/mcp/check-input"], "the plugin tried to hold the call on a v11 refusal"
    await plugin.aclose()


async def test_an_allow_answer_lets_the_tool_call_run(stub: _Stub) -> None:
    """The stub's control: the same channel answering an allow proceeds."""
    stub.answer(200, "application/json", json.dumps({"allowed": True, "policies_evaluated": 1}))
    plugin = _plugin(stub.url, fail_open=False)

    assert await _before_tool(plugin) is None
    await plugin.aclose()


# ---------------------------------------------------------------------------
# No answer: fail_open decides, and proceeding is never silent
# ---------------------------------------------------------------------------


async def test_no_answer_proceeds_with_a_notice_when_fail_open(dead_endpoint: str, caplog: pytest.LogCaptureFixture) -> None:
    plugin = _plugin(dead_endpoint, fail_open=True)
    caplog.set_level(logging.WARNING, logger="axonflow_adk.plugin")

    assert await _before_tool(plugin) is None
    assert await _after_tool(plugin) is None
    assert await _before_model(plugin) is None

    notices = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and "UNGOVERNED" in r.getMessage()]
    for op in ("check_tool_input", "check_tool_output", "pre_check"):
        assert any(f"AxonFlow {op} got no answer" in n for n in notices), f"no UNGOVERNED notice for {op}: {notices}"
    await plugin.aclose()


async def test_no_answer_denies_when_fail_open_is_false(dead_endpoint: str) -> None:
    plugin = _plugin(dead_endpoint, fail_open=False)

    tool_in = await _before_tool(plugin)
    assert isinstance(tool_in, dict) and tool_in["error"].startswith("[AxonFlow] check_tool_input got no answer from AxonFlow ("), tool_in
    assert tool_in["error"].endswith("and fail_open is False"), tool_in

    tool_out = await _after_tool(plugin)
    assert isinstance(tool_out, dict) and "check_tool_output got no answer" in tool_out["error"], tool_out
    assert _TOOL_RESULT["record"] not in json.dumps(tool_out)

    model = await _before_model(plugin)
    assert model is not None and "pre_check got no answer from AxonFlow" in _model_text(model)
    await plugin.aclose()


@pytest.mark.parametrize("fail_open", [True, False])
async def test_a_timeout_is_no_answer(stub: _Stub, fail_open: bool, caplog: pytest.LogCaptureFixture) -> None:
    stub.answer(200, "application/json", json.dumps({"allowed": True}))
    stub.delay_seconds = 1.0
    plugin = _plugin(stub.url, call_timeout_seconds=0.2, fail_open=fail_open)
    caplog.set_level(logging.WARNING, logger="axonflow_adk.plugin")

    result = await _before_tool(plugin)

    if fail_open:
        assert result is None
        assert any("check_tool_input got no answer (timed out after 0.2s)" in r.getMessage() for r in caplog.records)
    else:
        assert isinstance(result, dict) and "got no answer from AxonFlow (timed out after 0.2s)" in result["error"], result
    await plugin.aclose()


@pytest.mark.parametrize("fail_open", [True, False])
async def test_no_answer_opens_the_breaker_and_an_open_breaker_is_no_answer(stub: _Stub, fail_open: bool, caplog: pytest.LogCaptureFixture) -> None:
    from axonflow_adk.plugin import _BreakerState

    stub.answer(200, "application/json", json.dumps({"allowed": True}))
    stub.delay_seconds = 1.0
    plugin = _plugin(stub.url, call_timeout_seconds=0.2, breaker_failure_threshold=3, breaker_recovery_seconds=60.0, fail_open=fail_open)
    caplog.set_level(logging.WARNING, logger="axonflow_adk.plugin")

    for _ in range(3):
        await _before_tool(plugin)
    assert plugin._breaker.state is _BreakerState.OPEN
    hits_when_opened = len(stub.hits)

    result = await _before_tool(plugin)

    assert len(stub.hits) == hits_when_opened, "an open breaker still called the platform"
    if fail_open:
        assert result is None
        assert any("got no answer (circuit breaker open after repeated connection failures)" in r.getMessage() for r in caplog.records)
    else:
        assert isinstance(result, dict) and "circuit breaker open" in result["error"], result
    await plugin.aclose()
