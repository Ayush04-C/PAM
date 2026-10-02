"""Gemini adapter; SDK-specific tool conversion is contained in this module."""

from __future__ import annotations

import asyncio

from google import genai
from google.genai import types

from pam.conversation.models import ModelDecision, ModelTurn, ToolCall, ToolResult
from pam.conversation.provider import ModelUnavailable


class GeminiProvider:
    """Use Google's maintained Gen AI SDK for provider-neutral PAM turns."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def respond(self, turn: ModelTurn) -> ModelDecision:
        response = await self._generate(self._initial_contents(turn), turn)
        return self._decision_from_response(response)

    async def respond_after_tool(
        self, turn: ModelTurn, tool_call: ToolCall, tool_result: ToolResult
    ) -> ModelDecision:
        response = await self._generate(
            [
                *self._initial_contents(turn),
                types.Content(
                    role="model",
                    parts=[
                        types.Part.from_function_call(
                            name=tool_call.name, args=dict(tool_call.arguments)
                        )
                    ],
                ),
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=tool_call.name,
                            response=dict(tool_result.result),
                        )
                    ],
                ),
            ],
            turn,
        )
        return self._decision_from_response(response)

    async def _generate(self, contents: list[object], turn: ModelTurn) -> object:
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=dict(tool.input_schema),
            )
            for tool in turn.tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=turn.system_instruction,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        try:
            return await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=contents,
                config=config,
            )
        except Exception as error:
            raise ModelUnavailable("model provider is unavailable") from error

    @staticmethod
    def _initial_contents(turn: ModelTurn) -> list[object]:
        return [
            *[
                types.Content(
                    role="model" if message.role == "assistant" else "user",
                    parts=[types.Part(text=message.content)],
                )
                for message in turn.history
            ],
            turn.user_message,
        ]

    @staticmethod
    def _decision_from_response(response: object) -> ModelDecision:
        function_calls = getattr(response, "function_calls", None)
        if function_calls:
            call = function_calls[0]
            name = getattr(call, "name", None)
            arguments = getattr(call, "args", None)
            if isinstance(name, str) and isinstance(arguments, dict):
                return ModelDecision(tool_call=ToolCall(name, arguments))
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return ModelDecision(text=text)
        raise ModelUnavailable("model provider returned an invalid response")
