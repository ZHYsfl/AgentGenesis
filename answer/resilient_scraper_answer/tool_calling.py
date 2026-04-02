"""Synchronous tool-calling agent SDK for answer deployment."""

import json
from typing import Any, Callable

from openai import OpenAI
from pydantic import BaseModel


class LLMConfig(BaseModel):
    api_key: str
    model: str
    base_url: str
    extra_body: dict[str, Any] | None = None


class Tool(BaseModel):
    name: str
    description: str
    function: Callable
    parameters: dict


class Agent:
    def __init__(self, config: LLMConfig, max_iterations: int = 15):
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.tools: list[Tool] = []
        self.config = config
        self.max_iterations = max_iterations

    def add_tool(self, tool: Tool):
        self.tools.append(tool)

    def _get_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self.tools
        ]

    def chat(self, observations: list[dict]) -> list[dict]:
        available_functions: dict[str, Callable] = {
            tool.name: tool.function for tool in self.tools
        }
        tools_spec = self._get_tools()

        extra: dict[str, Any] = {}
        if self.config.extra_body:
            extra["extra_body"] = self.config.extra_body

        def _create():
            return self.client.chat.completions.create(
                model=self.config.model,
                messages=observations,
                tools=tools_spec if tools_spec else None,
                **extra,
            )

        response = _create()

        iteration = 0
        while response.choices[0].finish_reason == "tool_calls" and iteration < self.max_iterations:
            iteration += 1
            message = response.choices[0].message
            observations.append(message)

            for tool_call in message.tool_calls:
                fn = available_functions.get(tool_call.function.name)
                if fn is None:
                    result = f"Error: unknown tool '{tool_call.function.name}'"
                else:
                    try:
                        args = json.loads(tool_call.function.arguments)
                        result = str(fn(**args))
                    except Exception as exc:
                        result = f"Error: {type(exc).__name__}: {exc}"

                observations.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tool_call.id,
                })

            response = _create()

        if response.choices[0].message.content:
            observations.append(response.choices[0].message)

        return observations
