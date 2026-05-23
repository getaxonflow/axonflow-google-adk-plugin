# Changelog

All notable changes to the AxonFlow Google ADK Plugin will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
