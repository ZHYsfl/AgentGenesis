"""Reference solution for Parallel Weather Query.

LLM calls tools and extracts numeric values from NL responses:
  1. get_weather / get_humidity to query data (4 calls in parallel)
     — each returns a randomized natural language sentence
  2. LLM extracts the numeric value from each sentence
  3. submit_answer to submit the result (1 call)

5 questions run as 5 parallel Agent.chat() sessions via batch().
"""

from __future__ import annotations

import asyncio
import json
import os

from tool_calling import Agent, Tool, LLMConfig, batch


def solve(env):
    model_name = os.getenv("LLM_MODEL", "deepseek-chat")
    # Kimi supports "thinking: disabled" via extra_body.
    extra_body = {"thinking": {"type": "disabled"}}

    config = LLMConfig(
        api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "",
        model=model_name,
        base_url=os.getenv("LLM_BASE_URL") or "https://api.deepseek.com",
        extra_body=extra_body,
    )

    questions_raw = env.get_questions()
    questions = json.loads(questions_raw)

    get_weather_tool = Tool(
        name="get_weather",
        description="Get the temperature of a city. Returns a natural language sentence containing the temperature value. Extract the numeric value from the sentence.",
        function=env.get_weather,
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        },
    )

    get_humidity_tool = Tool(
        name="get_humidity",
        description="Get the humidity of a city. Returns a natural language sentence containing the humidity value. Extract the numeric value from the sentence. This is an async function.",
        function=env.get_humidity,
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        },
    )

    submit_answer_tool = Tool(
        name="submit_answer",
        description="Submit the answer for one question. Call this after getting all 4 values.",
        function=env.submit_answer,
        parameters={
            "type": "object",
            "properties": {
                "q_index": {"type": "integer", "description": "Question index"},
                "city_a_temperature": {"type": "number", "description": "Temperature of city_a"},
                "city_a_humidity": {"type": "number", "description": "Humidity of city_a"},
                "city_b_temperature": {"type": "number", "description": "Temperature of city_b"},
                "city_b_humidity": {"type": "number", "description": "Humidity of city_b"},
            },
            "required": [
                "q_index",
                "city_a_temperature",
                "city_a_humidity",
                "city_b_temperature",
                "city_b_humidity",
            ],
        },
    )

    agent = Agent(config, max_tool_retries=2, debug=False)
    agent.add_tool(get_weather_tool)
    agent.add_tool(get_humidity_tool)
    agent.add_tool(submit_answer_tool)

    all_observations: list[list[dict]] = []
    for q in questions:
        q_idx = q["q_index"]
        city_a = q["city_a"]
        city_b = q["city_b"]
        obs = [
            {
                "role": "system",
                "content": (
                    "You are a weather query assistant. You MUST use tools to get data. "
                    "Do NOT guess values.\n\n"
                    "Steps:\n"
                    "1. Call get_weather and get_humidity for BOTH cities "
                    "(4 tool calls in one request)\n"
                    "2. The tools return natural language sentences. Extract the "
                    "numeric value from each response (watch for arithmetic like "
                    "'base X + offset Y = Z' — use the final value Z).\n"
                    "3. Call submit_answer with all 4 extracted values\n\n"
                    "That's it. No text output needed."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question {q_idx}: Get temperature and humidity for "
                    f"{city_a} (city_a) and {city_b} (city_b), "
                    f"then submit_answer with q_index={q_idx}."
                ),
            },
        ]
        all_observations.append(obs)

    asyncio.run(batch(agent, all_observations, max_concurrent=5))
