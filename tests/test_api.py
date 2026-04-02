from __future__ import annotations

from types import SimpleNamespace

import pytest

from .. import api
from ..base import BaseEvaluator
from ..models import PhaseConfig


class DummyEvaluator(BaseEvaluator):
    def evaluate(self, submission, parallel_cases=1, on_case_start=None, on_case_end=None):
        raise NotImplementedError


def _phase() -> PhaseConfig:
    return PhaseConfig(phase_level="Easy", phase_order=1)


def test_create_config_and_phase() -> None:
    cfg = api.create_config(num_cases=3, parallel_cases=2, case_idle_timeout=12)
    assert cfg.num_cases == 3
    assert cfg.parallel_cases == 2
    assert cfg.case_idle_timeout == 12

    p = api.create_phase(DummyEvaluator, cfg)
    assert p.evaluator_module == DummyEvaluator.__module__
    assert p.evaluator_class == "DummyEvaluator"


def test_create_problem_defaults_and_validation() -> None:
    ph = _phase()
    problem = api.create_problem(title="Maze Exploration", phases=[ph], overview="o")
    assert problem.level == "Easy"
    assert problem.slug == "maze-exploration"
    assert problem.background == ""

    with pytest.raises(ValueError):
        api.create_problem(title="A", phases=[])


def test_create_problem_with_background() -> None:
    ph = _phase()
    background = "## Background\n\nUse BFS to explore unknown grids."
    problem = api.create_problem(
        title="Maze Exploration",
        phases=[ph],
        overview="o",
        background=background,
    )
    assert problem.background == background


def test_create_problem_with_is_public_true() -> None:
    ph = _phase()
    problem = api.create_problem(
        title="Open Source Problem",
        phases=[ph],
        overview="o",
        is_public=True,
        data_public=True,
    )
    assert problem.is_public is True
    assert problem.data_public is True


def test_create_problem_is_public_defaults_false() -> None:
    ph = _phase()
    problem = api.create_problem(title="Private", phases=[ph], overview="o")
    assert problem.is_public is False
    assert problem.data_public is False


def test_create_problem_mixed_visibility() -> None:
    ph = _phase()
    problem = api.create_problem(
        title="Mixed",
        phases=[ph],
        overview="o",
        is_public=True,
        data_public=False,
    )
    assert problem.is_public is True
    assert problem.data_public is False


def test_create_problem_all_open_source_fields() -> None:
    ph = _phase()
    bg = "# Background\nSome context."
    problem = api.create_problem(
        title="Full Featured",
        phases=[ph],
        overview="overview",
        background=bg,
        is_public=True,
        data_public=True,
    )
    assert problem.is_public is True
    assert problem.data_public is True
    assert problem.background == bg
    assert problem.slug == "full-featured"


def test_registry_proxies(monkeypatch) -> None:
    class DummyRegistry:
        def __init__(self):
            self.calls = []
            self.problem = api.create_problem("Maze Exploration", [_phase()], level="Easy")

        def register(self, definition):
            self.calls.append(("register", definition.title))

        def get(self, title):
            return self.problem if title == self.problem.title else None

        def sync_to_db(self, definition):
            self.calls.append(("sync_to_db", definition.title))
            return {1: True}

        def sync_all(self):
            return {self.problem.title: {1: True}}

    reg = DummyRegistry()
    monkeypatch.setattr(api, "get_registry", lambda: reg)

    api.register_problem(reg.problem)
    assert api.sync_problem("Maze Exploration") == {1: True}
    assert api.sync_problem("Nope") == {}
    assert api.sync_all_problems() == {"Maze Exploration": {1: True}}


def test_init_registry_and_get_registry(monkeypatch) -> None:
    called = {}

    def _init(**kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setattr(api.ProblemRegistry, "init", staticmethod(_init))
    monkeypatch.setattr(api.ProblemRegistry, "instance", staticmethod(lambda: "inst"))

    assert api.init_registry(mode=api.ClientMode.USER, api_key="k", backend_url="b") == "ok"
    assert called["api_key"] == "k"
    assert api.get_registry() == "inst"


def test_revision_related_wrappers(monkeypatch) -> None:
    class DummyClient:
        def get_version_history(self, title, limit=50, phase_order=None):
            return {"title": title, "limit": limit, "phase_order": phase_order}

        def list_revisions(self, title, phase_order=0, status=""):
            return [{"title": title, "phase_order": phase_order, "status": status}]

        def create_revision(self, **kwargs):
            return kwargs

        def merge_revision(self, *args, **kwargs):
            return {"args": args, "kwargs": kwargs}

        def close_revision(self, title, revision_id, comment=""):
            return (title, revision_id, comment) == ("Maze Exploration", 1, "c")

        def get_data_export(self, title, limit=1000, offset=0):
            return {"title": title, "limit": limit, "offset": offset}

        def get_phase_template(self, title, phase_order=1, lang="en", commit=""):
            return {"title": title, "phase_order": phase_order, "lang": lang, "commit": commit}

    c = DummyClient()
    assert api.get_version_history("Maze Exploration", client=c)["title"] == "Maze Exploration"
    assert api.list_revisions("Maze Exploration", 2, "open", client=c)[0]["phase_order"] == 2
    created = api.create_revision("Maze Exploration", "rev", {"x": 1}, description="d", client=c)
    assert created["revision_title"] == "rev"
    merged = api.merge_revision("Maze Exploration", 3, resolved_files={"a": "b"}, client=c)
    assert merged["args"][0] == "Maze Exploration"
    assert api.close_revision("Maze Exploration", 1, comment="c", client=c) is True
    assert api.get_data_export("Maze Exploration", 10, 5, client=c)["offset"] == 5
    assert api.get_phase_template("Maze Exploration", 2, "zh-CN", "sha", client=c)["lang"] == "zh-CN"


def test_runtime_entry_wrappers_and_phase_file_diff_wrappers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self, base_url=None, api_key=None):
            captured["client_init"] = {"base_url": base_url, "api_key": api_key}

        def get_version_diff(self, title, from_sha, to_sha):
            return {"title": title, "from": from_sha, "to": to_sha}

        def get_phase_files(self, title, phase_order=1, commit=""):
            return {"title": title, "phase_order": phase_order, "commit": commit}

    class DummyWorker:
        def __init__(self, client=None, max_workers=None, poll_interval=None):
            captured["worker_init"] = {
                "client": client,
                "max_workers": max_workers,
                "poll_interval": poll_interval,
            }
            self.ran = False

        def run(self):
            self.ran = True
            captured["worker_ran"] = True

    monkeypatch.setattr(api, "EvaluationClient", DummyClient)
    monkeypatch.setattr("agent_genesis.service.EvaluationService", DummyWorker)

    c = api.create_client(backend_url="http://b", api_key="k")
    assert captured["client_init"] == {"base_url": "http://b", "api_key": "k"}

    w = api.create_service(max_workers=3, poll_interval=9, client=c)
    assert captured["worker_init"]["max_workers"] == 3
    assert captured["worker_init"]["poll_interval"] == 9
    assert captured["worker_init"]["client"] is c

    api.run_service(max_workers=2, poll_interval=7)
    assert captured["worker_ran"] is True

    # wrappers without passing client should fallback to create_client
    monkeypatch.setattr(api, "create_client", lambda: c)
    assert api.get_version_diff("Maze", "a1", "b2")["to"] == "b2"
    out = api.get_phase_files("Maze", phase_order=2, commit="sha")
    assert out["phase_order"] == 2
    assert out["commit"] == "sha"


def test_create_problem_revision_registry_wrapper(monkeypatch) -> None:
    calls: list[tuple] = []
    problem = api.create_problem("Maze Exploration", [_phase()], level="Easy")

    class DummyRegistry:
        def get(self, title):
            return problem if title == problem.title else None

        def create_revision(self, definition, phase_order=1, title=None, description=None):
            calls.append((definition.title, phase_order, title, description))
            return True

    monkeypatch.setattr(api, "get_registry", lambda: DummyRegistry())
    assert api.create_problem_revision("Nope") is False
    assert api.create_problem_revision(
        "Maze Exploration",
        phase_order=2,
        revision_title="rev",
        revision_description="desc",
    ) is True
    assert calls == [("Maze Exploration", 2, "rev", "desc")]
