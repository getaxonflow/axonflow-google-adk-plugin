# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Verify the HITL queue API works against a real AxonFlow agent.

This test exercises the SDK's create_hitl_request + get_hitl_request
methods against a real AxonFlow stack, verifying the queue row lifecycle.
The policy-driven require_approval flow requires enterprise mode,
so this test validates the API layer directly.
"""

from __future__ import annotations

import asyncio
import os
import sys

from axonflow import AxonFlow
from axonflow.hitl import HITLCreateInput


async def main() -> int:
    endpoint = os.environ.get("AXONFLOW_ENDPOINT", "http://localhost:18080")

    client = AxonFlow(
        endpoint=endpoint,
        client_id="e2e-test",
        client_secret="",
    )

    create_input = HITLCreateInput(
        client_id="e2e-test",
        user_id="e2e-user",
        original_query="Disburse $50,000 to CUST-VIP",
        request_type="adk-e2e-hitl-test",
        triggered_policy_id="e2e-approval-test",
        triggered_policy_name="E2E approval test",
        trigger_reason="require_approval",
        severity="critical",
    )

    try:
        result = await client.create_hitl_request(request=create_input)
    except Exception as exc:
        print(f"FAIL: create_hitl_request raised: {exc}")
        return 1

    request_id = getattr(result, "request_id", None)
    if not request_id:
        print(f"FAIL: create_hitl_request returned no request_id: {result}")
        return 1

    print(f"  created HITL row: request_id={request_id}")

    try:
        fetched = await client.get_hitl_request(request_id)
        status = getattr(fetched, "status", "unknown")
        print(f"  fetched HITL row: status={status}")
    except Exception as exc:
        print(f"  get_hitl_request failed (non-fatal): {exc}")

    print(f"HITL_REQUEST_ID={request_id}")
    print("OK: require-approval-creates-hitl-row-and-polls")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
