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
3. Run all six test scenarios
4. Print a PASS/FAIL/SKIP summary
5. Tear down the stack

To leave the stack running for debugging:

```bash
./run-all.sh --no-down
```

To run specific tests:

```bash
TESTS="agent-runs-with-plugin-registered audit-recorded-on-tool-success" ./run-all.sh
```

## Test scenarios

| Directory | What it tests |
|-----------|---------------|
| `agent-runs-with-plugin-registered/` | Plugin registers on Runner, pre_check fires, agent completes |
| `policy-deny-blocks-tool-call/` | Deny policy blocks tool execution |
| `audit-recorded-on-tool-success/` | Successful tool calls emit audit_tool_call(success=True) |
| `require-approval-creates-hitl-row-and-polls/` | HITL 4-step flow: gate, create row, poll, resume/deny |
| `mcp-toolset-loads-axonflow-tools/` | axonflow_mcp_toolset() constructs valid McpToolset |
| `agent-tool-bypass-gotcha-pinned/` | Documents AgentTool sub-agent isolation limitation |

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
`.github/workflows/release.yml` for the `runtime-e2e` job configuration.
