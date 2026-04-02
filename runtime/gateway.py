"""Gateway token lifecycle and per-case usage accounting helpers."""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from ..models import CaseResult, UserSubmission

logger: logging.Logger = logging.getLogger(__name__)


class GatewayConfigLike(Protocol):
    allow_user_key: bool
    gateway_max_chars: int
    gateway_max_requests: int
    num_cases: int
    gateway_allowed_models: list[str]
    gateway_ttl_minutes: int


class GatewayClientLike(Protocol):
    def create_gateway_token(
        self,
        *,
        submit_id: int,
        user_id: int,
        key_ids: list[int],
        allowed_models: Optional[list[str]],
        max_chars: int,
        max_requests: int,
        ttl_minutes: int,
    ) -> Optional[dict[str, Any]]: ...

    def get_gateway_token_usage(self, submit_id: int) -> Optional[dict[str, Any]]: ...

    def revoke_gateway_token(self, submit_id: int) -> Any: ...


class GatewayEvaluatorLike(Protocol):
    config: GatewayConfigLike
    _gateway_token_info: Optional[dict[str, Any]]
    _prev_usage_chars: int
    _prev_usage_requests: int

    def _get_client(self) -> GatewayClientLike: ...


def create_gateway_token_for_user(
    evaluator: GatewayEvaluatorLike,
    submission: UserSubmission,
    aggregate_limit: bool = True,
) -> Optional[str]:
    key_ids = submission.runtime_config.key_ids
    if not evaluator.config.allow_user_key:
        return None
    if not key_ids:
        raise ValueError("This phase requires a user API key, but no key_id was provided in submission")

    max_chars = evaluator.config.gateway_max_chars
    max_requests = evaluator.config.gateway_max_requests
    if aggregate_limit and evaluator.config.num_cases > 1:
        max_chars *= evaluator.config.num_cases
        max_requests *= evaluator.config.num_cases

    client = evaluator._get_client()
    token_info = client.create_gateway_token(
        submit_id=submission.submit_id,
        user_id=submission.user_id,
        key_ids=key_ids,
        allowed_models=evaluator.config.gateway_allowed_models or None,
        max_chars=max_chars,
        max_requests=max_requests,
        ttl_minutes=evaluator.config.gateway_ttl_minutes,
    )
    if token_info and token_info.get("token"):
        evaluator._gateway_token_info = token_info
        return str(token_info["token"])
    raise ValueError("Failed to create Gateway Token; check whether the selected API key is valid")


def attach_llm_usage_delta(
    evaluator: GatewayEvaluatorLike,
    case_result: CaseResult,
    submission: UserSubmission,
) -> CaseResult:
    if not evaluator._gateway_token_info:
        return case_result
    try:
        usage = evaluator._get_client().get_gateway_token_usage(submission.submit_id)
        if usage:
            current_chars = int(usage.get("used_chars", 0))
            current_requests = int(usage.get("used_requests", 0))
            case_result.chars_used = max(0, current_chars - evaluator._prev_usage_chars)
            case_result.requests_used = max(
                0,
                current_requests - evaluator._prev_usage_requests,
            )
            evaluator._prev_usage_chars = current_chars
            evaluator._prev_usage_requests = current_requests
    except Exception as exc:
        logger.warning("Failed to fetch LLM usage: %s", exc)
    return case_result


def revoke_gateway_token(evaluator: GatewayEvaluatorLike, submission: UserSubmission) -> None:
    if evaluator._gateway_token_info:
        try:
            evaluator._get_client().revoke_gateway_token(submission.submit_id)
        except Exception:
            pass
        evaluator._gateway_token_info = None
