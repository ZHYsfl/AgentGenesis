"""Short-Circuit Scraper problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class ShortCircuitScraperConfig(PhaseConfig):
    """Config for the Short-Circuit Scraper challenge."""

    # =========== Problem-specific parameters ===========
    num_endpoints: int = 10
    valid_delay: float = 10.0
    invalid_delay: float = 25.0
    submit_deadline: float = 25.0
    submit_block_delay: float = 25.0

    # =========== Evaluation parameters ===========
    num_cases: int = 5
    min_passed_cases: Optional[int] = 5
    parallel_cases: int = 1
    time_limit: float = 300.0
    sandbox_timeout: int = 600
    case_idle_timeout: int = 60

    # =========== Dependencies ===========
    pip_dependencies: list[str] = [
        "openai",
        "pydantic",
    ]

    # =========== User bridge ===========
    solve_attr_name: str = "solve"
    adapter_preset: str = "short_circuit_scraper"

    # =========== Private files ===========
    private_files: Optional[list[str]] = []

    # =========== Evaluator metadata ===========
    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"


# =============================================================================
# Localized content — English
# =============================================================================

OVERVIEW_EN = (
    "Build an orchestrator agent that dispatches parallel scraper agents to find "
    "user profile data across 10 endpoints, short-circuits on the first valid result, "
    "uses an LLM to extract structured fields from a fuzzy natural-language profile, "
    "and cascade-terminates remaining scrapers before submitting."
)

BACKGROUND_EN = """
# The Short-Circuit Scraper — Background

## Scenario

You are building an **orchestrator agent** for a user-data retrieval system.
Given a target user name, you need to find their profile — but the data is
scattered across **10 endpoints** (indexed 0–9), and only **one** of them
actually hosts the profile. You don't know which one in advance.

Calling `env.get_info(user_name, i)` dispatches a **scraper agent** to crawl
endpoint `i`:

- The **valid endpoint** — its scraper agent locates and returns the user's
  profile in **~10 seconds**.
- The **9 invalid endpoints** — their scraper agents spend **~25 seconds**
  crawling the site before reporting back empty-handed.

## The Challenge

**The profile is returned as fuzzy, natural-language text** — not structured
JSON. Each test case generates a completely different writing style, sentence
structure, and wording. Your agent must use an **LLM to extract two specific
fields** — `email` and `member_id` — from this free-form description.

**The deadline is brutal: 25 seconds** from `env.get_user()` to
`env.submit(email, member_id)`. The valid scraper alone takes ~10s, and LLM
extraction takes ~3–5s. There is **zero room** to wait for all 10 scrapers
sequentially. You MUST dispatch all 10 in parallel and short-circuit as soon
as the valid one returns.

**Cascade termination is mandatory.** After you submit, the system blocks for
25 seconds and checks whether any scraper agents are still running. If leaked
threads are detected, the case fails — even if your answer was correct. You
must call `env.cancel()` to terminate all remaining scrapers before submitting.

## Strategy

1. Call `env.get_user()` to get the target user name.
2. Dispatch 10 scraper agents in parallel (`env.get_info` for i=0..9).
3. As soon as one returns valid data (~10s), feed it to an LLM to extract
   `email` and `member_id`.
4. Call `env.cancel()` to terminate the other 9 scrapers.
5. Call `env.submit(email=..., member_id=...)` within 25s of step 1.
""".strip()

PHASE1_DESCRIPTION_EN = """
# Phase 1: The Short-Circuit Scraper

Build an orchestrator that parallelizes scraper agents, short-circuits on
the first valid result, extracts fields via LLM, and cascade-terminates
remaining scrapers.

## 1. Interface

```python
def solve(env):
    user_name = env.get_user()                   # target user name (str)
    info = env.get_info(user_name, "3")           # dispatch scraper to endpoint 3
    env.cancel()                                  # terminate all pending scrapers
    result = env.submit(email="a@b.com", member_id="XY-123")
```

### Methods

- `env.get_user() -> str`
  Returns the target user name. Starts the 25-second countdown.

- `env.get_info(user_name: str, i: str) -> str`
  Dispatches a scraper agent to endpoint `i` (0–9). **Blocks** for ~10s
  (valid endpoint) or ~25s (invalid endpoints). The valid endpoint returns
  a **fuzzy natural-language profile** containing the user's email and
  member ID buried in free-form text. Invalid endpoints return an error
  message starting with `"Error:"`.

- `env.cancel()`
  Cascade-terminates all pending scraper agents. Call this **before**
  `env.submit()` to ensure no leaked threads.

- `env.submit(email: str, member_id: str) -> str`
  Submit the extracted email and member ID. Blocks for ~25s while the
  system checks for cascade termination.
  Returns `"correct"` or `"wrong: <reason>"`.

## 2. Rules

- **5 test cases** per evaluation.
- Each case has 10 endpoints; exactly 1 is valid (random index).
- The valid endpoint returns fuzzy natural-language text — your agent must
  use an LLM to extract the `email` and `member_id` fields.
- **Submit deadline: 25 seconds** from `get_user()`. Exceeding it fails
  the case regardless of correctness.
- **Cascade termination: mandatory.** After submit, the system monitors for
  25 seconds. Any leaked scraper threads cause the case to fail.
- Call `env.cancel()` before `env.submit()` to avoid cascade violations.

## 3. Scoring

| Condition | Score | Pass? |
|-----------|-------|-------|
| Correct email + member_id, within 25s, no leaked threads | 100 | Yes |
| Wrong fields, deadline exceeded, or leaked threads | 0 | No |

**All 5 test cases must score 100 to pass. Any single failure means overall failure.**

## 4. Hints

- Dispatch all 10 scraper agents in parallel (e.g. `ThreadPoolExecutor`).
- Use `concurrent.futures.as_completed` to short-circuit on the first
  valid result — don't wait for all 10.
- Valid results are natural-language text; invalid results start with `"Error:"`.
- Feed the valid profile text to an LLM to extract `email` and `member_id`.
- Call `env.cancel()` immediately after getting the valid result to kill
  the remaining 9 scrapers, then call `env.submit(...)`.
- The 25s deadline is tight: ~10s scraping + ~3–5s LLM + overhead. Minimize
  LLM calls and disable thinking mode if supported.
""".strip()

PHASE1_STARTER_CODE_EN = r'''
def solve(env):
    """
    Short-Circuit Scraper

    Args:
        env: environment namespace with these methods:
             env.get_user() -> str             : get target user name (starts 25s timer)
             env.get_info(user_name, i) -> str  : dispatch scraper to endpoint i (~10s valid, ~25s invalid)
             env.cancel()                       : terminate all pending scrapers
             env.submit(email, member_id) -> str: submit extracted fields

    Key constraints:
        - 10 endpoints (i="0" to "9"), only 1 has valid data
        - Valid scraper returns fuzzy natural-language profile text (~10s)
        - Invalid scrapers return "Error: ..." after ~25s
        - Must submit within 25 seconds of get_user()
        - Must call cancel() before submit() to avoid cascade violation
        - Use LLM to extract email and member_id from the fuzzy profile text
    """
    # TODO: implement your solution
    user_name = env.get_user()
    # 1. Dispatch 10 scrapers in parallel
    # 2. Short-circuit on first valid result
    # 3. LLM-extract email and member_id
    # 4. env.cancel() then env.submit(email=..., member_id=...)
    pass
'''.strip()


# =============================================================================
# Localized content — Chinese
# =============================================================================

OVERVIEW_ZH = (
    "构建一个编排器 Agent，并行派遣多个爬虫 Agent 在 10 个端点中查找用户档案数据，"
    "在首个有效结果返回后立即短路，使用 LLM 从模糊的自然语言档案中提取结构化字段，"
    "并在提交前级联终止剩余爬虫。"
)

BACKGROUND_ZH = """
# 短路爬虫 — 背景

## 场景

你正在为一个用户数据检索系统构建**编排器 Agent**。
给定一个目标用户名，你需要找到他们的档案——但数据分布在 **10 个端点**
（索引 0–9）上，其中只有 **1 个** 端点真正存有该用户的档案。
你事先不知道是哪一个。

调用 `env.get_info(user_name, i)` 会派遣一个**爬虫 Agent** 去爬取端点 `i`：

- **有效端点** — 爬虫 Agent 在 **约 10 秒** 内找到并返回用户档案。
- **9 个无效端点** — 爬虫 Agent 花费 **约 25 秒** 搜索后空手而归。

## 挑战

**档案以模糊的自然语言文本返回**，而非结构化 JSON。每个测试点的写作风格、
句式和措辞完全不同。你的 Agent 必须使用 **LLM 提取两个特定字段** ——
`email`（邮箱）和 `member_id`（会员 ID）。

**截止时间极其紧迫：从 `env.get_user()` 到 `env.submit(email, member_id)`
仅有 25 秒。** 有效爬虫本身就需要约 10 秒，LLM 提取需要约 3–5 秒。
**完全没有时间** 按顺序等待所有 10 个爬虫。你必须并行派遣全部 10 个，
并在有效结果到达后立即短路。

**级联终止是强制要求。** 提交后，系统会阻塞 25 秒检查是否有爬虫 Agent
仍在运行。如果检测到泄漏的线程，即使答案正确也会判负。
你必须在提交前调用 `env.cancel()` 来终止所有剩余爬虫。

## 策略

1. 调用 `env.get_user()` 获取目标用户名。
2. 并行派遣 10 个爬虫 Agent（对 i=0..9 调用 `env.get_info`）。
3. 一旦某个爬虫返回有效数据（约 10 秒），将其交给 LLM 提取
   `email` 和 `member_id`。
4. 调用 `env.cancel()` 终止其余 9 个爬虫。
5. 在步骤 1 的 25 秒内调用 `env.submit(email=..., member_id=...)`。
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：短路爬虫

构建一个编排器，并行化爬虫 Agent、短路首个有效结果、通过 LLM 提取字段、
级联终止剩余爬虫。

## 1. 接口

```python
def solve(env):
    user_name = env.get_user()                   # 获取目标用户名 (str)
    info = env.get_info(user_name, "3")           # 派遣爬虫到端点 3
    env.cancel()                                  # 终止所有待处理的爬虫
    result = env.submit(email="a@b.com", member_id="XY-123")
```

### 方法说明

- `env.get_user() -> str`
  返回目标用户名。启动 25 秒倒计时。

- `env.get_info(user_name: str, i: str) -> str`
  派遣爬虫 Agent 到端点 `i`（0–9）。**阻塞** 约 10 秒（有效端点）或
  约 25 秒（无效端点）。有效端点返回一段**模糊的自然语言档案**，
  其中包含用户的邮箱和会员 ID。无效端点返回以 `"Error:"` 开头的错误信息。

- `env.cancel()`
  级联终止所有待处理的爬虫 Agent。务必在 `env.submit()` **之前**调用，
  以确保没有泄漏的线程。

- `env.submit(email: str, member_id: str) -> str`
  提交提取的邮箱和会员 ID。阻塞约 25 秒，同时系统检查级联终止情况。
  返回 `"correct"` 或 `"wrong: <原因>"`。

## 2. 规则

- 每次评测 **5 个测试点**。
- 每个测试点有 10 个端点，其中恰好 1 个有效（随机索引）。
- 有效端点返回模糊的自然语言文本——你的 Agent 必须使用 LLM 提取
  `email` 和 `member_id` 字段。
- **提交截止时间：从 `get_user()` 起 25 秒。** 超时则不论正确与否判负。
- **级联终止：强制要求。** 提交后系统监控 25 秒，任何泄漏的爬虫线程都会导致判负。
- 在 `env.submit()` 之前调用 `env.cancel()` 以避免级联违规。

## 3. 计分

| 条件 | 得分 | 通过？ |
|------|------|--------|
| 邮箱和会员 ID 正确、25 秒内提交、无泄漏线程 | 100 | 是 |
| 字段错误、超时或存在泄漏线程 | 0 | 否 |

**全部 5 个测试点每个都必须得 100 分才算通过，任何一个失败则整体不通过。**

## 4. 提示

- 并行派遣所有 10 个爬虫 Agent（如使用 `ThreadPoolExecutor`）。
- 使用 `concurrent.futures.as_completed` 短路首个有效结果，不要等全部完成。
- 有效结果是自然语言文本；无效结果以 `"Error:"` 开头。
- 将有效档案文本交给 LLM 提取 `email` 和 `member_id`。
- 获取到有效结果后立即调用 `env.cancel()` 终止其余 9 个爬虫，
  然后调用 `env.submit(...)`。
- 25 秒截止很紧：约 10 秒爬取 + 约 3–5 秒 LLM + 开销。尽量减少
  LLM 调用次数，如果支持的话禁用思考模式。
""".strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve(env):
    """
    短路爬虫

    参数:
        env: 环境命名空间，提供以下方法:
             env.get_user() -> str             : 获取目标用户名（启动 25s 计时）
             env.get_info(user_name, i) -> str  : 派遣爬虫到端点 i（有效约 10s，无效约 25s）
             env.cancel()                       : 终止所有待处理的爬虫
             env.submit(email, member_id) -> str: 提交提取的字段

    关键约束:
        - 10 个端点 (i="0" 到 "9")，仅 1 个有有效数据
        - 有效爬虫返回模糊自然语言档案文本（约 10s）
        - 无效爬虫返回 "Error: ..."（约 25s）
        - 必须在 get_user() 后 25 秒内提交
        - 必须在 submit() 前调用 cancel() 避免级联违规
        - 使用 LLM 从模糊档案文本中提取 email 和 member_id
    """
    # TODO: 实现你的方案
    user_name = env.get_user()
    # 1. 并行派遣 10 个爬虫
    # 2. 短路首个有效结果
    # 3. LLM 提取 email 和 member_id
    # 4. env.cancel() 然后 env.submit(email=..., member_id=...)
    pass
'''.strip()
