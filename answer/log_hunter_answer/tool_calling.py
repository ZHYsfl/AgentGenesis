"""Async tool-calling SDK (self-contained copy for answer deployment).

Combines Agent, LLMConfig, Tool, and batch into a single module.
The Agent handles both sync and async tool functions automatically:
  - sync functions → asyncio.to_thread (non-blocking)
  - async functions → direct await
"""

import asyncio
import inspect
import json
from typing import Any, Callable

from openai import AsyncOpenAI
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
    def __init__(self, config: LLMConfig, max_tool_retries: int = 3, debug: bool = False):
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self.tools: list[Tool] = []
        self.config = config
        self.debug = debug
        self.max_tool_retries = max_tool_retries

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

    def remove_tool(self, tool: Tool):
        self.tools = [t for t in self.tools if t.name != tool.name]

    async def _execute_tool_call(self, tool_call, available_functions: dict[str, Callable]) -> dict:
        function_name = tool_call.function.name
        raw_arguments = tool_call.function.arguments
        function_args = {}

        if raw_arguments and raw_arguments.strip() and raw_arguments != "{}":
            try:
                function_args = json.loads(raw_arguments)
            except json.JSONDecodeError as e:
                error_msg = f"[PARSE_ERROR] JSON parse failed: {e}. Raw: '{raw_arguments}'"
                return {
                    "role": "tool",
                    "content": error_msg,
                    "tool_call_id": tool_call.id,
                    "_tool_status": "error",
                    "_error_type": "parse_error",
                }

        if function_name not in available_functions:
            error_msg = f"[NOT_FOUND] Function '{function_name}' not found"
            return {
                "role": "tool",
                "content": error_msg,
                "tool_call_id": tool_call.id,
                "_tool_status": "error",
                "_error_type": "not_found",
            }

        function_to_call = available_functions[function_name]

        try:
            if inspect.iscoroutinefunction(function_to_call):
                result = await function_to_call(**function_args)
            else:
                result = await asyncio.to_thread(function_to_call, **function_args)
                if inspect.isawaitable(result):
                    result = await result

            return {
                "role": "tool",
                "content": str(result),
                "tool_call_id": tool_call.id,
                "_tool_status": "success",
            }

        except TypeError as e:
            error_msg = f"[ARG_ERROR] Argument mismatch: {e}"
            return {
                "role": "tool",
                "content": error_msg,
                "tool_call_id": tool_call.id,
                "_tool_status": "error",
                "_error_type": "arg_error",
            }

        except Exception as e:
            import traceback
            error_msg = f"[EXEC_ERROR] Execution failed: {e}\n{traceback.format_exc()}"
            return {
                "role": "tool",
                "content": error_msg,
                "tool_call_id": tool_call.id,
                "_tool_status": "error",
                "_error_type": "exec_error",
            }

    async def _get_tool_response_observations(self, observations: list[dict], response) -> list[dict]:
        available_functions = {tool.name: tool.function for tool in self.tools}
        tool_calls = response.choices[0].message.tool_calls
        if tool_calls:
            tool_tasks = [
                self._execute_tool_call(tc, available_functions) for tc in tool_calls
            ]
            return await asyncio.gather(*tool_tasks)
        return []

    def _has_tool_errors(self, tool_responses: list[dict]) -> bool:
        return any(r.get("_tool_status") == "error" for r in tool_responses)

    def _get_error_summary(self, tool_responses: list[dict]) -> str:
        errors = []
        for r in tool_responses:
            if r.get("_tool_status") == "error":
                errors.append(f"- {r.get('_error_type', 'unknown')}: {r.get('content', '')[:200]}")
        return "\n".join(errors) or "unknown error"

    async def chat(self, observations: list[dict]) -> list[dict]:
        request_kwargs = {
            "model": self.config.model,
            "messages": observations,
            "tools": self._get_tools(),
            "tool_choice": "auto",
        }
        if self.config.extra_body is not None:
            request_kwargs["extra_body"] = self.config.extra_body

        response = await self.client.chat.completions.create(**request_kwargs)
        observations_next = observations.copy()
        retry_count = 0

        while response.choices[0].finish_reason == "tool_calls":
            observations_next.append(response.choices[0].message.model_dump())
            tool_responses = await self._get_tool_response_observations(observations_next, response)
            observations_next.extend(tool_responses)

            if self._has_tool_errors(tool_responses) and retry_count < self.max_tool_retries:
                retry_count += 1
                error_summary = self._get_error_summary(tool_responses)
                observations_next.append({
                    "role": "user",
                    "content": (
                        f"[System] Tool execution errors detected:\n\n{error_summary}\n\n"
                        f"Please fix and retry. Retries left: {self.max_tool_retries - retry_count}"
                    ),
                })

            retry_kwargs = {
                "model": self.config.model,
                "messages": observations_next,
                "tools": self._get_tools(),
                "tool_choice": "auto",
            }
            if self.config.extra_body is not None:
                retry_kwargs["extra_body"] = self.config.extra_body

            response = await self.client.chat.completions.create(**retry_kwargs)

        observations_next.append(response.choices[0].message.model_dump())
        return observations_next


async def batch(
    agent: Agent,
    observations: list[list[dict]],
    max_concurrent: int = 20,
) -> list[list[dict]]:
    """Run multiple Agent.chat() sessions concurrently with bounded concurrency."""
    semaphore = asyncio.Semaphore(max_concurrent)
    assert len(observations) > 0, "observations must not be empty"
    assert max_concurrent > 0, "max_concurrent must be positive"

    async def _run(idx: int) -> tuple[int, list[dict]]:
        async with semaphore:
            result = await agent.chat(observations[idx])
            return idx, result

    tasks = [_run(i) for i in range(len(observations))]
    results_with_index = await asyncio.gather(*tasks)
    results_with_index = sorted(results_with_index, key=lambda x: x[0])
    return [r[1] for r in results_with_index]
