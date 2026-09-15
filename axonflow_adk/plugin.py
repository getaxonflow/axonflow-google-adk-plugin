# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""AxonFlow governance plugin for Google ADK.

`AxonFlowPlugin` extends `google.adk.plugins.BasePlugin` and routes the six
governance-relevant hooks through the existing `axonflow` Python SDK
(`pre_check`, `audit_llm_call`, `check_tool_input`, `check_tool_output`,
`audit_tool_call`) so every model + tool call across every agent on the
Runner is governed.

Three hard design constraints:

1. **Reuse the `axonflow` Python SDK.** The plugin does not speak raw HTTP.
   Auth, retry, observability, and version pinning are inherited from the
   SDK that already ships to PyPI as `axonflow>=8.0`.

2. **An unreachable AxonFlow must not break the agent, and a refusing one
   must not be ignored.** Every hook is wrapped by a per-call timeout
   (default 5s) and a half-open circuit breaker (default open after 5
   consecutive connection failures, recover after 30s). What a FAILED
   governed call (`pre_check`, `check_tool_input`, `check_tool_output`)
   does is one table, `_classify_failure`:

     - The platform ANSWERED and did not allow: a 401, a 403 the SDK
       raises, a 429, a 5xx, an answer that cannot be read, or any failure
       that is not a connection failure. The call is DENIED with the
       platform's text. No setting changes this.
     - NO ANSWER arrived: the connection could not be made, a read or write
       failed on the network, the call timed out, or the breaker is open.
       `AxonFlowPluginConfig.fail_open` decides. True (the default) lets
       the call proceed UNGOVERNED with a WARNING notice; False denies it.

   An answer that broke off partway, a proxy's refusal, and a load
   balancer's 502 / 503 in front of an AxonFlow that is down are all
   answers, so they deny even with `fail_open=True`.

   The audit hooks never block.

3. **`require_approval` fails closed (platforms before v11.0.0).** When a
   pre-v11 platform answers the exact `require_approval` sentinel, the
   plugin polls the HITL queue and denies on rejection, expiry, or polling
   timeout. From v11.0.0 the platform never holds on the planes this plugin
   drives: it REFUSES, with a `block_reason` beginning `approval_required:`,
   and that is a plain deny here. The hold branch is not entered on v11.

The plugin signatures match `BasePlugin` exactly (keyword-only args, async
def, optional return). See
https://github.com/google/adk-python/blob/main/src/google/adk/plugins/base_plugin.py
for the canonical hook surface.

Cross-language clone discipline (Java / Go / TypeScript / Kotlin /
OpenAI Agents SDK):

  • All SDK invocations use keyword arguments. Positional args are an
    anti-pattern here because the SDK reorders + renames params across
    minor releases, and the cross-language clones cannot mirror Python
    positional binding rules.
  • The 4-step HITL flow is canonical: gate → create_hitl_row → poll →
    resume/deny. Same shape in every language.
  • Defensive defaults (timeout; a half-open breaker that only no-answer
    failures open; a deny on every answer that did not allow; `fail_open`
    for no answer only, with a notice; fail-closed on approvals) are part
    of the contract, not the implementation — clone them.
  • `enable_hitl_polling` defaults to True. Callers who want
    deny-fast must set False explicitly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import TracebackType

    from axonflow import AxonFlow
    from google.adk.agents.callback_context import CallbackContext
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.tool_context import ToolContext
    from google.genai import types as genai_types

# google-adk + axonflow are hard runtime dependencies. We import at module
# scope so subclass attribution is correct under the framework's plugin
# discovery, and so import failures surface at agent boot rather than at
# the first hook call (where they could otherwise bypass `_call_with_guard`
# and break the agent).
import httpx
from axonflow.exceptions import ConnectionError as _SdkConnectionError
from axonflow.exceptions import TimeoutError as _SdkTimeoutError
from axonflow.types import AuditToolCallRequest, TokenUsage
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types as genai_types

from axonflow_adk.pep_handshake import (
    PEP_HANDSHAKE_HEADER,
    PepHandshakes,
    build_pep_handshakes,
)

# State keys are prefixed with `temp:` (the ADK convention) so they do
# NOT persist to long-term session state across invocations
# (`google.adk.sessions.state.TEMP_PREFIX` equivalent).
_STATE_PREFIX = "temp:_axonflow_"

logger = logging.getLogger(__name__)


class ApprovalTimeout(Exception):
    """Raised internally when HITL polling exceeds the configured ceiling."""


class ApprovalRejected(Exception):
    """Raised internally when a reviewer rejected (or the platform expired) the request."""


class _BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _FailureClass(Enum):
    """What a failed governed call means. The class decides the posture."""

    # The platform answered and did not allow, its answer could not be read,
    # or the call failed some other way that is not a connection failure.
    # Always denied.
    NOT_ALLOWED = "not_allowed"
    # No answer arrived: the connection failed, the call timed out, or the
    # breaker is open after repeated connection failures. `fail_open` decides.
    UNREACHABLE = "unreachable"


# The failures that mean NO ANSWER ARRIVED; anything else a governed call
# raises is NOT_ALLOWED. Read against the SDK this plugin runs on (axonflow
# 9.4.0): `check_tool_input` / `check_tool_output` post through the SDK's
# httpx client directly, so their transport failures escape as httpx's own
# classes, while `pre_check` maps them to the SDK's ConnectionError /
# TimeoutError (which are NOT the builtins). The builtins cover a transport
# below httpx and asyncio's own timeout (a distinct class before Python 3.11).
#
# No answer is: the connection could not be made (refused, DNS, TLS: an
# outage and a wrong host look the same here), a read or write failed on the
# network (httpx.NetworkError), or the call timed out. Deliberately absent, so
# they DENY: httpx.RemoteProtocolError (an answer that broke off or was not
# HTTP, e.g. a 401 whose body was cut short, or a port that does not speak
# HTTP), httpx.ProxyError (a proxy that refused the request), and
# UnsupportedProtocol / InvalidURL (a malformed endpoint). Those are
# answers or configuration errors, and reading them as no answer would let
# every call run ungoverned.
_NO_ANSWER_FAILURES: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.NetworkError,
    _SdkConnectionError,
    _SdkTimeoutError,
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)


def _classify_failure(exc: BaseException) -> _FailureClass:
    """The status-class table for a failed governed call.

    Two rows, not one per HTTP status: the SDK does not carry the status on
    the tool path (every non-2xx answer except 403 is one `ConnectorError`),
    so a 401, a 429 and a 5xx are indistinguishable here, and all three are
    answers that did not allow.
    """
    if isinstance(exc, _NO_ANSWER_FAILURES):
        return _FailureClass.UNREACHABLE
    return _FailureClass.NOT_ALLOWED


# Bound on the exception text a deny reason or a notice carries: enough for the
# platform's own sentence, short enough that a large error body does not flood
# the model's context or the log.
_FAILURE_DETAIL_MAX_CHARS = 500


@dataclass(frozen=True)
class _GuardFailure:
    """A governed call that produced no result: its failure class and detail."""

    failure_class: _FailureClass
    detail: str


class _CircuitBreaker:
    """Half-open circuit breaker around the AxonFlow client.

    The breaker exists so that an AxonFlow outage cannot take down every
    ADK agent registered on the Runner. Only calls that got no answer open
    it. While it is open, every governed hook is a no-answer outcome until
    the recovery window elapses: `fail_open` decides whether the call
    proceeds (with a WARNING notice) or is denied. HALF_OPEN admits exactly ONE probe at a time
    — concurrent hook invocations during recovery do not
    leak a thundering herd onto a still-recovering AxonFlow.

    All state mutations are guarded by an `asyncio.Lock`
    so concurrent hook calls cannot race the counter. The lock is async
    because all hooks are async — if you mix this plugin with threaded
    callers, wrap with `asyncio.run_coroutine_threadsafe`.
    """

    def __init__(self, failure_threshold: int, recovery_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.state: _BreakerState = _BreakerState.CLOSED
        self.consecutive_failures: int = 0
        self.opened_at: float = 0.0
        self._lock = asyncio.Lock()
        self._probe_in_flight: bool = False

    async def acquire(self) -> bool:
        """Atomically check the breaker and reserve a probe slot if HALF_OPEN.

        Returns True when the caller may proceed with the underlying call,
        False when the breaker is blocking (either OPEN before recovery,
        or HALF_OPEN with a probe already in flight).
        """
        async with self._lock:
            if self.state is _BreakerState.CLOSED:
                return True
            if self.state is _BreakerState.OPEN:
                if (time.monotonic() - self.opened_at) >= self.recovery_seconds:
                    self.state = _BreakerState.HALF_OPEN
                    self._probe_in_flight = True
                    return True
                return False
            # HALF_OPEN: admit exactly one probe.
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    async def record_success(self) -> None:
        async with self._lock:
            self.state = _BreakerState.CLOSED
            self.consecutive_failures = 0
            self.opened_at = 0.0
            self._probe_in_flight = False

    async def record_failure(self) -> None:
        async with self._lock:
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.failure_threshold:
                self.state = _BreakerState.OPEN
                self.opened_at = time.monotonic()
            self._probe_in_flight = False

    async def release(self) -> None:
        """Free the probe slot without counting the call either way.

        For a call that ended without an outcome (cancelled by its caller):
        it says nothing about whether AxonFlow answers, so it must neither
        reset the failure count nor add to it. ADK cancels sibling tool calls
        when one of them raises; counted as failures, those cancellations
        could open the breaker and turn a platform that is answering into
        no-answer outcomes.
        """
        async with self._lock:
            self._probe_in_flight = False


@dataclass
class AxonFlowPluginConfig:
    """Tunable knobs. All have safe defaults — most users do not set these."""

    # Per-hook deadline. An AxonFlow REST call that exceeds this is abandoned
    # and counts as no answer: see `fail_open` below.
    call_timeout_seconds: float = 5.0
    # Default `user_token` propagated when ADK's invocation context does not
    # carry one. Override via callback_context state['axonflow_user_token'].
    # In enterprise mode this MUST be a JWT, not a free-form identifier
    # — the platform's apiAuthMiddleware rejects non-JWTs.
    default_user_token: str = "anonymous"
    # HITL polling applies to platforms BEFORE v11.0.0 only. From v11.0.0 the
    # platform refuses an approval-requiring call on the planes this plugin
    # drives (block_reason "approval_required: ... refused rather than held"),
    # which is a plain deny: the flow below is never entered, whatever this is
    # set to, and no HITL row is written.
    #
    # On a pre-v11 platform, HITL polling is ENABLED by default — the plugin
    # runs the full 4-step approval flow:
    #
    #   1. pre_check / check_tool_input returns require_approval
    #   2. plugin calls axonflow.create_hitl_request(...) → approval_id
    #   3. plugin polls axonflow.get_hitl_request(approval_id) until terminal
    #   4. plugin allows on "approved" / denies on rejected | expired | timeout
    #
    # Earlier v1 drafts shipped this as opt-in because the SDK had no
    # `create_hitl_request` method, so polling against the gate-minted
    # correlation IDs 404'd indefinitely. That gap
    # closed in `axonflow` v8.2.0 with the explicit row-create endpoint,
    # so the full reviewer-driven flow is now functional. Set this False
    # if you want deny-fast semantics — the plugin will short-circuit on
    # `require_approval` without enqueuing a row.
    enable_hitl_polling: bool = True
    approval_poll_interval_seconds: float = 2.0
    approval_max_wait_seconds: float = 300.0
    # Circuit breaker. Only a call that got NO ANSWER counts as a failure; an
    # answer that did not allow means the platform is reachable, so it cannot
    # open the breaker (an open breaker is itself a no-answer outcome).
    breaker_failure_threshold: int = 5
    breaker_recovery_seconds: float = 30.0
    # What a governed call (pre_check, check_tool_input, check_tool_output)
    # does when NO ANSWER arrives from AxonFlow: the connection failed, the call
    # timed out, or the breaker is open. True, the default, lets the model or
    # tool call proceed UNGOVERNED and logs a WARNING notice each time; False
    # denies it. It never applies to an ANSWER that did not allow (a 401, a
    # 429, a 5xx, an answer that cannot be read): those always deny. See
    # `_classify_failure`.
    fail_open: bool = True
    # Default request_type label propagated to AxonFlow's pre_check. Useful
    # for filtering decisions in the AxonFlow audit log.
    request_type: str = "adk-chat"
    # Default connector_type label for tool-call audit. ADK tools are not
    # MCP connectors, but reusing the MCP-style check-input / check-output
    # endpoints gives us PII redaction + policy enforcement on tool I/O.
    tool_connector_type: str = "adk-tool"
    # Default tenant_id / client_id (overrides what is on the SDK client).
    tenant_id: str | None = None
    # Stable identifier surfaced in audit context. Unique per Runner is OK.
    plugin_name: str = "AxonFlowPlugin"
    # Extra static fields merged into every audit context.
    extra_context: dict[str, Any] = field(default_factory=dict)
    # Optional callback that scrubs sensitive fields from tool_args BEFORE
    # they are sent to `audit_tool_call`. Default: send as-is.
    argument_redactor: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # ADR-065 capability handshake audience
    # (getaxonflow/axonflow-enterprise#3763).
    #
    # SET AS `AXONFLOW_PEP_AUDIENCE`, or passed here. Both names matter: the
    # environment variable is what an operator sets and this field is what a
    # reader of the code finds.
    #
    # UNSET IS THE DEFAULT AND SENDS NO HEADER, leaving the plugin behaving
    # byte for byte as before. Opt-in because on an Enterprise platform the
    # transition it gates on the REQUEST path is ALLOW -> DENY: that path
    # performs no substitution, so it declares nothing and the platform refuses
    # rather than allowing on the strength of a substitution it does not
    # perform. See axonflow_adk/pep_handshake.py.
    pep_audience: str | None = None

    def __post_init__(self) -> None:
        # surface configuration mistakes at construction time
        # rather than at first hook call (where they would just fail open).
        if self.call_timeout_seconds <= 0:
            raise ValueError("call_timeout_seconds must be > 0")
        if self.approval_poll_interval_seconds <= 0:
            raise ValueError("approval_poll_interval_seconds must be > 0")
        if self.approval_max_wait_seconds <= 0:
            raise ValueError("approval_max_wait_seconds must be > 0")
        if self.breaker_failure_threshold <= 0:
            raise ValueError("breaker_failure_threshold must be > 0")
        if self.breaker_recovery_seconds <= 0:
            raise ValueError("breaker_recovery_seconds must be > 0")


_PEP_UNSET = object()


class AxonFlowPlugin(BasePlugin):
    """Registers AxonFlow governance on a Google ADK Runner.

    Usage:
        from google.adk.runners import InMemoryRunner
        from axonflow_adk import AxonFlowPlugin

        runner = InMemoryRunner(
            agent=root_agent,
            app_name="loan_desk",
            plugins=[AxonFlowPlugin(
                endpoint="http://localhost:8080",
                client_id="loan-desk",
                client_secret="...",
            )],
        )

    Or with an existing `AxonFlow` client:

        from axonflow import AxonFlow
        axon = AxonFlow(endpoint="...", client_id="...", client_secret="...")
        runner = InMemoryRunner(
            agent=root_agent,
            app_name="loan_desk",
            plugins=[AxonFlowPlugin.from_client(axon)],
        )

    Hook → endpoint mapping:

        on_user_message_callback     → no-op (reserved for ADR-pinned future use)
        before_model_callback        → axonflow.pre_check
        after_model_callback         → axonflow.audit_llm_call
        before_tool_callback         → axonflow.check_tool_input
        after_tool_callback          → axonflow.check_tool_output
        on_tool_error_callback       → axonflow.audit_tool_call

    Known ADK behaviors the plugin does NOT work around:

      • `AgentTool` does not inherit Runner plugins
        (https://github.com/google/adk-python/issues/2809). Sub-agents
        invoked via `AgentTool` are NOT governed by this plugin. Use the
        explicit `RemoteA2aAgent` pattern, or register the plugin on the
        inner Runner as well.

    Args (constructor):
        endpoint: AxonFlow agent URL (e.g. `http://localhost:8080`).
        client_id: AxonFlow client identifier.
        client_secret: AxonFlow client secret.
        config: Optional `AxonFlowPluginConfig` overriding tunables.
        axonflow_client: Optional pre-built `AxonFlow` instance — when
            provided, `endpoint`/`client_id`/`client_secret` are ignored
            and the plugin reuses the caller's client.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        config: AxonFlowPluginConfig | None = None,
        axonflow_client: AxonFlow | None = None,
    ) -> None:
        cfg = config or AxonFlowPluginConfig()
        super().__init__(name=cfg.plugin_name)
        self._config = cfg
        self._owns_client = axonflow_client is None
        self._client: AxonFlow | None = axonflow_client
        # When the caller did not pass an AxonFlow client, build one
        # lazily on first hook so that constructing the plugin in a sync
        # context (e.g. at module import) does not need an event loop.
        self._endpoint = endpoint
        self._client_id = client_id
        self._client_secret = client_secret
        self._client_lock = asyncio.Lock()
        # Built on first use; see _pep_handshakes.
        self._pep_handshakes_cache: PepHandshakes | None | object = _PEP_UNSET
        self._breaker = _CircuitBreaker(
            failure_threshold=cfg.breaker_failure_threshold,
            recovery_seconds=cfg.breaker_recovery_seconds,
        )

    @classmethod
    def from_client(
        cls,
        client: AxonFlow,
        *,
        config: AxonFlowPluginConfig | None = None,
    ) -> AxonFlowPlugin:
        return cls(config=config, axonflow_client=client)

    # ----- Lifecycle ----------------------------------------------------

    async def aclose(self) -> None:
        """Close the owned AxonFlow client (no-op if the caller passed one in).

        ADK does not call plugin lifecycle hooks on Runner shutdown, so
        the host app is responsible for invoking this when its Runner is
        being torn down (long-running services that swap Runners per
        deployment, test harnesses that build many Runners, etc).
        Without this, the underlying httpx client's connection pool
        leaks until process exit.

        Safe to call from multiple tasks concurrently. The shared client
        lock guards the read-and-clear of `self._client`, so only one
        caller actually invokes `close()` on the underlying SDK client
       .
        """
        if not self._owns_client:
            return
        async with self._client_lock:
            client = self._client
            if client is None:
                return
            self._client = None  # subsequent calls (or concurrent ones
            # released from the lock below) will short-circuit on this.
        close = getattr(client, "close", None)
        if close is None:
            return
        try:
            result = close()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001 - never raise out of cleanup
            logger.warning("axonflow client close failed: %s", exc)

    async def __aenter__(self) -> AxonFlowPlugin:  # noqa: PYI034 - see below
        # PYI034 asks for `Self` so a subclass's `async with` narrows to the
        # subclass. This class is a concrete ADK plugin, not a base, and `Self`
        # needs `typing_extensions` on the 3.10 the test matrix still covers -
        # a dependency for an annotation no caller here benefits from.
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ----- Internal helpers ---------------------------------------------

    def _pep_handshakes(self) -> PepHandshakes | None:
        """The two declarations this plugin presents, built once.

        Cached on the instance rather than rebuilt per call: a declaration is a
        property of the build and the deployment, not of a request. Built
        lazily so a malformed audience raises at the first governed call rather
        than at import.

        env wins over config, the same precedence every other credential-shaped
        value on this surface uses.
        """
        if self._pep_handshakes_cache is _PEP_UNSET:
            audience = os.environ.get("AXONFLOW_PEP_AUDIENCE", "").strip() or self._config.pep_audience
            self._pep_handshakes_cache = build_pep_handshakes(audience)
        return self._pep_handshakes_cache

    def _pep_headers(self, which: str) -> dict[str, str] | None:
        """Headers for one governed call, or None.

        `which` selects the enforcement point: "request" for the tool-input
        path, "response" for the tool-output path. They declare DIFFERENT
        capability sets and must not be interchanged - see
        axonflow_adk/pep_handshake.py for why one document for both would
        misdescribe one of them.

        Returns None rather than an empty dict when unconfigured, so no header
        is sent at all: a header PRESENT with an empty value is MALFORMED to
        the platform and refuses the request, which an ABSENT header does not.
        """
        handshakes = self._pep_handshakes()
        if handshakes is None:
            return None
        return {PEP_HANDSHAKE_HEADER: getattr(handshakes, which)}

    async def _get_client(self) -> AxonFlow:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                # Imported lazily so unit tests that stub the plugin out
                # do not need the SDK on the import path.
                from axonflow import AxonFlow as AxonFlowClient

                try:
                    self._client = AxonFlowClient(
                        endpoint=self._endpoint,
                        client_id=self._client_id,
                        client_secret=self._client_secret,
                    )
                except Exception as exc:  # noqa: BLE001 - the SDK's text can quote the secret
                    # The SDK's validation error quotes the values it was given,
                    # and a governed call puts a failure's text into the deny
                    # reason and the log. Name the error class only.
                    msg = (
                        "the AxonFlow client could not be built from the plugin's endpoint, "
                        f"client_id and client_secret ({type(exc).__name__})"
                    )
                    raise RuntimeError(msg) from None
            return self._client

    async def _call_with_guard(
        self,
        op_name: str,
        coro_factory: Any,
        *,
        governed: bool = False,
    ) -> Any:
        """Run `coro_factory()` with timeout + circuit breaker.

        `coro_factory` is a 0-arg async callable so we can short-circuit
        without ever scheduling the underlying coroutine when the breaker
        is open (avoids the un-awaited-coroutine warning).

        A GOVERNED call (`pre_check`, `check_tool_input`, `check_tool_output`)
        returns its result or a `_GuardFailure` naming the failure's class,
        and its hook turns a failure into a posture through `_failure_denial`:
        a failure is never read as an allow. Any other call (the audits, the
        HITL row create) returns None on failure: an audit carries on, and the
        HITL caller denies.

        Breaker accounting follows the class. A result, or an answer that did
        not allow, is a success: the platform is reachable. Only a call that
        got no answer is a failure, so a refusing platform can never open the
        breaker and turn its refusals into no-answer outcomes. A call that
        ended without an outcome (cancelled by its caller) counts neither way.

        the breaker probe slot MUST be released even
        when a caller cancels the awaiting task (`asyncio.CancelledError`
        is a `BaseException` subclass; it would otherwise leak the slot
        and permanently disable the breaker). We use try/finally with an
        explicit `outcome` flag so success/failure attribution is
        preserved AND the slot is freed on any exit path.
        """
        if not await self._breaker.acquire():
            if governed:
                return _GuardFailure(
                    _FailureClass.UNREACHABLE,
                    "circuit breaker open after repeated connection failures",
                )
            logger.debug("axonflow.%s skipped: circuit open", op_name)
            return None
        # "cancelled" stays only if we leave through a BaseException.
        outcome: str = "cancelled"
        try:
            try:
                result = await asyncio.wait_for(
                    coro_factory(),
                    timeout=self._config.call_timeout_seconds,
                )
                outcome = "success"
                return result
            except asyncio.TimeoutError:
                failure = _GuardFailure(
                    _FailureClass.UNREACHABLE,
                    f"timed out after {self._config.call_timeout_seconds:.1f}s",
                )
            except Exception as exc:  # noqa: BLE001 - intentional broad catch at the boundary
                failure = _GuardFailure(_classify_failure(exc), self._failure_detail(exc))
            outcome = "success" if failure.failure_class is _FailureClass.NOT_ALLOWED else "failure"
            if governed:
                return failure
            logger.warning(
                "axonflow.%s failed (%s): %s",
                op_name,
                failure.failure_class.value,
                failure.detail,
            )
            return None
        finally:
            # Always release the breaker slot. "success" resets the counter,
            # "failure" increments it (and may trip OPEN), and a cancellation
            # only frees the slot: it says nothing about whether AxonFlow
            # answers, and the cancel re-raises through this finally anyway.
            if outcome == "success":
                await self._breaker.record_success()
            elif outcome == "failure":
                await self._breaker.record_failure()
            else:
                await self._breaker.release()

    def _failure_denial(self, op_name: str, failure: _GuardFailure) -> str | None:
        """The posture for a governed call that produced no result.

        Returns the deny reason the hook shows, or None when the call proceeds
        ungoverned. NOT_ALLOWED always denies. UNREACHABLE follows
        `config.fail_open`, and proceeding is never silent: it logs a WARNING
        notice naming the call and the cause, every time.
        """
        if failure.failure_class is _FailureClass.NOT_ALLOWED:
            logger.warning(
                "AxonFlow %s did not complete with an allow (%s); denying",
                op_name,
                failure.detail,
            )
            return f"{op_name} did not complete with an allow: {failure.detail}"
        if self._config.fail_open:
            logger.warning(
                "AxonFlow %s got no answer (%s); the call proceeds UNGOVERNED because fail_open is True",
                op_name,
                failure.detail,
            )
            return None
        logger.warning(
            "AxonFlow %s got no answer (%s); denying because fail_open is False",
            op_name,
            failure.detail,
        )
        return f"{op_name} got no answer from AxonFlow ({failure.detail}), and fail_open is False"

    @staticmethod
    def _failure_detail(exc: BaseException) -> str:
        """The exception's class and text, bounded: what a deny or notice shows.

        The class name is kept because the text alone can be opaque (a non-JSON
        answer reads "Expecting value: line 1 column 1 (char 0)").
        """
        text = str(exc).strip()
        detail = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
        if len(detail) > _FAILURE_DETAIL_MAX_CHARS:
            detail = detail[: _FAILURE_DETAIL_MAX_CHARS - 3] + "..."
        return detail

    def _effective_client_id(self) -> str:
        """Resolve the AxonFlow `client_id` for HITL row creation.

        The HITL `CreateRequestInput.client_id` is required (platform
        rejects empty). Prefer the explicit constructor arg, then the
        underlying SDK client's configured client_id, else fall back to
        the plugin name (visible label, never empty).
        """
        if isinstance(self._client_id, str) and self._client_id:
            return self._client_id
        client = self._client
        if client is not None:
            inner = getattr(client, "_config", None)
            cid = getattr(inner, "client_id", None)
            if isinstance(cid, str) and cid:
                return cid
        return self._config.plugin_name

    def _user_token(self, ctx: Any) -> str:
        """Resolve the AxonFlow `user_token` for the current call.

        ADK does not have a first-class `user_token` concept. We look in:
          1. callback_context.state['axonflow_user_token']
          2. config.default_user_token

        We do NOT fall back to `ctx.user_id`. In enterprise
        mode the platform's apiAuthMiddleware expects a JWT signed with
        the tenant key, and ADK's `user_id` is a raw identifier string
        (e.g. "cust-001"). Falling back to it would 401 every call, and
        a 401 denies every governed model and tool call. Host apps MUST
        set `state["axonflow_user_token"] = <jwt>` for enterprise mode.
        """
        state_token: Any = None
        state = getattr(ctx, "state", None)
        if state is not None:
            try:
                state_token = state.get("axonflow_user_token")
            except Exception:  # noqa: BLE001 - state.get can be a dict-like or a model
                state_token = getattr(state, "axonflow_user_token", None)
        if isinstance(state_token, str) and state_token:
            return state_token
        return self._config.default_user_token

    @staticmethod
    def _stringify_llm_request(llm_request: LlmRequest) -> str:
        """Best-effort extraction of the user prompt for governance evaluation.

        ADK's `LlmRequest.contents` is a list of `Content` parts. We
        concatenate the text parts of the most-recent user-role content
        block. This is the same heuristic ADK's own session service uses
        when it surfaces a "user query" to plugins.
        """
        contents = getattr(llm_request, "contents", None) or []
        for item in reversed(contents):
            role = getattr(item, "role", None)
            parts = getattr(item, "parts", None) or []
            text_parts = [getattr(p, "text", None) for p in parts]
            text = " ".join(t for t in text_parts if isinstance(t, str) and t)
            if role in (None, "user") and text:
                return text
        # Fall back: stringify the whole request shape (only used for
        # audit; never for blocking).
        return str(contents)[:2000]

    @staticmethod
    def _stringify_llm_response(llm_response: LlmResponse) -> str:
        content = getattr(llm_response, "content", None)
        if content is None:
            return ""
        parts = getattr(content, "parts", None) or []
        text_parts = [getattr(p, "text", None) for p in parts]
        return " ".join(t for t in text_parts if isinstance(t, str) and t)

    @staticmethod
    def _deny_llm_response(reason: str) -> LlmResponse:
        """Build the canonical deny short-circuit for `before_model_callback`.

        Returning an `LlmResponse` from `before_model_callback` skips the
        actual LLM call. The model output the agent sees becomes the text
        we pass here. We use `genai_types.Content` directly rather than
        `LlmResponse.from_text` because the latter is not a public/stable
        constructor across ADK 2.x versions.
        """
        return LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=f"[AxonFlow policy denial] {reason}")],
            )
        )

    # ----- HITL approval path -------------------------------------------

    @staticmethod
    def _is_approval_required_block_reason(block_reason: str | None) -> bool:
        """Exact-match check against the pre-v11 `require_approval` sentinel.

        Platforms before v11.0.0 set `BlockReason = "require_approval"`
        verbatim at the pre-check and proxy-mode gates, and only that answer
        enters the HITL hold. From v11.0.0 the platform never holds on these
        planes: it refuses with a `block_reason` beginning `approval_required:`
        ("... refused rather than held (PRD v11 §1.13)"), which does not match
        and is a plain deny carrying that text. Substring matching previously
        false-positived on any policy whose reason mentioned the word
        "approval", so the match stays exact.
        """
        return block_reason == "require_approval"

    async def _create_hitl_row(
        self,
        *,
        client_id: str,
        user_id: str | None,
        original_query: str,
        request_type: str,
        request_context: dict[str, Any] | None,
        block_reason: str,
        triggered_policies: list[tuple[str, str | None]] | None,
        severity: str | None = None,
    ) -> str | None:
        """Step 2 of the 4-step HITL flow — enqueue a queue row + return its id.

        The platform's `pre_check` / `check_tool_input` gate sets
        `BlockReason="require_approval"` and mints a correlation
        `context_id` / `decision_id`, but does NOT create the HITL
        queue row at those sites. The plugin owns step 2 — calling
        `client.create_hitl_request(...)` to enqueue the row so a
        reviewer can act on it. The returned `request_id` is the
        canonical handle for polling.

        `triggered_policies` is a list of (policy_id, policy_name?)
        tuples; the first entry is sent on the wire. When the policy
        name is None we mirror policy_id into the name field (the
        platform stores both, but for `pre_check` the SDK only surfaces
        IDs — `check_tool_input` surfaces both via `ExplainPolicy`).

        Returns None on transient failure (network, breaker open).
        The caller treats None as deny-fast (fail-closed for approvals).
        """
        from axonflow.hitl import HITLCreateInput

        if triggered_policies:
            first_id, first_name = triggered_policies[0]
        else:
            first_id, first_name = "", None
        create_input = HITLCreateInput(
            client_id=client_id,
            user_id=user_id or None,
            original_query=original_query,
            request_type=request_type,
            request_context=request_context,
            triggered_policy_id=first_id,
            triggered_policy_name=first_name or first_id,
            trigger_reason=block_reason,
            severity=severity,
        )

        async def _do_create() -> Any:
            client = await self._get_client()
            return await client.create_hitl_request(request=create_input)

        created = await self._call_with_guard("create_hitl_request", _do_create)
        if created is None:
            return None
        rid = getattr(created, "request_id", None)
        return rid if isinstance(rid, str) and rid else None

    async def _await_hitl_decision(self, request_id: str) -> bool:
        """Step 3 of the 4-step HITL flow — poll the queue until terminal.

        Returns:
            True  → reviewer approved
            False → reviewer rejected OR platform expired OR polling exceeded
                    `approval_max_wait_seconds`

        Fail-closed: polling errors that aren't transient deny the call.
        Approvals are safety-critical and silently allowing them on an
        AxonFlow outage would defeat the gate. Polling uses a LOCAL
        consecutive-failure counter — it does NOT share the global
        breaker counter, so a misconfigured approval gate cannot trip
        the breaker OPEN for other in-flight calls on the Runner
       .
        """
        # User-visible signal of the canonical approval_id. Without
        # this the loan-desk example's "AWAITING APPROVAL: <id>" prompt
        # would never fire — the only logs in the polling loop are
        # `logger.debug` on individual poll errors. INFO so default-
        # configured loggers actually surface it.
        logger.info(
            "axonflow hitl AWAITING APPROVAL: request_id=%s; approve via "
            "POST /api/v1/hitl/queue/%s/{approve|reject} (poll_interval=%.1fs, "
            "max_wait=%.0fs)",
            request_id,
            request_id,
            self._config.approval_poll_interval_seconds,
            self._config.approval_max_wait_seconds,
        )
        deadline = time.monotonic() + self._config.approval_max_wait_seconds
        client = await self._get_client()
        # HITL polling failures MUST NOT share the
        # global breaker counter. Otherwise a single misconfigured
        # approval gate (e.g. polling against a platform that doesn't
        # create the HITL row on `pre_check`) trips the breaker OPEN
        # and disables governance for every OTHER in-flight call across
        # the Runner. Use a local counter + raw call with timeout, and
        # leave the global breaker reflecting only the AxonFlow agent's
        # actual availability.
        consecutive_poll_failures = 0
        while time.monotonic() < deadline:
            try:
                req = await asyncio.wait_for(
                    client.get_hitl_request(request_id),
                    timeout=self._config.call_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.debug("axonflow hitl poll for %s timed out", request_id)
                consecutive_poll_failures += 1
                req = None
            except Exception as exc:  # noqa: BLE001 - boundary
                logger.debug("axonflow hitl poll for %s failed: %s", request_id, exc)
                consecutive_poll_failures += 1
                req = None
            if req is None:
                # Bail early on a sustained outage so the agent doesn't
                # hang for the full approval_max_wait_seconds when the
                # platform is clearly unreachable / the HITL row never
                # gets created.
                if consecutive_poll_failures >= self._config.breaker_failure_threshold:
                    logger.warning(
                        "axonflow hitl poll for %s denied: %d consecutive failures",
                        request_id,
                        consecutive_poll_failures,
                    )
                    return False
                await asyncio.sleep(self._config.approval_poll_interval_seconds)
                continue
            consecutive_poll_failures = 0
            status = (getattr(req, "status", "") or "").lower()
            if status == "approved":
                return True
            if status in ("rejected", "expired"):
                return False
            await asyncio.sleep(self._config.approval_poll_interval_seconds)
        logger.warning(
            "axonflow hitl poll for %s exceeded %.0fs; denying",
            request_id,
            self._config.approval_max_wait_seconds,
        )
        return False

    # ----- BasePlugin hooks ---------------------------------------------

    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: genai_types.Content,
    ) -> genai_types.Content | None:
        """No-op in v1.

        Returning a non-None Content here REPLACES the user message — far
        too dangerous a side effect for a governance plugin. Audit of the
        user prompt happens at `before_model_callback` time via `pre_check`.
        Reserved for a future ADR if we add user-message redaction.
        """
        return None

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        """Pre-check + (optionally) HITL-gate the LLM call.

        Returns:
            None        → allow (the framework proceeds to the real LLM call)
            LlmResponse → short-circuit (the agent sees this as the model output)
        """
        query = self._stringify_llm_request(llm_request)
        user_token = self._user_token(callback_context)
        context = {
            "framework": "google-adk",
            "agent_name": getattr(callback_context, "agent_name", None),
            "invocation_id": getattr(callback_context, "invocation_id", None),
            **self._config.extra_context,
        }
        # Stash the model name so the after_model audit can label the
        # provider correctly without having to re-parse LlmRequest later.
        model_name = getattr(llm_request, "model", None)
        if isinstance(model_name, str):
            self._set_state(callback_context, "last_model", model_name)
        self._set_state(callback_context, "call_start_monotonic", time.monotonic())

        async def _do_pre_check() -> Any:
            client = await self._get_client()
            return await client.pre_check(
                user_token=user_token,
                query=query,
                context=context,
            )

        result = await self._call_with_guard(
            "pre_check",
            _do_pre_check,
            governed=True,
        )
        if isinstance(result, _GuardFailure):
            denial = self._failure_denial("pre_check", result)
            return None if denial is None else self._deny_llm_response(denial)
        if getattr(result, "approved", False):
            # Stash context_id so the after_model audit can link to the
            # pre-check decision in AxonFlow's audit log.
            self._set_state(
                callback_context,
                "last_context_id",
                getattr(result, "context_id", None),
            )
            return None

        block_reason = getattr(result, "block_reason", None) or "blocked by policy"
        if self._is_approval_required_block_reason(block_reason):
            if not self._config.enable_hitl_polling:
                # Deny-fast mode — caller has set the flag explicitly to
                # OFF, opting out of the reviewer-driven flow. Host app
                # is expected to surface the deny + drive its own
                # workflow.
                logger.info(
                    "axonflow pre_check require_approval: denying (HITL polling disabled)",
                )
                return self._deny_llm_response(block_reason)
            # Step 2 — enqueue the HITL row. The platform's `pre_check`
            # gate sets BlockReason="require_approval" but does not
            # create the queue row itself; we own that step. For the
            # model path the SDK only surfaces policy IDs, so the name
            # column on the HITL row mirrors the ID.
            triggered_ids = getattr(result, "policies", None) or []
            triggered_tuples: list[tuple[str, str | None]] = [
                (pid, None) for pid in triggered_ids if isinstance(pid, str) and pid
            ]
            new_request_id = await self._create_hitl_row(
                client_id=self._effective_client_id(),
                user_id=self._user_id(callback_context),
                original_query=query,
                request_type=self._config.request_type,
                request_context=context,
                block_reason=block_reason,
                triggered_policies=triggered_tuples,
            )
            if not new_request_id:
                logger.warning(
                    "axonflow pre_check require_approval: queue row creation "
                    "failed; denying (fail-closed)",
                )
                return self._deny_llm_response(block_reason)
            # Step 3 — poll the queue.
            approved = await self._await_hitl_decision(new_request_id)
            # Step 4 — resume or deny.
            if approved:
                self._set_state(callback_context, "last_context_id", new_request_id)
                return None
            return self._deny_llm_response(block_reason)
        return self._deny_llm_response(block_reason)

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        """Audit the LLM response. Never blocks.

        Returning None tells ADK to use the unmodified `llm_response`.
        Output policy enforcement on model output is owned by the
        platform (separate ADR roadmap). Audit only here.
        """
        context_id = self._get_state(callback_context, "last_context_id")
        if not isinstance(context_id, str) or not context_id:
            # No pre-check ran (or pre-check failed open) — without a
            # context_id the audit endpoint will 400. Skip.
            return None
        response_summary = self._stringify_llm_response(llm_response)[:2000] or "<no-content>"
        model_name = self._get_state(callback_context, "last_model") or "unknown"
        start = self._get_state(callback_context, "call_start_monotonic")
        latency_ms = int((time.monotonic() - start) * 1000) if isinstance(start, float) else 0
        try:
            token_usage = self._extract_token_usage(llm_response)
        except Exception as exc:  # noqa: BLE001 - defensive: never break the agent
            logger.warning("axonflow token-usage extraction failed: %s", exc)
            token_usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        provider = self._infer_provider(model_name)

        async def _do_audit() -> Any:
            client = await self._get_client()
            return await client.audit_llm_call(
                context_id=context_id,
                response_summary=response_summary,
                provider=provider,
                model=str(model_name),
                token_usage=token_usage,
                latency_ms=latency_ms,
            )

        # Audit failures must never break the agent.
        await self._call_with_guard("audit_llm_call", _do_audit)
        return None

    @staticmethod
    def _extract_token_usage(llm_response: LlmResponse) -> TokenUsage:
        """Pull a `TokenUsage` from an ADK `LlmResponse`.

        ADK proxies the genai `usage_metadata` shape, which exposes
        `prompt_token_count`, `candidates_token_count`,
        `total_token_count`. When the upstream LLM did not report usage,
        we return zeros — `audit_llm_call` accepts that.

        `TokenUsage` is imported at module scope so a stale
        / missing SDK can't surface here as an unguarded ImportError.
        """
        usage = getattr(llm_response, "usage_metadata", None)
        if usage is None:
            return TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion = int(getattr(usage, "candidates_token_count", 0) or 0)
        total = int(getattr(usage, "total_token_count", 0) or (prompt + completion))
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )

    @staticmethod
    def _infer_provider(model_name: Any) -> str:
        """Best-effort provider label from the model name.

        ADK does not surface a separate `provider` field at this point in
        the callback. The audit endpoint just stores the string. When the
        name is ambiguous we fall back to `"google"` (the ADK default).
        """
        if not isinstance(model_name, str) or not model_name:
            return "google"
        lowered = model_name.lower()
        if "gemini" in lowered or "palm" in lowered:
            return "google"
        if "gpt" in lowered or "openai" in lowered:
            return "openai"
        if "claude" in lowered or "anthropic" in lowered:
            return "anthropic"
        if "bedrock" in lowered:
            return "bedrock"
        if "ollama" in lowered:
            return "ollama"
        return "google"

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        """Check tool input. Returns `{"error": reason}` on deny."""
        tool_name = getattr(tool, "name", tool.__class__.__name__)
        user_token = self._user_token(tool_context)

        async def _do_check() -> Any:
            client = await self._get_client()
            return await client.check_tool_input(
                # The REQUEST enforcement point's declaration. Per-call rather
                # than a client default, because this plugin's two paths
                # declare different capability sets (SDK >= 9.3.0).
                extra_headers=self._pep_headers("request"),
                connector_type=self._config.tool_connector_type,
                statement=tool_name,
                operation="execute",
                parameters=tool_args,
                user_token=user_token,
                tenant_id=self._config.tenant_id,
            )

        result = await self._call_with_guard(
            "check_tool_input",
            _do_check,
            governed=True,
        )
        if isinstance(result, _GuardFailure):
            denial = self._failure_denial("check_tool_input", result)
            return None if denial is None else {"error": f"[AxonFlow] {denial}"}
        if getattr(result, "allowed", False):
            self._set_state(
                tool_context,
                "last_decision_id",
                getattr(result, "decision_id", None),
            )
            return None

        block_reason = getattr(result, "block_reason", None) or "tool blocked by policy"
        if self._is_approval_required_block_reason(block_reason):
            if not self._config.enable_hitl_polling:
                logger.info(
                    "axonflow check_tool_input require_approval: denying (HITL polling disabled)",
                )
                return {"error": f"[AxonFlow] {block_reason}"}
            # Step 2 — enqueue the HITL row. The platform's
            # check_tool_input gate sets BlockReason="require_approval"
            # but does not create the queue row at that site; we own it.
            # `check_tool_input` surfaces `ExplainPolicy` matches with
            # both `policy_id` AND `policy_name`, so we plumb the name
            # through to the HITL row for reviewer readability.
            triggered_tuples: list[tuple[str, str | None]] = []
            policy_matches = getattr(result, "policy_matches", None) or []
            for match in policy_matches:
                pid = getattr(match, "policy_id", None) or getattr(match, "id", None)
                if not isinstance(pid, str) or not pid:
                    continue
                pname = getattr(match, "policy_name", None) or getattr(match, "name", None)
                triggered_tuples.append((pid, pname if isinstance(pname, str) and pname else None))
            new_request_id = await self._create_hitl_row(
                client_id=self._effective_client_id(),
                user_id=self._user_id(tool_context),
                original_query=f"tool: {tool_name}",
                request_type=self._config.tool_connector_type,
                request_context={"tool_name": tool_name, "tool_args": self._safe_input_dict(tool_args)},
                block_reason=block_reason,
                triggered_policies=triggered_tuples,
                severity=getattr(result, "risk_level", None),
            )
            if not new_request_id:
                logger.warning(
                    "axonflow check_tool_input require_approval: queue row "
                    "creation failed; denying (fail-closed)",
                )
                return {"error": f"[AxonFlow] {block_reason}"}
            # Step 3 — poll.
            approved = await self._await_hitl_decision(new_request_id)
            # Step 4 — resume or deny.
            if approved:
                self._set_state(tool_context, "last_decision_id", new_request_id)
                return None
            return {"error": f"[AxonFlow] {block_reason}"}
        return {"error": f"[AxonFlow] {block_reason}"}

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check tool output. Returns redacted dict on PII; None on pass."""
        tool_name = getattr(tool, "name", tool.__class__.__name__)
        user_token = self._user_token(tool_context)
        # ADK tool results are arbitrary JSON-serializable dicts. We pass
        # the result through `message=` so the platform's content-safety
        # + PII redaction passes can scan it. Row-shaped results (e.g.
        # SQL connectors) should go through the connector-typed MCP
        # check-output path instead — that is a separate integration.
        try:
            result_text = json.dumps(result, default=str)[:8000]
        except (TypeError, ValueError):
            result_text = str(result)[:8000]

        async def _do_check() -> Any:
            client = await self._get_client()
            return await client.check_tool_output(
                # The RESPONSE enforcement point's declaration. This path
                # substitutes the platform's redacted_message back into the
                # tool result, so it declares field_redact@1 - a different set
                # from the request path's.
                extra_headers=self._pep_headers("response"),
                connector_type=self._config.tool_connector_type,
                message=result_text,
                metadata={"tool_name": tool_name},
                user_token=user_token,
                tenant_id=self._config.tenant_id,
            )

        check = await self._call_with_guard(
            "check_tool_output",
            _do_check,
            governed=True,
        )
        if isinstance(check, _GuardFailure):
            # The tool result is withheld unless no answer arrived and
            # fail_open lets it through: the model must not receive output the
            # platform refused to check.
            denial = self._failure_denial("check_tool_output", check)
            return None if denial is None else {"error": f"[AxonFlow] {denial}"}
        allowed = bool(getattr(check, "allowed", False))
        # The platform's masked tool output, whether the answer allowed or
        # blocked: check-output fills `redacted_data` (older builds
        # `redacted_message`). The model must receive the masked content, never
        # the original, so it replaces the tool result on BOTH answers.
        masked = self._masked_output(check)
        if allowed and masked is None and self._redaction_withheld(check):
            return {
                "error": "[AxonFlow] the platform did not evaluate redaction for this "
                "tool result, so it is withheld"
            }
        if allowed:
            # Record the success audit entry so successful tool calls have
            # an explicit trail — previously only on_tool_error_callback
            # wrote audit rows, leaving a gap for the happy path.
            scrubbed = self._safe_input_dict(tool_args)
            if scrubbed and self._config.argument_redactor is not None:
                try:
                    scrubbed = self._config.argument_redactor(scrubbed)
                except Exception as exc:  # noqa: BLE001 - never break audit
                    logger.warning("axonflow argument_redactor failed: %s", exc)
            audit_request: Any = None
            try:
                audit_request = AuditToolCallRequest(
                    tool_name=tool_name,
                    # Client identity. `caller_name` is the current field;
                    # `tool_type` is the deprecated fallback the platform still
                    # honors (precedence: caller_name > tool_type > default).
                    # Dual-send both during the deprecation window: correct on
                    # platforms with caller_name support (v9.11.0+) and an SDK
                    # that serializes it, unchanged on older platforms/SDKs
                    # (which silently drop the unknown field).
                    caller_name="adk-tool",
                    tool_type="adk-tool",
                    input=scrubbed,
                    user_id=self._user_id(tool_context),
                    success=True,
                    error_message=None,
                )
            except Exception as exc:  # noqa: BLE001 - SDK shape drift tolerated
                # Skip only the audit: the masked content below must still
                # replace the tool result.
                logger.warning(
                    "axonflow AuditToolCallRequest construction failed: %s; skipping success audit", exc
                )
            if audit_request is not None:

                async def _do_success_audit() -> Any:
                    client = await self._get_client()
                    return await client.audit_tool_call(request=audit_request)

                await self._call_with_guard("audit_tool_call", _do_success_audit)
            if masked is None:
                return None
            return self._redacted_result(masked)

        if masked is None:
            block_reason = getattr(check, "block_reason", None) or "output blocked by policy"
            return {"error": f"[AxonFlow] {block_reason}"}
        return self._redacted_result(masked)

    @staticmethod
    def _user_id(ctx: Any) -> str | None:
        """The user id sent in fields that NAME a user (audit and HITL rows).

        It is the ADK invocation's own user id, or nothing. It is never the
        AxonFlow user token: the token is a credential, and these fields are
        stored as the user id of an audit record or a HITL row. The token is
        sent only as `user_token`, where the API takes it.
        """
        uid = getattr(ctx, "user_id", None)
        return uid if isinstance(uid, str) and uid else None

    @staticmethod
    def _masked_output(check: Any) -> Any:
        """The platform's masked tool output, or None when it returned none.

        check-output fills `redacted_data`; older platform builds fill
        `redacted_message`. An empty value is no masked content.
        """
        for name in ("redacted_data", "redacted_message"):
            value = getattr(check, name, None)
            if value is None or (isinstance(value, (str, dict, list)) and not value):
                continue
            return value
        return None

    def _redaction_withheld(self, check: Any) -> bool:
        """True when the platform did NOT evaluate redaction while the response
        path's handshake declares `field_redact@1`.

        `redaction_evaluated` absent reads exactly as false: the platform sends
        the field only when its detector ran (omitempty), and the SDK defaults
        it to False. With nothing masked to substitute, forwarding the original
        would treat an unevaluated redaction as a clean one; the SDK's rule for
        a false `redaction_evaluated` is to fail closed. Without a handshake no
        obligation is declared, and the answer stands as before.
        """
        return not getattr(check, "redaction_evaluated", False) and self._pep_handshakes() is not None

    @staticmethod
    def _redacted_result(masked: Any) -> dict[str, Any]:
        """Substitute the platform's masked output for the tool result.

        The masked output is the same payload we sent in, with PII spans
        masked. When it is the JSON we serialized, it round-trips back to a
        dict, so downstream tool chaining still sees the same key structure
        (with masked values). When it isn't parseable (a non-JSON string),
        it falls back to the wrapper shape. Both carry the redaction tag.
        """
        if isinstance(masked, str):
            # broaden the exception scope. `TypeError`/
            # `ValueError` cover well-formed-but-not-JSON inputs, but
            # pathologically nested payloads can raise `RecursionError`
            # (a subclass of Exception, not of ValueError) and we must
            # not crash the agent on a buggy platform release.
            try:
                parsed = json.loads(masked)
            except Exception as exc:  # noqa: BLE001 - boundary defense
                logger.warning(
                    "axonflow redacted output JSON parse failed: %s; "
                    "falling back to wrapper shape",
                    exc,
                )
                parsed = None
            if isinstance(parsed, dict):
                # Preserve typed shape so the model sees the same keys.
                parsed["_axonflow_redacted"] = True
                return parsed
            return {"result": masked, "_axonflow_redacted": True}
        # Some platform builds return a dict directly.
        if isinstance(masked, dict):
            out: dict[str, Any] = dict(masked)
            out["_axonflow_redacted"] = True
            return out
        return {"result": masked, "_axonflow_redacted": True}

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> dict[str, Any] | None:
        """Audit tool errors. Never blocks."""
        tool_name = getattr(tool, "name", tool.__class__.__name__)
        scrubbed = self._safe_input_dict(tool_args)
        if scrubbed and self._config.argument_redactor is not None:
            try:
                scrubbed = self._config.argument_redactor(scrubbed)
            except Exception as exc:  # noqa: BLE001 - never break audit
                logger.warning("axonflow argument_redactor failed: %s", exc)
        try:
            request = AuditToolCallRequest(
                tool_name=tool_name,
                # Dual-send client identity: caller_name (current) + tool_type
                # (deprecated fallback). See after_tool_callback for details.
                caller_name="adk-tool",
                tool_type="adk-tool",
                input=scrubbed,
                user_id=self._user_id(tool_context),
                success=False,
                error_message=str(error)[:2000],
            )
        except Exception as exc:  # noqa: BLE001 - SDK shape drift tolerated
            logger.warning(
                "axonflow AuditToolCallRequest construction failed: %s; skipping audit", exc
            )
            return None

        async def _do_audit() -> Any:
            client = await self._get_client()
            return await client.audit_tool_call(request=request)

        await self._call_with_guard("audit_tool_call", _do_audit)
        return None

    @staticmethod
    def _safe_input_dict(args: Any) -> dict[str, Any] | None:
        """Coerce tool_args into a dict for AuditToolCallRequest.input.

        ADK passes positional/keyword args through `tool_args` as a dict
        most of the time, but we accept Pydantic models and namespaces too.
        """
        if isinstance(args, dict):
            return args
        if hasattr(args, "model_dump"):
            try:
                dumped = args.model_dump()
                return dumped if isinstance(dumped, dict) else None
            except Exception:  # noqa: BLE001
                return None
        if hasattr(args, "__dict__"):
            return {k: v for k, v in vars(args).items() if not k.startswith("_")}
        return None

    # ----- State helpers ------------------------------------------------
    #
    # All plugin bookkeeping keys are prefixed with `_STATE_PREFIX`
    # (= `"temp:_axonflow_"`). The `temp:` segment is ADK's documented
    # convention for non-persistent session state (per
    # google.adk.sessions.state.TEMP_PREFIX), so these keys do NOT leak
    # across invocations or persist long-term.

    @staticmethod
    def _set_state(ctx: Any, suffix: str, value: Any) -> None:
        state = getattr(ctx, "state", None)
        if state is None:
            return
        key = _STATE_PREFIX + suffix
        try:
            state[key] = value
        except (TypeError, KeyError):
            # `state` is a model-like with attribute access, not a Mapping.
            setattr(state, key, value)

    @staticmethod
    def _get_state(ctx: Any, suffix: str) -> Any:
        state = getattr(ctx, "state", None)
        if state is None:
            return None
        key = _STATE_PREFIX + suffix
        try:
            return state.get(key)
        except AttributeError:
            return getattr(state, key, None)
