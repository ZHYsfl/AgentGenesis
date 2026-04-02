"""Dynamic tool creator for the agent.

Provides create_tool, list_custom_tools, and delete_custom_tool capabilities.
The agent can write Python code at runtime, compile it, and register the
resulting function as a new callable tool.
"""

import json
from tool_calling import Agent, Tool


def build_tool_creator_tools(agent: Agent) -> list[Tool]:
    """Build and return the tool-creator tools bound to the given agent."""

    created_registry: dict[str, dict] = {}

    def create_tool(
        tool_name: str,
        tool_description: str,
        function_code: str,
        parameters_json: str,
    ) -> str:
        try:
            parameters = json.loads(parameters_json)
        except json.JSONDecodeError as e:
            return f"Error: invalid parameters_json: {e}"

        exec_locals: dict = {}
        try:
            exec(function_code, {"__builtins__": __builtins__}, exec_locals)
        except Exception as e:
            return f"Error: code compilation failed: {e}"

        func = None
        for name, obj in exec_locals.items():
            if callable(obj) and not name.startswith("_"):
                func = obj
                break

        if func is None:
            return "Error: no function definition found. Include a 'def func_name(...):' block."

        existing = [t.name for t in agent.tools]
        if tool_name in existing:
            return f"Tool '{tool_name}' already exists. Use it directly or delete it first."

        agent.add_tool(Tool(
            name=tool_name,
            description=tool_description,
            function=func,
            parameters=parameters,
        ))
        created_registry[tool_name] = {"description": tool_description}
        return f"Tool '{tool_name}' created successfully. You can now call it."

    def list_custom_tools() -> str:
        if not created_registry:
            return "No custom tools created yet."
        lines = [f"- {n}: {info['description']}" for n, info in created_registry.items()]
        return "Custom tools:\n" + "\n".join(lines)

    def delete_custom_tool(tool_name: str) -> str:
        if tool_name not in created_registry:
            return f"Error: no custom tool named '{tool_name}'."
        agent.tools = [t for t in agent.tools if t.name != tool_name]
        del created_registry[tool_name]
        return f"Tool '{tool_name}' deleted."

    return [
        Tool(
            name="create_tool",
            description=(
                "Create a new computational tool by providing Python code. "
                "The code must contain a function definition (def func_name(...)). "
                "The function will be compiled and registered as a callable tool. "
                "You can import standard library modules inside the function body."
            ),
            function=create_tool,
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Tool name (snake_case, e.g. 'fibonacci_calculator')",
                    },
                    "tool_description": {
                        "type": "string",
                        "description": "What the tool does",
                    },
                    "function_code": {
                        "type": "string",
                        "description": "Python code with a function definition",
                    },
                    "parameters_json": {
                        "type": "string",
                        "description": "JSON schema for the function parameters",
                    },
                },
                "required": ["tool_name", "tool_description", "function_code", "parameters_json"],
            },
        ),
        Tool(
            name="list_custom_tools",
            description="List all dynamically created custom tools.",
            function=list_custom_tools,
            parameters={"type": "object", "properties": {}},
        ),
        Tool(
            name="delete_custom_tool",
            description="Delete a previously created custom tool by name.",
            function=delete_custom_tool,
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the tool to delete",
                    },
                },
                "required": ["tool_name"],
            },
        ),
    ]
