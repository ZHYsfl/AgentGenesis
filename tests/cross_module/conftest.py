"""Cross-module integration tests: Python SDK -> Go backend over real HTTP."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

# Ensure evaluation package is importable when run from env-demo root.
ENV_DEMO_ROOT = Path(__file__).resolve().parents[3]
if str(ENV_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(ENV_DEMO_ROOT))


def _cross_module_config(
    backend_url: str,
    internal_api_key: str,
    user_api_key: str,
    request_timeout: int,
):
    """Build config from fixed values provided by Go bridge."""
    return SimpleNamespace(
        backend_url=backend_url,
        internal_api_key=internal_api_key,
        user_api_key=user_api_key,
        request_timeout=request_timeout,
    )


@pytest.fixture(scope="module", autouse=True)
def patch_config_for_cross_module(backend_url: str):
    """Patch get_config so EvaluationClient gets keys from env (avoids Pydantic singleton bugs)."""
    internal_api_key = os.getenv("INTERNAL_API_KEY", "")
    user_api_key = os.getenv("AGENT_GENESIS_API_KEY", "")
    request_timeout = int(os.getenv("REQUEST_TIMEOUT", "30"))

    import evaluation.client as client_mod
    import evaluation.registry as registry_mod

    # evaluation/config.py loads .env with override=True on import, which can
    # overwrite subprocess-provided env vars. Re-assert test-specific values.
    os.environ["BACKEND_URL"] = backend_url
    os.environ["INTERNAL_API_KEY"] = internal_api_key
    os.environ["AGENT_GENESIS_API_KEY"] = user_api_key
    os.environ["REQUEST_TIMEOUT"] = str(request_timeout)

    def _fixed_config():
        return _cross_module_config(
            backend_url=backend_url,
            internal_api_key=internal_api_key,
            user_api_key=user_api_key,
            request_timeout=request_timeout,
        )

    client_mod.get_config = _fixed_config
    registry_mod.get_config = _fixed_config


def pytest_configure(config):
    """Register cross_module marker (always). Skip via fixtures when BACKEND_URL not set."""
    config.addinivalue_line(
        "markers",
        "cross_module: marks test as cross-module (deselect with '-m \"not cross_module\"')",
    )


@pytest.fixture(scope="module")
def backend_url() -> str:
    url = os.getenv("BACKEND_URL", "")
    if not url:
        pytest.skip("cross-module tests require BACKEND_URL (run via Go: go test -run TestPythonCrossModule)")
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except OSError:
        pytest.skip(
            f"cross-module tests require reachable backend at {url} "
            "(start backend or run via Go bridge: go test -run TestPythonCrossModule)"
        )
    return url


@pytest.fixture(scope="module")
def cross_slug() -> str:
    slug = os.getenv("CROSS_TEST_SLUG", "")
    if not slug:
        pytest.skip("cross-module tests require CROSS_TEST_SLUG (run via Go bridge)")
    return slug


@pytest.fixture(scope="module")
def submit_id_claim() -> int:
    """Submit ID for claim/unclaim flow (pending)."""
    raw = os.getenv("CROSS_TEST_SUBMIT_ID", "")
    if not raw:
        pytest.skip("CROSS_TEST_SUBMIT_ID not set")
    return int(raw)


@pytest.fixture(scope="module")
def cross_slug_internal() -> str:
    """Slug of system-owned problem (for get-phase-artifact)."""
    return os.getenv("CROSS_TEST_SLUG_INTERNAL", "")


@pytest.fixture(scope="module")
def cross_title_internal() -> str:
    """Title of system-owned problem (for get-phase-artifact)."""
    return os.getenv("CROSS_TEST_TITLE_INTERNAL", "")


@pytest.fixture(scope="module")
def submit_id_claimed() -> int:
    """Submit ID already claimed, for create_case_record test."""
    raw = os.getenv("CROSS_TEST_SUBMIT_ID_CLAIMED", "")
    if not raw:
        pytest.skip("CROSS_TEST_SUBMIT_ID_CLAIMED not set")
    return int(raw)


@pytest.fixture(scope="module")
def cross_user_id() -> int:
    """User ID for create_gateway_token test."""
    raw = os.getenv("CROSS_TEST_USER_ID", "")
    if not raw:
        pytest.skip("CROSS_TEST_USER_ID not set")
    return int(raw)


@pytest.fixture(scope="module")
def cross_key_id() -> int:
    """User-provided key ID for create_gateway_token test."""
    raw = os.getenv("CROSS_TEST_KEY_ID", "")
    if not raw:
        pytest.skip("CROSS_TEST_KEY_ID not set")
    return int(raw)
