# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Deterministic stub LLM for ADK runtime E2E tests.

Returns hardcoded responses so tests do not need real API keys. The stub
cycles through a predetermined response sequence:

  1. First call: returns a function_call to a specified tool with given args.
  2. Second call (after tool result): returns a text response.

Usage:
    from runtime_e2e._lib.stub_model import StubModel

    model = StubModel(
        tool_name="get_balance",
        tool_args={"account_id": "ACC-001"},
        final_text="The balance is $1,000.",
    )
    agent = LlmAgent(model=model, ...)

ADK's LlmAgent accepts either a string (model name looked up in the
registry) or a BaseLlm instance. We extend BaseLlm so the agent can use
the instance directly without registry lookup.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types as genai_types


class StubModel(BaseLlm):
    """Deterministic model that returns a tool call then a text response."""

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

    @property
    def model(self) -> str:
        return self._model_name if hasattr(self, "_model_name") else "stub-model"

    @model.setter
    def model(self, value: str) -> None:
        self._model_name = value

    async def generate_content_async(
        self,
        *,
        llm_request: Any,
        **kwargs: Any,
    ) -> LlmResponse:
        self._call_count += 1

        if self._call_count == 1:
            # First call: return a function call
            return LlmResponse(
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
            # Subsequent calls: return text
            return LlmResponse(
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(text=self._final_text)],
                )
            )

    async def generate_content_stream(
        self,
        *,
        llm_request: Any,
        **kwargs: Any,
    ) -> AsyncIterator[LlmResponse]:
        response = await self.generate_content_async(
            llm_request=llm_request, **kwargs
        )
        yield response


class TextOnlyStubModel(BaseLlm):
    """Stub model that returns only text (no tool calls)."""

    def __init__(
        self,
        *,
        text: str = "Hello, I am a test agent.",
        model_name: str = "stub-text-model",
    ) -> None:
        super().__init__(model=model_name)
        self._text = text

    async def generate_content_async(
        self,
        *,
        llm_request: Any,
        **kwargs: Any,
    ) -> LlmResponse:
        return LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=self._text)],
            )
        )

    async def generate_content_stream(
        self,
        *,
        llm_request: Any,
        **kwargs: Any,
    ) -> AsyncIterator[LlmResponse]:
        response = await self.generate_content_async(
            llm_request=llm_request, **kwargs
        )
        yield response
