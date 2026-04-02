# Environment -> observations -> Agent
# Agent -> tool_action -> ToolEnvironment
# Agent -> output_action -> OutputEnvironment
# Agent 外生出一个ToolEnvironment，用于执行tool_action获取tool_observations
# Agent 外生出一个OutputEnvironment，用于执行output_action获取output_observations
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

    def get_tool_response_observations(self, observations: list[dict], response) -> list[dict]:
        available_functions = {
            tool.name: tool.function for tool in self.tools
        }
        
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
                        print(f"[错误] 解析函数 '{function_name}' 的参数失败: '{raw_arguments}'")
                        function_response = f"调用函数 {function_name} 失败：参数格式错误。"
                        observations.append({
                            "role": "tool", "content": function_response, "tool_call_id": tool_call.id
                        })
                        continue
                
                if function_name in available_functions:
                    function_to_call = available_functions[function_name]
                    try:
                        # 检查函数是否需要 g 参数
                        func_params = function_to_call.__code__.co_varnames[0:function_to_call.__code__.co_argcount]
                        if 'g' in func_params:
                            function_args['g'] = globals()
                        
                        print(f"[调试] 正在执行函数 {function_name} 参数: {list(function_args.keys())}")
                        function_response = str(function_to_call(**function_args))
                    except TypeError as e:
                        expected_args = function_to_call.__code__.co_varnames[0:function_to_call.__code__.co_argcount] 
                        print(f"[错误] 函数 {function_name} 调用参数错误: {e}. 需要的参数: {expected_args}, 实际得到: {list(function_args.keys())}")
                        function_response = f"调用函数 {function_name} 失败：参数不匹配或缺失。错误: {e}"
                    except Exception as e:
                        error_msg = f"函数 {function_name} 使用报错如下: {e}"
                        function_response = error_msg
                        print(f"[错误] {error_msg}")
                else:
                    function_response = f"错误：未找到名为 {function_name} 的函数。"
                    print(f"[错误] {function_response}")

                observations.append({
                    "role": "tool", "content": function_response, "tool_call_id": tool_call.id,
                })
        return observations

    # Tloop -> Tloop -> Tloop -> ... -> OLoop -> observations_final
    # Tloop : observations -> Agent -> tool_action -> Environment -> ...
    # OLoop : observations -> Agent -> output_action -> Environment -> ...
    def chat(self, observations: list[dict]) -> list[dict]:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=observations,
            tools=self.get_tools(),
            tool_choice="auto"
        )
        observations_next = observations
        # 处理 tool calls 循环
        while response.choices[0].finish_reason == "tool_calls":
            observations_next = self.get_tool_response_observations(observations_next, response)
            response = self.client.chat.completions.create(
                model=self.config.model,  
                messages=observations_next,
                tools=self.get_tools(),
                tool_choice="auto"
            )

        observations_final = observations_next
        # 添加最终回复到 observations
        observations_final.append(response.choices[0].message.model_dump())
        return observations_final