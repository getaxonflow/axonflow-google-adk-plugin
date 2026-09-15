# axonflow-google-adk-plugin

AxonFlow governance plugin for [Google Agent Development Kit (ADK)](https://adk.dev/).

Register `AxonFlowPlugin` once on a `Runner` and **every model call and every
tool call across every agent on that Runner** is governed by AxonFlow
policies: pre-check, deny short-circuit, audit trail, PII redaction on tool
I/O, and HITL approval on platforms before v11.0.0.

## Install

```bash
pip install axonflow-google-adk-plugin
```

Requires `google-adk[mcp]>=2.0.0` and `axonflow>=9.3.0` (AxonFlow Python SDK).

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

What a governed call does when it does not return an allow (a rejected
credential, a quota, a server error, no answer) is in
[Failure semantics](#failure-semantics).

## Failure semantics

A governed call is `pre_check` (before the model), `check_tool_input` (before a
tool) or `check_tool_output` (after a tool). When one does not return an allow,
what happens depends on one question: did the platform ANSWER?

| What happened | Model call | Tool call | Tool result | Setting |
|---|---|---|---|---|
| The platform answered with a policy deny | denied with the reason | denied with the reason | withheld, or replaced by the platform's masked content | none |
| The platform answered with an error: a rejected credential (401), a quota (429), a server error (5xx), or an answer that cannot be read | **denied**, with the error the SDK reports | **denied** | **withheld** | none: `fail_open` does not apply |
| No answer: the connection failed, the call timed out (`call_timeout_seconds`, default 5s), or the circuit breaker is open | proceeds **ungoverned**, with a WARNING notice | proceeds ungoverned, with a WARNING notice | passed through, with a WARNING notice | `fail_open=True` (the default); `fail_open=False` denies all three |

```python
from axonflow_adk.plugin import AxonFlowPluginConfig

# Deny the call when AxonFlow cannot be reached, instead of running it ungoverned.
AxonFlowPlugin(endpoint=..., client_id=..., client_secret=...,
               config=AxonFlowPluginConfig(fail_open=False))
```

- **The notice.** Every call that proceeds ungoverned logs a WARNING on the
  `axonflow_adk.plugin` logger, for example `AxonFlow check_tool_input got no
  answer (ConnectError: All connection attempts failed); the call proceeds
  UNGOVERNED because fail_open is True`. With no logging configured, Python
  prints WARNING records to stderr.
- **Why a 401, a 429 and a 5xx are treated alike.** The `axonflow` SDK reports
  them as the same error on the tool checks, without the HTTP status, so the
  plugin cannot tell them apart. A server error that answers therefore denies
  too; it is never read as an allow. That includes a load balancer or proxy in
  front of an AxonFlow that is down: its 502 or 503 is an answer, so calls are
  denied even with `fail_open=True`, which covers only a platform that cannot
  be reached at all.
- **A broken answer is not "no answer".** An answer the server cuts off by
  closing the connection partway, a connection it closes after the request
  without answering, a port that does not speak HTTP, a proxy that refuses the
  request and a malformed endpoint URL all deny. Two network failures follow
  `fail_open` instead: a connection that cannot be made at all (refused, DNS,
  TLS), because the plugin cannot tell a wrong host from an outage, and a
  connection reset (RST), even partway through an answer.
- **The cost of that strictness.** A server or proxy that closes an idle
  keep-alive connection just as the SDK reuses it produces "server
  disconnected without sending a response", and that call is denied. The SDK
  keeps httpx's default 5-second keep-alive expiry, so this can happen in front
  of a server or proxy whose own keep-alive timeout is 5 seconds or less.
- **The circuit breaker** (default: open after 5 consecutive failures, recover
  after 30s; HALF_OPEN admits exactly one probe) counts only calls that got no
  answer. **A refusal never opens the breaker**, so a platform that refuses
  keeps being asked, and its refusals are never turned into ungoverned calls.
- The audit hooks (`audit_llm_call`, `audit_tool_call`) never block.

## Platform requests per tool call

One agent turn that calls one tool makes seven requests to AxonFlow (measured
through a real ADK `Runner` against AxonFlow v11.0.0):

| Request | Count | What it is for |
|---|---|---|
| `POST /api/policy/pre-check` | 2 | one per model call: the call that chooses the tool, and the call that answers with its result |
| `POST /api/audit/llm-call` | 2 | the audit record of each model call |
| `POST /api/v1/mcp/check-input` | 1 | the tool's arguments, before the tool runs |
| `POST /api/v1/mcp/check-output` | 1 | the tool's result, before the model sees it |
| `POST /api/v1/audit/tool-call` | 1 | the audit record of the tool call |

Each governs or records a different model call or tool step, so none is
dropped. Every one counts against any request rate or quota your deployment
enforces, such as a Community SaaS Free-tier limit: size an agent's tool-call
rate at a seventh of that request limit.

## HITL approval flow — 4-step (platforms before v11.0.0)

> **AxonFlow v11.0.0 and later never hold a call on the planes this plugin
> drives.** An approval-requiring call is refused with a `block_reason`
> beginning `approval_required:` ("... refused rather than held"), and the
> plugin denies it like any other policy deny: no HITL row is created and
> nothing is polled, whatever `enable_hitl_polling` is set to. The flow below
> applies to earlier platforms, which answer the exact `require_approval`
> sentinel.

When a pre-v11 platform evaluates a policy to `require_approval`, the plugin
runs the full **4-step HITL flow** by default (`enable_hitl_polling=True`):

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
this flow. Detection is an exact-string match against the pre-v11
`require_approval` sentinel. Substring matching previously false-positived
on any policy whose reason text contained the word "approval".

The 4-step flow fails closed: a queue row that cannot be created, a poll
that keeps failing, a rejection, an expiry and a wait that runs out all
deny. Approvals are safety-critical; defaulting to "allow" on an AxonFlow
outage during an approval gate would defeat the gate.

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

A rejected token is a 401, and a 401 denies every governed model and tool
call (see [Failure semantics](#failure-semantics)).

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

### Client identification

Every call this helper makes carries `X-Axonflow-Client: google-adk-plugin/<version>`, so AxonFlow can tell ADK adoption apart from any other caller. The version comes from the installed package's own metadata.

**What this is and is not.** It is attribution on a request the platform already receives — no additional request is made, and **this integration sends no heartbeat or telemetry ping of its own**. It is never used for authentication: the platform authenticates on the `Authorization` header, so a missing or mangled value cannot fail a call. Nothing about your prompts, tool arguments, policy data, or identity is added.

The header is applied after `extra_headers`, so a caller cannot make this integration claim to be something else.

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
