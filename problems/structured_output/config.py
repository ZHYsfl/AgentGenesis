"""Structured Output problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class StructuredOutputConfig(PhaseConfig):
    """Config for the Structured Output challenge."""

    # =========== Problem-specific parameters ===========
    total_questions: int = 1000
    time_limit: float = 25.0

    # =========== Evaluation parameters ===========
    num_cases: int = 10
    min_passed_cases: Optional[int] = None
    parallel_cases: int = 1
    sandbox_timeout: int = 500
    case_idle_timeout: int = 25

    # =========== Dependencies ===========
    pip_dependencies: list[str] = [
        "openai",
        "pydantic",
    ]

    # =========== Image data baking ===========
    image_data_dirs: list[str] = ["data"]

    # =========== User bridge ===========
    solve_attr_name: str = "solve"
    adapter_preset: str = "structured_output"

    # =========== Private files ===========
    private_files: Optional[list[str]] = [
        "data"
    ]

    # =========== Evaluator metadata ===========
    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"


OVERVIEW_EN = (
    "Test your LLM's ability to produce precise, schema-compliant JSON "
    "by answering structured-output questions drawn from a 1000-question bank."
)

OVERVIEW_ZH = (
    "测试大语言模型生成精确、符合 schema 的 JSON 的能力，"
    "从 1000 道题库中随机抽取结构化输出题目进行作答。"
)

BACKGROUND_EN = """
# Structured Output Background

Large Language Models are increasingly used to produce **structured data** rather than
free-form text.  Applications such as data extraction, form filling, and API response
generation all require the model to emit valid JSON that matches a precise schema.

## Why this is challenging

- The model must respect exact key names, value types, and nesting.
- Invalid JSON (including trailing commas) or wrong field values/types will fail.
- Some questions demand reasoning before formatting the answer.

## Strategy hints

- Use the system prompt to enforce output format rules.
- Ask the model to reply with **only** the JSON object, no wrapping text.
- Validate or post-process the output to strip accidental fences or whitespace.
""".strip()

BACKGROUND_ZH = """
# 结构化输出 背景知识

大语言模型越来越多地被用于生成**结构化数据**而非自由文本。数据提取、表单填写、
API 响应生成等应用场景都要求模型输出严格符合指定 schema 的合法 JSON。

## 为什么具有挑战性

- 模型必须严格遵守键名、值类型和嵌套结构。
- 非法 JSON（例如尾逗号）或字段值/类型错误都会导致判错。
- 部分题目需要先推理再格式化答案。

## 策略提示

- 在 system prompt 中强制规定输出格式。
- 要求模型**仅**回复 JSON 对象，不要包含任何其他文字。
- 对输出进行后处理，去除意外的代码围栏或多余空白。
""".strip()

PHASE1_DESCRIPTION_EN = """
# Phase 1: Structured Output

Answer randomly-selected structured-output questions by producing schema-correct JSON.

## 1. Interface

```python
def solve(env):
    question = env.get_question()   # fetch the question text
    # ... use an LLM to produce clean JSON ...
    result = env.submit_answer(json_str)  # submit your answer
```

- `env.get_question() -> str`
  - Returns the full question text describing the required JSON schema and content.
- `env.submit_answer(answer: str) -> str`
  - Submit your JSON string answer. Returns feedback ("correct" / "wrong").
  - **Only one submission per test case.**

## 2. Rules

- Each test case presents one question randomly drawn from a 1000-question bank.
- Your answer must be a **clean JSON string** — no markdown fences, no extra text.
- The judge parses both outputs as JSON and checks **semantic equality**
  (structure, keys, value types, and values), not formatting.
- 10 test cases total; **all 10 must pass** to succeed.

## 3. Scoring

- Each correct answer: 100 points
- Each wrong answer: 0 points
- Time limit: 25 seconds per case, 500 seconds total

## 4. Difficulty distribution (for reference)

The question bank contains:
- 250 easy questions (simple key-value JSON)
- 300 medium questions (nested objects, arrays)
- 450 hard questions (complex schemas, conditional fields, reasoning required)
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：结构化输出

回答随机抽取的结构化输出题目，生成 schema 正确的 JSON。

## 1. 接口

```python
def solve(env):
    question = env.get_question()   # 获取题目文本
    # ... 调用大模型生成干净的 JSON ...
    result = env.submit_answer(json_str)  # 提交答案
```

- `env.get_question() -> str`
  - 返回完整的题目文本，描述需要生成的 JSON schema 和内容。
- `env.submit_answer(answer: str) -> str`
  - 提交你的 JSON 字符串答案。返回反馈（"correct" / "wrong"）。
  - **每个测试点只能提交一次。**

## 2. 规则

- 每个测试点从 1000 道题库中随机抽取一道题目。
- 答案必须是**干净的 JSON 字符串** — 不能包含 markdown 围栏、不能有多余文字。
- 评判会将双方答案解析为 JSON 后做**语义等价比较**
  （结构、键名、值类型和值），不看格式化差异。
- 共 10 个测试点，**全部正确才算通过**。

## 3. 计分

- 每道正确：100 分
- 每道错误：0 分
- 时间限制：每个测试点 25 秒，总计 500 秒

## 4. 难度分布（参考）

题库包含：
- 250 道简单题（简单键值对 JSON）
- 300 道中等题（嵌套对象、数组）
- 450 道困难题（复杂 schema、条件字段、需要推理）
""".strip()

PHASE1_STARTER_CODE_EN = r'''
def solve(env):
    """
    Structured Output Agent

    Args:
        env: environment namespace with two methods:
             env.get_question() -> str   : fetch the question text
             env.submit_answer(s) -> str : submit your JSON answer

    Call get_question() to read the task, produce a clean JSON string,
    then call submit_answer(json_str).
    """
    # TODO: implement your structured output strategy
    question = env.get_question()
    # ... call LLM, get JSON ...
    # env.submit_answer(json_str)
    pass
'''.strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve(env):
    """
    结构化输出 Agent

    参数:
        env: 环境命名空间，提供两个方法:
             env.get_question() -> str   : 获取题目文本
             env.submit_answer(s) -> str : 提交 JSON 答案

    调用 get_question() 获取题目，生成干净的 JSON 字符串，
    然后调用 submit_answer(json_str) 提交。
    """
    # TODO: 实现你的结构化输出策略
    question = env.get_question()
    # ... 调用大模型，获取 JSON ...
    # env.submit_answer(json_str)
    pass
'''.strip()
