# Environment -> observations -> Agent
# Agent -> tool_action -> ToolEnvironment
# Agent -> output_action -> OutputEnvironment
# Agent 外生出一个ToolEnvironment，用于执行tool_action获取tool_observations
# Agent 外生出一个OutputEnvironment，用于执行output_action获取output_observations
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
        """转换为 OpenAI tools 格式"""
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
        执行单个工具调用
        返回带有结构化错误标记的 tool 消息
        """
        function_name = tool_call.function.name
        raw_arguments = tool_call.function.arguments
        function_args = {}

        # 解析参数错误
        if raw_arguments and raw_arguments.strip() and raw_arguments != "{}":
            try:
                function_args = json.loads(raw_arguments)
            except json.JSONDecodeError as e:
                error_msg = f"[PARSE_ERROR] 参数 JSON 解析失败: {e}. 原始参数: '{raw_arguments}'"
                if self.debug:
                    print(f"[错误] {error_msg}")
                return {
                    "role": "tool",
                    "content": error_msg,
                    "tool_call_id": tool_call.id,
                    "_tool_status": "error",
                    "_error_type": "parse_error"
                }

        # 函数不存在
        if function_name not in available_functions:
            error_msg = f"[NOT_FOUND] 未找到名为 '{function_name}' 的函数"
            if self.debug:
                print(f"[错误] {error_msg}")
            return {
                "role": "tool",
                "content": error_msg,
                "tool_call_id": tool_call.id,
                "_tool_status": "error",
                "_error_type": "not_found"
            }

        function_to_call = available_functions[function_name]
        
        try:
            # 检查函数是否需要 g 参数
            func_params = function_to_call.__code__.co_varnames[0:function_to_call.__code__.co_argcount]
            if "g" in func_params:
                function_args["g"] = globals()

            if self.debug:
                print(f"[调试] 正在执行函数 {function_name} 参数: {list(function_args.keys())}")

            # 执行函数
            if inspect.iscoroutinefunction(function_to_call):
                result = await function_to_call(**function_args)
            else:
                result = await asyncio.to_thread(function_to_call, **function_args)
                if inspect.isawaitable(result):
                    result = await result
            
            # 成功返回
            return {
                "role": "tool",
                "content": str(result),
                "tool_call_id": tool_call.id,
                "_tool_status": "success"
            }
            
        except TypeError as e:
            expected_args = function_to_call.__code__.co_varnames[0:function_to_call.__code__.co_argcount]
            error_msg = f"[ARG_ERROR] 参数不匹配: {e}. 需要: {expected_args}, 实际: {list(function_args.keys())}"
            if self.debug:
                print(f"[错误] {error_msg}")
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
            error_msg = f"[EXEC_ERROR] 执行失败: {e}\n\n详细错误:\n{error_detail}"
            if self.debug:
                print(f"[错误] {error_msg}")
            return {
                "role": "tool",
                "content": error_msg,
                "tool_call_id": tool_call.id,
                "_tool_status": "error",
                "_error_type": "exec_error"
            }

    async def _get_tool_response_observations(self, response) -> list[dict]:
        """
        执行工具调用并返回响应列表
        注意：这个方法只执行工具，不修改 observations，返回的列表需要由调用方 extend
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
        """检查工具响应中是否有错误（通过结构化标记）"""
        for resp in tool_responses:
            # 优先检查结构化标记
            status = resp.get("_tool_status")
            if status == "error":
                return True
            # 兜底：检查旧式错误标记
            content = resp.get("content", "")
            if isinstance(content, str) and content.startswith("[") and "_ERROR" in content:
                return True
        return False
    
    def _get_error_summary(self, tool_responses: list[dict]) -> str:
        """获取错误摘要，用于提示模型"""
        errors = []
        for resp in tool_responses:
            if resp.get("_tool_status") == "error":
                error_type = resp.get("_error_type", "unknown")
                content = resp.get("content", "")
                errors.append(f"- {error_type}: {content[:200]}")  # 截取前200字符
        return "\n".join(errors) if errors else "未知错误"

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
        
        # 处理 tool calls 循环（带自动重试）
        while response.choices[0].finish_reason == "tool_calls":
            # 添加助手的 tool_calls 消息
            observations_next.append(response.choices[0].message.model_dump())
            
            # 并行执行所有工具调用
            tool_responses = await self._get_tool_response_observations(response)
            observations_next.extend(tool_responses)
            
            # 检查是否有工具错误，如果有且未超过重试次数，让模型修正
            if self._has_tool_errors(tool_responses) and retry_count < self.max_tool_retries:
                retry_count += 1
                error_summary = self._get_error_summary(tool_responses)
                if self.debug:
                    print(f"[重试 {retry_count}/{self.max_tool_retries}] 检测到工具执行错误:\n{error_summary}")
                # 添加用户提示，告诉模型修正错误
                observations_next.append({
                    "role": "user",
                    "content": f"【系统通知】你之前调用的工具执行失败，错误信息如下：\n\n{error_summary}\n\n请分析错误原因并修正后重新调用。剩余重试次数：{self.max_tool_retries - retry_count}"
                })
            
            response = await self.client.chat.completions.create(
                model=self.config.model,  
                messages=observations_next,
                tools=self._get_tools(),
                tool_choice="auto"
            )

        observations_final = observations_next
        # 添加最终回复到 observations
        observations_final.append(response.choices[0].message.model_dump())
        return observations_final