"""ML Hyperparameter Tuner problem configuration."""

from typing import Optional

from agent_genesis import PhaseConfig


class MLHyperparamTunerConfig(PhaseConfig):
    """Config for the ML Hyperparameter Tuning challenge."""

    # =========== Problem-specific parameters ===========
    max_trials: int = 10
    random_state: Optional[int] = None  # None = random per case

    # =========== Evaluation parameters ===========
    num_cases: int = 3
    min_passed_cases: Optional[int] = 3  # All cases must pass (hard mode)
    parallel_cases: int = 1
    time_limit: float = 120.0
    sandbox_timeout: int = 300
    case_idle_timeout: int = 60
    user_deps_timeout: int = 300
    chmod_timeout: int = 10
    run_timeout: int = 120
    sandbox_cpu_count: float = 0.8
    memory_limit_mb: int = 1024

    # =========== Dependencies ===========
    pip_dependencies: list[str] = [
        "scikit-learn",
        "numpy",
    ]

    # =========== User bridge ===========
    solve_attr_name: str = "solve"
    adapter_preset: str = "ml_hyperparam_tuner"

    # =========== Private files ===========
    private_files: Optional[list[str]] = []

    # =========== Evaluator metadata ===========
    evaluator_module: str = "agent_genesis.dual_sandbox_evaluator"
    evaluator_class: str = "DualSandboxEvaluator"

    artifact_entry: str = "sandbox/run.py"

    # =========== Gateway limits ===========
    gateway_max_chars: int = 5000000
    gateway_max_requests: int = 1000
    gateway_ttl_minutes: int = 30


# =============================================================================
# Localized content
# =============================================================================

OVERVIEW_EN = (
    "Build an AI agent that tunes machine learning model hyperparameters "
    "to maximize classification accuracy on hidden datasets. "
    "You have a limited number of training trials — use them wisely."
)

OVERVIEW_ZH = (
    "构建一个 AI Agent，为隐藏的分类数据集调优机器学习模型的超参数，"
    "以最大化分类准确率。你的训练尝试次数有限——请明智地使用它们。"
)

BACKGROUND_EN = """
# ML Hyperparameter Tuning Background

## Scenario

You are building an AI agent for automated machine learning (AutoML). The agent
must select the best model and hyperparameters for a given classification dataset.

## The Challenge

For each test case, you are given a hidden classification dataset. You do not
see the data directly. Instead, you interact with a training environment that
lets you:

1. Query the list of available models and their hyperparameter ranges
2. Train a model with specific hyperparameters and receive a validation score
3. Submit your best configuration for final evaluation

**Key constraint**: You have at most **10 training trials** per case. Each call
to `env.train(...)` consumes one trial. Once you run out of trials, you can only
submit your final answer.

## Available Models

Three sklearn classifiers are available:

- **LogisticRegression**
  - `C`: regularization strength (float, range 0.01 ~ 10.0)
- **RandomForestClassifier**
  - `n_estimators`: number of trees (int, range 10 ~ 200)
  - `max_depth`: maximum depth per tree (int, range 2 ~ 20, or null for unlimited)
- **SVC** (Support Vector Machine)
  - `C`: regularization strength (float, range 0.1 ~ 10.0)
  - `kernel`: "linear" or "rbf"

## Strategy Tips

- Start by querying `env.get_problem_info()` to know the dataset shape and available models.
- Use your first few trials to explore different model families.
- Once you find a promising model, fine-tune its hyperparameters.
- Keep track of the best validation score and the configuration that produced it.
- Submit the configuration with the highest validation score.
""".strip()

BACKGROUND_ZH = """
# 机器学习超参数调优背景知识

## 场景

你正在构建一个用于自动化机器学习（AutoML）的 AI Agent。该 Agent 必须为给定的
分类数据集选择最佳模型和超参数。

## 挑战

对于每个测试用例，你都会获得一个隐藏的分类数据集。你无法直接看到数据，
而是通过训练环境进行交互：

1. 查询可用模型列表及其超参数范围
2. 用特定超参数训练模型并接收验证分数
3. 提交最佳配置进行最终评估

**关键约束**：每个用例最多 **10 次训练尝试**。每次调用 `env.train(...)`
消耗一次尝试次数。用完尝试次数后，你只能提交最终答案。

## 可用模型

提供三种 sklearn 分类器：

- **LogisticRegression**
  - `C`：正则化强度（浮点数，范围 0.01 ~ 10.0）
- **RandomForestClassifier**
  - `n_estimators`：树的数量（整数，范围 10 ~ 200）
  - `max_depth`：每棵树的最大深度（整数，范围 2 ~ 20，或 null 表示无限制）
- **SVC**（支持向量机）
  - `C`：正则化强度（浮点数，范围 0.1 ~ 10.0）
  - `kernel`："linear" 或 "rbf"

## 策略建议

- 首先调用 `env.get_problem_info()` 了解数据集形状和可用模型。
- 用前几次尝试探索不同的模型族。
- 找到有潜力的模型后，微调其超参数。
- 记录最佳验证分数及其对应的配置。
- 提交验证分数最高的配置。
""".strip()

PHASE1_DESCRIPTION_EN = """
# Phase 1: ML Hyperparameter Tuner

Tune hyperparameters to maximize classification accuracy on hidden datasets.

## 1. Interface

```python
def solve(env):
    info = env.get_problem_info()
    # ... explore hyperparameter space using env.train(...) ...
    score = env.train(model_name="RandomForest", params={"n_estimators": 50, "max_depth": 10})
    # ... after at most 10 trials, submit your best configuration ...
    env.submit_answer(best_config)
```

### Methods

- `env.get_problem_info() -> dict`
  Returns dataset and model information:
  ```json
  {
    "n_features": 10,
    "n_samples": 500,
    "n_classes": 3,
    "available_models": {
      "LogisticRegression": {"C": {"type": "float", "min": 0.01, "max": 10.0}},
      "RandomForest": {
        "n_estimators": {"type": "int", "min": 10, "max": 200},
        "max_depth": {"type": "int", "min": 2, "max": 20, "nullable": true}
      },
      "SVM": {
        "C": {"type": "float", "min": 0.1, "max": 10.0},
        "kernel": {"type": "choice", "options": ["linear", "rbf"]}
      }
    },
    "max_trials": 10
  }
  ```

- `env.train(model_name: str, params: dict) -> dict`
  Train a model with the given hyperparameters and return validation metrics.
  **Consumes 1 trial.**
  Returns:
  ```json
  {"trial": 3, "accuracy": 0.87, "trials_remaining": 7}
  ```
  Raises `RuntimeError` if no trials remain.

- `env.submit_answer(config: dict) -> dict`
  Submit the best configuration for final test-set evaluation.
  Returns:
  ```json
  {"test_accuracy": 0.92, "score": 80}
  ```
  After submission, the case ends.

## 2. Rules

- **Max 10 trials** per case. Each `env.train(...)` call counts as 1 trial.
- `env.get_problem_info()` does **not** consume a trial.
- `env.submit_answer(...)` does **not** consume a trial, but ends the case.
- You may call `env.train(...)` with the same configuration multiple times (wasteful but allowed).
- Total time limit per case: **120 seconds**.

## 3. Scoring

Final score is based on **test-set accuracy** of your submitted configuration:

| Test Accuracy | Score | Pass? |
|---------------|-------|-------|
| >= 0.95 | 100 | Yes |
| >= 0.90 | 80 | Yes |
| >= 0.85 | 60 | Yes |
| >= 0.80 | 40 | No |
| < 0.80 | 0 | No |

**Note**: All **3 out of 3** cases must score >= 60 (pass threshold) for overall success.

## 4. Hints

- Try different model families first (LogisticRegression, RandomForest, SVM) with default-ish parameters.
- RandomForest often handles non-linear relationships well.
- SVM with RBF kernel can be powerful but sensitive to `C`.
- LogisticRegression is fast and good baseline for linearly separable data.
- You do not need to use all 10 trials — if you find a great config early, submit it.
""".strip()

PHASE1_DESCRIPTION_ZH = """
# 第一阶段：机器学习超参数调优

为隐藏的分类数据集调优超参数，以最大化分类准确率。

## 1. 接口

```python
def solve(env):
    info = env.get_problem_info()
    # ... 使用 env.train(...) 探索超参数空间 ...
    score = env.train(model_name="RandomForest", params={"n_estimators": 50, "max_depth": 10})
    # ... 最多 10 次尝试后，提交最佳配置 ...
    env.submit_answer(best_config)
```

### 方法说明

- `env.get_problem_info() -> dict`
  返回数据集和模型信息：
  ```json
  {
    "n_features": 10,
    "n_samples": 500,
    "n_classes": 3,
    "available_models": {
      "LogisticRegression": {"C": {"type": "float", "min": 0.01, "max": 10.0}},
      "RandomForest": {
        "n_estimators": {"type": "int", "min": 10, "max": 200},
        "max_depth": {"type": "int", "min": 2, "max": 20, "nullable": true}
      },
      "SVM": {
        "C": {"type": "float", "min": 0.1, "max": 10.0},
        "kernel": {"type": "choice", "options": ["linear", "rbf"]}
      }
    },
    "max_trials": 10
  }
  ```

- `env.train(model_name: str, params: dict) -> dict`
  用给定超参数训练模型并返回验证指标。
  **消耗 1 次尝试。**
  返回：
  ```json
  {"trial": 3, "accuracy": 0.87, "trials_remaining": 7}
  ```
  如果没有剩余尝试次数，抛出 `RuntimeError`。

- `env.submit_answer(config: dict) -> dict`
  提交最佳配置进行最终测试集评估。
  返回：
  ```json
  {"test_accuracy": 0.92, "score": 80}
  ```
  提交后，该用例结束。

## 2. 规则

- 每个用例最多 **10 次尝试**。每次 `env.train(...)` 调用消耗 1 次。
- `env.get_problem_info()` **不**消耗尝试次数。
- `env.submit_answer(...)` **不**消耗尝试次数，但会结束该用例。
- 可以多次用相同配置调用 `env.train(...)`（浪费但允许）。
- 每个用例总时间限制：**120 秒**。

## 3. 计分

最终得分基于提交配置在**测试集**上的准确率：

| 测试准确率 | 得分 | 通过？ |
|-----------|------|--------|
| >= 0.95 | 100 | 是 |
| >= 0.90 | 80 | 是 |
| >= 0.85 | 60 | 是 |
| >= 0.80 | 40 | 否 |
| < 0.80 | 0 | 否 |

**注意**：**3/3** 个用例得分都必须 >= 60（通过阈值）才算整体成功。

## 4. 提示

- 先用默认-ish 参数尝试不同模型族（LogisticRegression、RandomForest、SVM）。
- RandomForest 通常能很好地处理非线性关系。
- SVM 配合 RBF 核可以很强大，但对 `C` 敏感。
- LogisticRegression 速度快，对于线性可分数据是很好的基线。
- 不需要用完所有 10 次尝试——如果早期找到很好的配置，直接提交。
""".strip()

PHASE1_STARTER_CODE_EN = r'''
def solve(env):
    """
    ML Hyperparameter Tuning Agent

    Args:
        env: environment namespace with these methods:
             env.get_problem_info() -> dict   : dataset & model info
             env.train(model, params) -> dict : train model, returns {trial, accuracy, trials_remaining}
             env.submit_answer(config) -> dict: submit best config, returns {test_accuracy, score}

    Constraints:
        - Max 10 training trials per case
        - Each env.train(...) consumes 1 trial
        - Total time limit: 120 seconds
    """
    info = env.get_problem_info()
    max_trials = info["max_trials"]
    # TODO: implement your hyperparameter search strategy
    pass
'''.strip()

PHASE1_STARTER_CODE_ZH = r'''
def solve(env):
    """
    机器学习超参数调优 Agent

    参数:
        env: 环境命名空间，提供以下方法:
             env.get_problem_info() -> dict   : 数据集和模型信息
             env.train(model, params) -> dict : 训练模型，返回 {trial, accuracy, trials_remaining}
             env.submit_answer(config) -> dict: 提交最佳配置，返回 {test_accuracy, score}

    约束:
        - 每个用例最多 10 次训练尝试
        - 每次 env.train(...) 消耗 1 次尝试
        - 总时间限制：120 秒
    """
    info = env.get_problem_info()
    max_trials = info["max_trials"]
    # TODO: 实现你的超参数搜索策略
    pass
'''.strip()
