"""Wolf NPC AI -- runs in wolf sandboxes (Judge-provided code).

Two entry points: solve_wolf_1(env) and solve_wolf_2(env).
Each uses the synchronous Agent with tool calling to play as a wolf.

Strategy:
- Night: kill seer/witch first if suspected, otherwise random good player
- Day speak: blend in as a villager, deflect suspicion
- Day vote: coordinate to vote against the most threatening good player
"""

from __future__ import annotations

import os
from typing import Any

from tool_calling import Agent, Tool, LLMConfig

PLAYER_ID_RULE = (
    "所有可选目标编号范围是 player_1 到 player_6。"
    " 凡是需要 target 的工具，都必须传这个范围内的 player_x。"
)
DEAD_CONNECTION_RULE = (
    "如果你已出局，或当前阶段不该你行动，必须调用 connection()，"
    " 不要调用其他工具。"
)


WOLF_SYSTEM_PROMPT = """\
你是一个狼人杀游戏中的【狼人】。你的目标是隐藏身份，杀掉所有好人（只要狼人数量大于等于好人数量即获胜）。

【绝对红线规则】
你必须根据游戏环境返回的 target/phase 来操作，绝对不能盲目猜测或者一直调死循环！
1. **SYNC（游戏开始）**：第一轮所有人必须调用 `connection()` 进入游戏，工具会返回 NIGHT_WOLF 信息。
2. **【出局红线】如果你已出局**，之后所有阶段（包括 DAY_VOTE、DAY_SPEAK 等）你**必须且只能**调用 `connection()`！绝对不能调用 `vote`、`speak` 或任何其他工具，否则直接判负！observation 会写「你已出局」或「已出局」。
3. **如果当前不是你的行动回合**，你必须且只能调用 `connection()`，任何其他调用都会导致你直接被系统判死！
   - 白天（如果是别人发言、投死公布等环节），只能 `connection()`。
   - 夜晚：**虽然是夜晚，但如果是女巫阶段（NIGHT_WITCH）或预言家阶段（NIGHT_SEER），你必须调用 `connection()` 等待！**

【狼人允许的操作环节】
- **NIGHT_WOLF 阶段（狼人夜晚杀人）**：你必须必须使用 `kill(target)` 尝试杀人。目标 public ID 为 player_1 到 player_6。
  - **【绝对禁止】**：target 必须是**除你本人和同伴外的**存活玩家！环境会告诉你「你的编号」和「你的狼人同伴编号」，绝不能选这两个编号，否则视为无效、游戏直接结束！
  - **重要逻辑**：如果你和同伴选择了不同的目标，系统会随机从你们的选择中挑选一个作为最终击杀目标。因此，你可以根据直觉行动，无需担心与同伴冲突。
- **DAY_SPEAK 阶段（白天发言，红线）**：同一时刻只有一人能发言！只有当 observation 明确写「轮到你（player_X）发言」且你的编号就是该 player_X 时，才能调用 `speak(text)`。若写的是「player_Y 正在发言，请等待」或其他人编号，你必须 `connection()`，绝不能 speak，否则直接判负！
- **DAY_VOTE 阶段（白天投票）**：**仅当你存活时**才可调用 `vote(target)`。若你已出局，必须 `connection()`，绝不能 vote！

【生存策略】
- 第一夜 `NIGHT_WOLF`，观察中会写明「你的编号」和「同伴编号」，从存活玩家里选一个**既不是你也不是同伴**的 player_x 作为 target。必须调用 `kill`！
- 白天装好人，可以胡乱分析或者跟风踩人。如果有人针对你，你可以悍跳预言家。
"""

def _make_config() -> LLMConfig:
    return LLMConfig(
        api_key=os.getenv("LLM_API_KEY"),
        model=os.getenv("LLM_MODEL"),
        base_url=os.getenv("LLM_BASE_URL"),
    )


def _make_agent() -> Agent:
    return Agent(_make_config())


def _loop_chat(agent: Agent, role_prompt: str) -> None:
    first_msg = (
        f"{role_prompt}\n\n游戏即将开始。"
        "请先调用 connection() 进入游戏，工具会返回当前阶段信息。"
        "进入 NIGHT_WOLF 阶段后，根据返回的编号和同伴信息立刻调用 kill(target)。"
    )
    observations = [
        {"role": "system", "content": role_prompt},
        {"role": "user", "content": first_msg},
    ]
    while True:
        try:
            observations = agent.chat(observations)
            observations.append(
                {
                    "role": "user",
                    "content": "游戏仍在进行，请根据环境信息调用对应工具继续游戏。",
                }
            )
        except StopIteration:
            break


def _target_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"target": {"type": "string", "description": description}},
        "required": ["target"],
    }


def _text_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"text": {"type": "string", "description": description}},
        "required": ["text"],
    }


WOLF_TOOL_SPECS = [
    ("kill", "夜晚选择杀人目标（target 必须是除你本人和同伴外的存活玩家，绝不能选自己或同伴的编号）", "kill", _target_schema("要杀的好人玩家编号 player_x，必须排除你自己和同伴的编号")),
    ("speak", "白天发言", "speak", _text_schema("发言内容")),
    ("vote", "投票淘汰某人", "vote", _target_schema("投票目标公开编号（player_1..player_6）")),
    ("connection", "等待/跳过当前阶段", "connection", {"type": "object", "properties": {}}),
]


def _register_wolf_tools(agent: Agent, env) -> None:
    for name, description, env_attr, parameters in WOLF_TOOL_SPECS:
        agent.add_tool(
            Tool(
                name=name,
                description=description,
                function=getattr(env, env_attr),
                parameters=parameters,
            )
        )


def _solve_wolf_common(env) -> None:
    agent = _make_agent()
    _register_wolf_tools(agent, env)
    _loop_chat(
        agent,
        f"{WOLF_SYSTEM_PROMPT}\n\n{PLAYER_ID_RULE} {DEAD_CONNECTION_RULE}",
    )


def solve_wolf_1(env) -> None:
    _solve_wolf_common(env)


def solve_wolf_2(env) -> None:
    _solve_wolf_common(env)
