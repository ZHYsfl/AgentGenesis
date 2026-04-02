import os
import asyncio
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SDK_DIR = CURRENT_DIR.parent
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from async_tool_calling import Agent, Tool, LLMConfig
from dotenv import load_dotenv
load_dotenv(override=True)

# Tool Environment
def get_weather(city: str) -> str: # Tool Action
    return f"The weather in {city} is sunny, temperature 20C, humidity 50%, wind level 2, air quality excellent." # Tool Observation

async def main():
    config = LLMConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        model=os.getenv("MODEL"),
        base_url=os.getenv("BASE_URL")
    )
    agent = Agent(config)
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
    agent.add_tool(tool)
    observations = [{"role": "user", "content": "Please get the weather for Beijing and Hangzhou, call get_weather for both in parallel"}]
    observations_final = await agent.chat(observations)
    print(observations_final)

if __name__ == "__main__":
    asyncio.run(main())