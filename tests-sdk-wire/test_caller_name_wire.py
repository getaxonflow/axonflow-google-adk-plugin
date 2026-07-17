# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Real-SDK wire-shape contract for the caller_name dual-send migration.

Unlike ``tests/`` (which stubs ``axonflow.types.AuditToolCallRequest`` so the
plugin's *logic* can be exercised without the SDK installed), this module runs
against the **real** ``axonflow`` SDK and asserts the audit request the plugin
builds actually serializes ``caller_name`` (and the deprecated ``tool_type``)
onto the wire body POSTed to ``/api/v1/audit/tool-call``.

``caller_name`` is only present on the SDK from the migration onward
(v9.11.0-aligned; unreleased on PyPI at authoring time), so the dedicated
``sdk-wire-contract`` CI job installs the caller_name-capable SDK from a pinned
git build before running these tests. They are NOT collected by the default
``pytest`` run (``testpaths = ["tests"]``); the job invokes this directory
explicitly. Nothing here skips — if the installed SDK lacks ``caller_name`` the
test fails loudly, which is exactly the drift we want CI to catch.

Together with ``tests/test_plugin.py`` (which proves the plugin *sets*
``caller_name="adk-tool"`` on both audit paths) this closes the loop:
plugin sets the field -> real SDK serializes it -> the field reaches the wire.
"""

from __future__ import annotations

import types
from typing import Any

from axonflow.types import AuditToolCallRequest

CALLER = "adk-tool"


def test_real_sdk_declares_and_serializes_caller_name() -> None:
    """The real SDK type carries caller_name and emits it on the wire body.

    ``client.audit_tool_call`` POSTs exactly
    ``request.model_dump(by_alias=True, exclude_none=True)``, so asserting on
    that dict is asserting on the literal HTTP payload.
    """
    assert "caller_name" in AuditToolCallRequest.model_fields, (
        "installed axonflow SDK has no caller_name field — the dual-send is a "
        "no-op on this build; the sdk-wire-contract CI job must install a "
        "caller_name-capable SDK"
    )

    body = AuditToolCallRequest(
        tool_name="disburse_payment",
        caller_name=CALLER,
        tool_type=CALLER,
    ).model_dump(by_alias=True, exclude_none=True)

    assert body["caller_name"] == CALLER
    assert body["tool_type"] == CALLER


async def test_plugin_error_path_emits_caller_name_on_real_wire() -> None:
    """Drive the real error-audit callback with the real SDK type installed.

    The plugin constructs a genuine ``AuditToolCallRequest``; we capture it via
    a minimal recording client and serialize it the same way the SDK client
    would, proving the plugin's own construction site lands caller_name on the
    wire (not just a hand-built request).
    """
    request = await _capture_audit_request(_drive_error_path)
    body = request.model_dump(by_alias=True, exclude_none=True)
    assert body["caller_name"] == CALLER
    assert body["tool_type"] == CALLER
    assert body["success"] is False


async def test_plugin_success_path_emits_caller_name_on_real_wire() -> None:
    """Same, for the allowed-tool-output success-audit callback."""
    request = await _capture_audit_request(_drive_success_path)
    body = request.model_dump(by_alias=True, exclude_none=True)
    assert body["caller_name"] == CALLER
    assert body["tool_type"] == CALLER
    assert body["success"] is True


# ---------------------------------------------------------------------------
# Helpers — import the real plugin lazily so a missing google-adk fails the
# individual test (loudly) rather than the whole module at collection.
# ---------------------------------------------------------------------------


class _RecordingClient:
    """Captures the request handed to audit_tool_call; nothing else is needed."""

    def __init__(self, *, allow_output: bool = False) -> None:
        self.captured: Any = None
        self._allow_output = allow_output

    async def audit_tool_call(self, request: Any) -> Any:
        self.captured = request
        return types.SimpleNamespace(audit_id="a", status="ok", timestamp="t")

    async def check_tool_output(self, **_kwargs: Any) -> Any:
        # allowed=True triggers the plugin's success-audit path.
        return types.SimpleNamespace(
            allowed=self._allow_output, block_reason=None, redacted_message=None
        )

    async def aclose(self) -> None:  # pragma: no cover - defensive
        return None


def _new_plugin(client: Any) -> Any:
    from axonflow_adk.plugin import AxonFlowPlugin, AxonFlowPluginConfig

    return AxonFlowPlugin.from_client(
        client, config=AxonFlowPluginConfig(call_timeout_seconds=2.0)
    )


def _tool_and_ctx() -> tuple[Any, Any]:
    tool = types.SimpleNamespace(name="disburse_payment")
    ctx = types.SimpleNamespace(
        state={}, user_id="", invocation_id="inv-wire-1", agent_name="wire_agent"
    )
    return tool, ctx


async def _drive_error_path(client: _RecordingClient) -> None:
    plugin = _new_plugin(client)
    tool, ctx = _tool_and_ctx()
    await plugin.on_tool_error_callback(
        tool=tool,
        tool_args={"amount_cents": 100000},
        tool_context=ctx,
        error=RuntimeError("downstream timeout"),
    )


async def _drive_success_path(client: _RecordingClient) -> None:
    plugin = _new_plugin(client)
    tool, ctx = _tool_and_ctx()
    await plugin.after_tool_callback(
        tool=tool,
        tool_args={"amount_cents": 100000},
        tool_context=ctx,
        result={"status": "ok"},
    )


async def _capture_audit_request(driver: Any) -> Any:
    allow = driver is _drive_success_path
    client = _RecordingClient(allow_output=allow)
    await driver(client)
    assert client.captured is not None, "plugin did not call audit_tool_call"
    assert isinstance(client.captured, AuditToolCallRequest), (
        "plugin built a non-SDK request object; wire serialization unverified"
    )
    return client.captured
