"""Reference solution for The Resilient Scraper.

A single LLM agent orchestrates the entire flow: fetch, verify claims
using its own common-sense knowledge, backoff, and submit.
"""

from __future__ import annotations

import os
import time

from tool_calling import Agent, Tool, LLMConfig

SYSTEM_PROMPT = """\
You are a resilient data-fetching agent. Your task is to retrieve valid data
from an unreliable server and submit it.

## How it works

1. Call `get_problem` to receive the task description.
2. Call `fetch_data` to get a server response. Each response contains:
   - A **factual claim** (a common-sense statement)
   - A **data record**
   If the claim is **factually correct**, the data is valid — extract the
   data record and submit it. If the claim is **factually wrong**, the data
   is garbage — you must retry.
3. You may call `fetch_data` up to 4 times total. Between calls you MUST
   respect exponential backoff:
   - Before 2nd attempt: wait at least 10 seconds
   - Before 3rd attempt: wait at least 20 seconds
   - Before 4th attempt: wait at least 40 seconds
   Use the `wait` tool to sleep.
4. If all 4 claims are wrong (none factually correct), call `submit`
   with an empty string — finding nothing is a valid outcome.
5. Call `submit` with the data record string (just the data portion,
   NOT the full response text).

## Important

- Verify each claim using your own knowledge — there are NO error keywords.
- Extract the data record precisely as it appears in the response.
- The data appears after labels like "Record:", "Attached payload:",
  "Scraped data follows >>", "Data block:", "Extracted record:", or
  "Result payload >>".
- Only call `submit` once.
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

    agent = Agent(config, max_iterations=15)

    agent.add_tool(Tool(
        name="get_problem",
        description="Get the task description for this test case.",
        function=lambda: env.get_problem(),
        parameters={"type": "object", "properties": {}},
    ))

    agent.add_tool(Tool(
        name="fetch_data",
        description=(
            "Fetch data from the unreliable server. Returns a response "
            "containing a factual claim and a data record. If the claim "
            "is factually correct, the data is valid. If wrong, retry. "
            "Maximum 4 calls total."
        ),
        function=lambda: env.fetch_data(),
        parameters={"type": "object", "properties": {}},
    ))

    agent.add_tool(Tool(
        name="submit",
        description=(
            "Submit the data record. Pass the data portion from a response "
            "with a correct claim, or an empty string if all 4 claims were "
            "wrong. Returns 'correct' or 'wrong: <reason>'."
        ),
        function=lambda data: env.submit(data=data),
        parameters={
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "The data record to submit (or empty string if nothing found)",
                },
            },
            "required": ["data"],
        },
    ))

    agent.add_tool(Tool(
        name="wait",
        description=(
            "Wait for a specified number of seconds. Use this for "
            "exponential backoff between fetch_data retries."
        ),
        function=lambda seconds: (time.sleep(float(seconds)), "waited")[1],
        parameters={
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "Number of seconds to wait",
                },
            },
            "required": ["seconds"],
        },
    ))

    agent.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Begin the task. Start by calling get_problem."},
    ])
