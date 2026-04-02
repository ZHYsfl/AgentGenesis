# Environment -> observations -> Agent
# Agent -> tool_action -> ToolEnvironment
# Agent -> output_action -> OutputEnvironment
# Agent spawns a ToolEnvironment outside itself to execute tool_action and get tool_observations
# Agent spawns an OutputEnvironment outside itself to execute output_action and get output_observations
import asyncio
import inspect
import json
from typing import Any, Callable

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

class LLMConfig(BaseModel):
    api_key: str
    model: str
    base_url: str
    extra_body: dict[str, Any] | None = Field(default=None)

    def model_dump(self, **kwargs):
        """Override to exclude None values by default."""
        data = super().model_dump(**kwargs)
        if data.get("extra_body") is None:
            data.pop("extra_body", None)
        return data

class Tool(BaseModel):
    name: str
    description: str
    function: Callable
    parameters: dict

class Agent:
    def __init__(self, config: LLMConfig,  max_tool_retries: int = 3, debug: bool = False):
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self.tools = []
        self.config = config
        self.debug = debug
        self.max_tool_retries = max_tool_retries

    def add_tool(self, tool: Tool):
        self.tools.append(tool)

    def _get_tools(self) -> list[dict]:
        """Convert to OpenAI tools format"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            }
            for tool in self.tools
        ]

    def remove_tool(self, tool: Tool):
        tools = [t for t in self.tools if t.name != tool.name]
        self.tools = tools

    async def _execute_tool_call(self, tool_call, available_functions: dict[str, Callable]) -> dict:
        """
        Execute a single tool call.
        Returns a tool message with structured error markers.
        """
        function_name = tool_call.function.name
        raw_arguments = tool_call.function.arguments
        function_args = {}

        # Parse argument errors
        if raw_arguments and raw_arguments.strip() and raw_arguments != "{}":
            try:
                function_args = json.loads(raw_arguments)
            except json.JSONDecodeError as e:
                error_msg = f"[PARSE_ERROR] Argument JSON parsing failed: {e}. Raw arguments: '{raw_arguments}'"
                if self.debug:
                    print(f"[Error] {error_msg}")
                return {
                    "role": "tool",
                    "content": error_msg,
                    "tool_call_id": tool_call.id,
                    "_tool_status": "error",
                    "_error_type": "parse_error"
                }

        # Function does not exist
        if function_name not in available_functions:
            error_msg = f"[NOT_FOUND] Function named '{function_name}' not found"
            if self.debug:
                print(f"[Error] {error_msg}")
            return {
                "role": "tool",
                "content": error_msg,
                "tool_call_id": tool_call.id,
                "_tool_status": "error",
                "_error_type": "not_found"
            }

        function_to_call = available_functions[function_name]

        try:
            # Check if function requires 'g' parameter
            func_params = function_to_call.__code__.co_varnames[0:function_to_call.__code__.co_argcount]
            if "g" in func_params:
                function_args["g"] = globals()

            if self.debug:
                print(f"[Debug] Executing function {function_name} with args: {list(function_args.keys())}")

            # Execute function
            if inspect.iscoroutinefunction(function_to_call):
                result = await function_to_call(**function_args)
            else:
                result = await asyncio.to_thread(function_to_call, **function_args)
                if inspect.isawaitable(result):
                    result = await result

            # Success return
            return {
                "role": "tool",
                "content": str(result),
                "tool_call_id": tool_call.id,
                "_tool_status": "success"
            }

        except TypeError as e:
            expected_args = function_to_call.__code__.co_varnames[0:function_to_call.__code__.co_argcount]
            error_msg = f"[ARG_ERROR] Argument mismatch: {e}. Expected: {expected_args}, Got: {list(function_args.keys())}"
            if self.debug:
                print(f"[Error] {error_msg}")
            return {
                "role": "tool",
                "content": error_msg,
                "tool_call_id": tool_call.id,
                "_tool_status": "error",
                "_error_type": "arg_error"
            }

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            error_msg = f"[EXEC_ERROR] Execution failed: {e}\n\nDetail:\n{error_detail}"
            if self.debug:
                print(f"[Error] {error_msg}")
            return {
                "role": "tool",
                "content": error_msg,
                "tool_call_id": tool_call.id,
                "_tool_status": "error",
                "_error_type": "exec_error"
            }

    async def _get_tool_response_observations(self, response) -> list[dict]:
        """
        Execute tool calls and return response list.
        Note: This method only executes tools, does not modify observations.
        The returned list needs to be extended by the caller.
        """
        available_functions = {
            tool.name: tool.function for tool in self.tools
        }

        tool_calls = response.choices[0].message.tool_calls

        if tool_calls:
            tool_tasks = [
                self._execute_tool_call(tool_call, available_functions)
                for tool_call in tool_calls
            ]
            tool_responses = await asyncio.gather(*tool_tasks)
            return tool_responses
        return []

    def _has_tool_errors(self, tool_responses: list[dict]) -> bool:
        """Check if tool responses contain errors (via structured markers)"""
        for resp in tool_responses:
            # Prioritize structured markers
            status = resp.get("_tool_status")
            if status == "error":
                return True
            # Fallback: check old-style error markers
            content = resp.get("content", "")
            if isinstance(content, str) and content.startswith("[") and "_ERROR" in content:
                return True
        return False

    def _get_error_summary(self, tool_responses: list[dict]) -> str:
        """Get error summary for prompting the model"""
        errors = []
        for resp in tool_responses:
            if resp.get("_tool_status") == "error":
                error_type = resp.get("_error_type", "unknown")
                content = resp.get("content", "")
                errors.append(f"- {error_type}: {content[:200]}")  # Truncate to first 200 chars
        return "\n".join(errors) if errors else "Unknown error"

    # Tloop -> Tloop -> Tloop -> ... -> OLoop -> observations_final
    # Tloop : observations -> Agent -> tool_action -> Environment -> ...
    # OLoop : observations -> Agent -> output_action -> Environment -> ...
    async def chat(self, observations: list[dict]) -> list[dict]:
        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=observations,
            tools=self._get_tools(),
            tool_choice="auto"
        )
        observations_next = observations.copy()
        retry_count = 0

        # Handle tool calls loop (with auto-retry)
        while response.choices[0].finish_reason == "tool_calls":
            # Add assistant's tool_calls message
            observations_next.append(response.choices[0].message.model_dump())

            # Execute all tool calls in parallel
            tool_responses = await self._get_tool_response_observations(response)
            observations_next.extend(tool_responses)

            # Check for tool errors, if found and retry count not exceeded, let model correct
            if self._has_tool_errors(tool_responses) and retry_count < self.max_tool_retries:
                retry_count += 1
                error_summary = self._get_error_summary(tool_responses)
                if self.debug:
                    print(f"[Retry {retry_count}/{self.max_tool_retries}] Tool execution errors detected:\n{error_summary}")
                # Add user hint telling model to correct the error
                observations_next.append({
                    "role": "user",
                    "content": f"[System Notice] The tool you previously called failed to execute. Error info as follows:\n\n{error_summary}\n\nPlease analyze the error and correct it on retry. Remaining retries: {self.max_tool_retries - retry_count}"
                })

            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=observations_next,
                tools=self._get_tools(),
                tool_choice="auto"
            )

        observations_final = observations_next
        # Add final reply to observations
        observations_final.append(response.choices[0].message.model_dump())
        return observations_final