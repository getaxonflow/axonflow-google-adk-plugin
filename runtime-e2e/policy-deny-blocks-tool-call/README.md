# policy-deny-blocks-tool-call

Verifies that when AxonFlow has a static deny policy matching a tool name,
the plugin's `before_tool_callback` returns an error dict that prevents
the tool function from executing.

If the AxonFlow agent does not support policy management (community mode
without the admin API), the test verifies the fail-open path instead.

## What this catches

- `check_tool_input` not propagating deny decisions correctly.
- Tool functions executing despite a deny response.
- Silent failures in the deny-to-error-dict conversion.
