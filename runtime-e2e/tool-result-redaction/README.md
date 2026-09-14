# tool-result-redaction

**Asserts**, through a real ADK `InMemoryRunner` with `AxonFlowPlugin` against a live AxonFlow stack:

1. **A tool result reaches the model with the platform's redaction applied.** A tool returns a customer record with an email address and a card number. The platform's output check answers `allowed: true` with the masked record in `redacted_data`, and the model must receive that masked record, tagged `_axonflow_redacted`, never the original.
2. **The tool-call audit's `user_id` is the ADK user, never the AxonFlow user token.** The session carries a canary user token; the audit request must name the ADK invocation's user instead.

Both run in two states: `default` (no capability handshake) and `handshake` (`AXONFLOW_PEP_AUDIENCE` set, so the response path declares `field_redact@1`).

The model is a stub that calls the tool once and records the `function_response` it is given on its second call, which is exactly what ADK hands a real model. A pass-through recorder around the SDK client's `audit_tool_call` notes the audit request's `user_id`; the real request still goes to the platform.

Each assertion prints `PASS` or `FAIL` with its name, and `OBSERVED:` lines show what the model and the audit actually received, so a run against the previous plugin release and a run against this one compare line by line: before the fix, the model received the raw email and card number and the audit `user_id` was the token.

## Run

    AGENT_URL=http://localhost:18080 ./test.sh

`PYTHON` selects the interpreter (and so the installed plugin version); the default is `python3`.
