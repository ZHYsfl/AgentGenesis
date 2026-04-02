"""Reference solution for The Short-Circuit Scraper.

Strategy:
1. get_user() to obtain target name.
2. Dispatch 10 scraper agents in parallel via ThreadPoolExecutor.
3. Short-circuit on the first valid result using as_completed.
4. Use LLM (tool-calling Agent) to extract email + member_id from fuzzy text.
5. cancel() to cascade-terminate remaining scrapers.
6. submit(email, member_id) within 25s deadline.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from tool_calling import Agent, Tool, LLMConfig

SYSTEM_PROMPT = """\
You are a data extraction assistant. You will receive a block of free-form,
natural-language user profile text. Your job is to extract exactly two fields:

1. **email** — the user's email address
2. **member_id** — the user's membership / account ID

Call the extract_fields tool with the extracted values. Be precise:
- Email must be the exact email address (e.g. "alice.johnson@gmail.com")
- Member ID must be the exact ID string as it appears (e.g. "MEM-48201", "USR_7293XZ")

Do NOT guess or fabricate. Extract only what is explicitly present in the text.
"""

NUM_ENDPOINTS = 10


def _build_llm_config() -> LLMConfig:
    return LLMConfig(
        api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "",
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        base_url=os.getenv("LLM_BASE_URL") or "https://api.deepseek.com",
        extra_body={"enable_thinking": False},
    )


def _llm_extract(profile_text: str, config: LLMConfig) -> tuple[str, str]:
    """Use LLM tool-calling to extract email and member_id from fuzzy text."""
    extracted = {}

    def extract_fields(email: str, member_id: str) -> str:
        extracted["email"] = email
        extracted["member_id"] = member_id
        return "Fields extracted successfully."

    agent = Agent(config, max_iterations=3)
    agent.add_tool(Tool(
        name="extract_fields",
        description=(
            "Submit the extracted email and member_id from the profile text. "
            "Both fields must be exact strings as they appear in the text."
        ),
        function=extract_fields,
        parameters={
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "The user's email address extracted from the profile",
                },
                "member_id": {
                    "type": "string",
                    "description": "The user's membership/account ID extracted from the profile",
                },
            },
            "required": ["email", "member_id"],
        },
    ))

    agent.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Extract email and member_id from this profile:\n\n{profile_text}"},
    ])

    return extracted.get("email", ""), extracted.get("member_id", "")


def solve(env):
    config = _build_llm_config()
    user_name = env.get_user()

    with ThreadPoolExecutor(max_workers=NUM_ENDPOINTS) as executor:
        futures = {
            executor.submit(env.get_info, user_name, str(i)): i
            for i in range(NUM_ENDPOINTS)
        }

        for future in as_completed(futures):
            result = future.result()
            if not result.startswith("Error"):
                email, member_id = _llm_extract(result, config)
                env.cancel()
                env.submit(email=email, member_id=member_id)
                return
