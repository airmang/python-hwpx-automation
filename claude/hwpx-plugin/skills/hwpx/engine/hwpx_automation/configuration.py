# SPDX-License-Identifier: Apache-2.0
"""Canonical automation configuration with bounded 6.x MCP fallbacks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

CANONICAL_ENV_PREFIX = "HWPX_AUTOMATION_"
LEGACY_ENV_PREFIX = "HWPX_MCP_"


def canonical_env_name(suffix: str) -> str:
    return f"{CANONICAL_ENV_PREFIX}{suffix}"


def legacy_env_name(suffix: str) -> str:
    return f"{LEGACY_ENV_PREFIX}{suffix}"


def env_value(suffix: str, default: str | None = None) -> str | None:
    """Read canonical configuration first, then the supported 6.x legacy key."""

    canonical = os.environ.get(canonical_env_name(suffix))
    if canonical is not None:
        return canonical
    legacy = os.environ.get(legacy_env_name(suffix))
    if legacy is not None:
        return legacy
    return default


def env_int(suffix: str, default: int) -> int:
    raw = env_value(suffix)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(suffix: str, default: float) -> float:
    raw = env_value(suffix)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def find_executable(name: str, *, search_path: str | None = None) -> str | None:
    """Locate a program on ``PATH`` without consulting the working directory.

    ``shutil.which`` on Windows looks in the current directory first, and the
    current directory is commonly the document workspace. This lookup only
    accepts absolute ``PATH`` entries that are not the working directory, and
    only bare program names.
    """

    if not name or os.path.basename(name) != name or name in {".", ".."}:
        return None
    raw = os.environ.get("PATH", "") if search_path is None else search_path
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        cwd = None
    if sys.platform == "win32":
        pathext = [
            ext
            for ext in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep)
            if ext
        ]
        if any(name.lower().endswith(ext.lower()) for ext in pathext):
            names = [name]
        else:
            names = [name + ext for ext in pathext]
    else:
        names = [name]
    for entry in raw.split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        directory = Path(entry)
        if not directory.is_absolute():
            continue
        try:
            if cwd is not None and directory.resolve() == cwd:
                continue
        except OSError:
            continue
        for candidate_name in names:
            candidate = directory / candidate_name
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
            except OSError:
                continue
    return None


def absolute_executable(value: str | None) -> str | None:
    """Return *value* only when it names an existing file by absolute path."""

    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        return None
    try:
        return str(candidate) if candidate.is_file() else None
    except OSError:
        return None


def windows_powershell(preferred: str | None = None) -> str:
    """Program to launch for Windows PowerShell; on Windows always absolute.

    A bare name handed to process creation on Windows can be satisfied from
    the working directory, so a missing or bare *preferred* value is replaced
    by the system location.
    """

    if preferred and os.path.basename(preferred) != preferred:
        return preferred
    if sys.platform != "win32":
        return (
            find_executable(preferred or "powershell")
            or find_executable("pwsh")
            or preferred
            or "powershell"
        )
    relative = Path("System32") / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    for variable in ("SystemRoot", "WINDIR"):
        root = os.environ.get(variable)
        if root and Path(root).is_absolute() and (Path(root) / relative).is_file():
            return str(Path(root) / relative)
    found = find_executable(preferred or "powershell") or find_executable("pwsh")
    if found:
        return found
    return str(Path("C:/Windows") / relative)


__all__ = [
    "CANONICAL_ENV_PREFIX",
    "LEGACY_ENV_PREFIX",
    "absolute_executable",
    "canonical_env_name",
    "env_float",
    "env_int",
    "env_value",
    "find_executable",
    "legacy_env_name",
    "windows_powershell",
]
