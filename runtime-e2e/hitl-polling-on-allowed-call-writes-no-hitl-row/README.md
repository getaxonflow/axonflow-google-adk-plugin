# hitl-polling-on-allowed-call-writes-no-hitl-row

Verifies, through `Runner.run_async(...)` against the live stack, that with
`enable_hitl_polling=True` a v11 platform's allowed tool call runs and nothing
holds it.

From AxonFlow v11.0.0 the platform never holds a call on the planes this
plugin drives. An approval-requiring call is refused with a `block_reason`
beginning `approval_required:` ("... refused rather than held"), and the
plugin denies it without entering the HITL flow. That refusal is proven
through the stub channel in `platform-error-posture` (scenario D). None of the
platform's shipped controls gives an approval verdict for this suite's tool
call, so here the call is allowed.

This suite was `require-approval-creates-hitl-row-and-polls`. On v11 it could
no longer create a HITL row or poll one, so it was renamed to what it checks.

What it cannot catch: because its call is allowed, it passes whether or not
the plugin mishandles an `approval_required:` refusal. That refusal is
asserted by `platform-error-posture` (scenario D) and by
`tests-sdk-wire/test_platform_error_posture_wire.py`.

## What this catches

- The allowed tool call not running with HITL polling on.
- The plugin entering the HITL hold (an `AWAITING APPROVAL` log line) on a v11
  platform.
- A HITL row written for this suite's client id (`e2e-hitl-polling`).
