"""Regression gate for Windows portable-fallback publication (issue #98).

On Windows ``os.open`` defaults to CRT text mode: reads translate CRLF and
stop at the first 0x1A byte. Every HWPX payload is a ZIP container, so both
byte patterns always occur, and a snapshot digest taken through a text-mode
descriptor can never match the same file read in binary mode. POSIX runners
cannot reproduce text-mode descriptor semantics, so this file doubles as the
scoped suite the Windows CI job executes on a real Windows runner.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import hwpx_automation.workspace as workspace_module
from hwpx_automation.workspace import WorkspaceResolver

# CRLF plus 0x1A: the byte sequences the Windows CRT text mode rewrites or
# truncates at. Real HWPX (ZIP) payloads always contain both.
TEXT_MODE_HOSTILE = b"PK\x03\x04\r\nbody\x1atrailer\r\n\x00\x1a" * 3


def _force_portable_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace_module, "_descriptor_cas_supported", lambda: False)


def test_snapshot_target_opens_descriptor_in_binary_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "sample.hwpx"
    target.write_bytes(TEXT_MODE_HOSTILE)
    on_windows = os.name == "nt"
    binary_flag = getattr(os, "O_BINARY", 0) if on_windows else 0x40000000
    if not on_windows:
        monkeypatch.setattr(os, "O_BINARY", binary_flag, raising=False)
    real_open = os.open
    seen_flags: list[int] = []

    def recording_open(path, flags, *args, **kwargs):
        seen_flags.append(flags)
        if not on_windows:
            flags &= ~binary_flag
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(workspace_module.os, "open", recording_open)

    existed, _, _, digest, _ = workspace_module._snapshot_target(target)

    assert existed
    assert digest == hashlib.sha256(TEXT_MODE_HOSTILE).hexdigest()
    assert seen_flags and all(flags & binary_flag for flags in seen_flags)


@pytest.mark.skipif(
    os.open not in os.supports_dir_fd,
    reason="descriptor-relative snapshots require dir_fd support",
)
def test_relative_file_snapshot_opens_descriptor_in_binary_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "sample.hwpx"
    target.write_bytes(TEXT_MODE_HOSTILE)
    binary_flag = 0x40000000
    monkeypatch.setattr(os, "O_BINARY", binary_flag, raising=False)
    real_open = os.open
    seen_flags: list[int] = []

    def recording_open(path, flags, *args, **kwargs):
        seen_flags.append(flags)
        flags &= ~binary_flag
        return real_open(path, flags, *args, **kwargs)

    parent_fd = os.open(tmp_path, os.O_RDONLY)
    try:
        monkeypatch.setattr(workspace_module.os, "open", recording_open)
        _, _, digest, _ = workspace_module._relative_file_snapshot(
            parent_fd,
            target.name,
        )
    finally:
        monkeypatch.setattr(workspace_module.os, "open", real_open)
        os.close(parent_fd)

    assert digest == hashlib.sha256(TEXT_MODE_HOSTILE).hexdigest()
    assert seen_flags and all(flags & binary_flag for flags in seen_flags)


def test_read_guarded_bytes_fallback_matches_binary_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_portable_fallback(monkeypatch)
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "target.hwpx"
    target.write_bytes(TEXT_MODE_HOSTILE)
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output(target)

    assert resolver.read_guarded_bytes(guard) == TEXT_MODE_HOSTILE


def test_portable_fallback_inplace_publish_survives_text_mode_hostile_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_portable_fallback(monkeypatch)
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "target.hwpx"
    target.write_bytes(TEXT_MODE_HOSTILE)
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output(target)
    updated = TEXT_MODE_HOSTILE + b"\r\n\x1aupdated"

    published = resolver.atomic_write_bytes(guard, updated)

    assert published == guard.path
    assert target.read_bytes() == updated


def test_portable_fallback_new_output_publish_survives_text_mode_hostile_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_portable_fallback(monkeypatch)
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "fresh.hwpx"
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output(target)

    published = resolver.atomic_write_bytes(guard, TEXT_MODE_HOSTILE)

    assert published == guard.path
    assert target.read_bytes() == TEXT_MODE_HOSTILE


def test_portable_fallback_remove_output_survives_text_mode_hostile_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_portable_fallback(monkeypatch)
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "target.hwpx"
    target.write_bytes(TEXT_MODE_HOSTILE)
    resolver = WorkspaceResolver.from_roots([root])
    guard = resolver.capture_output(target)

    resolver.remove_output(guard)

    assert not target.exists()
