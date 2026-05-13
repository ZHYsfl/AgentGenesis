"""Local Evaluation SDK exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_genesis.tool_calling import LLMConfig

    from .eval_types import EvalEvent, EvalEventType
    from .evaluator import LocalEvaluator
    from .visualization import TerminalVisualizer

__all__ = [
    "LocalEvaluator",
    "LLMConfig",
    "EvalEvent",
    "EvalEventType",
    "TerminalVisualizer",
]

_LOCAL_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "LocalEvaluator": (".evaluator", "LocalEvaluator"),
    "LLMConfig": ("agent_genesis.tool_calling", "LLMConfig"),
    "EvalEvent": (".eval_types", "EvalEvent"),
    "EvalEventType": (".eval_types", "EvalEventType"),
    "TerminalVisualizer": (".visualization", "TerminalVisualizer"),
}


def __getattr__(name: str):  # noqa: ANN001
    if name in _LOCAL_LAZY_IMPORTS:
        import importlib

        module_path, attr = _LOCAL_LAZY_IMPORTS[name]
        if module_path.startswith("."):
            mod = importlib.import_module(module_path, __package__)
        else:
            mod = importlib.import_module(module_path)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
