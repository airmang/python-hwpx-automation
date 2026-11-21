# SPDX-License-Identifier: Apache-2.0
"""The public-hygiene gate must inspect the commit candidate, not just disk."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _hygiene_module():
    script = ROOT / "scripts" / "check_public_hygiene.py"
    spec = importlib.util.spec_from_file_location("check_public_hygiene", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout


def _init_plugin_repo(repo: Path, *, skill_text: str = "clean\n") -> None:
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Hygiene Test")
    _git(repo, "config", "user.email", "hygiene@example.invalid")
    (repo / "packaging").mkdir()
    (repo / "packaging" / "hosts.json").write_text("{}\n", encoding="utf-8")
    (repo / "README.md").write_text("clean\n", encoding="utf-8")
    (repo / "SKILL.md").write_text(skill_text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")


def _private_path() -> str:
    return "/" + "Users" + "/staged-only/secret.txt"


def test_staged_add_is_scanned_after_worktree_copy_is_deleted(tmp_path: Path) -> None:
    hygiene = _hygiene_module()
    repo = tmp_path / "repo"
    _init_plugin_repo(repo)
    added = repo / "references" / "staged.md"
    added.parent.mkdir()
    added.write_text(_private_path() + "\n", encoding="utf-8")
    _git(repo, "add", "references/staged.md")
    added.unlink()

    files = hygiene._repository_files(repo)
    staged = [
        item
        for item in files
        if item.path == "references/staged.md" and item.source == "index"
    ]
    _kind, _count, failures = hygiene._collect_failures(repo)

    assert len(staged) == 1
    assert _private_path().encode() in staged[0].data
    assert any(
        "workstation-shaped path: references/staged.md [index]" in failure
        for failure in failures
    )


def test_staged_modification_wins_over_clean_worktree_bytes(tmp_path: Path) -> None:
    hygiene = _hygiene_module()
    repo = tmp_path / "repo"
    _init_plugin_repo(repo)
    readme = repo / "README.md"
    readme.write_text(_private_path() + "\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    readme.write_bytes(_git(repo, "show", "HEAD:README.md"))

    files = hygiene._repository_files(repo)
    readme_snapshots = [item for item in files if item.path == "README.md"]
    _kind, _count, failures = hygiene._collect_failures(repo)

    assert {item.source for item in readme_snapshots} == {"index", "worktree"}
    assert _private_path().encode() in next(
        item.data for item in readme_snapshots if item.source == "index"
    )
    assert _private_path().encode() not in next(
        item.data for item in readme_snapshots if item.source == "worktree"
    )
    assert any(
        "workstation-shaped path: README.md [index]" in failure for failure in failures
    )


def test_staged_delete_does_not_resurrect_head_blob(tmp_path: Path) -> None:
    hygiene = _hygiene_module()
    repo = tmp_path / "repo"
    _init_plugin_repo(repo, skill_text=_private_path() + "\n")
    _git(repo, "rm", "-q", "SKILL.md")

    files = hygiene._repository_files(repo)
    _kind, _count, failures = hygiene._collect_failures(repo)

    assert all(item.path != "SKILL.md" for item in files)
    assert not any("SKILL.md" in failure for failure in failures)
    assert not any("workstation-shaped path" in failure for failure in failures)
