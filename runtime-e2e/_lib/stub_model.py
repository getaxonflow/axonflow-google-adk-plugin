# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Deterministic stub LLM for ADK runtime E2E tests.

Returns hardcoded responses so tests do not need real API keys. The stub
cycles through a predetermined response sequence:

  1. First call: returns a function_call to a specified tool with given args.
  2. Second call (after tool result): returns a text response.

ADK's BaseLlm.generate_content_async is an AsyncGenerator that yields
LlmResponse objects. The stub mirrors this interface exactly.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types as genai_types


class StubModel(BaseLlm):
    """Deterministic model that returns a tool call then a text response."""

    _tool_name: str = "get_balance"
    _tool_args: dict[str, Any] = {}
    _final_text: str = "Done."
    _call_count: int = 0

    def __init__(
        self,
        *,
        tool_name: str = "get_balance",
        tool_args: dict[str, Any] | None = None,
        final_text: str = "Done.",
        model_name: str = "stub-model",
    ) -> None:
        super().__init__(model=model_name)
        self._tool_name = tool_name
        self._tool_args = tool_args or {}
        self._final_text = final_text
        self._call_count = 0

    async def generate_content_async(
        self, llm_request: Any = None, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self._call_count += 1

        if self._call_count == 1:
            yield LlmResponse(
                content=genai_types.Content(
                    role="model",
                    parts=[
                        genai_types.Part(
                            function_call=genai_types.FunctionCall(
                                name=self._tool_name,
                                args=self._tool_args,
                            )
                        )
                    ],
                )
            )
        else:
            yield LlmResponse(
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(text=self._final_text)],
                )
            )


class TextOnlyStubModel(BaseLlm):
    """Stub model that returns only text (no tool calls)."""

    _text: str = "Hello, I am a test agent."

    def __init__(
        self,
        *,
        text: str = "Hello, I am a test agent.",
        model_name: str = "stub-text-model",
    ) -> None:
        super().__init__(model=model_name)
        self._text = text

    async def generate_content_async(
        self, llm_request: Any = None, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=self._text)],
            )
        )
