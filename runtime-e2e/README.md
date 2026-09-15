# Runtime End-to-End Tests

Real-framework tests that invoke `AxonFlowPlugin` through ADK
`InMemoryRunner` against a live AxonFlow stack. These tests verify
behavior that unit tests with stubs cannot catch: hook signature
compatibility, SDK wire shape, circuit breaker against a real endpoint,
and audit trail persistence.

## Prerequisites

- Docker and Docker Compose
- Python >= 3.10
- The `axonflow-google-adk-plugin` package (installed from local checkout)
- Access to the AxonFlow agent container image

## Quick start

```bash
cd runtime-e2e
./run-all.sh
```

This will:
1. Bring up Postgres + Redis + AxonFlow Agent via docker-compose
2. Install the plugin from the local checkout
3. Run every suite in `run-all.sh`'s `ALL_TESTS` (twelve); a listed suite
   whose directory or `test.sh` is missing fails the run
4. Print a PASS/FAIL/SKIP summary (SKIP only for a suite not selected)
5. Tear down the stack

To leave the stack running for debugging:

```bash
./run-all.sh --no-down
```

To run specific tests:

```bash
TESTS="agent-runs-with-plugin-registered audit-recorded-on-tool-success" ./run-all.sh
```

To print the suite list: `./run-all.sh --list`.

## Test scenarios

| Directory | What it tests |
|-----------|---------------|
| `agent-runs-with-plugin-registered/` | Plugin registers on Runner, pre_check fires, agent completes |
| `policy-deny-blocks-tool-call/` | Deny policy blocks tool execution |
| `audit-recorded-on-tool-success/` | Successful tool calls emit audit_tool_call(success=True) |
| `hitl-polling-on-allowed-call-writes-no-hitl-row/` | With HITL polling on, a v11 platform's allowed call runs, the hold is never entered, and no HITL row is written (was `require-approval-creates-hitl-row-and-polls`) |
| `mcp-toolset-loads-axonflow-tools/` | axonflow_mcp_toolset() integrates into Runner.run_async |
| `agent-tool-bypass-gotcha-pinned/` | AgentTool sub-agent governance through plugin propagation |
| `on-tool-error-callback-fires/` | Tool error triggers on_tool_error_callback audit |
| `sequential-runs-breaker-stable/` | 5 sequential runs, circuit breaker stays closed |
| `breaker-opens-on-stack-down/` | No answer: with `fail_open=True` the agent completes ungoverned with a WARNING notice per governed call, and the breaker opens; with `fail_open=False` the same outage denies |
| `on-user-message-callback-fires/` | Multi-turn conversation, no-op callback does not interfere |
| `tool-result-redaction/` | A tool result reaches the model with the platform's redaction applied; the audit `user_id` is never the user token |
| `platform-error-posture/` | **Stub channel** (a local HTTP server, not the stack): a 401, a 429, a 5xx, a non-JSON answer and an `approval_required` refusal each deny the governed call; no answer and a timeout follow `fail_open`; a refusal never opens the breaker |

`platform-error-posture/` does not use the stack: the stack cannot be made to
answer a 401 (a community agent accepts any credential), a 429 or a 5xx on
demand, so those answers come from a stub server in front of the real SDK and
plugin.

## AxonFlow agent image

By default, the docker-compose uses `ghcr.io/getaxonflow/axonflow-agent:latest`.
To use a custom image:

```bash
export AXONFLOW_AGENT_IMAGE=my-registry/axonflow-agent:v8.1.0
./run-all.sh
```

For local development with a checkout of axonflow-enterprise:

```bash
export AXONFLOW_AGENT_IMAGE=axonflow-agent:local
docker build -t axonflow-agent:local -f path/to/platform/agent/Dockerfile path/to/axonflow-enterprise/
./run-all.sh
```

## Stub model

The tests use a deterministic `StubModel` (in `_lib/stub_model.py`) that
extends ADK's `BaseLlm` and returns hardcoded responses. No real LLM API
keys are needed.

## CI integration

The release workflow gates PyPI publish on these tests passing. See
`.github/workflows/release.yml` for the `runtime-e2e` job configuration. It
runs the suites `_lib/check-suite-list.sh` prints, and that script fails when
`run-all.sh`'s `ALL_TESTS` and the suite directories differ, so a suite can
neither be added without running nor silently dropped.
