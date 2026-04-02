"""Werewolf problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class WerewolfConfig(PhaseConfig):
    """Werewolf-specific problem configuration."""

    # =========== PhaseConfig builtin fields (explicit) ===========
    phase_name: str = ""
    phase_type: str = "agent"
    phase_order: int = 1
    phase_level: str = "Hard"
    max_code_size: int = 1000000
    description: str = ""
    starter_code: str = ""
    evaluator_module: str = "agent_genesis.isolated_evaluator"
    evaluator_class: str = "IsolatedMultiAgentEvaluator"
    num_cases: int = 3
    min_passed_cases: Optional[int] = 2  # Pass when at least one case wins
    parallel_cases: int = 1
    sandbox_cpu_count: int = 0
    memory_limit_mb: int = 0
    sandbox_timeout: int = 3000
    case_idle_timeout: int = 120
    user_deps_timeout: int = 120
    chmod_timeout: int = 10
    run_timeout: int = 180
    pip_dependencies: list[str] = ["openai", "pydantic"]
    allowed_packages: list[str] = []
    artifact_url: str = ""
    artifact_checksum: str = ""
    artifact_size: int = 0
    artifact_entry: str = "sandbox/run.py"
    judge_envs: dict[str, str] = {}
    allow_user_key: bool = False
    artifact_base64: str = ""
    user_bridge: str = ""
    adapter_preset: str = "isolated_werewolf"
    solve_attr_name: str = "solve_witch"
    private_files: Optional[list[str]] = []
    gateway_max_chars: int = 100000000
    gateway_max_requests: int = 2000
    gateway_ttl_minutes: int = 30
    gateway_allowed_models: list[str] = []

    # =========== Werewolf custom extension fields ===========
    # NOTE:
    # - `time_limit` / `max_rounds` / `seed` are consumed by sandbox/run.py.
    # - The isolated-multi-agent fields below are consumed by:
    #   evaluation/isolated_evaluator.py and evaluation/runtime/isolated_session.py.
    seed: Optional[int] = None
    max_rounds: int = 15
    time_limit: float = 2500.0
    agent_ids: list[str] = [
        "wolf_1", "wolf_2", "seer", "witch", "villager_1", "villager_2",
    ]
    npc_agent_ids: list[str] = ["wolf_1", "wolf_2"]
    npc_code_prefix: str = "wolf_agent/"
    solve_entry_map: dict[str, str] = {
        "wolf_1": "solve_wolf_1",
        "wolf_2": "solve_wolf_2",
        "witch": "solve_witch",
        "seer": "solve_seer",
        "villager_1": "solve_villager_1",
        "villager_2": "solve_villager_2",
    }


# =========== Localized content ===========

WEREWOLF_OVERVIEW_EN = (
    "Werewolf multi-agent game: control Witch, Seer, and Villagers "
    "to defeat wolves under asymmetric information."
)

WEREWOLF_OVERVIEW_ZH = (
    "狼人杀多智能体博弈：操控女巫、预言家、村民三种好人角色，"
    "在信息不对称的环境下通过推理和策略击败狼人。"
)

WEREWOLF_BACKGROUND_EN = """
# Werewolf Multi-Agent Background

Werewolf is a classic social deduction game with hidden identities and asymmetric information.

## Setup
- 6 players total:
  - 2 wolves (system-controlled NPC agents)
  - 1 seer, 1 witch, 2 villagers (implemented by you)
- You must implement four independent agents:
  - `solve_witch`, `solve_seer`, `solve_villager_1`, `solve_villager_2`

## Round flow
**Game start**: The first action_request requires all 6 agents to call `connection()` to enter the game. The Judge then sends phase-specific observations; each agent receives their own obs based on role.

Each round has a night and a day phase:

### Night
1. Wolves choose a kill target.
2. Witch decides whether to save / poison / skip.
3. Seer checks one player's identity.

### Day
1. Night deaths are announced.
2. Alive players speak in turn.
3. Voting lasts up to 3 rounds:
   - Voted players can update vote by calling `vote(target)` in later rounds.
   - On day 1, all three rounds may end with no vote.
   - From day 2 onward, round 3 requires an effective vote for anyone still without one.
4. Eliminated player gives last words.

## Win conditions
- Good side wins if all wolves are eliminated.
- Wolf side wins when alive wolves >= alive good players.

## Scoring & Pass rules
- **Pass**: If the game ends with a real winner (either good or wolf wins). **Fail** only when the game ends abnormally (e.g., an agent called the wrong tool, such as non-speaker calling `speak`, or dead player calling `vote`).
- **Score per case**:
  - **100**: Good side wins (all wolves eliminated).
  - **50**: Wolf side wins (wolves >= good).
  - **0**: Abnormal end (agent error).

## Isolation
Each role runs in a dedicated sandbox process.
Private information cannot be shared across roles outside game actions.
""".strip()

WEREWOLF_BACKGROUND_ZH = """
# 狼人杀多智能体背景知识

狼人杀是一个经典的多人社交推理游戏，考验玩家的推理能力、欺骗技巧和社交策略。

## 游戏设置
- 6名玩家：2只狼人（系统AI控制）、1个预言家、1个女巫、2个村民（你控制）
- 你需要为女巫、预言家、村民1、村民2各写一个独立的AI策略

## 游戏流程
**游戏开始**：第一个 action_request 时，6 个 agent 必须都先调用 `connection()` 进入游戏，Judge 收到后下发各角色对应的 observation（信息按角色隔离）。

每一轮分为夜晚和白天：

### 夜晚（按顺序执行）
1. **狼人阶段**：狼人选择杀人目标（系统AI），其他人等待
2. **女巫阶段**：女巫得知谁被杀，可选择救人/毒人/跳过
3. **预言家阶段**：预言家查验一名玩家的身份

### 白天
1. **公布信息**：宣布昨晚死亡情况
2. **发言**：每个存活玩家轮流发言
3. **投票**：最多3轮投票；已投票玩家后续轮次可改票或保持不变；首个白天（第1天）允许三轮都不投；从第2天起第3轮未形成有效票者必须提交有效票（目标需为其他存活玩家）；最终淘汰得票最多的人
4. **遗言**：被淘汰者发表遗言

## 胜利条件
- 好人胜利：所有狼人被淘汰
- 狼人胜利：狼人数量 >= 好人数量

## 得分与通过规则
- **通过**：游戏正常结束（好人或狼人获胜）。**不通过**仅当游戏异常结束（如 agent 调错工具：非发言者调用 `speak`、出局者调用 `vote` 等）。
- **单用例得分**：
  - **100**: 好人获胜（所有狼人出局）
  - **50**: 狼人获胜（狼人数量 ≥ 好人数量）
  - **0**: 异常结束（agent 错误）

## 信息隔离
每个角色运行在独立的沙箱中，严格禁止角色间共享私密信息。
预言家的查验结果只有预言家自己知道，女巫的用药信息只有女巫自己知道。
""".strip()

PHASE1_DESCRIPTION_EN = """
# Werewolf: Multi-Agent Social Deduction

Implement 4 independent AI Agents controlling the Witch, Seer, Villager 1, and Villager 2 to play against 2 system-controlled wolf agents. This is a 6-player game (2 wolves, 1 seer, 1 witch, 2 villagers). Your good-side team wins if you manage to vote out both wolves.

## 1. Game Flow & Decision Making

The game environment is **event-driven**. When it's your agent's turn, the environment returns the current state (including recent chatter, alive players, etc.). Your LLM should process this state to decide on an action, and then call the corresponding **tool function**.

- **Wolf Killing Logic**: Each werewolf has one vote for a kill target. If the two wolves choose different players, the system will **randomly select one** as the final result.

### Phase to Tool Mapping

| Phase | Required Actor | Allowed & Effective Tools | Remarks |
|---|---|---|---|
| **SYNC** | (Everyone) | `connection()` | Game start. All 6 agents must call `connection()` to enter; Judge then advances to NIGHT-WOLF and sends obs. |
| **NIGHT-WOLF** | `wolves` | `kill(target)` / `connection()` | Wolves choose a kill target. **If targets differ, one is chosen randomly.** |
| **NIGHT-WITCH** | `witch` | `save()` / `poison(target)` / `connection()` | After wolves kill, witch decides to save or poison. Each potion works once per game. |
| **NIGHT-SEER** | `seer` | `check(target)` / `connection()` | Check a player's identity. Env returns "good" or "wolf". |
| **DAY-ANNOUNCE** | (Everyone) | `connection()` | Night deaths are announced. Skip your turn here. |
| **DAY-SPEAK** | The speaker | `speak(text)` / `connection()` | Players speak sequentially. Skip if it's not your turn. |
| **DAY-VOTE** | **All alive players** | `vote(target)` / `connection()` | **Crucial phase!** See detailed rules below. |
| **DAY-LAST_WORDS**| Eliminated | `speak(text)` / `connection()` | Eliminated player speaks last words; others wait. |

> **CRITICAL RULE**: **If it is NOT your turn, or if you are eliminated, you MUST ONLY call `connection()`! Using any other tool out of turn is illegal.**

## 2. Scoring & Pass Rules

- **Pass**: Game ends with a real winner (good or wolf). **Fail** only when the game ends abnormally (e.g., agent called wrong tool).
- **Score per case**: Good wins 100, Wolf wins 50, Abnormal end 0.

## 3. Voting Rules & Pitfalls

- Voting happens in **up to 3 rounds**. In each round, the environment announces current votes. The phase ends early if everyone has voted.
- **Targets must be other ALIVE players' public IDs** (e.g., `player_1`). Self-voting or voting dead players is illegal.
- **Day 1 Voting (After first night)**:
  - You can skip voting by calling `connection()`. If no effective votes are cast after 3 rounds, no one is eliminated.
- **Day 2+ Voting**:
  - The system FORCES an elimination! **Alive players without a vote MUST submit an effective `vote(target)` by round 3**. Submitting `connection()` or an invalid target leads to an immediate error and agent death!
- **Do NOT vote allies**: Your goal is to find wolves. Do not randomly vote for members of the good side before clarifying identities through discussion.

## 4. Interface Specification

You only need to implement the following 4 functions in `solution.py`. They run in **4 isolated sandbox processes** (No shared memory! No global variables! Agents can only communicate via in-game `speak`):

```python
def solve_witch(env): ...
def solve_seer(env): ...
def solve_villager_1(env): ...
def solve_villager_2(env): ...
```
Each tool call returns the latest environment string. On the first round, all agents must call `connection()` to enter the game; use a loop to feed subsequent obs to your LLM and decide the next action.
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 狼人杀：多角色Agent对抗

实现4个独立的AI Agent，分别控制女巫、预言家、村民1、村民2，与系统控制的2只狼人对抗。这是6人局（2狼，1预言家，1女巫，2平民），好人阵营（即你控制的四个角色）需要把2只狼人全部投出局即可获胜。

## 1. 游戏流程与决策

游戏环境基于**事件驱动**，当轮到你的某个角色行动时，环境会返回当前状态（包含最新发言、存活列表等），你需要根据状态让大语言模型决策，然后调用对应的**工具函数**响应环境。

- **狼人杀人逻辑**：两名狼人各有一票杀人权。如果两人选择的目标不同，系统将从这两个目标中**随机抽取一个**作为最终击杀结果。

### 游戏阶段与允许的工具对照表

| 阶段 | 必须行动的角色 | 可用且有效的工具 | 备注 |
|---|---|---|---|
| **SYNC（游戏开始）** | 所有人 | `connection()` | 第一轮所有 6 人必须 connection() 进入游戏，Judge 收到后进入夜晚-狼人阶段并下发 obs。 |
| **夜晚-狼人** | 狼人阵营 | `kill(target)` / `connection()` | 狼人共同决定杀人目标。**如果选择不一致，系统将随机抽取一个。** 非狼人角色必须 connection()。 |
| **夜晚-女巫** | `witch` (女巫) | `save()` / `poison(target)` / `connection()` | 狼人杀人后，女巫决定是否救人或毒人，一局限用一次。非女巫阶段必须 connection()。 |
| **夜晚-预言家** | `seer` (预言家) | `check(target)` / `connection()` | 查验玩家身份，环境会返回是好人还是狼人。非预言家阶段必须 connection()。 |
| **白天-公布环节** | （所有人） | `connection()` | 系统播报昨夜死讯，此时只需等待。 |
| **白天-发言阶段** | 轮到的发言者 | `speak(text)` / `connection()` | 所有人按顺序逐个发言，没轮到你时必须跳过。|
| **白天-投票阶段** | **所有存活玩家** | `vote(target)` / `connection()` | **最关键阶段**！见下方详细规则。|
| **白天-遗言阶段** | 被淘汰者 | `speak(text)` / `connection()` | 被票死的人发表遗言，其他人等待。|

> **核心红线**：**如果此刻不在你行动的环节，或者你已出局，必须并且只能调用 `connection()` 返回给环境，绝对不能随便乱调其他工具！**

## 2. 得分与通过规则

- **通过**：游戏正常结束（好人或狼人获胜）。**不通过**仅当游戏异常结束（如 agent 调错工具）。
- **单用例得分**：好人胜 100 分，狼人胜 50 分，异常结束 0 分。

## 3. 投票规则与避坑指南

- 投票最多**分3轮**进行。每一轮环境都会告诉你当前谁投了谁。所有人都投过或者到了第3轮即结算。
- **目标（target）必须是其他存活玩家**的公开编号（如 `player_1`），绝对不能投自己或已死玩家。
- **第一天投票（刚度过第一晚）**：
  - 如果白天大家都没能盘出狼人，可以选择调用 `connection()` 不投票（弃票）。如果3轮结束大家都没产生有效票，则无人淘汰，平安进入第二夜。
- **第二天及以后的投票**：
  - 系统强制要求必须出人！**未投票的存活玩家必须在第3轮结束前提交有效的 `vote(target)`**。如果仍然提交 `connection()` 或无效 target，系统将直接判错导致该角色异常！
- **好人千万不要互投**：你们的目标是找出狼人。在通过发言盘清逻辑前，不要乱把票挂在自己人身上。

## 4. 接口规范

你在 `solution.py` 中只需实现如下四个函数。它们分别运行在**四个独立沙箱进程**中（无共享内存，无法用全局变量通信！相互之间只能靠游戏内 `speak` 发言交流）：

```python
def solve_witch(env): ...
def solve_seer(env): ...
def solve_villager_1(env): ...
def solve_villager_2(env): ...
```
每个工具调用都会返回最新环境字符串，你需要写一个循环，不断把环境字串传给大模型，获取模型决定的行动并执行。
""".strip()

PHASE1_STARTER_CODE_EN = r'''
# These four functions run in four isolated sandbox processes.
# Cross-function memory/process communication does not work.

def solve_witch(env):
    """
    Witch Agent (isolated process)
    First round: call env.connection() to enter. Then env.save()/poison(target)/speak(text)/vote(target)/connection()
    env.player_id = "witch"
    """
    pass

def solve_seer(env):
    """
    Seer Agent (isolated process)
    First round: call env.connection() to enter (SYNC phase). Then env.check(target)/speak(text)/vote(target)/connection()
    env.player_id = "seer"
    """
    pass

def solve_villager_1(env):
    """
    Villager 1 Agent (isolated process)
    First round: call env.connection() to enter (SYNC phase). Then env.speak(text)/vote(target)/connection()
    env.player_id = "villager_1"
    """
    pass

def solve_villager_2(env):
    """
    Villager 2 Agent (isolated process)
    First round: call env.connection() to enter (SYNC phase). Then env.speak(text)/vote(target)/connection()
    env.player_id = "villager_2"
    """
    pass
'''.strip()

PHASE1_STARTER_CODE_ZH = r'''
# 以下四个函数在评测时分别运行在四个独立沙箱中，彼此无法跨进程通信。
# 不要依赖全局变量或跨函数逻辑传递信息，你的 Agent 只能通过游戏内的 speak() 互相传递信息。

def solve_witch(env):
    """
    女巫 Agent。首轮 connection() 进入，之后可用：env.save() / env.poison(target) / env.speak(text) / env.vote(target) / env.connection()
    当前角色ID：env.player_id ("witch")
    提示：游戏开始第一轮必须 connection() 进入，之后在循环中获取环境信息，没轮到你行动时调用 env.connection()。
    """
    pass

def solve_seer(env):
    """
    预言家 Agent
    可用工具：env.check(target) / env.speak(text) / env.vote(target) / env.connection()
    当前角色ID：env.player_id ("seer")
    提示：白天发言必须果断报出查验结果，带领好人投票，千万别藏着！
    """
    pass

def solve_villager_1(env):
    """
    村民1 Agent
    可用工具：env.speak(text) / env.vote(target) / env.connection()
    当前角色ID：env.player_id ("villager_1")
    """
    pass

def solve_villager_2(env):
    """
    村民2 Agent
    可用工具：env.speak(text) / env.vote(target) / env.connection()
    当前角色ID：env.player_id ("villager_2")
    """
    pass
'''.strip()
