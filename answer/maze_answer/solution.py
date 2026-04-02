from __future__ import annotations

import os
from tool_calling import Agent, Tool, LLMConfig

def solve(move):
    # 1) 创建 Agent
    config = LLMConfig(
        api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "",
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        base_url=os.getenv("LLM_BASE_URL") or "https://api.deepseek.com",
    )
    agent = Agent(config)

    # 3) 注册 maze_move 工具（包装评测器传入的 move）
    def maze_move(direction: str) -> str:
        return str(move(direction))

    agent.add_tool(
        Tool(
            name="maze_move",
            description="在迷宫中移动一步，direction 只能是 up/down/left/right",
            function=maze_move,
            parameters={
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                        "description": "移动方向",
                    }
                },
                "required": ["direction"],
            },
        )
    )

    # 4) 一次 chat（内部自动多轮 tool-calling）
    observations = [
        {
            "role": "system",
            "content": (
                "你在迷宫中寻路，只能用 maze_move(direction) 行动。\n\n"
                "**规划要求**：\n"
                "1.  mentally 记录已尝试的方向和结果（墙/成功）\n"
                "2. 优先探索未走过的方向，避免在同一区域打转\n"
                "3. 若某方向撞墙，记住并换其他方向\n"
                "4. 反馈中出现「恭喜」「终点」「出口」即成功，立即停止\n\n"
                "开始探索。"
            ),
        },
        {
            "role": "user",
            "content": "找到出口",
        }
    ]

    _ = agent.chat(observations)
    return