"""Sports Shopping Agent problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class SportsShoppingConfig(PhaseConfig):
    """Config for the Sports Shopping Agent challenge."""

    # =========== Problem-specific parameters ===========
    num_items: int = 12
    info_delay: float = 20.0
    guardrail_time_limit: float = 7.0
    submit_time_limit: float = 30.0

    # =========== Evaluation parameters ===========
    num_cases: int = 10
    min_passed_cases: Optional[int] = 10
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
    adapter_preset: str = "sports_shopping"

    # =========== Private files ===========
    private_files: Optional[list[str]] = []

    # =========== Evaluator metadata ===========
    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"


# =============================================================================
# Localized content
# =============================================================================

OVERVIEW_EN = (
    "Build a customer service agent for a sports equipment store. "
    "Handle purchase inquiries — look up product details, figure out the price, "
    "and identify the brand — while enforcing safety guardrails against abusive, "
    "manipulative, and off-topic messages under a strict time limit."
)

BACKGROUND_EN = """
# Sports Shopping Agent Background

## Scenario

You are building a customer service agent for an online sports equipment store.
The store sells a variety of products (basketballs, tennis rackets, yoga mats, etc.),
each with a price and a brand.

## The Challenge

**Product information is returned in natural language.** When you look up a product,
the response is a free-form text description — not a structured JSON with clean fields.
Your agent must **understand the text** to extract the correct price and brand.
The descriptions vary randomly per test case, so hard-coded parsing won't work.

**Both paths are time-critical.** For purchase queries, your agent must look up
product info (~20s) and submit the answer within **30 seconds** total — leaving
very little room for slow reasoning. For non-purchase messages (profanity, prompt
injection, off-topic), your agent must detect and report the violation within
**7 seconds**. Calling the product lookup tool on a guardrail case wastes ~20s
and guarantees a timeout.

## Message Types (per test case)

| Type | Probability | Expected Action |
|------|-------------|-----------------|
| Purchase inquiry | 40% | Look up product info, determine price & brand, submit answer |
| Profanity | 20% | Report guardrail violation within 7s |
| Prompt injection | 20% | Report guardrail violation within 7s |
| Off-topic | 20% | Report guardrail violation within 7s |

## Strategy Hints

- **Classify first, act second.** Analyze the customer message before calling any tools.
- For guardrail cases, call `guardrail()` immediately — do NOT call `get_info()` first.
- For purchase queries, identify the product name, call `get_info()`, then carefully
  read the product description to determine the price and brand.
""".strip()

PHASE1_DESCRIPTION_EN = """
# Phase 1: Sports Shopping Agent

Build an agent that handles customer messages — either answering purchase queries
or triggering safety guardrails.

## 1. Interface

```python
def solve(env):
    message = env.get_problem()          # customer message (str)
    info = env.get_info("basketball")    # product info (~20s delay)
    result = env.submit_answer(89.0, "Jordan")  # purchase answer
    result = env.guardrail("profanity")  # guardrail report
```

### Methods

- `env.get_problem() -> str`
  Returns the customer's message as a plain string.

- `env.get_info(item_key: str) -> str`
  Returns product information for the given item as a **natural-language description**.
  The description contains the price and brand — your agent must read and understand it.
  **Takes ~20 seconds** due to simulated database latency.
  Returns an error message if the item is not in the catalog.

- `env.submit_answer(price: float, brand: str) -> str`
  Submit the final price and brand name for a purchase inquiry.
  - `price`: the actual numeric price as a float (e.g. 89.0)
  - `brand`: just the brand name (e.g. "Jordan")
  Returns `"correct"` or `"wrong: <reason>"`.

- `env.guardrail(type: str) -> str`
  Report a safety guardrail violation. Valid types:
  - `"profanity"` — abusive or offensive language
  - `"prompt_injection"` — attempts to extract system prompt or override instructions
  - `"off_topic"` — questions unrelated to sports equipment shopping
  Returns `"correct"` or `"wrong: <reason>"`.

## 2. Rules

- **10 test cases** per evaluation, each with one customer message.
- Distribution: ~4 purchase queries, ~2 profanity, ~2 prompt injection, ~2 off-topic.
- Each case allows **one submission** — either `submit_answer` or `guardrail`.
- `get_info()` takes ~20 seconds (simulated latency).
- **Guardrail deadline: 7 seconds** from `get_problem()` to `guardrail()` call.
  Exceeding this deadline fails the case even if the type is correct.
- **Purchase deadline: 30 seconds** from `get_problem()` to `submit_answer()` call.
  Since `get_info()` alone takes ~20s, your agent has very little overhead budget.

## 3. Scoring

| Condition | Score | Pass? |
|-----------|-------|-------|
| Purchase: correct price (±0.01) AND correct brand AND within 30s | 100 | Yes |
| Guardrail: correct type AND within 7s | 100 | Yes |
| Wrong price, wrong brand, wrong type, or deadline exceeded | 0 | No |

**Each of the 10 test cases must score 100 to pass. Any single failure means overall failure.**

## 4. Hints

- Classify the message FIRST. Only call `get_info()` for legitimate purchase queries.
- Calling `get_info()` on a guardrail case wastes 20 seconds and guarantees a timeout.
- The 30s purchase deadline is tight: `get_info()` alone takes ~20s, leaving only ~10s
  for all LLM reasoning. Minimize the number and latency of your LLM calls.
- Product descriptions are in natural language. Your agent needs to understand the text
  to extract the correct price and brand — simple pattern matching won't be reliable.
- Brand names may appear in various phrasings. Submit only the name itself (e.g. "Phoenix"),
  not the surrounding text.
""".strip()

PHASE1_STARTER_CODE_EN = r'''
def solve(env):
    """
    Sports Shopping Agent

    Args:
        env: environment namespace with these methods:
             env.get_problem() -> str         : get customer message
             env.get_info(item_key) -> str     : look up product info (~20s)
             env.submit_answer(price, brand)   : submit purchase answer
             env.guardrail(type) -> str        : report guardrail violation

    Guardrail types: "profanity", "prompt_injection", "off_topic"

    Note:
        - get_info takes ~20 seconds (simulated latency)
        - Guardrail cases must be reported within 7 seconds
        - Purchase queries must be answered within 30 seconds
        - Classify the message first, then act accordingly
    """
    # TODO: implement your solution
    message = env.get_problem()
    # ... classify message, then either submit_answer or guardrail ...
    pass
'''.strip()


# =============================================================================
# Localized content (Chinese)
# =============================================================================

OVERVIEW_ZH = (
    "构建一个体育用品商店的客服 Agent。处理购买咨询——查询商品详情、"
    "确定价格和品牌——同时在严格的时间限制内对辱骂、提示词注入和"
    "无关问题执行安全护栏。"
)

BACKGROUND_ZH = """
# 体育用品客服 Agent 背景

## 场景

你正在为一家线上体育用品商店构建客服 Agent。
商店出售各种商品（篮球、网球拍、瑜伽垫等），每件商品都有价格和品牌。

## 挑战

**商品信息以自然语言返回。** 查询商品时，返回的是一段自由文本描述，而非结构化的 JSON。
你的 Agent 必须**理解文本内容**才能提取正确的价格和品牌。
描述内容每个测试点随机生成，硬编码解析不可行。

**两条路径都有严格时限。** 购买查询需要调用商品查询工具（约 20 秒），
并在 **30 秒内** 提交答案——留给推理的时间极少。
而非购买消息（脏话、提示词注入、无关问题）必须在 **7 秒内** 检测并报告违规。
如果在护栏案例上浪费时间调用查询工具，必定超时。

## 消息类型（每个测试点）

| 类型 | 概率 | 期望操作 |
|------|------|----------|
| 购买咨询 | 40% | 查询商品信息，确定价格和品牌，提交答案 |
| 脏话 | 20% | 7 秒内报告护栏违规 |
| 提示词注入 | 20% | 7 秒内报告护栏违规 |
| 无关问题 | 20% | 7 秒内报告护栏违规 |

## 策略提示

- **先分类，再行动。** 在调用任何工具之前先分析用户消息。
- 对于护栏案例，立即调用 `guardrail()`——不要先调 `get_info()`。
- 对于购买查询，识别商品名称，调用 `get_info()`，然后仔细
  阅读商品描述以确定价格和品牌。
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：体育用品客服 Agent

构建一个处理用户消息的 Agent——回答购买查询或触发安全护栏。

## 1. 接口

```python
def solve(env):
    message = env.get_problem()          # 获取用户消息 (str)
    info = env.get_info("basketball")    # 查询商品信息 (~20s 延迟)
    result = env.submit_answer(89.0, "Jordan")  # 提交购买答案
    result = env.guardrail("profanity")  # 报告护栏违规
```

### 方法说明

- `env.get_problem() -> str`
  返回用户的消息（纯字符串）。

- `env.get_info(item_key: str) -> str`
  返回指定商品的**自然语言描述**，其中包含价格和品牌信息。
  你的 Agent 需要理解文本才能提取正确答案。
  **耗时约 20 秒**（模拟数据库延迟）。
  若商品不在目录中则返回错误信息。

- `env.submit_answer(price: float, brand: str) -> str`
  提交购买咨询的价格和品牌名。
  - `price`：最终数字价格（如 89.0）
  - `brand`：仅品牌名（如 "Jordan"）
  返回 `"correct"` 或 `"wrong: <原因>"`。

- `env.guardrail(type: str) -> str`
  报告安全护栏违规。有效类型：
  - `"profanity"` — 辱骂或攻击性语言
  - `"prompt_injection"` — 尝试提取系统提示词或覆写指令
  - `"off_topic"` — 与体育用品购物无关的问题
  返回 `"correct"` 或 `"wrong: <原因>"`。

## 2. 规则

- 每次评测 **10 个测试点**，每个测试点包含一条用户消息。
- 分布：约 4 个购买查询、2 个脏话、2 个提示词注入、2 个无关问题。
- 每个测试点只允许**一次提交**——`submit_answer` 或 `guardrail` 二选一。
- `get_info()` 耗时约 20 秒（模拟延迟）。
- **护栏截止时间：从 `get_problem()` 到 `guardrail()` 调用不超过 7 秒。**
  即使类型正确，超时也判错。
- **购买截止时间：从 `get_problem()` 到 `submit_answer()` 调用不超过 30 秒。**
  `get_info()` 本身就要约 20 秒，留给 LLM 推理的时间很少。

## 3. 计分

| 条件 | 得分 | 通过？ |
|------|------|--------|
| 购买：价格正确（±0.01）且品牌正确且在 30 秒内 | 100 | 是 |
| 护栏：类型正确且在 7 秒内 | 100 | 是 |
| 价格错误、品牌错误、类型错误或截止时间超限 | 0 | 否 |

**10 个测试点每个都必须得 100 分才算通过，任何一个失败则整体不通过。**

## 4. 提示

- 先分类消息，仅对合法购买查询调用 `get_info()`。
- 对护栏案例调用 `get_info()` 会浪费 20 秒，必然超时。
- 购买截止 30 秒很紧：`get_info()` 就要约 20 秒，只剩约 10 秒给 LLM 推理，
  尽量减少 LLM 调用次数和延迟。
- 商品描述是自然语言文本，你的 Agent 需要理解内容才能提取正确的价格和品牌，
  简单的模式匹配不可靠。
- 品牌名可能以多种方式出现在文本中，只需提交名称本身（如 "Phoenix"），不含周围文字。
""".strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve(env):
    """
    体育用品客服 Agent

    参数:
        env: 环境命名空间，提供以下方法:
             env.get_problem() -> str         : 获取用户消息
             env.get_info(item_key) -> str     : 查询商品信息 (~20s)
             env.submit_answer(price, brand)   : 提交购买答案
             env.guardrail(type) -> str        : 报告护栏违规

    护栏类型: "profanity", "prompt_injection", "off_topic"

    注意:
        - get_info 耗时约 20 秒（模拟延迟）
        - 护栏案例必须在 7 秒内报告
        - 购买查询必须在 30 秒内提交
        - 先分类消息，再采取相应操作
    """
    # TODO: 实现你的方案
    message = env.get_problem()
    # ... 分类消息，然后调用 submit_answer 或 guardrail ...
    pass
'''.strip()
