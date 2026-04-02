"""Local Evaluation SDK

Enables developers to run evaluations locally without cloud services.

Basic Usage:
    from evaluation.local import LocalEvaluator, LLMConfig

    # Configure LLM
    llm_config = LLMConfig(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key="your-api-key",
        # extra_body={"enable_thinking": False},
    )

    # Create evaluator
    evaluator = LocalEvaluator(
        problem_path="problems/interrupt_judge",
        user_code_path="answer/interrupt_judge/solution.py",
        llm_config=llm_config,
    )

    # Run evaluation
    result = evaluator.evaluate()
    print(f"Passed: {result.passed_cases}/{result.total_cases}")

Streaming Evaluation (with visualization):
    from evaluation.local import TerminalVisualizer

    visualizer = TerminalVisualizer(show_oa_sequence=True)
    for event in evaluator.evaluate_stream():
        visualizer.on_event(event)
"""

from agent_genesis.tool_calling import LLMConfig

from .evaluator import LocalEvaluator
from .eval_types import EvalEvent, EvalEventType
from .visualization import TerminalVisualizer

__all__ = [
    "LocalEvaluator",
    "LLMConfig",
    "EvalEvent",
    "EvalEventType",
    "TerminalVisualizer",
]