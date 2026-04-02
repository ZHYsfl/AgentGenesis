from __future__ import annotations

import os

from tool_calling import Agent, Tool, LLMConfig

CORE_RULES = """\
【绝对核心红线规则——每次行动前必读】
1. **生存第一，绝不瞎玩**：你必须根据环境返回的 observation 中的 phase（当前阶段）和行动提示来操作。
2. **连接红线**：只要 observation 没明确说轮到你对应的专属技能阶段、也没说“轮到你发言”或“请提交有效 vote”，你必须并且只能调用 `connection()`。别人发言、公布信息、或者已出局时，一律 `connection()`！
   - **【出局红线】若 observation 写「你已出局」或「已出局」**，之后所有阶段（DAY_VOTE、DAY_SPEAK 等）你**必须且只能** `connection()`，绝不能调用 `vote`、`speak` 或任何其他工具，否则直接判负！
3. **允许思考（Think & Connection）**：在遇到不该你行动的阶段时，你可以先进行内心逻辑推理（通过思考记录分析局势），然后再调用 `connection()` 进入下一回合。
4. **DAY_SPEAK 发言红线（违反直接判负）**：
   - 同一时刻只有一人能发言。observation 会明确写「轮到你（player_X）发言」或「player_Y 正在发言，请等待」。
   - 只有当 observation 中出现「轮到你」且你的编号与其中 player_X 一致时，才能调用 `speak(text)`。
   - 若出现「正在发言」「请等待」或写的是其他玩家的编号，你必须且只能 `connection()`，绝对不能 `speak()`！多人同时 speak 会导致直接判负。
5. **DAY_VOTE 规则**：
   - 目标只能从 `player_1` 到 `player_6` 中存活的其他人里选。绝对禁止投给自己人或投自己！
   - 第二天开始，如果不提交有效 vote，你将被系统判死！
"""

SECRET_PROTOCOL = """\
【高级好人战术守则】
我们是好人阵营（女巫、预言家、2个村民）。我们绝不使用生硬刻板的暗号，以免引起怀疑或浪费发言机会。我们必须像真正的高阶人类玩家一样通过严密的逻辑推理来合作。请遵守以下博弈战术：

1. **预言家的节奏把控**：
   - 每晚必须查验（check）。
   - 【发金水】：如果你查验到好人，白天发言时用自然的话术力挺他，比如：“我昨天仔细听了 player_X 的发言，觉得他逻辑很正，我认下他是个好人，大家不要怀疑他。” 这样不动声色地保下金水。如果不幸被针对，再被迫跳明预言家身份报查验。
   - 【发查杀】：如果是狼人，白天必须果断强势出击，用尽各种逻辑去踩死他，比如：“player_Y 昨天的发言漏洞百出，明显是在转移视线，我强烈建议今天全票出他。”
   - **重要**：若你被集火投票，遗言时务必明跳预言家并报出查验结果（金水/查杀），给好人留下关键信息。

2. **女巫的局势判断**：
   - 首夜如有死者，必须用解药 `save()`。
   - 毒药 `poison()` 是终极武器。绝对不要在局势不明朗时盲毒！但当预言家遗言已报查杀、或白天某人被多人一致认定为狼时，夜晚务必考虑 `poison(target)` 毒掉他，否则狼人多活一轮好人会崩盘。
   - 白天发言要根据局势来，必要时可以说“昨晚平安夜，我的解药已经用了”，震慑狼人。

3. **村民的高阶伪装与煽动**：
   - 不要只是干巴巴地说“我是个好人，请大家相信我”。
   - 要主动去踩那些发言划水、逻辑矛盾的玩家：“我觉得 player_W 刚刚那番话毫无营养，像是在隐瞒身份。大家多注意他。”
   - 若某人保了一个还没发言的人，可能是预言家发金水，不要轻易跟风票预言家！先听被保的人表水。
   - 如果发现场上有人带起了节奏，评估他是不是真神职（如果他的目标和你的判断一致，就果断跟票；如果他像是在乱踩，你就要勇敢站出来质疑他）。

4. **投票铁律**：
   - 决不闭眼乱投。如果某人被几个玩家（像是在打配合）集火投票了，你要么果断跟上（如果你觉得他是狼），要么呼吁大家冷静。
   - 第一天不要轻易票出“保人”的玩家——他可能是预言家在隐晦发金水，票错预言家好人必崩。
   - 注意第二天及以后的强制投票规则，别因为忘了弃票导致自己被系统判死。
"""


def _make_config() -> LLMConfig:
    return LLMConfig(
        api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or "",
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        base_url=os.getenv("LLM_BASE_URL") or "https://api.deepseek.com",
    )


def _make_agent() -> Agent:
    return Agent(_make_config())


def _loop_chat(agent: Agent, role_prompt: str) -> None:
    # system 存规则，外加一条 user 确立开局状态
    observations = [
        {"role": "system", "content": role_prompt},
        {"role": "user", "content": f"{role_prompt}\n\n游戏即将开始。第一轮（SYNC 阶段）必须调用 connection() 进入游戏；之后根据工具返回的 observation 中的 phase 决定行动。"},
    ]
    while True:
        try:
            observations = agent.chat(observations)
            observations.append(
                {
                    "role": "user",
                    "content": (
                        "请仔细阅读上面工具返回的 observation，判断当前阶段和是否轮到你行动。"
                        " 如果不是你的行动回合或你已出局，调用 connection()。"
                        " 如果轮到你，调用对应工具。"
                    ),
                }
            )
        except StopIteration:
            break


def solve_witch(env):
    agent = _make_agent()
    agent.add_tool(
        Tool(
            name="save",
            description="女巫救人",
            function=env.save,
            parameters={"type": "object", "properties": {}},
        )
    )
    agent.add_tool(
        Tool(
            name="poison",
            description="女巫毒人",
            function=env.poison,
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "毒杀目标公开编号（player_x）"}
                },
                "required": ["target"],
            },
        )
    )
    agent.add_tool(
        Tool(
            name="speak",
            description="白天发言（仅在 observation 说轮到你发言时调用，否则用 connection）",
            function=env.speak,
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    )
    agent.add_tool(
        Tool(
            name="vote",
            description="白天投票",
            function=env.vote,
            parameters={
                "type": "object",
                "properties": {"target": {"type": "string", "description": "投票目标公开编号（player_1..player_6）"}},
                "required": ["target"],
            },
        )
    )
    agent.add_tool(
        Tool(
            name="connection",
            description="等待/跳过：不是你的行动回合、你已出局、或你选择不行动时调用",
            function=env.connection,
            parameters={"type": "object", "properties": {}},
        )
    )

    _loop_chat(
        agent,
        (
            "你是好人阵营的【女巫】。为了获胜，请严格遵守以下各阶段的具体行动指南，在行动前可以先思考局势：\n\n"
            "【阶段行动指南】\n"
            "- SYNC（游戏开始）：第一轮必须调用 `connection()` 进入游戏。\n"
            "- NIGHT_WOLF（狼人杀人）：不是你的回合。你可以思考谁最可疑，然后调用 `connection()` 等待。\n"
            "- NIGHT_WITCH（女巫阶段）：这是你的回合！observation 会告诉你昨晚谁被刀；首夜被刀哪怕是自己也强制使用 `save()` 救人！如果你觉得某人肯定是狼（比如预言家白天刚查杀了他但没票死），就调用 `poison(target)` 毒他。如果不救也不毒，必须调用 `connection()`。\n"
            "- NIGHT_SEER（预言家查验）：不是你的回合。思考局势后调用 `connection()`。\n"
            "- DAY_ANNOUNCE（公布死讯）：只听播报。思考局势后调用 `connection()`。\n"
            "- DAY_SPEAK（顺序发言）：当且仅当提示轮到你发言时，调用 `speak(text)` 引导局势。如果别人的回合，必须调用 `connection()`。\n"
            "- DAY_VOTE（白天投票）：如果你决定票死谁，调用 `vote(target)`；如果想弃票观察（仅限第一天），调用 `connection()`。\n"
            "- DAY_LAST_WORDS（遗言）：不是你的回合，调用 `connection()`。\n"
            f"\n{SECRET_PROTOCOL}\n{CORE_RULES}"
        ),
    )


def solve_seer(env):
    agent = _make_agent()
    agent.add_tool(
        Tool(
            name="check",
            description="预言家查验身份",
            function=env.check,
            parameters={
                "type": "object",
                "properties": {"target": {"type": "string", "description": "查验目标公开编号（player_1..player_6）"}},
                "required": ["target"],
            },
        )
    )
    agent.add_tool(
        Tool(
            name="speak",
            description="白天发言（仅在 observation 说轮到你发言时调用，否则用 connection）",
            function=env.speak,
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    )
    agent.add_tool(
        Tool(
            name="vote",
            description="白天投票",
            function=env.vote,
            parameters={
                "type": "object",
                "properties": {"target": {"type": "string", "description": "投票目标公开编号（player_1..player_6）"}},
                "required": ["target"],
            },
        )
    )
    agent.add_tool(
        Tool(
            name="connection",
            description="等待/跳过：不是你的行动回合、你已出局、或你选择不行动时调用",
            function=env.connection,
            parameters={"type": "object", "properties": {}},
        )
    )

    _loop_chat(
        agent,
        (
            "你是好人阵营的【预言家】。为了获胜，请严格遵守以下各阶段的具体行动指南，在行动前可以先思考局势：\n\n"
            "【阶段行动指南】\n"
            "- SYNC（游戏开始）：第一轮必须调用 `connection()` 进入游戏。\n"
            "- NIGHT_WOLF（狼人杀人）/ NIGHT_WITCH（女巫阶段）：不是你的回合。你可以思考谁最可疑，然后调用 `connection()` 等待。\n"
            "- NIGHT_SEER（预言家查验）：这是你的回合！你必须调用 `check(target)` 查验场上存活的某个玩家身份。\n"
            "- DAY_ANNOUNCE（公布死讯）：只听播报。思考局势后调用 `connection()`。\n"
            "- DAY_SPEAK（顺序发言）：当且仅当提示轮到你发言时，调用 `speak(text)` 报查验引导局势（报金水或报查杀）。如果别人的回合，必须调用 `connection()`。\n"
            "- DAY_VOTE（白天投票）：带领好人投票，调用 `vote(target)` 发起冲锋；绝不能投金水。\n"
            "- DAY_LAST_WORDS（遗言）：不是你的回合，调用 `connection()`。\n"
            f"\n{SECRET_PROTOCOL}\n{CORE_RULES}"
        ),
    )


def _solve_villager_common(env, villager_name: str):
    agent = _make_agent()
    agent.add_tool(
        Tool(
            name="speak",
            description="白天发言（仅在 observation 说轮到你发言时调用，否则用 connection）",
            function=env.speak,
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    )
    agent.add_tool(
        Tool(
            name="vote",
            description="白天投票",
            function=env.vote,
            parameters={
                "type": "object",
                "properties": {"target": {"type": "string", "description": "投票目标公开编号（player_1..player_6）"}},
                "required": ["target"],
            },
        )
    )
    agent.add_tool(
        Tool(
            name="connection",
            description="等待/跳过：不是你的行动回合、你已出局、或你选择不行动时调用",
            function=env.connection,
            parameters={"type": "object", "properties": {}},
        )
    )

    _loop_chat(
        agent,
        (
            f"你是好人阵营的【{villager_name}】。为了获胜，请严格遵守以下各阶段的具体行动指南，在行动前可以先思考局势：\n\n"
            "【阶段行动指南】\n"
            "- SYNC（游戏开始）：第一轮必须调用 `connection()` 进入游戏。\n"
            "- 所有夜晚阶段（NIGHT_WOLF/NIGHT_WITCH/NIGHT_SEER）：你没有任何技能！所以你只能在心里分析谁最有可能是狼，然后强行必须调用 `connection()` 继续睡觉！\n"
            "- DAY_ANNOUNCE（公布死讯）：只听播报。听取死讯后整理思路，然后调用 `connection()`。\n"
            "- DAY_SPEAK（顺序发言）：当且仅当提示\"轮到你发言\"时，调用 `speak(text)` 参与讨论，找狼、表水、跟票。如果没轮到你发言，必须调用 `connection()` 听别人秀。\n"
            "- DAY_VOTE（白天投票）：如果你决定跟随神明票死谁，调用 `vote(target)`；如果想弃票观察（仅限第一天），调用 `connection()`。\n"
            "- DAY_LAST_WORDS（遗言）：不是你的回合，调用 `connection()`。\n"
            f"\n{SECRET_PROTOCOL}\n{CORE_RULES}"
        ),
    )


def solve_villager_1(env):
    _solve_villager_common(env, "村民1")


def solve_villager_2(env):
    _solve_villager_common(env, "村民2")
