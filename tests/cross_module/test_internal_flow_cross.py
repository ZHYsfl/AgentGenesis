"""Cross-module: Internal endpoints (Worker flow) against real Go backend."""

from __future__ import annotations

import pytest

from ...client import EvaluationClient


@pytest.fixture(scope="module")
def internal_client(backend_url: str) -> EvaluationClient:
    """Client for internal endpoints (uses INTERNAL_API_KEY from env)."""
    return EvaluationClient(base_url=backend_url)


@pytest.mark.cross_module
def test_pending_submissions(internal_client: EvaluationClient) -> None:
    """get_pending_submissions returns a list of UserSubmission (may be empty or have items)."""
    result = internal_client.get_pending_submissions(limit=20)
    assert isinstance(result, list)
    for item in result:
        assert hasattr(item, "submit_id")


@pytest.mark.cross_module
def test_claim_unclaim_flow(internal_client: EvaluationClient, submit_id_claim: int) -> None:
    """Claim submission, then unclaim."""
    ok = internal_client.claim_submission(submit_id_claim)
    assert ok is True
    ok = internal_client.unclaim_submission(submit_id_claim)
    assert ok is True


@pytest.mark.cross_module
def test_create_eval_case(
    internal_client: EvaluationClient,
    submit_id_claimed: int,
) -> None:
    """create_case_record returns dict with case_id and optional OSS URLs."""
    from ...models import CaseResult, CaseStatus

    case = CaseResult(
        case_index=0,
        status=CaseStatus.PASSED,
        score=1,
        input_data="in",
        output_data="out",
        expected_output="exp",
        logs="log",
    )
    result = internal_client.create_case_record(submit_id_claimed, case)
    assert result is not None
    assert isinstance(result, dict)
    assert "case_id" in result
    # OSS URLs optional depending on storage config
    for k in ("input_url", "output_url", "expected_output_url", "logs_url"):
        if k in result:
            assert isinstance(result[k], str)


@pytest.mark.cross_module
def test_create_gateway_token(
    internal_client: EvaluationClient,
    submit_id_claimed: int,
    cross_user_id: int,
    cross_key_id: int,
) -> None:
    """create_gateway_token returns token for submit with user key."""
    result = internal_client.create_gateway_token(
        submit_id=submit_id_claimed,
        user_id=cross_user_id,
        key_ids=[cross_key_id],
    )
    assert result is not None
    assert isinstance(result, dict)
    assert "token" in result
