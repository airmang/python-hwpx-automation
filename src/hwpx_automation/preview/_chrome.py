# SPDX-License-Identifier: Apache-2.0

"""Capture a standalone preview page with headless Chrome."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def capture_page(
    chrome: str, html_path: Path, output_path: Path, width: int, height: int, *, flow: bool,
) -> tuple[int, str | None]:
    command = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    url = html_path.as_uri()
    if flow:
        measured = subprocess.run(
            [*command, f"--window-size={width},{height}", "--dump-dom", url],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        match = re.search(r'<section [^>]*\bdata-flow-height="(\d+)"', measured.stdout)
        if match is None:
            return height, "Chrome did not measure the flow height"
        height = max(height, int(match[1]))
    captured = subprocess.run(
        [*command, f"--window-size={width},{height}", f"--screenshot={output_path}", url],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if captured.returncode or not output_path.exists():
        return height, (captured.stderr or captured.stdout or "unknown error").strip()
    return height, None
