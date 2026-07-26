#!/usr/bin/env python3
"""Parse every shipped Python example and Python Markdown fence."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_FENCE = re.compile(
    r"^```(?:python|py)\s*\n(?P<code>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)
JSON_FENCE = re.compile(
    r"^```json\s*\n(?P<code>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)


def _markdown_paths() -> list[Path]:
    return [
        ROOT / "README.md",
        ROOT / "SKILL.md",
        *sorted((ROOT / "references").glob("*.md")),
        *sorted((ROOT / "examples").glob("*.md")),
    ]


def validate() -> tuple[int, int, int]:
    python_files = sorted((ROOT / "examples").glob("*.py"))
    for path in python_files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    fence_count = 0
    json_fence_count = 0
    for path in _markdown_paths():
        text = path.read_text(encoding="utf-8")
        for index, match in enumerate(PYTHON_FENCE.finditer(text), 1):
            fence_count += 1
            ast.parse(
                match.group("code"),
                filename=f"{path}#python-fence-{index}",
            )
        for index, match in enumerate(JSON_FENCE.finditer(text), 1):
            json_fence_count += 1
            try:
                json.loads(match.group("code"))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}#json-fence-{index}: invalid JSON: {exc}"
                ) from exc
    if fence_count == 0:
        raise RuntimeError("no shipped Python Markdown fences were discovered")
    if json_fence_count == 0:
        raise RuntimeError("no shipped JSON Markdown fences were discovered")
    return len(python_files), fence_count, json_fence_count


def main() -> int:
    python_files, fences, json_fences = validate()
    print(
        f"[OK] parsed {python_files} shipped Python examples and "
        f"{fences} Python / {json_fences} JSON Markdown fences"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
