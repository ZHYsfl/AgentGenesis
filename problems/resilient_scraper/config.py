"""Resilient Scraper problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class ResilientScraperConfig(PhaseConfig):
    """Config for the Resilient Scraper challenge."""

    # =========== Problem-specific parameters ===========
    max_attempts: int = 4
    success_probabilities: list[float] = [0.30, 0.50, 0.80, 0.95]
    backoff_base: float = 10.0
    backoff_tolerance: float = 1.0

    # =========== Evaluation parameters ===========
    num_cases: int = 5
    min_passed_cases: Optional[int] = 5
    parallel_cases: int = 1
    time_limit: float = 300.0
    sandbox_timeout: int = 1800
    case_idle_timeout: int = 60

    # =========== Dependencies ===========
    pip_dependencies: list[str] = [
        "openai",
        "pydantic",
    ]

    # =========== User bridge ===========
    solve_attr_name: str = "solve"
    adapter_preset: str = "resilient_scraper"

    # =========== Private files ===========
    private_files: Optional[list[str]] = [
        "sandbox/data_pool.json",
    ]

    # =========== Evaluator metadata ===========
    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"


# =============================================================================
# Localized content — English
# =============================================================================

OVERVIEW_EN = (
    "Build a resilient data-fetching agent that implements retry with "
    "exponential backoff. The target server is unreliable and returns "
    "responses containing a factual claim and a data record — your "
    "agent must use an LLM to verify the claim's correctness to "
    "determine if the fetch succeeded or failed."
)

BACKGROUND_EN = """
# The Resilient Scraper — Background

## Scenario

You are building an agent that fetches data records from an unreliable
server. Each call to `env.fetch_data()` returns a response containing:

1. A **factual claim** (a common-sense statement that may be true or false)
2. A **data record**

If the claim is **factually correct**, the fetch succeeded and the data
record is valid. If the claim is **factually wrong**, the fetch failed
and the data record is garbage.

There are no `"Error:"` prefixes or success/failure keywords — the
**only way** to determine success is to verify the factual claim using
an LLM.

## Success Probabilities

| Attempt | Probability that the claim is correct (= successful fetch) |
|---------|-----------------------------------------------------------|
| 1st     | 30%                                                       |
| 2nd     | 50%                                                       |
| 3rd     | 80%                                                       |
| 4th     | 95%                                                       |

If all 4 claims happen to be wrong, the scraper found nothing — submit
an empty string. This is a valid outcome and scores full marks.

## Exponential Backoff

Between consecutive `fetch_data()` calls, your agent must wait at least:

| Retry  | Minimum Wait  |
|--------|--------------|
| Before 2nd attempt | 10 seconds |
| Before 3rd attempt | 20 seconds |
| Before 4th attempt | 40 seconds |

Formula: `wait >= 10 * 2^(retry_number - 1)` seconds.

Calling too soon violates the backoff policy and **fails the case**.

## Strategy

1. Call `env.get_problem()` to receive the task.
2. Call `env.fetch_data()` — use LLM to verify the claim.
3. If the claim is correct, extract the data record and submit.
4. If incorrect, wait the backoff interval and retry.
5. After 4 wrong claims, submit an empty string.
""".strip()

PHASE1_DESCRIPTION_EN = """
# Phase 1: The Resilient Scraper

Build an agent that retries with exponential backoff and uses an LLM to
verify factual claims in server responses.

## 1. Interface

```python
def solve(env):
    problem = env.get_problem()            # task description (str)
    response = env.fetch_data()            # response with claim + data
    status = env.submit(data="...")         # submit the data record
```

### Methods

- `env.get_problem() -> str`
  Returns the task description for this test case.

- `env.fetch_data() -> str`
  Returns a server response containing a **factual claim** and a
  **data record**. If the claim is factually correct, the data record
  is valid (successful fetch). If the claim is wrong, the data is
  garbage (failed fetch). There are no error keywords — you must
  use an LLM to judge the claim.
  **Rules:**
  - Maximum 4 calls per test case.
  - Must respect exponential backoff between calls (10s, 20s, 40s).
  - Violating either rule fails the case immediately.

- `env.submit(data: str) -> str`
  Submit the data record string (just the data, not the full response).
  - If a correct claim existed and you submit the matching data:
    returns `"correct"`.
  - If a correct claim existed but you submit wrong data:
    returns `"wrong: <reason>"`.
  - If all 4 claims were wrong, submit an empty string:
    always returns `"correct"` (finding nothing is valid).

## 2. Rules

- **5 test cases** per evaluation.
- Each `fetch_data()` response contains a factual claim + data record.
- Correct claim = valid data. Wrong claim = garbage data.
- Success probabilities per attempt: 30%, 50%, 80%, 95%.
- **Exponential backoff:** wait >= 10s, 20s, 40s before retries 2, 3, 4.
- If all 4 claims are wrong, submit an empty string — this is valid.
- Submit only the data record, not the full response text.

## 3. Scoring

| Condition | Score | Pass? |
|-----------|-------|-------|
| Correct data submitted (or empty when all claims wrong), backoff respected | 100 | Yes |
| Backoff violation, wrong data when correct claim existed, or excess attempts | 0 | No |

**All 5 test cases must score 100 to pass. Any single failure means overall failure.**

## 4. Hints

- Use an LLM to evaluate whether the factual claim is true or false.
- If the claim is correct, extract the data record from the response
  and submit it.
- If the claim is incorrect, wait the required backoff interval, then
  retry.
- Use `time.sleep()` for backoff: 10s, 20s, 40s before retries.
- After 4 wrong claims, submit an empty string.
""".strip()

PHASE1_STARTER_CODE_EN = r'''
def solve(env):
    """
    Resilient Scraper

    Args:
        env: environment namespace with these methods:
             env.get_problem() -> str           : get task description
             env.fetch_data() -> str            : server response (claim + data)
             env.submit(data: str) -> str       : submit the data record

    Key constraints:
        - fetch_data() returns a factual claim + data record
        - Correct claim = valid data; wrong claim = garbage data
        - Use LLM to verify the claim — no error keywords to regex
        - Maximum 4 fetch_data() calls, with exponential backoff (10s, 20s, 40s)
        - If all 4 claims are wrong, submit empty string
        - Submit only the data record, not the full response
    """
    # TODO: implement your solution
    problem = env.get_problem()
    # 1. Call fetch_data(), use LLM to verify the claim
    # 2. If claim correct -> extract data record -> submit
    # 3. If claim wrong -> wait backoff -> retry
    # 4. After 4 wrong claims -> submit("")
    pass
'''.strip()


# =============================================================================
# Localized content — Chinese
# =============================================================================

OVERVIEW_ZH = (
    "构建一个韧性数据抓取 Agent，实现带指数退避的重试机制。"
    "目标服务器不稳定，返回的响应包含一个事实性声明和一条数据记录——"
    "你的 Agent 必须用 LLM 验证声明的正确性来判断获取是否成功。"
)

BACKGROUND_ZH = """
# 韧性爬虫 — 背景

## 场景

你正在构建一个从不稳定服务器获取数据记录的 Agent。
每次调用 `env.fetch_data()` 返回的响应包含：

1. 一个**事实性声明**（一个可能正确或错误的常识判断）
2. 一条**数据记录**

如果声明**事实正确**，表示获取成功，数据记录有效。
如果声明**事实错误**，表示获取失败，数据记录是垃圾数据。

响应中没有 `"Error:"` 前缀或成功/失败关键词——
**唯一的判断方式**是用 LLM 验证事实性声明。

## 成功概率

| 尝试次数 | 声明正确的概率（= 获取成功） |
|---------|--------------------------|
| 第 1 次  | 30%                      |
| 第 2 次  | 50%                      |
| 第 3 次  | 80%                      |
| 第 4 次  | 95%                      |

如果 4 次声明恰好全错，爬虫没找到数据——提交空字符串即可。
这是合理结果，同样得满分。

## 指数退避

连续两次 `fetch_data()` 调用之间，必须等待至少：

| 重试    | 最小等待时间 |
|---------|------------|
| 第 2 次前 | 10 秒      |
| 第 3 次前 | 20 秒      |
| 第 4 次前 | 40 秒      |

公式：`等待 >= 10 * 2^(重试序号 - 1)` 秒。

调用过早违反退避策略会**直接判负**。

## 策略

1. 调用 `env.get_problem()` 接收任务。
2. 调用 `env.fetch_data()`——用 LLM 验证声明。
3. 声明正确→提取数据记录并提交。
4. 声明错误→等待退避间隔后重试。
5. 4 次声明全错→提交空字符串。
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：韧性爬虫

构建一个带指数退避重试和 LLM 声明验证的 Agent。

## 1. 接口

```python
def solve(env):
    problem = env.get_problem()            # 获取任务描述 (str)
    response = env.fetch_data()            # 响应（声明 + 数据）
    status = env.submit(data="...")         # 提交数据记录
```

### 方法说明

- `env.get_problem() -> str`
  返回本测试点的任务描述。

- `env.fetch_data() -> str`
  返回服务器响应，包含一个**事实性声明**和一条**数据记录**。
  声明正确→数据有效（获取成功）。声明错误→数据是垃圾（获取失败）。
  响应中没有错误关键词——必须用 LLM 判断声明正误。
  **规则：**
  - 每个测试点最多调用 4 次。
  - 连续调用之间必须遵循指数退避（10 秒、20 秒、40 秒）。
  - 违反任一规则直接判负。

- `env.submit(data: str) -> str`
  提交数据记录字符串（仅数据，不含完整响应文本）。
  - 存在正确声明且提交了匹配的数据：返回 `"correct"`。
  - 存在正确声明但提交了错误数据：返回 `"wrong: <原因>"`。
  - 4 次声明全错时提交空字符串：始终返回 `"correct"`
    （没找到数据是合理结果）。

## 2. 规则

- 每次评测 **5 个测试点**。
- 每次 `fetch_data()` 响应包含事实性声明 + 数据记录。
- 声明正确 = 数据有效。声明错误 = 垃圾数据。
- 各次尝试的成功概率：30%、50%、80%、95%。
- **指数退避：** 第 2、3、4 次尝试前需分别等待 >= 10 秒、20 秒、40 秒。
- 4 次声明全错→提交空字符串，这是合理结果。
- 仅提交数据记录，不含完整响应文本。

## 3. 计分

| 条件 | 得分 | 通过？ |
|------|------|--------|
| 数据正确（或全错时提交空值）、退避合规 | 100 | 是 |
| 退避违规、有正确声明却提交错误数据、超出次数 | 0 | 否 |

**全部 5 个测试点每个都必须得 100 分才算通过，任何一个失败则整体不通过。**

## 4. 提示

- 用 LLM 判断事实性声明是否正确。
- 声明正确→从响应中提取数据记录并提交。
- 声明错误→等待规定退避间隔后重试。
- 用 `time.sleep()` 实现退避：重试前分别等待 10 秒、20 秒、40 秒。
- 4 次声明全错后提交空字符串。
""".strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve(env):
    """
    韧性爬虫

    参数:
        env: 环境命名空间，提供以下方法:
             env.get_problem() -> str           : 获取任务描述
             env.fetch_data() -> str            : 服务器响应（声明 + 数据）
             env.submit(data: str) -> str       : 提交数据记录

    关键约束:
        - fetch_data() 返回事实性声明 + 数据记录
        - 声明正确 = 数据有效；声明错误 = 垃圾数据
        - 用 LLM 验证声明——无法用正则表达式判断
        - 最多调用 4 次 fetch_data()，需指数退避（10s、20s、40s）
        - 4 次声明全错后提交空字符串
        - 仅提交数据记录，不含完整响应文本
    """
    # TODO: 实现你的方案
    problem = env.get_problem()
    # 1. 调用 fetch_data()，用 LLM 验证声明
    # 2. 声明正确 -> 提取数据记录 -> submit
    # 3. 声明错误 -> 等待退避 -> 重试
    # 4. 4 次全错 -> submit("")
    pass
'''.strip()
