"""Public API helpers for evaluation package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Type, Optional

if TYPE_CHECKING:
    from .service import EvaluationService

from .models import (
    PhaseConfig,
    ProblemConfig,
)
from .base import BaseEvaluator
from .client import EvaluationClient
from .registry import ProblemRegistry
from .config import ClientMode


def create_config(
    num_cases: int = 10,
    parallel_cases: int = 1,
    **kwargs,
) -> PhaseConfig:
    return PhaseConfig(
        num_cases=num_cases,
        parallel_cases=parallel_cases,
        **kwargs,
    )


def create_phase(
    evaluator: Type[BaseEvaluator],
    config: PhaseConfig,
) -> PhaseConfig:
    return config.model_copy(update={
        "evaluator_module": evaluator.__module__,
        "evaluator_class": evaluator.__name__,
    })


def create_problem(
    title: str,
    phases: list[PhaseConfig],
    overview: str = "",
    background: str = "",
    level: str = "",
    language: str = "en",
    gitattributes: str = "",
    is_public: bool = False,
    data_public: bool = False,
) -> ProblemConfig:
    if not phases:
        raise ValueError("At least one phase is required")
    if not level:
        level = phases[0].phase_level or "Medium"
    return ProblemConfig(
        title=title,
        overview=overview,
        background=background,
        level=level,
        language=language,
        gitattributes=gitattributes,
        is_public=is_public,
        data_public=data_public,
        phases=phases,
    )


def init_registry(
    mode: ClientMode,
    api_key: str,
    backend_url: Optional[str] = None,
) -> ProblemRegistry:
    return ProblemRegistry.init(mode=mode, api_key=api_key, backend_url=backend_url)


def get_registry() -> ProblemRegistry:
    return ProblemRegistry.instance()


def register_problem(definition: ProblemConfig) -> None:
    get_registry().register(definition)


def sync_problem(title: str) -> dict[int, bool]:
    registry = get_registry()
    definition: Optional[ProblemConfig] = registry.get(title)
    if definition is None:
        return {}
    return registry.sync_to_db(definition)


def sync_all_problems() -> dict[str, dict[int, bool]]:
    return get_registry().sync_all()


def create_problem_revision(
    title: str,
    phase_order: int = 1,
    revision_title: Optional[str] = None,
    revision_description: Optional[str] = None,
) -> bool:
    registry = get_registry()
    definition: Optional[ProblemConfig] = registry.get(title)
    if definition is None:
        return False
    return registry.create_revision(
        definition,
        phase_order=phase_order,
        title=revision_title,
        description=revision_description,
    )


def create_client(
    backend_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> EvaluationClient:
    return EvaluationClient(base_url=backend_url, api_key=api_key)


def create_service(
    max_workers: Optional[int] = None,
    poll_interval: Optional[int] = None,
    client: Optional[EvaluationClient] = None,
) -> "EvaluationService":
    from .service import EvaluationService
    return EvaluationService(
        client=client,
        max_workers=max_workers,
        poll_interval=poll_interval,
    )


def run_service(
    max_workers: Optional[int] = None,
    poll_interval: Optional[int] = None,
) -> None:
    service = create_service(max_workers, poll_interval)
    service.run()


def get_version_history(
    title: str,
    limit: int = 50,
    phase_order: Optional[int] = None,
    client: Optional[EvaluationClient] = None,
) -> dict:
    c = client or create_client()
    return c.get_version_history(title, limit=limit, phase_order=phase_order)


def get_version_diff(
    title: str,
    from_sha: str,
    to_sha: str,
    client: Optional[EvaluationClient] = None,
) -> dict:
    c = client or create_client()
    return c.get_version_diff(title, from_sha, to_sha)


def list_revisions(
    title: str,
    phase_order: int = 0,
    status: str = "",
    client: Optional[EvaluationClient] = None,
) -> list[dict]:
    c = client or create_client()
    return c.list_revisions(title, phase_order=phase_order, status=status)


def create_revision(
    title: str,
    revision_title: str,
    phase_config: dict,
    description: str = "",
    phase_order: int = 1,
    problem_meta: Optional[dict] = None,
    client: Optional[EvaluationClient] = None,
) -> Optional[dict]:
    c = client or create_client()
    return c.create_revision(
        title=title,
        revision_title=revision_title,
        description=description,
        phase_config=phase_config,
        phase_order=phase_order,
        problem_meta=problem_meta,
    )


def merge_revision(
    title: str,
    revision_id: int,
    comment: str = "",
    force: bool = False,
    resolved_files: Optional[dict[str, str]] = None,
    client: Optional[EvaluationClient] = None,
) -> dict:
    c = client or create_client()
    return c.merge_revision(
        title, revision_id,
        comment=comment, force=force, resolved_files=resolved_files,
    )


def close_revision(
    title: str,
    revision_id: int,
    comment: str = "",
    client: Optional[EvaluationClient] = None,
) -> bool:
    c = client or create_client()
    return c.close_revision(title, revision_id, comment=comment)


def get_data_export(
    title: str,
    limit: int = 1000,
    offset: int = 0,
    client: Optional[EvaluationClient] = None,
) -> dict:
    c = client or create_client()
    return c.get_data_export(title, limit=limit, offset=offset)


def get_phase_template(
    title: str,
    phase_order: int = 1,
    lang: str = "en",
    commit: str = "",
    client: Optional[EvaluationClient] = None,
) -> dict:
    c = client or create_client()
    return c.get_phase_template(title, phase_order=phase_order, lang=lang, commit=commit)


def get_phase_files(
    title: str,
    phase_order: int = 1,
    commit: str = "",
    client: Optional[EvaluationClient] = None,
) -> dict:
    c = client or create_client()
    return c.get_phase_files(title, phase_order=phase_order, commit=commit)


