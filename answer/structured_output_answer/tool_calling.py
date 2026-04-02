import os
from openai import OpenAI
from pydantic import BaseModel
from typing import Callable
import json


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
        self.tools = []
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

    def remove_tool(self, tool: Tool):
        self.tools = [t for t in self.tools if t.name != tool.name]

    def get_tool_response_observations(
        self, observations: list[dict], response
    ) -> list[dict]:
        available_functions = {tool.name: tool.function for tool in self.tools}
        tool_calls = response.choices[0].message.tool_calls
        observations.append(response.choices[0].message.model_dump())

        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                raw_arguments = tool_call.function.arguments
                function_args = {}

                if raw_arguments and raw_arguments.strip() and raw_arguments != "{}":
                    try:
                        function_args = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        function_response = (
                            f"Error parsing arguments for {function_name}."
                        )
                        observations.append(
                            {
                                "role": "tool",
                                "content": function_response,
                                "tool_call_id": tool_call.id,
                            }
                        )
                        continue

                if function_name in available_functions:
                    function_to_call = available_functions[function_name]
                    try:
                        function_response = str(function_to_call(**function_args))
                    except Exception as e:
                        function_response = f"Error calling {function_name}: {e}"
                else:
                    function_response = f"Unknown function: {function_name}"

                observations.append(
                    {
                        "role": "tool",
                        "content": function_response,
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
        observations_next = observations
        while response.choices[0].finish_reason == "tool_calls":
            observations_next = self.get_tool_response_observations(
                observations_next, response
            )
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=observations_next,
                tools=self.get_tools(),
                tool_choice="auto",
            )

        observations_next.append(response.choices[0].message.model_dump())
        return observations_next
