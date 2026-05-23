# Changelog

All notable changes to the AxonFlow Google ADK Plugin will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-05-24

### Fixed (caught by runtime E2E)

- `before_model_callback`: `pre_check` now passes `tenant_id` from plugin
  config, matching `before_tool_callback` which already did. Without this,
  model-level governance used the SDK default tenant while tool-level
  governance used the configured tenant.
- `before_model_callback`: `pre_check` now passes `request_type` from plugin
  config. The field was declared on `AxonFlowPluginConfig` but never
  propagated to the SDK call, so audit-log filtering by request type did
  not work for model-level checks.
- `after_model_callback`: `audit_llm_call` now passes `user_token` so
  audit rows are attributed to the user who triggered the model call.
- `after_tool_callback`: successful tool calls now emit an
  `audit_tool_call(success=True)` entry. Previously only
  `on_tool_error_callback` recorded audit rows, leaving successful tool
  calls without an explicit audit trail.

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
