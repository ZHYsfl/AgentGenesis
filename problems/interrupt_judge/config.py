# problems/interrupt_judge/config.py
"""Interrupt judgment problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class InterruptJudgeConfig(PhaseConfig):
    """Interrupt judgment-specific problem configuration."""

    # =========== Evaluation parameters ===========
    num_cases: int = 5
    min_passed_cases: Optional[int] = None
    parallel_cases: int = 5
    time_limit: float = 180.0
    sandbox_timeout: int = 240
    case_idle_timeout: int = 35

    # =========== Judge script dependencies ===========
    pip_dependencies: list[str] = []

    # =========== User bridge ===========
    solve_attr_name: str = "solve"
    adapter_preset: str = "interrupt_judge"

    # =========== Private files ===========
    private_files: Optional[list[str]] = []

    # =========== Evaluator metadata ===========
    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"


# =========== Localized problem content ===========
INTERRUPT_JUDGE_OVERVIEW_EN = "Determine whether user utterances should be interrupted."
INTERRUPT_JUDGE_OVERVIEW_ZH = "判断用户话语是否需要打断。"

# =========== Phase description and starter code (English) ===========
INTERRUPT_JUDGE_BACKGROUND = """
# Interrupt Judgment Background Knowledge

This problem trains an LLM-driven agent to determine whether a user's utterance should be interrupted.

## Judgment Criteria (V1)

**interrupt (需要打断)：**
- Complete sentence: "今天天气怎么样"
- Incomplete sentence: "我想问"、"那个东西"
- Single-word command: "停"、"好"、"对"、"不"
- Confirmation/negation: "可以"、"不要"、"谢谢"、"再说一遍"
- Filler + content: "嗯我想问"、"啊对了"

**do not interrupt (不打断)：**
- Pure filler words: "嗯"、"啊"、"哦"、"呃"、"emm"、"额"
- Repeated filler: "啊啊啊"、"嗯嗯"、"呃呃"
- ASR misrecognition (cough/sneeze): usually garbled or single syllable
- Pure noise/blank: meaningless text from environmental noise

## Prerequisites

**This problem requires deploying your own inference service to a public endpoint.**

Since this is an edge-side inference challenge, you need to:

1. Deploy your fine-tuned model as an API service
2. Expose your local API to the internet using ngrok, cloudflare tunnel, etc.
3. Configure your solution to call your public endpoint
""".strip()

INTERRUPT_JUDGE_BACKGROUND_ZH = """
# 打断判断背景知识

本题训练 LLM 驱动的智能体判断用户话语是否需要打断。

## 判断标准 (V1)

**interrupt (需要打断)：**
- 完整句子："今天天气怎么样"
- 半句话："我想问"、"那个东西"
- 单字指令："停"、"好"、"对"、"不"
- 确认/否定词："可以"、"不要"、"谢谢"、"再说一遍"
- 语气词+实词："嗯我想问"、"啊对了"

**do not interrupt (不打断)：**
- 纯语气词："嗯"、"啊"、"哦"、"呃"、"emm"、"额"
- 重复语气词："啊啊啊"、"嗯嗯"、"呃呃"
- ASR 误识别（咳嗽/喷嚏）：通常是乱码或单音节
- 纯噪音/空白：环境噪音产生的无意义文字

## 前置要求

**本题需要将你自己的推理服务部署到公网端点。**

由于这是端侧推理挑战，你需要：

1. 部署你的微调模型作为 API 服务
2. 将本地 API 暴露到公网（使用 ngrok、cloudflare tunnel 等）
3. 在解决方案中配置调用你的公网端点
""".strip()

PHASE1_DESCRIPTION = """
# Phase 1: Interrupt Judgment

Determine whether each user utterance should be interrupted.

## 1. Interface

You need to implement the `solve` function, receiving one parameter:

```python
def solve(get_problem, submit_answer):
    # Your code here
    pass
```

### Parameters

- `env`: An object that provides access to the environment APIs.
  - `env.get_problem()`: Returns a list of user utterances (`list[str]`)
    - Example: `["哦？", "给我找附近的餐厅", "啊啊呵呵", ...]`
  - `env.submit_answer(answers)`: Submit your predictions
    - Parameter: `answers` should be a `list[bool]` with the same length as questions
      - `True` = this utterance **should be interrupted** (需要打断)
      - `False` = this utterance **should NOT be interrupted** (不需要打断)
    - Returns: `dict` with keys:
      - `accuracy`: float (0.0 to 1.0, e.g., 0.984 means 98.4%)
      - `score`: float (same as accuracy, 98.4 for 98.4%)
      - `correct`: int (number of correct predictions)
      - `total`: int (total number of questions)
      - `passed`: bool (True if accuracy >= 0.985)

### Example

```python
def solve(env):
    # Step 1: Get all questions (user utterances)
    questions = env.get_problem()  # e.g., ["哦？", "给我找附近的餐厅", "啊啊呵呵"]

    # Step 2: Your model predicts True/False for each question
    answers = []
    for q in questions:
        # Your logic here - call your fine-tuned model
        prediction = your_model.predict(q)
        answers.append(prediction)  # True or False

    # Step 3: Submit all answers at once
    result = env.submit_answer(answers)

    # Step 4: Check result
    print(f"Accuracy: {result['accuracy'] * 100:.1f}%")  # e.g., "Accuracy: 98.4%"
    print(f"Passed: {result['passed']}")  # True or False
```

## 2. Task Description

Each test case contains **500 Chinese utterances**. For each utterance, you need to predict:

- **True (打断)**: The utterance should be interrupted because:
  - It's a complete sentence with clear intent (e.g., "给我找附近的餐厅")
  - It's a fragment with clear intent (e.g., "我要查询")
  - It's a command or request

- **False (不打断)**: The utterance should NOT be interrupted because:
  - It's just filler words with no semantic meaning (e.g., "啊啊呵呵", "哇哇哇哇哇")
  - It's incomplete and waiting for user to continue

## 3. Constraints

- **Time limit**: 25 seconds per test case (from get_problem() to submit_answer())
- **Total test cases**: 5
- **Pass threshold**: Accuracy >= 98.5%

## 4. Scoring

- **Accuracy = Score**: If you get 98.4% correct, you get 98.4 points
- **Pass condition**: accuracy >= 98.5% (i.e., at least 493 out of 500 correct)
- Each test case is scored independently
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：打断判断

判断每个用户话语是否需要打断。

## 1. 接口

你需要补充实现 `solve` 函数，接收一个参数 `env`：

```python
def solve(env):
    # 你的代码
    pass
```

### 参数说明

- `env`: 提供环境 API 的对象。
  - `env.get_problem()`: 返回用户话语列表 (`list[str]`)
    - 例如：`["哦？", "给我找附近的餐厅", "啊啊呵呵", ...]`
  - `env.submit_answer(answers)`: 提交你的预测
    - 参数：`answers` 应该是一个 `list[bool]`，长度必须与 questions 相同
      - `True` = 这个话语**需要打断**
      - `False` = 这个话语**不需要打断**
    - 返回：`dict`，包含：
      - `accuracy`: float (0.0 到 1.0，例如 0.984 表示 98.4%)
      - `score`: float (同 accuracy，98.4 表示 98.4 分)
      - `correct`: int (正确预测的数量)
      - `total`: int (问题总数)
      - `passed`: bool (True 如果 accuracy >= 0.985)

### 示例代码

```python
def solve(env):
    # 第一步：获取所有问题（用户话语）
    questions = env.get_problem()  # 例如 ["哦？", "给我找附近的餐厅", "啊啊呵呵"]

    # 第二步：你的模型预测每个问题是 True 还是 False
    answers = []
    for q in questions:
        # 在这里调用你的微调模型
        prediction = your_model.predict(q)
        answers.append(prediction)  # True 或 False

    # 第三步：一次性提交所有答案
    result = env.submit_answer(answers)

    # 第四步：查看结果
    print(f"正确率: {result['accuracy'] * 100:.1f}%")  # 例如 "正确率: 98.4%"
    print(f"是否通过: {result['passed']}")  # True 或 False
```

## 2. 任务描述

每个测试用例包含 **500 条中文话语**。对每条话语，你需要预测：

- **True (打断)**: 该话语需要打断，因为：
  - 是完整句子，有明确意图（例如："给我找附近的餐厅"）
  - 是半句话，有明确意图（例如："我要查询"）
  - 是指令或请求

- **False (不打断)**: 该话语不需要打断，因为：
  - 只是语气词，没有语义（例如："啊啊呵呵"、"哇哇哇哇哇"）
  - 是不完整表达，等用户继续说

## 3. 约束条件

- **时间限制**：每个测试用例 25 秒（从 get_problem() 调用到 submit_answer() 返回）
- **总测试用例数**：5 个
- **通过阈值**：正确率 >= 98.5%

## 4. 评分规则

- **正确率 = 得分**：如果你答对 98.4%，就得 98.4 分
- **通过条件**：正确率 >= 98.5%（即 500 题中至少答对 493 题）
- 每个测试用例独立计分
""".strip()

PHASE1_STARTER_CODE = r'''
def solve(env):
    questions = env.get_problem()  # list[str]
    # TODO: call your model API to predict True/False for each question
    answers = [False] * len(questions)
    result = env.submit_answer(answers)
'''.strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve(env):
    questions = env.get_problem()  # list[str]
    # TODO: 调用你的模型 API 预测每个问题是 True 还是 False
    answers = [False] * len(questions)
    result = env.submit_answer(answers)
'''.strip()
