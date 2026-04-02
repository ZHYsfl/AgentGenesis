# Meta-Tool: Tool Creator
# Enables Agent to create tools, dynamically expanding its action space
# Agent can connect to any Environment through this tool

from dotenv import load_dotenv
load_dotenv(override=True)
import os
import json
import asyncio

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SDK_DIR = CURRENT_DIR.parent
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from async_tool_calling import Agent, Tool, LLMConfig

# =============================================================================
# Tool Creator - The tool that creates tools
# =============================================================================

async def create_tool_creator(agent: Agent):
    """
    Factory function: Creates a tool_creator tool bound to a specific agent.
    Uses closure to capture agent reference, allowing tool_creator to dynamically add tools.
    """

    # Store created tools for management and tracing
    created_tools_registry = {}

    def tool_creator(
        tool_name: str,
        tool_description: str,
        function_code: str,
        parameters_json: str
    ) -> str:
        """
        Create and register a new tool with the Agent.

        :param tool_name: Tool name (English, snake_case naming)
        :param tool_description: Tool description (tells Agent when to use this tool)
        :param function_code: Python function code (must contain one function definition)
        :param parameters_json: JSON format parameter schema
        :return: Creation result
        """
        print(f"[Tool Creator] Creating new tool: {tool_name}")

        # 1. Parse parameter schema
        try:
            parameters = json.loads(parameters_json)
        except json.JSONDecodeError as e:
            return f"[Error] Parameter schema parsing failed: {e}"

        # 2. Compile function code
        exec_locals = {}

        try:
            exec(function_code, globals(), exec_locals)
        except Exception as e:
            return f"[Error] Function code compilation failed: {e}"

        # 3. Find defined function
        func = None
        func_name = None
        for name, obj in exec_locals.items():
            if callable(obj) and not name.startswith('_'):
                func = obj
                func_name = name
                break

        if func is None:
            return f"[Error] No function definition found in code. Ensure code contains 'def function_name(...):' form." # tool_creator observation

        # 4. Check if tool with same name already exists
        existing_tool_names = [t.name for t in agent.tools]
        if tool_name in existing_tool_names:
            return f"[Warning] Tool '{tool_name}' already exists. Delete old tool first to update." # tool_creator observation

        # 5. Create and register tool
        try:
            new_tool = Tool(
                name=tool_name,
                description=tool_description,
                function=func,
                parameters=parameters
            )
            agent.add_tool(new_tool)

            # Record in registry
            created_tools_registry[tool_name] = {
                'description': tool_description,
                'function_name': func_name,
                'code': function_code,
                'parameters': parameters
            }

            print(f"[Tool Creator] Tool '{tool_name}' created successfully!")
            return f"[Success] Tool '{tool_name}' created successfully!\n\n" \
                   f"Tool Info:\n" \
                   f"- Name: {tool_name}\n" \
                   f"- Description: {tool_description}\n" \
                   f"- Function: {func_name}\n" \
                   f"- Parameters: {list(parameters.get('properties', {}).keys())}\n\n" \
                   f"You can now use this new tool!" # tool_creator observation

        except Exception as e:
            return f"[Error] Tool registration failed: {e}" # tool_creator observation

    def list_created_tools() -> str:
        """List all tools created via tool_creator"""
        if not created_tools_registry:
            return "[Empty] No custom tools created yet." # list_created_tools observation

        result = "[Tool List] Custom tools created:\n\n"
        for name, info in created_tools_registry.items():
            result += f"- {name}\n"
            result += f"  Description: {info['description']}\n"
            result += f"  Parameters: {list(info['parameters'].get('properties', {}).keys())}\n\n"
        return result + "[Done] Tool list displayed successfully." # list_created_tools observation

    def delete_tool(tool_name: str) -> str:
        """Delete a created tool"""
        if tool_name not in created_tools_registry:
            return f"[Error] Custom tool named '{tool_name}' not found." # delete_tool observation

        # Remove from agent
        agent.tools = [t for t in agent.tools if t.name != tool_name]
        # Remove from registry
        del created_tools_registry[tool_name]

        return f"[Success] Tool '{tool_name}' deleted. Current tool list: {list_created_tools()}" # delete_tool observation

    # Return three related tools
    return tool_creator, list_created_tools, delete_tool, created_tools_registry


# =============================================================================
# Create Tool Objects
# =============================================================================

async def build_tool_creator_tools(agent: Agent) -> list[Tool]:
    """
    Build tool_creator series tools and return Tool object list.
    """
    tool_creator, list_created_tools, delete_tool, registry = await create_tool_creator(agent)

    # Example code for description
    example_code = '''def get_stock_price(symbol: str) -> str:
    # Call real API here
    return f"Current price of stock {symbol} is $150.00"'''

    example_params = '''{
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Stock symbol, e.g., AAPL, GOOGL"
        }
    },
    "required": ["symbol"]
}'''

    tools = [
        Tool(
            name="create_tool",
            description=(
                "[Meta-Tool] Create New Tools\n\n"
                "When you find existing tools cannot meet your needs, use this tool to create a new one.\n"
                "The created tool will be immediately available, expanding your capabilities.\n\n"
                "**Parameters:**\n"
                "1. `tool_name`: Tool name (English, snake_case naming)\n"
                "2. `tool_description`: Tool description (clearly explain tool purpose and use cases)\n"
                "3. `function_code`: Python function code, must contain complete function definition\n"
                "4. `parameters_json`: JSON format parameter schema\n\n"
                f"**Example - Create a tool to get stock prices:**\n"
                f"```\ntool_name: get_stock_price\n"
                f"function_code:\n{example_code}\n"
                f"parameters_json:\n{example_params}\n```"
            ),
            function=tool_creator,
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Tool name, use English and underscores, e.g., 'get_weather', 'calculate_tax'"
                    },
                    "tool_description": {
                        "type": "string",
                        "description": "Tool description, explain tool purpose and use cases"
                    },
                    "function_code": {
                        "type": "string",
                        "description": "Complete Python function code, must contain def function definition"
                    },
                    "parameters_json": {
                        "type": "string",
                        "description": "JSON format parameter schema, define function parameter types and descriptions"
                    }
                },
                "required": ["tool_name", "tool_description", "function_code", "parameters_json"]
            }
        ),
        Tool(
            name="list_custom_tools",
            description="[List] List all custom tools created via create_tool",
            function=list_created_tools,
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="delete_custom_tool",
            description="[Delete] Delete a custom tool created via create_tool",
            function=delete_tool,
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the tool to delete"
                    }
                },
                "required": ["tool_name"]
            }
        )
    ]

    return tools


# =============================================================================
# Test
# =============================================================================

async def main():
    # Create Agent
    agent = Agent(LLMConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        model=os.getenv("MODEL"),
        base_url=os.getenv("BASE_URL")
    ))

    # Add tool_creator series tools
    tool_creator_tools = await build_tool_creator_tools(agent)
    for tool in tool_creator_tools:
        agent.add_tool(tool)

    print(f"[Agent] Started with {len(agent.tools)} initial tools")
    print(f"[Tools] Available: {[t.name for t in agent.tools]}")

    # Test: Let Agent create a new tool and use it
    observations = [{
        "role": "user",
        "content": """Please help me create a tool to calculate Fibonacci sequence, then use this tool to calculate the 10th Fibonacci number.

Requirements:
1. First use create_tool to create a tool named 'fibonacci'
2. Then call this new tool to calculate the result"""
    }]

    observations_final = await agent.chat(observations)

    print(observations_final)
    print(f"\n[Final] Tool count: {len(agent.tools)}")
    print(f"[Final] Available tools: {[t.name for t in agent.tools]}")

if __name__ == "__main__":
    asyncio.run(main())