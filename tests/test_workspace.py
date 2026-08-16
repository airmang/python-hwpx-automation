# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath

import pytest

import hwpx_automation.workspace as workspace_module
from hwpx_automation.workspace import (
    LEGACY_SANDBOX_ROOT_ENV,
    LEGACY_WORKSPACE_ROOTS_ENV,
    WORKSPACE_ROOTS_ENV,
    WorkspaceConfigurationError,
    WorkspacePathError,
    WorkspaceResolver,
    _normalize_path_input,
)


def test_relative_absolute_and_multi_root_resolution(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    secondary.mkdir()
    (primary / "inside.hwpx").write_bytes(b"primary")
    (secondary / "inside.hwpx").write_bytes(b"secondary")
    resolver = WorkspaceResolver.from_roots([primary, secondary])

    assert resolver.resolve("inside.hwpx") == primary / "inside.hwpx"
    assert resolver.resolve(secondary / "inside.hwpx") == secondary / "inside.hwpx"
    assert resolver.display_path(primary / "inside.hwpx") == "inside.hwpx"
    assert resolver.display_path(secondary / "inside.hwpx") == str(secondary / "inside.hwpx")


def test_workspace_path_input_normalization(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    document = root / "inside document.hwpx"
    document.write_bytes(b"document")
    resolver = WorkspaceResolver.from_roots([root])

    assert resolver.resolve(f'"{document.as_uri()}"') == document.resolve()
    assert (
        _normalize_path_input(
            r"file:///C:/workspace/Documents/inside%20document.hwpx",
            windows=True,
        )
        == r"C:\workspace\Documents\inside document.hwpx"
    )
    assert (
        _normalize_path_input(
            r"'C:/workspace\Documents/inside document.hwpx'",
            windows=True,
        )
        == r"C:\workspace\Documents\inside document.hwpx"
    )


def test_ordinary_spaced_path_name_is_preserved(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    unspaced = root / "report.hwpx"
    spaced = root / " report.hwpx "
    unspaced.write_bytes(b"unspaced")
    spaced.write_bytes(b"spaced")
    resolver = WorkspaceResolver.from_roots([root])

    # An ordinary path with meaningful surrounding whitespace must resolve to
    # the byte-identical file, not be silently redirected to the unspaced one.
    assert _normalize_path_input(" report.hwpx ") == " report.hwpx "
    assert resolver.resolve(" report.hwpx ") == spaced
    assert _normalize_path_input('" report.hwpx "') == " report.hwpx "
    assert resolver.resolve('" report.hwpx "') == spaced
    assert resolver.resolve("report.hwpx") == unspaced


def test_file_uri_localhost_authority_resolves_local(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    document = root / "inside.hwpx"
    document.write_bytes(b"document")
    resolver = WorkspaceResolver.from_roots([root])

    abs_path = str(document)
    # Both an empty authority (file:///abs) and a localhost authority
    # (file://localhost/abs) denote the same local file.
    assert _normalize_path_input(f"file://{abs_path}") == abs_path
    assert _normalize_path_input(f"file://localhost{abs_path}") == abs_path
    assert _normalize_path_input(f"file://LOCALHOST{abs_path}") == abs_path
    assert resolver.resolve(f"file://localhost{abs_path}") == document.resolve()
    assert resolver.resolve(document.as_uri()) == document.resolve()


def test_file_uri_non_local_authority_is_rejected() -> None:
    # A remote host authority is not an addressable local workspace path; it
    # must raise the typed contract rather than be localized or mangled.
    with pytest.raises(WorkspacePathError) as excinfo:
        _normalize_path_input("file://remotehost/inside.hwpx")
    assert excinfo.value.code == "WORKSPACE_PATH_INVALID"
    assert excinfo.value.reason == "non_local_file_uri_authority"


def test_malformed_file_uri_raises_workspace_path_error() -> None:
    with pytest.raises(WorkspacePathError) as excinfo:
        _normalize_path_input("file://[invalid]/inside.hwpx")
    assert excinfo.value.code == "WORKSPACE_PATH_INVALID"
    assert excinfo.value.reason == "malformed_file_uri"
    # The submitted path must not be exposed in the safe details.
    assert "inside.hwpx" not in json.dumps(excinfo.value.safe_details())


@pytest.mark.parametrize(
    "value",
    [
        "/mnt/user-data/uploads/document.hwpx",
        r"\mnt\user-data\uploads\document.hwpx",
        "/MNT/USER-DATA/document.hwpx",
    ],
)
def test_client_upload_paths_fail_with_actionable_typed_error(
    tmp_path: Path, value: str
) -> None:
    resolver = WorkspaceResolver.from_roots([tmp_path])

    with pytest.raises(WorkspacePathError) as excinfo:
        resolver.resolve(value)

    assert excinfo.value.code == "CLIENT_UPLOAD_PATH_UNAVAILABLE"
    assert excinfo.value.reason == "client_upload_path"
    assert "document.hwpx" not in json.dumps(excinfo.value.safe_details())


def test_missing_output_parent_is_created_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    resolver = WorkspaceResolver.from_roots([root])

    output = resolver.resolve_output("new/deep/result.hwpx")

    assert output == root / "new/deep/result.hwpx"
    assert output.parent.is_dir()


def test_missing_output_precondition_creates_and_cleans_only_owned_chain(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    resolver = WorkspaceResolver.from_roots([root])
    target = root / "new/deep/result.hwpx"

    precondition = resolver.capture_output_precondition(target)

    assert not target.parent.exists()
    guard = resolver.materialize_output_guard(precondition)
    publication = resolver.atomic_publish_bytes(guard, b"candidate")
    resolver.remove_output(publication)

    assert resolver.cleanup_owned_parent_directories(publication) is True
    assert not (root / "new").exists()


def test_identity_bound_output_guard_publishes_only_to_captured_parent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")

    published = resolver.atomic_write_bytes(guard, b"candidate")

    assert published == parent / "final.hwpx"
    assert published.read_bytes() == b"candidate"


def test_identity_bound_output_guard_rejects_parent_swap_and_symlink_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    parent = root / "results"
    parent.mkdir(parents=True)
    outside.mkdir()
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")

    parent.rename(root / "captured-results")
    parent.mkdir()
    with pytest.raises(WorkspacePathError) as replaced:
        resolver.atomic_write_bytes(guard, b"must-not-publish")
    assert replaced.value.code == "WORKSPACE_PATH_CHANGED"
    assert not (parent / "final.hwpx").exists()

    parent.rmdir()
    parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkspacePathError):
        resolver.atomic_write_bytes(guard, b"must-not-escape")
    assert not (outside / "final.hwpx").exists()


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="descriptor-anchored publication is POSIX-only",
)
@pytest.mark.parametrize(
    ("existing_bytes", "expected_outside_bytes"),
    [(None, None), (b"existing-destination", b"existing-destination")],
)
def test_identity_bound_output_guard_cleans_commit_window_parent_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_bytes: bytes | None,
    expected_outside_bytes: bytes | None,
) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    parent = root / "results"
    parent.mkdir(parents=True)
    outside.mkdir()
    target = parent / "final.hwpx"
    if existing_bytes is not None:
        target.write_bytes(existing_bytes)

    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    attacked = False

    real_link = workspace_module.os.link
    real_exchange = workspace_module._exchange_entries

    def swap_parent() -> None:
        nonlocal attacked
        if not attacked:
            attacked = True
            parent.rename(outside / "escaped")
            parent.mkdir()

    if existing_bytes is None:
        def link_with_parent_swap(src, dst, *args, **kwargs):
            if os.fspath(src).endswith(".tmp") and os.fspath(dst) == "final.hwpx":
                swap_parent()
            return real_link(src, dst, *args, **kwargs)

        monkeypatch.setattr(workspace_module.os, "link", link_with_parent_swap)
    else:
        def exchange_with_parent_swap(parent_fd, first, second):
            if first.endswith(".tmp") and second == "final.hwpx":
                swap_parent()
            return real_exchange(parent_fd, first, second)

        monkeypatch.setattr(
            workspace_module,
            "_exchange_entries",
            exchange_with_parent_swap,
        )

    with pytest.raises(WorkspacePathError) as changed:
        resolver.atomic_write_bytes(guard, b"candidate-must-not-remain")

    assert changed.value.code == "WORKSPACE_PATH_CHANGED"
    assert attacked is True
    assert not target.exists()
    escaped = outside / "escaped"
    escaped_target = escaped / "final.hwpx"
    if expected_outside_bytes is None:
        assert not escaped_target.exists()
        assert list(escaped.iterdir()) == []
    else:
        assert escaped_target.read_bytes() == expected_outside_bytes
        assert [item.name for item in escaped.iterdir()] == ["final.hwpx"]


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="descriptor-anchored publication is POSIX-only",
)
def test_identity_bound_output_guard_rejects_target_directory_created_after_capture(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    target = parent / "final.hwpx"
    target.mkdir()

    with pytest.raises(WorkspacePathError) as changed:
        resolver.atomic_write_bytes(guard, b"candidate-must-not-publish")

    assert changed.value.code == "WORKSPACE_PATH_CHANGED"
    assert changed.value.reason == "output_target_changed"
    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert [item.name for item in parent.iterdir()] == ["final.hwpx"]


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="descriptor-anchored publication is POSIX-only",
)
def test_identity_bound_output_guard_rejects_directory_swap_at_backup_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    target = parent / "final.hwpx"
    target.write_bytes(b"captured-output")
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    real_exchange = workspace_module._exchange_entries
    attacked = False

    def swap_target_at_snapshot(parent_fd, first, second):
        nonlocal attacked
        if not attacked and first.endswith(".tmp") and second == "final.hwpx":
            attacked = True
            target.unlink()
            target.mkdir()
        return real_exchange(parent_fd, first, second)

    monkeypatch.setattr(
        workspace_module,
        "_exchange_entries",
        swap_target_at_snapshot,
    )

    with pytest.raises(WorkspacePathError) as changed:
        resolver.atomic_write_bytes(guard, b"candidate-must-not-publish")

    assert changed.value.code == "WORKSPACE_PATH_CHANGED"
    assert attacked is True
    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert [item.name for item in parent.iterdir()] == ["final.hwpx"]


@pytest.mark.skipif(
    not workspace_module._descriptor_cas_supported(),
    reason="descriptor-anchored atomic CAS is unavailable",
)
def test_absent_output_preserves_external_creation_at_link_cas_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    target = parent / "final.hwpx"
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    real_link = workspace_module.os.link
    attacked = False

    def link_after_external_creation(src, dst, *args, **kwargs):
        nonlocal attacked
        if not attacked and str(src).endswith(".tmp") and dst == "final.hwpx":
            attacked = True
            target.write_bytes(b"external-writer")
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(workspace_module.os, "link", link_after_external_creation)

    with pytest.raises(WorkspacePathError) as changed:
        resolver.atomic_write_bytes(guard, b"candidate-must-not-clobber")

    assert changed.value.code == "WORKSPACE_PATH_CHANGED"
    assert changed.value.reason == "output_target_changed"
    assert attacked is True
    assert target.read_bytes() == b"external-writer"
    assert [item.name for item in parent.iterdir()] == ["final.hwpx"]


@pytest.mark.skipif(
    not workspace_module._descriptor_cas_supported(),
    reason="descriptor-anchored atomic CAS is unavailable",
)
def test_existing_output_preserves_external_replacement_at_exchange_cas_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    target = parent / "final.hwpx"
    target.write_bytes(b"captured-output")
    replacement = parent / "external.hwpx"
    replacement.write_bytes(b"external-writer")
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    real_exchange = workspace_module._exchange_entries
    attacked = False

    def exchange_after_external_replacement(parent_fd, first, second):
        nonlocal attacked
        if not attacked and first.endswith(".tmp") and second == "final.hwpx":
            attacked = True
            os.replace(replacement, target)
        return real_exchange(parent_fd, first, second)

    monkeypatch.setattr(
        workspace_module,
        "_exchange_entries",
        exchange_after_external_replacement,
    )

    with pytest.raises(WorkspacePathError) as changed:
        resolver.atomic_write_bytes(guard, b"candidate-must-not-clobber")

    assert changed.value.code == "WORKSPACE_PATH_CHANGED"
    assert changed.value.reason == "output_target_changed"
    assert attacked is True
    assert target.read_bytes() == b"external-writer"
    assert [item.name for item in parent.iterdir()] == ["final.hwpx"]


@pytest.mark.skipif(
    not workspace_module._descriptor_cas_supported(),
    reason="descriptor-anchored atomic CAS is unavailable",
)
@pytest.mark.parametrize("existing_bytes", [None, b"captured-output"])
def test_output_preserves_external_replacement_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_bytes: bytes | None,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    target = parent / "final.hwpx"
    if existing_bytes is not None:
        target.write_bytes(existing_bytes)
    replacement = parent / "external.hwpx"
    replacement.write_bytes(b"external-writer")
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    attacked = False

    if existing_bytes is None:
        real_link = workspace_module.os.link

        def link_then_replace(src, dst, *args, **kwargs):
            nonlocal attacked
            result = real_link(src, dst, *args, **kwargs)
            if not attacked and str(src).endswith(".tmp") and dst == "final.hwpx":
                attacked = True
                os.replace(replacement, target)
            return result

        monkeypatch.setattr(workspace_module.os, "link", link_then_replace)
    else:
        real_exchange = workspace_module._exchange_entries

        def exchange_then_replace(parent_fd, first, second):
            nonlocal attacked
            result = real_exchange(parent_fd, first, second)
            if not attacked and first.endswith(".tmp") and second == "final.hwpx":
                attacked = True
                os.replace(replacement, target)
            return result

        monkeypatch.setattr(
            workspace_module,
            "_exchange_entries",
            exchange_then_replace,
        )

    with pytest.raises(WorkspacePathError) as changed:
        resolver.atomic_write_bytes(guard, b"published-candidate")

    assert changed.value.code == "WORKSPACE_PATH_CHANGED"
    assert changed.value.reason == "output_target_changed"
    assert attacked is True
    assert target.read_bytes() == b"external-writer"
    assert [item.name for item in parent.iterdir()] == ["final.hwpx"]


@pytest.mark.skipif(
    not workspace_module._descriptor_cas_supported(),
    reason="descriptor-anchored atomic CAS is unavailable",
)
def test_final_guard_failure_restores_immutable_original_after_old_fd_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    target = parent / "final.hwpx"
    target.write_bytes(b"captured-output")
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    old_fd = os.open(target, os.O_RDWR)
    real_unlink = workspace_module.os.unlink
    real_assert_output_guard = WorkspaceResolver._assert_output_guard
    old_fd_mutated = False

    def unlink_then_mutate_old_fd(path, *args, **kwargs):
        nonlocal old_fd_mutated
        result = real_unlink(path, *args, **kwargs)
        if not old_fd_mutated and str(path).endswith(".tmp"):
            old_fd_mutated = True
            os.ftruncate(old_fd, 0)
            os.write(old_fd, b"mutated-unlinked-inode")
        return result

    def fail_final_guard(self, current_guard):
        if old_fd_mutated:
            raise WorkspacePathError(
                "forced final guard failure",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_parent_changed",
            )
        return real_assert_output_guard(self, current_guard)

    monkeypatch.setattr(workspace_module.os, "unlink", unlink_then_mutate_old_fd)
    monkeypatch.setattr(WorkspaceResolver, "_assert_output_guard", fail_final_guard)
    try:
        with pytest.raises(WorkspacePathError) as changed:
            resolver.atomic_write_bytes(guard, b"candidate-must-roll-back")

        assert changed.value.code == "WORKSPACE_PATH_CHANGED"
        assert old_fd_mutated is True
        assert target.read_bytes() == b"captured-output"
        assert os.pread(old_fd, 128, 0) == b"mutated-unlinked-inode"
        assert [item.name for item in parent.iterdir()] == ["final.hwpx"]
    finally:
        os.close(old_fd)


@pytest.mark.skipif(
    not workspace_module._descriptor_cas_supported(),
    reason="descriptor-anchored atomic CAS is unavailable",
)
def test_remove_output_preserves_external_replacement_at_exchange_cas_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    target = parent / "final.hwpx"
    target.write_bytes(b"captured-output")
    replacement = parent / "external.hwpx"
    replacement.write_bytes(b"external-writer")
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    real_exchange = workspace_module._exchange_entries
    attacked = False

    def exchange_after_external_replacement(parent_fd, first, second):
        nonlocal attacked
        if not attacked and first.endswith(".remove") and second == "final.hwpx":
            attacked = True
            os.replace(replacement, target)
        return real_exchange(parent_fd, first, second)

    monkeypatch.setattr(
        workspace_module,
        "_exchange_entries",
        exchange_after_external_replacement,
    )

    with pytest.raises(WorkspacePathError) as changed:
        resolver.remove_output(guard)

    assert changed.value.code == "WORKSPACE_PATH_CHANGED"
    assert changed.value.reason == "output_target_changed"
    assert attacked is True
    assert target.read_bytes() == b"external-writer"
    assert [item.name for item in parent.iterdir()] == ["final.hwpx"]


@pytest.mark.skipif(
    not workspace_module._descriptor_cas_supported(),
    reason="descriptor-anchored atomic CAS is unavailable",
)
def test_output_candidate_tamper_is_rejected_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    target = parent / "final.hwpx"
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    real_snapshot = workspace_module._relative_file_snapshot
    attacked = False

    def mutate_candidate_before_snapshot(parent_fd, name):
        nonlocal attacked
        if not attacked and name.endswith(".tmp"):
            attacked = True
            descriptor = os.open(name, os.O_WRONLY, dir_fd=parent_fd)
            try:
                os.ftruncate(descriptor, 0)
                os.write(descriptor, b"externally-mutated-candidate")
            finally:
                os.close(descriptor)
        return real_snapshot(parent_fd, name)

    monkeypatch.setattr(
        workspace_module,
        "_relative_file_snapshot",
        mutate_candidate_before_snapshot,
    )

    with pytest.raises(WorkspacePathError) as changed:
        resolver.atomic_write_bytes(guard, b"verified-candidate")

    assert changed.value.reason == "output_candidate_changed"
    assert attacked is True
    assert not target.exists()
    assert list(parent.iterdir()) == []


@pytest.mark.skipif(
    not workspace_module._descriptor_cas_supported(),
    reason="descriptor-anchored atomic CAS is unavailable",
)
def test_remove_output_preserves_external_replacement_at_rmdir_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "results"
    parent.mkdir(parents=True)
    target = parent / "final.hwpx"
    target.write_bytes(b"captured-output")
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    real_rmdir = workspace_module.os.rmdir
    attacked = False

    def replace_sentinel_at_remove(name, *args, **kwargs):
        nonlocal attacked
        result = real_rmdir(name, *args, **kwargs)
        if not attacked and os.fspath(name) == "final.hwpx":
            attacked = True
            target.write_bytes(b"external-writer")
        return result

    monkeypatch.setattr(workspace_module.os, "rmdir", replace_sentinel_at_remove)

    with pytest.raises(WorkspacePathError) as changed:
        resolver.remove_output(guard)

    assert changed.value.reason == "output_target_changed"
    assert attacked is True
    assert target.read_bytes() == b"external-writer"
    assert [item.name for item in parent.iterdir()] == ["final.hwpx"]


@pytest.mark.skipif(
    not workspace_module._descriptor_cas_supported(),
    reason="descriptor-anchored atomic CAS is unavailable",
)
@pytest.mark.parametrize(
    ("existing_bytes", "expected_escaped_bytes"),
    [(None, None), (b"captured-output", b"captured-output")],
)
def test_output_cleans_candidate_when_parent_moves_at_final_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_bytes: bytes | None,
    expected_escaped_bytes: bytes | None,
) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    parent = root / "results"
    parent.mkdir(parents=True)
    outside.mkdir()
    target = parent / "final.hwpx"
    if existing_bytes is not None:
        target.write_bytes(existing_bytes)
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output("results/final.hwpx")
    real_fsync = workspace_module.os.fsync
    attacked = False

    def fsync_then_move_parent(descriptor):
        nonlocal attacked
        result = real_fsync(descriptor)
        descriptor_stat = os.fstat(descriptor)
        if not attacked and (
            descriptor_stat.st_dev,
            descriptor_stat.st_ino,
        ) == (guard.parent_device, guard.parent_inode):
            attacked = True
            parent.rename(outside / "escaped")
            parent.mkdir()
        return result

    monkeypatch.setattr(workspace_module.os, "fsync", fsync_then_move_parent)

    with pytest.raises(WorkspacePathError) as changed:
        resolver.atomic_write_bytes(guard, b"candidate-must-not-remain")

    assert changed.value.code == "WORKSPACE_PATH_CHANGED"
    assert attacked is True
    assert not target.exists()
    escaped = outside / "escaped"
    escaped_target = escaped / "final.hwpx"
    if expected_escaped_bytes is None:
        assert not escaped_target.exists()
        assert list(escaped.iterdir()) == []
    else:
        assert escaped_target.read_bytes() == expected_escaped_bytes
        assert [item.name for item in escaped.iterdir()] == ["final.hwpx"]


def test_portable_fallback_uses_platform_observed_candidate_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "snapshot.hwpx"
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output(target)
    real_chmod = workspace_module.os.chmod

    def windows_style_chmod(path, mode, *args, **kwargs):
        normalized = 0o444 if mode & 0o222 == 0 else 0o666
        return real_chmod(path, normalized, *args, **kwargs)

    monkeypatch.setattr(workspace_module, "_descriptor_cas_supported", lambda: False)
    monkeypatch.setattr(workspace_module.os, "chmod", windows_style_chmod)

    publication = resolver.atomic_publish_bytes(guard, b"snapshot", mode=0o400)

    assert target.read_bytes() == b"snapshot"
    assert publication.target_mode == 0o444
    resolver.remove_output(publication)
    assert not target.exists()


def test_portable_fallback_post_publish_failure_removes_owned_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "candidate.hwpx"
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output(target)
    original_assert = WorkspaceResolver._assert_output_guard
    checks = 0

    def fail_first_post_publish_check(self, current_guard):
        nonlocal checks
        if self is resolver:
            checks += 1
        if self is resolver and checks == 3:
            raise WorkspacePathError(
                "forced portable post-publish failure",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_parent_changed",
            )
        return original_assert(self, current_guard)

    monkeypatch.setattr(workspace_module, "_descriptor_cas_supported", lambda: False)
    monkeypatch.setattr(
        WorkspaceResolver,
        "_assert_output_guard",
        fail_first_post_publish_check,
    )

    with pytest.raises(WorkspacePathError, match="post-publish failure"):
        resolver.atomic_publish_bytes(guard, b"candidate")

    assert checks >= 3
    assert not target.exists()


@pytest.mark.skipif(os.name != "posix", reason="symlink relocation requires POSIX")
def test_portable_fallback_rejects_same_inode_symlink_relocation_at_final_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "candidate.hwpx"
    relocated = root / "relocated.hwpx"
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output(target)
    original_capture = WorkspaceResolver.capture_output
    relocated_once = False

    def relocate_before_claim(self, value, *, create_parents=True):
        nonlocal relocated_once
        if (
            self is resolver
            and not relocated_once
            and Path(value) == target
            and target.exists()
            and target.read_bytes() == b"candidate"
        ):
            target.rename(relocated)
            target.symlink_to(relocated.name)
            relocated_once = True
        return original_capture(self, value, create_parents=create_parents)

    monkeypatch.setattr(workspace_module, "_descriptor_cas_supported", lambda: False)
    monkeypatch.setattr(
        WorkspaceResolver,
        "capture_output",
        relocate_before_claim,
    )

    with pytest.raises(WorkspacePathError, match="ownership was claimed"):
        resolver.atomic_publish_bytes(guard, b"candidate")

    assert relocated_once is True
    assert target.is_symlink()
    assert relocated.read_bytes() == b"candidate"


def test_portable_fallback_post_publish_failure_restores_existing_prestate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "candidate.hwpx"
    target.write_bytes(b"original")
    target.chmod(0o640)
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output(target)
    original_assert = WorkspaceResolver._assert_output_guard
    original_replace = workspace_module.os.replace
    published = False
    failed = False

    def track_replace(source, destination, *args, **kwargs):
        nonlocal published
        result = original_replace(source, destination, *args, **kwargs)
        if Path(destination) == target and str(source).endswith(".tmp"):
            published = True
        return result

    def fail_post_publish_check(self, current_guard):
        nonlocal failed
        if self is resolver and published and not failed:
            failed = True
            raise WorkspacePathError(
                "forced portable existing-output failure",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_parent_changed",
            )
        return original_assert(self, current_guard)

    monkeypatch.setattr(workspace_module, "_descriptor_cas_supported", lambda: False)
    monkeypatch.setattr(workspace_module.os, "replace", track_replace)
    monkeypatch.setattr(
        WorkspaceResolver,
        "_assert_output_guard",
        fail_post_publish_check,
    )

    with pytest.raises(WorkspacePathError, match="existing-output failure"):
        resolver.atomic_publish_bytes(guard, b"candidate")

    assert failed is True
    assert target.read_bytes() == b"original"
    assert target.stat().st_mode & 0o777 == 0o640


def test_outside_traversal_and_symlink_escape_are_denied(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.hwpx").write_bytes(b"secret")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    resolver = WorkspaceResolver.from_roots([root])

    for value in (outside / "secret.hwpx", "../outside/secret.hwpx", "escape/secret.hwpx"):
        with pytest.raises(WorkspacePathError) as exc_info:
            resolver.resolve(value)
        assert exc_info.value.code == "WORKSPACE_OUTSIDE_ROOT"
        assert "secret.hwpx" not in str(exc_info.value)

    with pytest.raises(WorkspacePathError):
        resolver.resolve_output("escape/new/result.hwpx")
    assert not (outside / "new").exists()


def test_environment_json_roots_and_legacy_single_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(first), str(second)]))
    monkeypatch.setenv(LEGACY_SANDBOX_ROOT_ENV, str(tmp_path / "ignored"))

    resolver = WorkspaceResolver.from_environment()

    assert resolver.roots == (first, second)
    assert resolver.source == WORKSPACE_ROOTS_ENV

    monkeypatch.delenv(WORKSPACE_ROOTS_ENV)
    monkeypatch.setenv(LEGACY_SANDBOX_ROOT_ENV, str(first))
    assert WorkspaceResolver.from_environment().roots == (first,)


def test_process_cwd_is_bounded_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WORKSPACE_ROOTS_ENV, raising=False)
    monkeypatch.delenv(LEGACY_SANDBOX_ROOT_ENV, raising=False)
    resolver = WorkspaceResolver.from_environment(cwd=tmp_path)
    assert resolver.roots == (tmp_path,)
    assert resolver.source == "process-cwd"


@pytest.mark.parametrize("root", [Path("/"), Path(os.path.abspath(os.sep))])
def test_filesystem_root_authorization_is_rejected(root: Path) -> None:
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceResolver.from_roots([root])


def test_degenerate_filesystem_root_cwd_fallback_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(WORKSPACE_ROOTS_ENV, raising=False)
    monkeypatch.delenv(LEGACY_SANDBOX_ROOT_ENV, raising=False)
    with pytest.raises(WorkspaceConfigurationError) as excinfo:
        WorkspaceResolver.from_environment(cwd=Path(Path("/").anchor))
    message = str(excinfo.value)
    assert WORKSPACE_ROOTS_ENV in message
    # The message must be actionable: it names the env var and shows an example.
    assert "for example" in message
    assert excinfo.value.code == "WORKSPACE_ROOT_INVALID"


@pytest.mark.parametrize(
    ("workspace", "expected"),
    [
        (PureWindowsPath(r"C:\Windows\System32"), True),
        (PureWindowsPath(r"C:\Windows"), True),
        (PureWindowsPath(r"C:\WINDOWS\System32\drivers"), True),
        (PureWindowsPath("C:\\"), True),
        (PureWindowsPath(r"C:\Docs\reports"), False),
        (PureWindowsPath(r"D:\projects\hwpx"), False),
    ],
)
def test_is_degenerate_cwd_detects_windows_system_directory(
    workspace: PureWindowsPath, expected: bool
) -> None:
    # Structured to be testable on POSIX: PureWindowsPath plus an explicit
    # system root exercise the Windows rule without running on Windows.
    system_root = PureWindowsPath(r"C:\Windows")
    assert (
        workspace_module._is_degenerate_cwd(workspace, system_root=system_root)
        is expected
    )


def test_is_degenerate_cwd_posix_only_flags_filesystem_root() -> None:
    assert workspace_module._is_degenerate_cwd(Path("/"), system_root=None) is True
    assert (
        workspace_module._is_degenerate_cwd(Path("/srv/docs"), system_root=None)
        is False
    )


def test_windows_system_directory_cwd_fallback_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(WORKSPACE_ROOTS_ENV, raising=False)
    monkeypatch.delenv(LEGACY_SANDBOX_ROOT_ENV, raising=False)
    # Force the Windows system-root fence on POSIX so from_environment itself
    # rejects a System32 cwd (the real Windows Claude Desktop launch directory).
    monkeypatch.setattr(
        workspace_module,
        "_windows_system_root",
        lambda: PureWindowsPath(r"C:\Windows"),
    )
    with pytest.raises(WorkspaceConfigurationError) as excinfo:
        WorkspaceResolver.from_environment(cwd=PureWindowsPath(r"C:\Windows\System32"))
    assert WORKSPACE_ROOTS_ENV in str(excinfo.value)


def test_explicit_roots_still_accepted_when_cwd_would_be_degenerate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Explicit configuration must remain unchanged even from a degenerate cwd.
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, str(tmp_path))
    resolver = WorkspaceResolver.from_environment(cwd=Path(Path("/").anchor))
    assert resolver.roots == (tmp_path,)
    assert resolver.source == WORKSPACE_ROOTS_ENV


def test_unconfigured_degenerate_cwd_storage_defers_until_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hwpx_automation.storage import LocalDocumentStorage

    monkeypatch.delenv(WORKSPACE_ROOTS_ENV, raising=False)
    monkeypatch.delenv(LEGACY_SANDBOX_ROOT_ENV, raising=False)
    monkeypatch.chdir(Path("/").anchor)

    # Construction must not raise: the server has to boot so that
    # mcp_server_health and per-call errors stay reachable on an unconfigured
    # degenerate cwd. The actionable error is deferred to first use.
    storage = LocalDocumentStorage(auto_backup=False)

    with pytest.raises(WorkspaceConfigurationError) as excinfo:
        storage.resolve_path("doc.hwpx")
    assert excinfo.value.code == "WORKSPACE_ROOT_INVALID"
    with pytest.raises(WorkspaceConfigurationError):
        _ = storage.workspace


def test_explicit_invalid_env_root_fails_fast_not_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hwpx_automation.storage import LocalDocumentStorage

    monkeypatch.delenv(LEGACY_SANDBOX_ROOT_ENV, raising=False)
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, str(tmp_path / "does-not-exist"))
    # Explicit configuration errors surface at construction (fail fast); only the
    # unconfigured cwd fallback is deferred.
    with pytest.raises(WorkspaceConfigurationError):
        LocalDocumentStorage(auto_backup=False)


@pytest.mark.parametrize(
    "variable",
    [WORKSPACE_ROOTS_ENV, LEGACY_WORKSPACE_ROOTS_ENV],
)
def test_canonical_and_legacy_invalid_workspace_roots_fail_fast(
    variable: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hwpx_automation.storage import LocalDocumentStorage

    monkeypatch.delenv(WORKSPACE_ROOTS_ENV, raising=False)
    monkeypatch.delenv(LEGACY_WORKSPACE_ROOTS_ENV, raising=False)
    monkeypatch.delenv(LEGACY_SANDBOX_ROOT_ENV, raising=False)
    monkeypatch.setenv(variable, str(tmp_path / "does-not-exist"))

    with pytest.raises(WorkspaceConfigurationError):
        LocalDocumentStorage(auto_backup=False)
