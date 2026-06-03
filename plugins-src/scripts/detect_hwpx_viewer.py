#!/usr/bin/env python3
"""Detect the best local HWPX viewer for visual acceptance checks.

The result is intentionally small and JSON-friendly so batch runners and CI
fallbacks can depend on the same shape without requiring Hancom to be present.
Detection order is Hancom Office HWP, LibreOffice, Quick Look, then blocked.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


HANCOM_APP_NAMES = (
    "Hancom Office HWP",
    "Hancom Office",
    "Hanword",
)
HANCOM_APP_PATHS = (
    "/Applications/Hancom Office HWP.app",
    "/Applications/Hancom Office.app",
    "/Applications/Hanword.app",
)
LIBREOFFICE_APP_PATHS = (
    "/Applications/LibreOffice.app",
)


def _exists(value: str) -> bool:
    return bool(value) and Path(value).expanduser().exists()


def _which(name: str) -> str | None:
    path = shutil.which(name)
    return str(Path(path).resolve()) if path else None


def _mdfind_app(names: tuple[str, ...]) -> str | None:
    if platform.system() != "Darwin" or not shutil.which("mdfind"):
        return None

    quoted = " || ".join(f'kMDItemDisplayName == "{name}"' for name in names)
    try:
        result = subprocess.run(
            ["mdfind", f'kMDItemKind == "Application" && ({quoted})'],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None

    for line in result.stdout.splitlines():
        candidate = line.strip()
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _available(viewer: str, app: str, reason: str, command: list[str]) -> dict[str, Any]:
    return {
        "status": "available",
        "viewer": viewer,
        "app": app,
        "reason": reason,
        "command": command,
    }


def detect_hwpx_viewer(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Return the first available viewer in Hancom -> LibreOffice -> Quick Look order."""

    values = os.environ if env is None else env

    forced = values.get("HWPX_VIEWER_FORCE", "").strip().lower()
    if forced in {"blocked", "none"}:
        return {
            "status": "blocked",
            "viewer": "blocked",
            "app": "",
            "reason": "forced blocked by HWPX_VIEWER_FORCE",
            "command": [],
        }

    hancom_override = values.get("HWPX_HANCOM_APP", "").strip()
    if _exists(hancom_override):
        return _available(
            "hancom",
            str(Path(hancom_override).expanduser()),
            "Hancom app found from HWPX_HANCOM_APP",
            ["open", "-a", str(Path(hancom_override).expanduser())],
        )

    if platform.system() == "Darwin" and shutil.which("open"):
        for app_path in HANCOM_APP_PATHS:
            if Path(app_path).exists():
                return _available(
                    "hancom",
                    app_path,
                    "Hancom Office HWP app found in /Applications",
                    ["open", "-a", "Hancom Office HWP"],
                )
        mdfind_match = _mdfind_app(HANCOM_APP_NAMES)
        if mdfind_match:
            return _available(
                "hancom",
                mdfind_match,
                "Hancom app found by Spotlight metadata",
                ["open", "-a", str(Path(mdfind_match).expanduser())],
            )

    soffice_override = values.get("HWPX_SOFFICE", "").strip()
    if _exists(soffice_override):
        path = str(Path(soffice_override).expanduser())
        return _available("libreoffice", path, "soffice found from HWPX_SOFFICE", [path])

    for app_path in LIBREOFFICE_APP_PATHS:
        if Path(app_path).exists():
            return _available(
                "libreoffice",
                app_path,
                "LibreOffice app found in /Applications",
                ["open", "-a", "LibreOffice"],
            )

    soffice = _which("soffice")
    if soffice:
        return _available("libreoffice", soffice, "soffice found on PATH", [soffice])

    qlmanage = _which("qlmanage")
    if platform.system() == "Darwin" and qlmanage:
        return _available("quicklook", qlmanage, "Quick Look qlmanage found on PATH", [qlmanage, "-p"])

    return {
        "status": "blocked",
        "viewer": "blocked",
        "app": "",
        "reason": "no Hancom Office HWP, LibreOffice, or Quick Look viewer found",
        "command": [],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect the best local HWPX viewer")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = detect_hwpx_viewer()
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["status"] == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
