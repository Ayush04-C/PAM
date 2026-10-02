"""BharatCode adapter using its OpenAI-compatible chat-completions API."""

from __future__ import annotations

import json
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)

from pam.conversation.models import ModelDecision, ModelTurn, ToolCall, ToolResult
from pam.conversation.provider import ModelUnavailable


class BharatCodeProvider:
    """Translate PAM turns to bounded, stateless OpenAI-compatible requests."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        *,
        client: Any | None = None,
    ) -> None:
        self._client: Any = client or AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=1, timeout=30.0
        )
        self._model = model

    async def respond(self, turn: ModelTurn) -> ModelDecision:
        completion = await self._create_completion(self._initial_messages(turn), turn)
        message = self._message_from_completion(completion)
        return self._decision_from_message(message)

    async def respond_after_tool(
        self, turn: ModelTurn, tool_call: ToolCall, tool_result: ToolResult
    ) -> ModelDecision:
        if tool_call.call_id is None:
            raise ModelUnavailable("model provider returned an invalid tool call")
        messages = [
            *self._initial_messages(turn),
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call.call_id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(
                                dict(tool_call.arguments), separators=(",", ":")
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": tool_call.call_id,
                "content": json.dumps(dict(tool_result.result), separators=(",", ":")),
            },
        ]
        completion = await self._create_completion(messages, turn)
        message = self._message_from_completion(completion)
        return self._decision_from_message(message)

    async def _create_completion(
        self, messages: list[dict[str, Any]], turn: ModelTurn
    ) -> Any:
        try:
            return await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": dict(tool.input_schema),
                        },
                    }
                    for tool in turn.tools
                ],
                tool_choice="auto",
            )
        except (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            NotFoundError,
            RateLimitError,
        ) as error:
            raise ModelUnavailable("model provider is unavailable") from error
        except Exception as error:
            raise ModelUnavailable("model provider is unavailable") from error

    @staticmethod
    def _initial_messages(turn: ModelTurn) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": turn.system_instruction},
            *[
                {"role": message.role, "content": message.content}
                for message in turn.history
            ],
            {"role": "user", "content": turn.user_message},
        ]

    @staticmethod
    def _message_from_completion(completion: Any) -> Any:
        choices = getattr(completion, "choices", None)
        if not choices:
            raise ModelUnavailable("model provider returned an invalid response")
        message = getattr(choices[0], "message", None)
        if message is None:
            raise ModelUnavailable("model provider returned an invalid response")
        return message

    @staticmethod
    def _decision_from_message(message: Any) -> ModelDecision:
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            call = tool_calls[0]
            function = getattr(call, "function", None)
            call_id = getattr(call, "id", None)
            name = getattr(function, "name", None)
            arguments = getattr(function, "arguments", None)
            if (
                not isinstance(call_id, str)
                or not call_id
                or not isinstance(name, str)
                or not isinstance(arguments, str)
            ):
                raise ModelUnavailable("model provider returned an invalid tool call")
            try:
                parsed_arguments = json.loads(arguments)
            except (TypeError, json.JSONDecodeError) as error:
                raise ModelUnavailable(
                    "model provider returned an invalid tool call"
                ) from error
            if not isinstance(parsed_arguments, dict):
                raise ModelUnavailable("model provider returned an invalid tool call")
            return ModelDecision(
                tool_call=ToolCall(name, parsed_arguments, call_id=call_id)
            )
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return ModelDecision(text=content)
        raise ModelUnavailable("model provider returned an invalid response")
