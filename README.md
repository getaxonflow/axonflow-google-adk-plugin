# axonflow-google-adk-plugin

AxonFlow governance plugin for [Google Agent Development Kit (ADK)](https://adk.dev/).

Register `AxonFlowPlugin` once on a `Runner` and **every model call and every
tool call across every agent on that Runner** is governed by AxonFlow
policies: pre-check, HITL approval, deny short-circuit, audit trail, PII
redaction on tool I/O.

## Install

```bash
pip install axonflow-google-adk-plugin
```

Requires `google-adk>=2.0` and `axonflow>=8.2.0` (AxonFlow Python SDK).

## Quickstart (5 lines)

```python
from google.adk.runners import InMemoryRunner
from google.adk.agents import LlmAgent
from axonflow_adk import AxonFlowPlugin

agent = LlmAgent(model="gemini-2.0-flash", name="loan_desk", instruction="...")
runner = InMemoryRunner(
    agent=agent,
    app_name="loan_desk",
    plugins=[AxonFlowPlugin(
        endpoint="http://localhost:8080",
        client_id="loan-desk",
        client_secret="secret-from-axonflow",
    )],
)
```

## Hook → AxonFlow endpoint mapping

| ADK hook                     | AxonFlow call             | Deny shape                                     |
|------------------------------|---------------------------|------------------------------------------------|
| `before_model_callback`      | `pre_check`               | `LlmResponse` with policy-denial text          |
| `after_model_callback`       | `audit_llm_call`          | never blocks (audit only)                      |
| `before_tool_callback`       | `check_tool_input`        | `{"error": "[AxonFlow] <reason>"}`             |
| `after_tool_callback`        | `check_tool_output`       | redacted dict OR `{"error": ...}` on hard deny |
| `on_tool_error_callback`     | `audit_tool_call`         | never blocks (audit only)                      |
| `on_user_message_callback`   | no-op (v1)                | n/a                                            |

The `on_user_message_callback` hook is intentionally a no-op in v1 — returning
non-None Content there would silently **replace** the user's message, which is
the wrong tool for governance.

## HITL approval flow — 4-step

When AxonFlow policy evaluates to `require_approval`, the plugin runs the
full **4-step HITL flow** by default (`enable_hitl_polling=True`):

```
before_model_callback / before_tool_callback
    │
    ├─ STEP 1 — gate (pre_check / check_tool_input)
    │           returns blocked, BlockReason == "require_approval"
    │
    ├─ STEP 2 — POST /api/v1/hitl/queue
    │           plugin calls client.create_hitl_request(request=HITLCreateInput(...))
    │           returns approval_id (uuid)
    │
    ├─ STEP 3 — GET /api/v1/hitl/queue/{approval_id}
    │           polled every approval_poll_interval_seconds (default 2s);
    │           local consecutive-failure counter (NOT the shared
    │           breaker) so a polling outage can't disable governance
    │           for other in-flight calls
    │
    └─ STEP 4 — terminal state:
        ├─ "approved"            → return None (let LLM / tool proceed)
        ├─ "rejected" | "expired" → return deny short-circuit
        ├─ N consecutive poll failures → deny
        └─ time > approval_max_wait_seconds → deny
```

The plugin's `before_model_callback` and `before_tool_callback` both run
this flow. Detection is an exact-string match against the platform's
`require_approval` sentinel. Substring matching previously false-positived
on any policy whose reason text contained the word "approval".

The 4-step flow is the only **fail-closed** path in the plugin —
everything else fails open. Approvals are safety-critical; defaulting to
"allow" on an AxonFlow outage during an approval gate would defeat the
gate.

### Approving / rejecting out-of-band

When step 2 returns an `approval_id`, the plugin emits a single INFO log:

```
axonflow hitl AWAITING APPROVAL: request_id=<uuid>; approve via
POST /api/v1/hitl/queue/<uuid>/{approve|reject}
```

The reviewer (UI, Slack bot, internal portal) posts the decision via:

```bash
# Approve
curl -X POST $AXONFLOW_ENDPOINT/api/v1/hitl/queue/<approval_id>/approve \
     -H 'Content-Type: application/json' \
     -d '{"reviewer_id":"compliance","reviewer_email":"compliance@bank.example"}'

# Reject (same shape)
curl -X POST $AXONFLOW_ENDPOINT/api/v1/hitl/queue/<approval_id>/reject \
     -H 'Content-Type: application/json' \
     -d '{"reviewer_id":"compliance","reviewer_email":"compliance@bank.example"}'
```

### Opting out — deny-fast mode

Set `enable_hitl_polling=False` on the config to short-circuit
`require_approval` immediately without enqueuing a row. The host app
then drives its own approval workflow.

## Authenticating in enterprise mode

ADK does not carry a first-class `user_token` concept. To propagate the
end-user identity AxonFlow's enterprise-mode policy enforcement requires,
set `state["axonflow_user_token"]` to a valid JWT on the session BEFORE
calling `runner.run_async(...)`:

```python
session = runner.session_service.create_session(
    app_name="loan_desk", user_id="cust-001", session_id="sess-A",
)
session.state["axonflow_user_token"] = generate_axonflow_jwt(user_id="cust-001")
```

For **community mode** (no tenant signing key), leave the state key
unset; the plugin will use `config.default_user_token` (default
`"anonymous"`).

## Failure semantics

A buggy or unreachable AxonFlow **must not** break the agent. The plugin
ships with:

- **Per-hook timeout** (default 5s, configurable via `call_timeout_seconds`)
- **Half-open circuit breaker** (default open after 5 consecutive failures,
  recover after 30s). HALF_OPEN admits exactly one probe; concurrent
  hooks during recovery are skipped without leaking a thundering herd.
- **Fail-open default** — every hook except `_await_hitl_decision`
  returns `None` on error/timeout/open-circuit, letting the model or
  tool call proceed.

## MCP toolset helper

```python
from google.adk.agents import LlmAgent
from axonflow_adk import axonflow_mcp_toolset

agent = LlmAgent(
    model="gemini-2.0-flash",
    name="postgres_governed",
    instruction="Answer questions about the production DB.",
    tools=[axonflow_mcp_toolset(
        endpoint="http://localhost:8080",
        client_id="my-app",
        client_secret="secret",
    )],
)
```

## Run the example

```bash
pip install axonflow-google-adk-plugin
export GOOGLE_API_KEY=...
export AXONFLOW_ENDPOINT=http://localhost:8080
export AXONFLOW_CLIENT_ID=loan-desk
export AXONFLOW_CLIENT_SECRET=...

python -m examples.loan_disbursement_agent
# or: python examples/loan_disbursement_agent.py
```

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Documentation

Full integration guide: [docs.getaxonflow.com/docs/integration/google-adk](https://docs.getaxonflow.com/docs/integration/google-adk/)

## License

MIT. See [LICENSE](LICENSE).
