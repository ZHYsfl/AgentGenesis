"""Sync Agent with tool-calling loop for wolf NPC."""

import json
from typing import Callable

from openai import OpenAI
from pydantic import BaseModel


class LLMConfig(BaseModel):
    api_key: str
    model: str
    base_url: str


class Tool(BaseModel):
    name: str
    description: str
    function: Callable
    parameters: dict


class Agent:
    def __init__(self, config: LLMConfig):
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.tools: list[Tool] = []
        self.config = config

    def add_tool(self, tool: Tool):
        self.tools.append(tool)

    def get_tools(self) -> list[dict]:
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

    def _execute_tool_calls(self, observations: list[dict], response) -> list[dict]:
        available = {tool.name: tool.function for tool in self.tools}
        tool_calls = response.choices[0].message.tool_calls
        observations.append(response.choices[0].message.model_dump())

        if not tool_calls:
            return observations

        for tool_call in tool_calls:
            fn_name = tool_call.function.name
            raw_args = tool_call.function.arguments or "{}"
            try:
                fn_args = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                fn_args = {}

            if fn_name in available:
                try:
                    result = str(available[fn_name](**fn_args))
                except StopIteration:
                    raise
                except Exception as exc:
                    result = f"tool error: {exc}"
            else:
                result = f"unknown tool: {fn_name}"

            observations.append(
                {
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tool_call.id,
                }
            )

        return observations

    def chat(self, observations: list[dict]) -> list[dict]:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=observations,
            tools=self.get_tools(),
            tool_choice="auto",
        )

        while response.choices[0].finish_reason == "tool_calls":
            observations = self._execute_tool_calls(observations, response)
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=observations,
                tools=self.get_tools(),
                tool_choice="auto",
            )

        observations.append(response.choices[0].message.model_dump())
        return observations
