import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SDK_DIR = CURRENT_DIR.parent
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from batch import batch
from async_tool_calling import Agent, Tool, LLMConfig
from dotenv import load_dotenv
load_dotenv(override=True)
import os
import asyncio

from example.get_weather import get_weather

tool = Tool(
    name="get_weather",
    description="Get weather information",
    function=get_weather,
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name"
            }
        },
        "required": ["city"]
    }
)


async def main():
    agent = Agent(LLMConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        model=os.getenv("MODEL"),
        base_url=os.getenv("BASE_URL")
    ))
    agent.add_tool(tool)
    observations = [[{"role": "user", "content": "Please tell me the weather in Beijing and Hangzhou, call get_weather for both in parallel"}] for _ in range(50)]
    observations_final = await batch(agent, observations, max_concurrent=50)
    for observation in observations_final:
        print(observation[-1]["content"])
        print("-"*100)

if __name__ == "__main__":
    asyncio.run(main())