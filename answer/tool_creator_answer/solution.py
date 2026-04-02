"""Reference solution for The Tool Creator.

An LLM agent that:
1. Fetches the 10 computation queries
2. Dynamically creates Python computation tools via create_tool
3. Executes each tool to get exact numeric answers
4. Submits all 10 answers
"""

from __future__ import annotations

import os

from tool_calling import Agent, Tool, LLMConfig
from tool_creator import build_tool_creator_tools

SYSTEM_PROMPT = """\
You are a mathematical computation agent. Your task is to solve 10 computation
queries by dynamically creating Python tools and using them.

## Workflow

1. Call `get_queries` to receive the list of 10 computation tasks.
2. For each query, read the description carefully. It tells you:
   - What kind of computation tool to create (e.g., Fibonacci, factorial digit sum)
   - The exact definition/convention to follow
   - The specific input to compute
3. Use `create_tool` to write a Python function that performs the computation.
   - Your function code must be self-contained (include any imports inside the function).
   - The function must return the result as an integer or string.
   - Use Python's arbitrary-precision integers — do NOT use floats.
4. Call the newly created tool with the appropriate parameters to get the answer.
5. Call `submit_answer` with the query_id and the exact answer as a string.
6. Repeat for all 10 queries.

## Important Rules

- Answers are exact integers, often hundreds of digits long. No rounding.
- If multiple queries need the same type of tool, reuse it (don't recreate).
- A wrong answer immediately fails the case, so be precise.
- Submit answers as strings: submit_answer(query_id=0, answer="12345")
- Use `math.factorial()`, `math.comb()`, `pow(a,b,m)` etc. for efficiency.
- For Fibonacci/Tribonacci/Lucas: use iterative (not recursive) implementations.
- For nth prime: a sieve or trial-division loop works fine for n <= 10000.
- For integer partitions p(n): use dynamic programming.

## Tool Creation Example

To create a Fibonacci tool, call create_tool with:
- tool_name: "fibonacci"
- function_code: a string containing `def fibonacci(n): ...`
- parameters_json: `{"type":"object","properties":{"n":{"type":"integer"}},"required":["n"]}`

Then call fibonacci(n=157) to get the answer.
"""


def _build_llm_config() -> LLMConfig:
    return LLMConfig(
        api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "",
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        base_url=os.getenv("LLM_BASE_URL") or "https://api.deepseek.com",
        extra_body={"enable_thinking": False},
    )


def solve(env):
    config = _build_llm_config()
    agent = Agent(config, max_iterations=60)

    agent.add_tool(Tool(
        name="get_queries",
        description=(
            "Get the list of 10 computation queries. Each has query_id (int) "
            "and description (str) with the tool creation instruction and "
            "specific computation to perform."
        ),
        function=lambda: str(env.get_queries()),
        parameters={"type": "object", "properties": {}},
    ))

    agent.add_tool(Tool(
        name="submit_answer",
        description=(
            "Submit the answer for a query. Returns 'correct' or 'wrong: ...'. "
            "A wrong answer immediately fails the case."
        ),
        function=lambda query_id, answer: env.submit(
            query_id=int(query_id), answer=str(answer)
        ),
        parameters={
            "type": "object",
            "properties": {
                "query_id": {
                    "type": "integer",
                    "description": "The query_id from get_queries",
                },
                "answer": {
                    "type": "string",
                    "description": "The exact numeric answer as a string",
                },
            },
            "required": ["query_id", "answer"],
        },
    ))

    for tool in build_tool_creator_tools(agent):
        agent.add_tool(tool)

    agent.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Begin. Call get_queries to see the 10 tasks, then create "
                "tools and solve them one by one."
            ),
        },
    ])
