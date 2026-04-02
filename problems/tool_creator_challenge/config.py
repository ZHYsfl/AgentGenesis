"""Tool Creator Challenge problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class ToolCreatorConfig(PhaseConfig):
    """Config for the Tool Creator Challenge."""

    # =========== Problem-specific parameters ===========
    queries_per_case: int = 10

    # =========== Evaluation parameters ===========
    num_cases: int = 5
    min_passed_cases: Optional[int] = 5
    parallel_cases: int = 1
    time_limit: float = 600.0
    sandbox_timeout: int = 3600
    case_idle_timeout: int = 120

    # =========== Dependencies ===========
    pip_dependencies: list[str] = [
        "openai",
        "pydantic",
    ]

    # =========== User bridge ===========
    solve_attr_name: str = "solve"
    adapter_preset: str = "tool_creator"

    # =========== Private files ===========
    private_files: Optional[list[str]] = [
        "sandbox/data_pool.json",
        "sandbox/generator.py",
        "sandbox/environment.py",
        "sandbox/run.py",
    ]

    # =========== Evaluator metadata ===========
    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"


# =============================================================================
# Localized content — English
# =============================================================================

OVERVIEW_EN = (
    "Build an agent that dynamically creates computational tools at runtime "
    "using Python code generation, then uses those tools to solve mathematical "
    "queries whose answers are too large for any LLM to guess."
)

BACKGROUND_EN = """
# The Tool Creator — Background

## Scenario

You are building an agent that can **extend its own capabilities at runtime**.
Given a set of mathematical computation tasks, your agent must:

1. Understand what kind of computation is needed
2. **Write Python code** to create a new tool for that computation
3. **Execute the tool** to compute the exact answer
4. Submit the answer

The computation results are exact large integers (often hundreds of digits)
that no LLM can produce from memory — the agent **must** generate working
code and execute it.

## Task Types

Each query asks the agent to create a tool for one of these computation types:

| Type | Example |
|------|---------|
| Fibonacci number | F(431) — a 90-digit number |
| Factorial digit sum | Sum of digits of 317! |
| Modular exponentiation | 29^56789 mod 99929 |
| Collatz sequence steps | Steps for 456789 to reach 1 |
| Nth prime number | The 7000th prime |
| Binomial coefficient | C(220, 73) |
| Catalan number | The 97th Catalan number |
| Tribonacci number | T(421) |
| Lucas number | L(443) |
| Integer partitions | p(419) — partitions of 419 |

## Strategy

1. Call `env.get_queries()` to receive 10 computation tasks.
2. For each task, read the description to understand the computation.
3. Write Python code that implements the computation correctly.
4. Create a tool using `exec()` or any dynamic code execution approach.
5. Run the tool and get the exact numeric answer.
6. Call `env.submit(query_id, answer)` with the result as a string.
""".strip()

PHASE1_DESCRIPTION_EN = """
# Phase 1: The Tool Creator

Build an agent that dynamically creates Python computation tools and uses
them to answer mathematical queries with exact results.

## 1. Interface

```python
def solve(env):
    queries = env.get_queries()
    # queries = [{"query_id": 0, "description": "Create a Fibonacci..."}, ...]
    result = env.submit(query_id=0, answer="354224848179261915075")
```

### Methods

- `env.get_queries() -> list[dict]`
  Returns a list of 10 query objects, each with:
  - `query_id` (int): unique identifier (0–9)
  - `description` (str): full task description including the computation
    type definition and the specific input to compute

- `env.submit(query_id: int, answer: str) -> str`
  Submit the exact numeric answer as a string.
  - Returns `"correct"` if the answer matches exactly.
  - Returns `"wrong: ..."` if incorrect — **the case ends immediately
    on the first wrong answer**.

## 2. Rules

- **5 test cases**, each with **10 queries**.
- Queries are sampled from a pool of 100 computation tasks across 10 types.
- Answers are exact integers — they can be hundreds of digits long.
- The agent must **generate and execute Python code** to compute answers.
  No LLM can guess these values.
- A wrong submission on any query **immediately fails the entire case**.
- You may submit the 10 answers in any order.

## 3. Scoring

| Condition | Score | Pass? |
|-----------|-------|-------|
| All 10 answers correct | 100 | Yes |
| Any wrong answer | 0 | No |

**All 5 test cases must score 100 to pass. Any single failure means overall failure.**

## 4. Hints

- Use `exec()` to dynamically compile Python functions from generated code.
- If multiple queries need the same type of tool (e.g., two Fibonacci
  queries), you only need to create the tool once and reuse it.
- Carefully parse the task description to extract the computation
  definition and the specific input parameters.
- Python's `math` module has useful functions: `math.factorial()`,
  `math.comb()`, `pow(base, exp, mod)` for modular exponentiation.
- Return the answer as a **string** (e.g. `str(result)`), not a float.
""".strip()

PHASE1_STARTER_CODE_EN = r'''
def solve(env):
    """
    Tool Creator Challenge

    Args:
        env: environment namespace with these methods:
             env.get_queries() -> list[dict]      : get 10 computation tasks
             env.submit(query_id, answer) -> str   : submit answer string

    Key constraints:
        - Answers are exact large integers (hundreds of digits possible)
        - Must generate and execute Python code to compute answers
        - Any wrong submission immediately fails the case
        - Submit answers as strings: env.submit(query_id=0, answer="12345")
    """
    # TODO: implement your solution
    queries = env.get_queries()
    # For each query:
    #   1. Parse the description to understand the computation
    #   2. Generate Python code for the computation
    #   3. Execute the code to get the answer
    #   4. env.submit(query_id=..., answer=str(result))
    pass
'''.strip()


# =============================================================================
# Localized content — Chinese
# =============================================================================

OVERVIEW_ZH = (
    "构建一个能在运行时动态创建计算工具的 Agent——"
    "通过 Python 代码生成实现——然后用这些工具解决数学计算问题，"
    "这些问题的答案是 LLM 无法猜出的超大整数。"
)

BACKGROUND_ZH = """
# 工具创造者 — 背景

## 场景

你正在构建一个能**在运行时扩展自身能力**的 Agent。
面对一组数学计算任务，你的 Agent 需要：

1. 理解需要什么类型的计算
2. **编写 Python 代码**来创建对应的新工具
3. **执行工具**计算出精确答案
4. 提交答案

计算结果是精确的大整数（通常有几百位数字），
任何 LLM 都无法凭记忆给出——Agent **必须**生成可运行的代码并执行。

## 任务类型

每个问题要求 Agent 为以下某种计算类型创建工具：

| 类型 | 示例 |
|------|------|
| 斐波那契数 | F(431) — 一个 90 位数 |
| 阶乘数位和 | 317! 的所有数位之和 |
| 模幂运算 | 29^56789 mod 99929 |
| Collatz 序列步数 | 456789 到达 1 需要多少步 |
| 第 N 个素数 | 第 7000 个素数 |
| 二项式系数 | C(220, 73) |
| 卡特兰数 | 第 97 个卡特兰数 |
| Tribonacci 数 | T(421) |
| Lucas 数 | L(443) |
| 整数分拆数 | p(419) — 419 的分拆数 |

## 策略

1. 调用 `env.get_queries()` 获取 10 个计算任务。
2. 逐个阅读任务描述，理解所需的计算类型。
3. 编写能正确实现该计算的 Python 代码。
4. 使用 `exec()` 或任何动态代码执行方式创建工具。
5. 运行工具获取精确的数值答案。
6. 调用 `env.submit(query_id, answer)` 提交结果（字符串形式）。
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：工具创造者

构建一个能动态创建 Python 计算工具、并用它们精确回答数学问题的 Agent。

## 1. 接口

```python
def solve(env):
    queries = env.get_queries()
    # queries = [{"query_id": 0, "description": "Create a Fibonacci..."}, ...]
    result = env.submit(query_id=0, answer="354224848179261915075")
```

### 方法说明

- `env.get_queries() -> list[dict]`
  返回包含 10 个查询对象的列表，每个对象包含：
  - `query_id` (int): 唯一标识符 (0–9)
  - `description` (str): 完整任务描述，包括计算类型定义和
    需要计算的具体输入

- `env.submit(query_id: int, answer: str) -> str`
  以字符串形式提交精确的数值答案。
  - 答案完全匹配返回 `"correct"`。
  - 答案错误返回 `"wrong: ..."` — **第一个错误答案立刻导致
    整个测试点失败**。

## 2. 规则

- 每次评测 **5 个测试点**，每个测试点 **10 个问题**。
- 问题从 100 个计算任务池（10 种类型）中随机抽取。
- 答案都是精确整数——可能长达数百位。
- Agent 必须**生成并执行 Python 代码**来计算答案。
  LLM 不可能猜出这些值。
- 任何一个问题提交错误答案，**该测试点立刻失败**。
- 可以按任意顺序提交 10 个答案。

## 3. 计分

| 条件 | 得分 | 通过？ |
|------|------|--------|
| 全部 10 个答案正确 | 100 | 是 |
| 任何一个答案错误 | 0 | 否 |

**全部 5 个测试点必须每个得 100 分才算通过，任何一个失败则整体不通过。**

## 4. 提示

- 使用 `exec()` 动态编译从生成的代码中定义的 Python 函数。
- 如果多个问题需要同类型的工具（如两个斐波那契问题），
  只需创建一次工具即可复用。
- 仔细解析任务描述，提取计算定义和具体输入参数。
- Python 的 `math` 模块有实用函数：`math.factorial()`、
  `math.comb()`、`pow(base, exp, mod)` 用于模幂运算。
- 答案以**字符串**形式返回（如 `str(result)`），不要用浮点数。
""".strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve(env):
    """
    工具创造者挑战

    参数:
        env: 环境命名空间，提供以下方法:
             env.get_queries() -> list[dict]      : 获取 10 个计算任务
             env.submit(query_id, answer) -> str   : 提交答案字符串

    关键约束:
        - 答案是精确的大整数（可能有数百位）
        - 必须生成并执行 Python 代码来计算答案
        - 任何一个错误提交立刻导致测试点失败
        - 以字符串形式提交答案: env.submit(query_id=0, answer="12345")
    """
    # TODO: 实现你的方案
    queries = env.get_queries()
    # 对每个 query:
    #   1. 解析 description 理解计算类型
    #   2. 生成对应的 Python 计算代码
    #   3. 执行代码获取答案
    #   4. env.submit(query_id=..., answer=str(result))
    pass
'''.strip()
