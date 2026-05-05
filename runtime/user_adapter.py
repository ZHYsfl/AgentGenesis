"""User adapter contract and dynamic adapter loading."""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

import queue

DEFAULT_SOLVE_MODULE_NAME = "solution"
DEFAULT_SOLVE_ATTR_NAME = "solve"


@dataclass
class AdapterConfig:
    solve_attr_name: str = DEFAULT_SOLVE_ATTR_NAME


@runtime_checkable
class UserAdapterProtocol(Protocol):
    """Structural contract checked at runtime via isinstance().

    Immune to module-path mismatches (eval_runtime vs agent_genesis).
    """

    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any: ...


class UserAdapter(ABC):
    """Public base class for problem authors to inherit from.

    Provides IDE autocomplete and enforces implementation at class-definition
    time.  The runtime safety check uses UserAdapterProtocol instead so that
    adapters loaded from any module path pass correctly.
    """

    @abstractmethod
    def create_user_api(
        self,
        act_queue: "queue.Queue[Optional[dict[str, Any]]]",
        obs_queue: "queue.Queue[Optional[Any]]",
    ) -> Any:
        ...

def _load_problem_adapter_module() -> Any:
    for module_name in ("eval_runtime.problem_adapter", "agent_genesis.runtime.problem_adapter"):
        try:
            return importlib.import_module(module_name)
        except ImportError:
            continue
    return None


def get_adapter(preset_name: str = "default") -> UserAdapter:
    mod = _load_problem_adapter_module()
    if mod is None:
        raise RuntimeError(
            "problem adapter module not found; expected eval_runtime.problem_adapter"
        )

    factory = getattr(mod, "get_adapter", None)
    if callable(factory):
        adapter = factory(preset_name)
        if not isinstance(adapter, UserAdapterProtocol):
            raise RuntimeError(
                "problem adapter factory must return UserAdapter instance"
            )
        return adapter
    raise RuntimeError("problem adapter module must provide get_adapter(preset_name)")


def load_user_entry(config: AdapterConfig) -> Any:
    module = importlib.import_module(DEFAULT_SOLVE_MODULE_NAME)
    entry = getattr(module, config.solve_attr_name, None)
    if not callable(entry):
        raise RuntimeError(
            f"{DEFAULT_SOLVE_MODULE_NAME}.{config.solve_attr_name} is not callable"
        )
    return entry
