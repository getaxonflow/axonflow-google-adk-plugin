# Changelog

All notable changes to the AxonFlow Google ADK Plugin will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
