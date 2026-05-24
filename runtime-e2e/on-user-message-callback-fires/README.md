# on-user-message-callback-fires

Verifies that the `on_user_message_callback` (a no-op in v1) does not
break multi-turn conversations through `Runner.run_async(...)`.

Sends 3 sequential messages to the same session, each triggering a
tool call. The plugin's callback fires on each turn and returns None
(pass-through). The test verifies session continuity and audit trail
accumulation across turns.

## What this catches

- No-op callback returning non-None (would replace user message).
- Plugin state leakage across multi-turn conversations.
- Session state corruption from plugin hooks.
- Missing audit rows across turns.
