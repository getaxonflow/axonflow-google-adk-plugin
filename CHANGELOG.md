# Changelog

All notable changes to the AxonFlow Google ADK Plugin will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-09-26: a platform answer that does not allow denies the call

### Fixed

- **A governed call the platform answers without allowing is now denied.** Every failed governed call used to fail open: with the platform answering `401`, `429` or `5xx`, the tool call ran anyway. One table now classifies every failure of a `pre_check`, `check_tool_input` or `check_tool_output`, and the three outcomes are distinct:
  - **A policy deny** denies the model call and the tool call with the platform's reason, and withholds the tool result or replaces it with the platform's masked content.
  - **An answer that does not allow** - `401`, `429`, `5xx`, a body that cannot be read, and any failure that is not one of the no-answer failures below - **denies**, and `fail_open` does not apply to it.
  - **No answer at all** - a connect or read timeout, a network or connection error, a write error, and an open circuit breaker - follows `fail_open`.
- **An ambiguous answer is a refusal, not a missing answer.** An answer the server cut off by closing the connection (`httpx.RemoteProtocolError`) and a proxy's refusal (`httpx.ProxyError`) are neither timeouts nor network errors, so they are classified as "answered without allowing" and denied rather than handed to `fail_open`.
- **The SDK's own constructor error no longer reaches a deny reason or a log.** It quoted the endpoint, the client id and the client secret; only the exception's class name survives now.

### Added

- **A `fail_open` configuration option** (default `True`), which governs exactly one class: the call where the platform gave **no answer**. It cannot reopen a policy deny, and it cannot reopen an answer that did not allow.

### Changed

- **Circuit-breaker accounting** counts only the failures that represent an unreachable platform, so a platform that answers - even with a refusal - does not trip the breaker.

### Compatibility

An approval-requiring call is **refused, not held**, on every platform from v11.0.0: the platform answers a `block_reason` beginning `approval_required:` on the planes this plugin drives, and no approval-queue row is written. `enable_hitl_polling` and the four-step approval flow apply only to platforms **before** v11.0.0, which answered the `require_approval` sentinel. Nothing in this release changes the SDK floor.

## [1.3.1] - 2026-09-15: the release suite runs on AxonFlow v11.0.0

### Fixed

- **The runtime e2e suite no longer depends on legacy policy rows.** Its deny test wrote a block rule straight into `static_policies` and expected the tool call to be blocked. From AxonFlow v11.0.0 a row written there authors no verdict, so the v1.3.0 release run failed its runtime e2e and 1.3.0 was never published to PyPI. The deny test now calls a tool whose argument carries a destructive shell command, which the platform's shipped `sys_dangerous_destructive_fs` control blocks on the check-input pass. The require-approval test no longer writes its legacy row either. On AxonFlow v11.0.0 none of the platform's shipped controls gives an approval verdict for its tool call, so it proves the hook chain with HITL polling on, on an allowed call.
- The plugin itself is unchanged: 1.3.1 carries every change listed under 1.3.0.

## [1.3.0] - 2026-09-14: the platform's redaction reaches the model, and an unevaluated result is withheld

### Fixed

- **Tool results now reach the model with the platform's redaction applied.** `after_tool_callback` returned the original tool result whenever the output check answered `allowed: true`, so the masked content the platform returned (`redacted_data`, or `redacted_message` on older builds) never reached the model: an email address or a card number in a tool result went to the model unmasked. The masked content now replaces the tool result whether the answer allowed or blocked it, keeping the result's shape and the `_axonflow_redacted` tag; only when nothing masked came back is the original kept (or, on a block, the error returned).
- **A behaviour change for handshake users: a tool result the platform did not evaluate for redaction is now withheld.** With the capability handshake on (`AXONFLOW_PEP_AUDIENCE`), the response path declares that it discharges `field_redact@1`. When the output check allows a result with nothing masked and reports `redaction_evaluated` false, or omits it, which is how the platform reports a detector that did not run, the tool result is now withheld instead of passed through: forwarding it would treat an unevaluated redaction as a clean one. A result the platform evaluated and found nothing to mask passes unchanged, and without the handshake nothing changes.
- **The per-user token is no longer written as a user id.** The tool-call audit sent the AxonFlow user token as its `user_id`, and the HITL rows did the same whenever a token was configured, so a credential was stored in audit and HITL records. Those fields now carry the ADK invocation's own user id, or nothing; the token is still sent only as `user_token`.

## [1.2.0] - 2026-09-07

### Fixed

- **`axonflow_mcp_toolset()` now has the `mcp` SDK it runs on.** The dependency is `google-adk[mcp]>=2.0.0` rather than bare `google-adk`. google-adk keeps the `mcp` SDK optional and owns its supported range (`mcp>=1.24,<2` from 2.0.0 through 2.8.0), and this package had never asked for it: a fresh install had no `mcp` at all, and the release e2e stood in with an unpinned `pip install mcp`. On 2026-07-28 that started resolving `mcp` 2.x, whose module layout google-adk does not support, and ADK's `google.adk.tools.mcp_tool` package swallows the resulting import error and re-raises it as `cannot import name 'McpToolset'`. The first tagged release after that date, this one, failed its runtime e2e on exactly that line and was never published. The class itself has not moved: `McpToolset` is at `google.adk.tools.mcp_tool.mcp_toolset` at both ends of the admitted range, verified against installed 2.0.0 and 2.8.0.
- The helper imports `McpToolset` from the module that defines it, so a missing or incompatible `mcp` now surfaces its real cause (chained, with the remedy) instead of a misleading "cannot import name".
- Unit tests now prove, in a subprocess with nothing stubbed, that the import resolves under the installed google-adk, that the installed `mcp` is inside the range google-adk's own metadata declares, and that this package's dependency asks for the `mcp` extra. The release e2e no longer side-installs `mcp`; it runs on what the wheel installs, and its connection-params assertions read the attribute the real toolset holds (`_connection_params`), where before they silently did not run.

### Added

- **The plugin now declares what it can enforce** (ADR-065 capability handshake; getaxonflow/axonflow-enterprise#3763). Set `AXONFLOW_PEP_AUDIENCE` (or `pep_audience` on the plugin config) to the audience your decision proofs are bound to, and every governed call carries `X-Axonflow-PEP-Handshake`. A platform running v10.4.0 or later that would attach a mandatory obligation this plugin has declared it cannot carry out refuses the request instead of handing the content over and assuming the plugin will cope. Unset, the default, sends no header and nothing changes.
- **This plugin is TWO enforcement points and declares itself as two.** The response path discharges a redaction: `_check_tool_output` round-trips the platform's `redacted_message` back into the tool result, so it declares `field_redact@1`. The request path does not: `_check_tool_input` returns `None` on an allow and the original `tool_args` proceed unchanged, so it declares nothing, under its own name. A declaration describes what a path can do rather than what it should do, and declaring `field_redact` on the request path would tell the platform to allow the call on the strength of a substitution that path does not perform.

### Changed

- **Requires `axonflow>=9.3.0`.** The two declarations are presented through the SDK's per-call `extra_headers`, which that release adds. A process-wide default header could not express this plugin's two paths, because it can only carry one document.

## [1.1.0] - 2026-07-18

### Changed

- The tool-call audit path (success and error) now dual-sends `caller_name`
  (the current client-identity field) alongside the deprecated `tool_type` on
  the `AuditToolCallRequest`. Both keep the literal value `adk-tool`. Platforms
  with `caller_name` support (v9.11.0+) attribute from `caller_name`; older
  platforms continue to read `tool_type` (precedence: `caller_name` >
  `tool_type` > default), so attribution is correct on both.

### Notes

- `caller_name` is serialized by the `axonflow` SDK; it is a no-op on SDK builds
  that predate the field (the extra kwarg is silently dropped, `tool_type` is
  used). **Release is gated on the caller_name-capable `axonflow` SDK shipping
  to PyPI:** at release, bump the `axonflow` runtime pin to that version and
  point the `sdk-wire-contract` CI job at the released SDK instead of the pinned
  git build.

## [1.0.2] - 2026-05-24

### Fixed (caught by runtime E2E)

- Reverted false bug fixes from v1.0.1: `pre_check` does not accept
  `tenant_id`/`request_type`, `audit_llm_call` does not accept `user_token`
  (SDK TypeError surfaced by real `Runner.run_async` tests).
- `StubModel` for runtime E2E: correct `BaseLlm` interface (AsyncGenerator,
  positional `llm_request` arg, import from `google.adk.models.base_llm`).

### Added

- Runtime E2E expanded from 6 to 10 tests. Every test exercises the customer
  entry point: `Runner(agent=..., plugins=[AxonFlowPlugin(...)]).run_async(...)`.
- New tests: `on-tool-error-callback-fires`, `sequential-runs-breaker-stable`,
  `breaker-opens-on-stack-down`, `on-user-message-callback-fires`.
- Rewritten tests: HITL test uses real Runner (was raw SDK call), AgentTool test
  contains real `AgentTool` (was vacuous), MCP toolset test runs through Runner
  (was construction-only).

## [1.0.1] - 2026-05-24

### Fixed (caught by runtime E2E)

- `after_tool_callback`: successful tool calls now emit an
  `audit_tool_call(success=True)` entry. Previously only
  `on_tool_error_callback` recorded audit rows, leaving successful tool
  calls without an explicit audit trail.
- `StubModel` for runtime E2E uses correct `BaseLlm` interface
  (`AsyncGenerator`, positional `llm_request` arg). Previous stub used
  wrong import path and keyword-only signature.

### Added

- `runtime-e2e/` directory with real-framework end-to-end tests that invoke
  the plugin through ADK `InMemoryRunner` against a real AxonFlow stack.
  Six test scenarios covering registration, policy deny, success audit,
  HITL approval flow, MCP toolset loading, and the AgentTool isolation
  gotcha.
- Release workflow (`release.yml`) now gates PyPI publish on `runtime-e2e`
  job passing.
- Lint job (`ruff check`) added to both `test.yml` and `release.yml`.

## [1.0.0] - 2026-05-23

Initial standalone release. Previously shipped as an example integration in the
AxonFlow platform; now installable from PyPI as
`axonflow-google-adk-plugin`.

Requires AxonFlow platform >= 8.1.0 and AxonFlow Python SDK >= 8.2.0.

### Added

- `AxonFlowPlugin` — single-registration governance plugin for Google ADK v2.0+
  Runners. Maps 6 ADK hooks to AxonFlow endpoints (pre_check, audit_llm_call,
  check_tool_input, check_tool_output, audit_tool_call).
- Full 4-step HITL approval flow: gate → create queue row → poll → resume/deny.
  Enabled by default (`enable_hitl_polling=True`); set `False` for deny-fast
  semantics.
- Half-open circuit breaker with per-hook timeout (default 5s) for resilience.
  AxonFlow outage fails open; approval gates fail closed.
- `axonflow_mcp_toolset()` helper — returns an ADK `McpToolset` pointed at
  AxonFlow's MCP server for governed database/connector access.
- `AxonFlowPluginConfig` dataclass with all tunable knobs: timeouts, HITL
  polling intervals, breaker thresholds, argument redactor callback.
- `examples/loan_disbursement_agent.py` — end-to-end demo of the 4-step HITL
  flow with a loan-desk agent.
