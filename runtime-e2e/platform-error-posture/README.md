# platform-error-posture

Verifies what the plugin does when a governed call does not return an allow,
for each answer the platform can give, through `Runner.run_async(...)` with
the real `AxonFlowPlugin` and the real `axonflow` SDK.

**Channel: a local stub HTTP server.** The runtime stack cannot be made to
give these answers on demand: a community agent answers 200 for a missing or
wrong credential, and nothing makes it answer a 429 or a 5xx. The stub answers
each route on its own, so each governed hook is proven in isolation. The live
stack proves the other two legs: `policy-deny-blocks-tool-call` (the
platform's own deny) and `breaker-opens-on-stack-down` (no answer).

| Scenario | Stub answer | Expected |
|---|---|---|
| A | check-input: 401, 429 (the full Free-tier daily-quota envelope), 500, 503, 502 with an HTML body | the tool does not run; the model receives `[AxonFlow] check_tool_input did not complete with an allow: ...` with the platform's text; `fail_open` True and False alike |
| B | check-output: the same five | the tool ran (the output check follows it), and the model receives the deny, never the original result |
| C | pre-check: the same five | the model call is denied; no tool is requested |
| D | check-input: 403 `approval_required: ... refused rather than held` | a deny with that text; no HITL row is requested |
| E | nothing listening | `fail_open=True`: the tool runs, with a WARNING notice per governed call; `fail_open=False`: the model call is denied |
| F | check-input answers after the timeout | the same split as E |
| G | check-input: 401, six runs, breaker threshold 1 | every run denied; the breaker stays closed after each; all six reach the platform. Threshold 1 because the allowed pre-check between refusals resets the count: only then would a refusal that wrongly counted open the breaker and let the next run's tool through |

## What this catches

- A 401, a 429 or a 5xx letting a governed model or tool call run.
- A refused output check passing the original tool result to the model.
- `fail_open` loosening a refusal (it only governs a call that got no answer).
- Proceeding ungoverned without a WARNING notice.
- Refusals opening the circuit breaker, which would turn them into
  no-answer outcomes.
- The plugin trying to hold a call that a v11 platform refused.
