from __future__ import annotations

import importlib.util
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from repo_build_lock import repo_build_lock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_public_hygiene.py"
SPEC = importlib.util.spec_from_file_location("automation_public_hygiene", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def _hygiene_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Hygiene Test")
    _git(repository, "config", "user.email", "hygiene@example.invalid")
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    _git(repository, "add", "pyproject.toml")
    _git(repository, "commit", "-qm", "baseline")
    return repository


def _private_path(name: str) -> str:
    return "/" + "Users" + f"/private/{name}"


@pytest.fixture(scope="module")
def public_artifacts(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, ...]:
    output = tmp_path_factory.mktemp("automation-public-artifacts")
    canonical = output / "canonical"
    compat = output / "compat"
    canonical.mkdir()
    compat.mkdir()
    with repo_build_lock():  # one build of the repository root at a time (xdist workers)
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(canonical)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--outdir",
                str(compat),
                str(ROOT / "compat" / "hwpx-mcp-server"),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    return tuple(sorted((*canonical.iterdir(), *compat.iterdir())))


def test_wheel_and_sdist_text_is_public_clean(
    public_artifacts: tuple[Path, ...],
) -> None:
    failures: list[str] = []
    for artifact in public_artifacts:
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as archive:
                for name in archive.namelist():
                    failures.extend(
                        hygiene._artifact_text_failure(
                            artifact,
                            name,
                            archive.read(name),
                        )
                    )
        else:
            with tarfile.open(artifact, "r:gz") as archive:
                assert not any(
                    "/tests/" in member.name for member in archive.getmembers()
                )
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    extracted = archive.extractfile(member)
                    assert extracted is not None
                    failures.extend(
                        hygiene._artifact_text_failure(
                            artifact,
                            member.name,
                            extracted.read(),
                        )
                    )
    assert failures == []


def test_artifact_hygiene_distinguishes_versions_from_internal_labels() -> None:
    artifact = ROOT / "dist" / "fixture.whl"
    assert not hygiene._artifact_text_failure(
        artifact,
        "PKG-INFO",
        b"public versions 5.0.0, 6.0.0, and 1.0.0",
    )
    assert hygiene._artifact_text_failure(
        artifact,
        "module.py",
        b"internal label " + b"S-" + b"108",
    )
    assert hygiene._artifact_text_failure(
        artifact,
        "module.py",
        b"internal id " + b"STG-" + b"deadbeef",
    )
    assert hygiene._artifact_text_failure(
        artifact,
        "module.py",
        b"/" + b"Users" + b"/example/private.py",
    )


def test_current_shipped_source_has_no_internal_stage_labels() -> None:
    tracked = [
        "pyproject.toml",
        *(
            str(path.relative_to(ROOT))
            for path in (ROOT / "src" / "hwpx_automation").rglob("*")
            if path.is_file()
        ),
    ]
    assert hygiene._shipped_source_stage_failures(tracked) == []


def test_hygiene_reads_staged_add_from_index_after_worktree_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _hygiene_repository(tmp_path)
    staged = repository / "staged-add.txt"
    staged.write_text(_private_path("release-secret") + "\n", encoding="utf-8")
    _git(repository, "add", staged.name)
    staged.unlink()
    monkeypatch.setattr(hygiene, "ROOT", repository)

    assert hygiene.main() == 1
    assert (
        "workstation-shaped path: staged-add.txt [index]"
        in capsys.readouterr().out
    )


def test_hygiene_reads_staged_modify_instead_of_safe_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _hygiene_repository(tmp_path)
    tracked = repository / "tracked.txt"
    tracked.write_text("public\n", encoding="utf-8")
    _git(repository, "add", tracked.name)
    _git(repository, "commit", "-qm", "add tracked fixture")
    tracked.write_text(_private_path("staged-secret") + "\n", encoding="utf-8")
    _git(repository, "add", tracked.name)
    tracked.write_text("safe worktree replacement\n", encoding="utf-8")
    monkeypatch.setattr(hygiene, "ROOT", repository)

    assert hygiene.main() == 1
    assert (
        "workstation-shaped path: tracked.txt [index]"
        in capsys.readouterr().out
    )


def test_hygiene_excludes_staged_delete_even_when_head_blob_was_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _hygiene_repository(tmp_path)
    deleted = repository / "deleted.txt"
    deleted.write_text(_private_path("old-secret") + "\n", encoding="utf-8")
    _git(repository, "add", deleted.name)
    _git(repository, "commit", "-qm", "add deletion fixture")
    _git(repository, "rm", deleted.name)
    monkeypatch.setattr(hygiene, "ROOT", repository)

    assert hygiene.main() == 0


def test_hygiene_reads_unsafe_unstaged_tracked_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _hygiene_repository(tmp_path)
    source = repository / "src" / "hwpx_automation" / "probe.py"
    source.parent.mkdir(parents=True)
    source.write_text("PUBLIC = True\n", encoding="utf-8")
    _git(repository, "add", str(source.relative_to(repository)))
    _git(repository, "commit", "-qm", "add source fixture")
    source.write_text("import hwpx_automation.practice\n", encoding="utf-8")
    monkeypatch.setattr(hygiene, "ROOT", repository)

    assert hygiene.main() == 1
    output = capsys.readouterr().out
    assert (
        "internal runtime marker 'hwpx_automation.practice': "
        "src/hwpx_automation/probe.py [worktree]"
    ) in output
    assert "src/hwpx_automation/probe.py [index]" not in output


def test_hygiene_fails_closed_on_unmerged_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _hygiene_repository(tmp_path)
    conflict = repository / "conflict.txt"
    conflict.write_text("base\n", encoding="utf-8")
    _git(repository, "add", conflict.name)
    _git(repository, "commit", "-qm", "add conflict fixture")
    _git(repository, "checkout", "-qb", "other")
    conflict.write_text("other\n", encoding="utf-8")
    _git(repository, "commit", "-qam", "other side")
    _git(repository, "checkout", "-q", "-")
    conflict.write_text("current\n", encoding="utf-8")
    _git(repository, "commit", "-qam", "current side")
    merge = subprocess.run(
        ["git", "merge", "other"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0
    monkeypatch.setattr(hygiene, "ROOT", repository)

    assert hygiene.main() == 2
    assert (
        "public hygiene could not read repository snapshots: "
        "unmerged git index entry: conflict.txt"
    ) in capsys.readouterr().out
