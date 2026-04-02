"""Parallel Weather Query problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class ParallelWeatherConfig(PhaseConfig):
    """Config for the Parallel Weather Query challenge."""

    # =========== Problem-specific parameters ===========
    num_cities: int = 200
    num_questions: int = 5
    tool_delay: float = 10.0
    max_allowed_time: float = 27.0

    # =========== Evaluation parameters ===========
    num_cases: int = 3
    min_passed_cases: Optional[int] = 3  # ALL cases must pass (score 100)
    parallel_cases: int = 1
    time_limit: float = 120.0  # 3 cases × 27s = 81s, plus startup overhead
    sandbox_timeout: int = 180
    case_idle_timeout: int = 60

    # =========== Dependencies ===========
    pip_dependencies: list[str] = [
        "openai",
        "pydantic",
    ]

    # =========== User bridge ===========
    solve_attr_name: str = "solve"
    adapter_preset: str = "parallel_weather"

    # =========== Private files ===========
    private_files: Optional[list[str]] = []

    # =========== Evaluator metadata ===========
    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"


# =============================================================================
# Localized content
# =============================================================================

OVERVIEW_EN = (
    "Build an AI agent that answers 5 weather questions simultaneously "
    "under a strict 27-second time limit. "
    "Each tool call to the weather API takes ~10 seconds — "
    "you'll need a clever strategy to finish in time."
)

OVERVIEW_ZH = (
    "构建一个 AI Agent，在严格的 27 秒时间限制内同时回答 5 个天气查询问题。"
    "每次天气 API 调用耗时约 10 秒——"
    "你需要设计巧妙的策略才能按时完成。"
)

BACKGROUND_EN = """
# Parallel Weather Query Background

## Scenario

You are building an AI agent for a weather information service. The service
has a database of 200 cities with current weather data (temperature and humidity).
Users submit batches of questions, and your agent must query the weather API
and respond quickly.

## The Challenge

The weather API is deliberately slow — each call takes approximately **10 seconds**
to return. This simulates real-world scenarios where external API calls have
significant latency (network delays, rate limiting, cold starts, etc.).

Your agent receives **5 questions at once**. For each question, you need
temperature and humidity for **2 different cities**:

- 2 cities × 2 metrics (temperature + humidity) = 4 API calls per question
- 5 questions × 4 calls = 20 API calls per case

After collecting the values, you still need to submit 5 answers:

- 1 `submit_answer(...)` per question
- 5 questions = 5 submission calls per case

The total time budget from receiving questions to submitting answers is only
**27 seconds**. Think carefully about how many API calls you need to make and
how long they take.

## Two Types of Tools

The weather service provides two tools:

- `get_weather(city)` — a regular synchronous function
- `get_humidity(city)` — an asynchronous coroutine

Your agent framework must be able to work with both types correctly.

## Natural Language Responses

The tools do **not** return raw numeric values. Instead, each call returns a
**randomized natural language sentence** containing the data, for example:

- `"The current temperature in Tokyo is 23.5°C."`
- `"Station #427 calibration for London: base 10.2°C, offset 13.3°C, result 23.5°C."`

The sentence format varies randomly per call and may include noise numbers
(station IDs, timestamps) or arithmetic expressions. Your agent must extract
the correct numeric value from these sentences.
""".strip()

BACKGROUND_ZH = """
# 并行天气查询 背景知识

## 场景

你正在为一个天气信息服务构建 AI Agent。该服务拥有 200 个城市的实时天气数据
（温度和湿度）。用户会批量提交问题，你的 Agent 需要查询天气 API 并快速响应。

## 挑战

天气 API 速度很慢——每次调用大约需要 **10 秒** 才能返回。这模拟了真实场景中
外部 API 调用的高延迟（网络延迟、限流、冷启动等）。

你的 Agent 会一次性收到 **5 个问题**。每个问题都要获取 **2 个不同城市** 的温度和湿度：

- 每题：2 个城市 × 2 个指标（温度+湿度）= 4 次 API 调用
- 每个测试点：5 题 × 4 次 = 20 次 API 调用

拿到数据后，你还需要完成 5 次答案提交：

- 每题 1 次 `submit_answer(...)`
- 5 题共 5 次提交调用

从收到问题到提交答案的总时间预算只有 **27 秒**。
请仔细思考你总共需要多少次 API 调用，以及它们各自的耗时。

## 两种工具类型

天气服务提供两个工具：

- `get_weather(city)` — 普通同步函数
- `get_humidity(city)` — 异步协程

你的 Agent 框架必须能够正确处理这两种类型。

## 自然语言返回值

工具**不会**返回原始数字。每次调用返回一个**随机生成的自然语言句子**，
数据嵌入其中，例如：

- `"The current temperature in Tokyo is 23.5°C."`
- `"Station #427 calibration for London: base 10.2°C, offset 13.3°C, result 23.5°C."`

句式每次调用随机变化，可能包含干扰数字（站点 ID、时间戳）或算术表达式。
你的 Agent 必须从这些句子中提取出正确的数值。
""".strip()

PHASE1_DESCRIPTION_EN = """
# Phase 1: Parallel Weather Query

Build an agent that answers 5 weather questions within a strict time limit.

## 1. Interface

```python
def solve(env):
    questions_json = env.get_questions()
    # ... query weather data using env.get_weather / env.get_humidity ...
    status = env.submit_answer(
        q_index,
        city_a_temperature,
        city_a_humidity,
        city_b_temperature,
        city_b_humidity,
    )
```

### Methods

- `env.get_questions() -> str`
  Returns a JSON array of 5 questions. Each question has:
  ```json
  {"q_index": 0, "city_a": "Tokyo", "city_b": "London"}
  ```

- `env.get_weather(city: str) -> str`
  Returns a **natural language sentence** containing the temperature value
  (e.g. `"The current temperature in Tokyo is 23.5°C."` or an arithmetic
  form like `"base 15.3 + offset 8.2 = 23.5°C"`). The sentence format
  varies randomly per call and may include noise numbers (station IDs,
  timestamps, etc.).
  **Synchronous function** — takes ~10 seconds per call.

- `env.get_humidity(city: str) -> str`
  Returns a **natural language sentence** containing the humidity value
  (same randomized style as `get_weather`).
  **Asynchronous function** — takes ~10 seconds per call. Must be `await`-ed.

- `env.submit_answer(q_index, city_a_temperature, city_a_humidity, city_b_temperature, city_b_humidity) -> str`
  Submit one question answer with 5 numeric values.
  Returns:
  - `"accepted: X/5"` while partial answers are being collected
  - `"correct"` when the 5th answer is submitted and all are correct
  - `"wrong: <details>"` on validation failure

## 2. Rules

- **5 questions** per test case, each asking about 2 different cities.
- Each tool call (`get_weather` / `get_humidity`) takes ~10 seconds.
- Timer starts when you call `get_questions()` and stops when the 5th `submit_answer(...)` is received.
- **Time limit: 27 seconds** from `get_questions()` to final submission.
- Temperature/humidity values must match within ±0.01 tolerance.
- 3 test cases total; all must pass (score 100).

## 3. Scoring

| Condition | Score | Pass? |
|-----------|-------|-------|
| All correct AND time < 27s | 100 | ✓ |
| All correct BUT time >= 27s | 30 | ✗ |
| Any answer wrong | 0 | ✗ |

**Note**: All 3 test cases must score 100 to pass. Any case scoring 30 or 0 = overall failure.

## 4. Hints

- Per case, query count is: 5 questions × 2 cities/question × 2 metrics/city (temperature + humidity) = 20 data queries.
- So the full flow per case is 20 data queries + 5 `submit_answer(...)` calls.
- Calling `submit_answer(...)` with a repeated `q_index` overwrites that question instead of increasing progress.
- Compare total required tool latency with the 27-second budget, then design your scheduling strategy.
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：并行天气查询

构建一个 Agent，在严格的时间限制内回答 5 个天气查询问题。

## 1. 接口

```python
def solve(env):
    questions_json = env.get_questions()
    # ... 使用 env.get_weather / env.get_humidity 查询天气数据 ...
    status = env.submit_answer(
        q_index,
        city_a_temperature,
        city_a_humidity,
        city_b_temperature,
        city_b_humidity,
    )
```

### 方法说明

- `env.get_questions() -> str`
  返回包含 5 个问题的 JSON 数组，每个问题格式如下：
  ```json
  {"q_index": 0, "city_a": "Tokyo", "city_b": "London"}
  ```

- `env.get_weather(city: str) -> str`
  返回一个**自然语言句子**，其中包含温度值
  （如 `"The current temperature in Tokyo is 23.5°C."` 或算术形式
  `"base 15.3 + offset 8.2 = 23.5°C"`）。句式每次调用随机变化，
  可能包含干扰数字（站点 ID、时间戳等）。
  **同步函数** — 每次调用约 10 秒。

- `env.get_humidity(city: str) -> str`
  返回一个**自然语言句子**，其中包含湿度值
  （与 `get_weather` 相同的随机句式）。
  **异步函数** — 每次调用约 10 秒。必须用 `await` 调用。

- `env.submit_answer(q_index, city_a_temperature, city_a_humidity, city_b_temperature, city_b_humidity) -> str`
  用 5 个数值提交单题答案。
  返回值：
  - 尚未提交满 5 题时返回 `"accepted: X/5"`
  - 第 5 题提交后且全部正确返回 `"correct"`
  - 校验失败返回 `"wrong: <详情>"`

## 2. 规则

- 每个测试点 **5 个问题**，每个问题询问 2 个不同城市。
- 每次工具调用（`get_weather` / `get_humidity`）耗时约 10 秒。
- 计时从 `get_questions()` 开始，到第 5 次 `submit_answer(...)` 被接收时结束。
- **时间限制：从 `get_questions()` 到最终提交不超过 27 秒**。
- 温度/湿度值允许 ±0.01 误差。
- 共 3 个测试点，全部必须满分通过。

## 3. 计分

| 条件 | 得分 | 通过？ |
|------|------|--------|
| 全部正确且时间 < 27s | 100 | ✓ |
| 全部正确但时间 >= 27s | 30 | ✗ |
| 任一答案错误 | 0 | ✗ |

**注意**：3 个测试点必须全部得 100 分才算通过。任一点得 30 分或 0 分 = 整体失败。

## 4. 提示

- 每个测试点的数据查询次数为：5 个问题 × 每题 2 个城市 × 每个城市 2 个指标（温度+湿度）= 20 次查询。
- 因此每个测试点的完整流程是：20 次数据查询 + 5 次 `submit_answer(...)`。
- 如果对同一个 `q_index` 重复调用 `submit_answer(...)`，会覆盖该题答案，不会增加进度计数。
- 把总工具耗时与 27 秒预算对比后，再设计你的调用调度策略。
""".strip()

PHASE1_STARTER_CODE_EN = r'''
def solve(env):
    """
    Weather Query Agent

    Args:
        env: environment namespace with these methods:
             env.get_questions() -> str          : fetch 5 questions (JSON)
             env.get_weather(city) -> str         : get temperature as NL sentence (~10s)
             env.get_humidity(city) -> str         : get humidity as NL sentence (~10s)
             env.submit_answer(...) -> str         : submit one answer (5 numeric values)

    Note:
        - get_weather is a regular function (def)
        - get_humidity is an async coroutine (async def)
        - Both return natural language sentences with the value embedded
          (may include noise numbers or arithmetic expressions)
        - Total time limit: 27 seconds
    """
    # TODO: implement your solution
    questions = env.get_questions()
    # ... query weather data, extract values, and call env.submit_answer(...) ...
    pass
'''.strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve(env):
    """
    天气查询 Agent

    参数:
        env: 环境命名空间，提供以下方法:
             env.get_questions() -> str          : 获取 5 个问题 (JSON)
             env.get_weather(city) -> str         : 获取温度（自然语言句子，约 10s）
             env.get_humidity(city) -> str         : 获取湿度（自然语言句子，约 10s）
             env.submit_answer(...) -> str         : 提交单题答案（5 个数值）

    注意:
        - get_weather 是普通函数 (def)
        - get_humidity 是异步协程 (async def)
        - 两者都返回包含数值的自然语言句子
          （可能含干扰数字或算术表达式）
        - 总时间限制：27 秒
    """
    # TODO: 实现你的方案
    questions = env.get_questions()
    # ... 查询天气数据，提取数值，并对每个 q_index 调用 env.submit_answer(...) ...
    pass
'''.strip()
