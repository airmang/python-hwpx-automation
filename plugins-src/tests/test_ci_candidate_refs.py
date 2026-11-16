# SPDX-License-Identifier: Apache-2.0
"""The Tests job must run for fork PRs without weakening same-repository runs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE_SHA = "1" * 40
AUTOMATION_SHA = "2" * 40


def _resolver():
    script = ROOT / "scripts" / "resolve_ci_candidate_refs.py"
    spec = importlib.util.spec_from_file_location("resolve_ci_candidate_refs", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity() -> dict:
    return json.loads(
        (ROOT / "packaging" / "product-identity.json").read_text(encoding="utf-8")
    )


def _fork_env(**extra: str) -> dict[str, str]:
    env = {
        "EVENT_NAME": "pull_request",
        "HEAD_REPOSITORY": "contributor/hwpx-plugins",
        "BASE_REPOSITORY": "airmang/hwpx-plugins",
    }
    env.update(extra)
    return env


def _tags(calls: list[tuple[str, str]]):
    def resolve(repository: str, tag: str) -> str:
        calls.append((repository, tag))
        return CORE_SHA if repository.endswith("/python-hwpx") else AUTOMATION_SHA

    return resolve


def test_fork_pull_request_falls_back_to_declared_candidate_release_tags() -> None:
    resolver = _resolver()
    identity = _identity()
    candidate = identity["releaseState"]["candidate"]
    calls: list[tuple[str, str]] = []

    refs = resolver.resolve(_fork_env(), identity, _tags(calls))

    assert calls == [
        ("airmang/python-hwpx", f"v{candidate['pythonHwpx']}"),
        ("airmang/python-hwpx-automation", f"v{candidate['canonicalAutomation']}"),
    ]
    assert refs == {
        "core_ref": CORE_SHA,
        "automation_ref": AUTOMATION_SHA,
        "automation_repository": "airmang/python-hwpx-automation",
        "source": "released-tags",
    }


def test_fork_pull_request_with_unpublished_candidate_asks_for_dispatch() -> None:
    resolver = _resolver()

    with pytest.raises(resolver.ResolutionError, match="workflow_dispatch"):
        resolver.resolve(_fork_env(), _identity(), lambda repository, tag: None)


@pytest.mark.parametrize(
    "env",
    [
        # Same-repository pull request, push and dispatch keep the hard gate.
        {
            "EVENT_NAME": "pull_request",
            "HEAD_REPOSITORY": "airmang/hwpx-plugins",
            "BASE_REPOSITORY": "airmang/hwpx-plugins",
        },
        {"EVENT_NAME": "push", "BASE_REPOSITORY": "airmang/hwpx-plugins"},
        {"EVENT_NAME": "workflow_dispatch", "BASE_REPOSITORY": "airmang/hwpx-plugins"},
    ],
)
def test_non_fork_runs_without_candidate_refs_still_fail(env: dict[str, str]) -> None:
    resolver = _resolver()

    def must_not_resolve(repository: str, tag: str) -> str:
        raise AssertionError("released-tag fallback is fork-only")

    with pytest.raises(resolver.ResolutionError, match="HWPX_CORE_CANDIDATE_REF"):
        resolver.resolve(env, _identity(), must_not_resolve)


def test_explicit_candidate_refs_win_and_stay_exact() -> None:
    resolver = _resolver()
    env = _fork_env(CORE_CANDIDATE_REF=CORE_SHA, AUTOMATION_CANDIDATE_REF=AUTOMATION_SHA)

    refs = resolver.resolve(env, _identity(), lambda repository, tag: None)

    assert refs["core_ref"] == CORE_SHA
    assert refs["automation_ref"] == AUTOMATION_SHA
    assert refs["automation_repository"] == resolver.DEFAULT_AUTOMATION_REPOSITORY
    assert refs["source"] == "candidate-refs"

    with pytest.raises(resolver.ResolutionError, match="40-hex"):
        resolver.resolve(
            {"EVENT_NAME": "push", "CORE_CANDIDATE_REF": "main", "AUTOMATION_CANDIDATE_REF": AUTOMATION_SHA},
            _identity(),
        )
    with pytest.raises(resolver.ResolutionError, match="automation_ref or HWPX_AUTOMATION_CANDIDATE_REF"):
        resolver.resolve(_fork_env(CORE_CANDIDATE_REF=CORE_SHA), _identity())


def test_workflow_checks_out_the_resolved_refs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "run: python3 hwpx-skill/scripts/resolve_ci_candidate_refs.py" in workflow
    assert "HEAD_REPOSITORY: ${{ github.event.pull_request.head.repo.full_name }}" in workflow
    assert "ref: ${{ steps.refs.outputs.core_ref }}" in workflow
    assert "ref: ${{ steps.refs.outputs.automation_ref }}" in workflow
    assert "repository: ${{ steps.refs.outputs.automation_repository }}" in workflow
    assert "pull_request_target" not in workflow
