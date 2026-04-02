from __future__ import annotations

import json
import os
from tool_calling import Agent, Tool, LLMConfig


def solve(env):
    config = LLMConfig(
        api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "",
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        base_url=os.getenv("LLM_BASE_URL") or "https://api.deepseek.com",
    )
    agent = Agent(config)

    def get_question() -> str:
        return env.get_question()

    def validate_json(json_str: str) -> str:
        try:
            json.loads(json_str)
            return "true"
        except Exception:
            return "false"

    def submit_answer(answer: str) -> str:
        return env.submit_answer(answer)

    agent.add_tool(
        Tool(
            name="get_question",
            description=(
                "Fetch the structured-output question. "
                "Returns the full question text describing the required JSON."
            ),
            function=get_question,
            parameters={"type": "object", "properties": {}, "required": []},
        )
    )

    agent.add_tool(
        Tool(
            name="validate_json",
            description=(
                "Validate whether a string is valid JSON. "
                "Returns 'true' or 'false'. "
                "Always call this before submit_answer."
            ),
            function=validate_json,
            parameters={
                "type": "object",
                "properties": {
                    "json_str": {
                        "type": "string",
                        "description": "The JSON string to validate.",
                    }
                },
                "required": ["json_str"],
            },
        )
    )

    agent.add_tool(
        Tool(
            name="submit_answer",
            description=(
                "Submit your final answer as a clean JSON string (no markdown fences). "
                "Returns 'correct' or 'wrong'. Only call after validate_json returns VALID."
            ),
            function=submit_answer,
            parameters={
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "The clean JSON string to submit.",
                    }
                },
                "required": ["answer"],
            },
        )
    )

    observations = [
        {
            "role": "system",
            "content": (
                "You are a structured-output assistant. You have three tools:\n"
                "- get_question(): returns the question text.\n"
                "- validate_json(json_str): checks if a string is valid JSON, returns 'true' or 'false'.\n"
                "- submit_answer(answer): submits your final JSON answer, returns 'correct' or 'wrong'.\n\n"
                "Follow these steps EXACTLY:\n"
                "1. Call get_question() to retrieve the question.\n"
                "2. Read the question carefully. It describes a JSON object you must produce.\n"
                "3. Construct the JSON string. It must be raw JSON — no markdown fences like "
                "```json```, no extra text, no comments.\n"
                "4. Call validate_json(json_str=<your_json>) to verify it parses correctly.\n"
                "   - If 'true': the JSON is syntactically valid, proceed to step 5.\n"
                "   - If 'false': your JSON has a syntax error. Think about what went wrong "
                "(missing quotes, trailing comma, wrong brackets, etc.), fix it, "
                "and call validate_json again. Repeat until you get 'true'.\n"
                "5. Call submit_answer(answer=<your_json>) with the validated JSON string.\n\n"
                "Rules:\n"
                "- Key names, string values, booleans (true/false), null, and numbers must "
                "match the question's requirements EXACTLY.\n"
                "- Use the most compact JSON form (no extra whitespace) unless the question "
                "explicitly specifies pretty-printing.\n"
                "- You only get ONE submission per question, so make sure validate_json "
                "returns 'true' before you submit."
            ),
        },
        {
            "role": "user",
            "content": "Please fetch the question, validate your JSON, and submit the answer.",
        },
    ]

    _ = agent.chat(observations)
    return
