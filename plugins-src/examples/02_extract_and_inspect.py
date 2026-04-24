#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""기존 HWPX에서 텍스트를 추출하고 표 개수를 조사하는 예제."""

from __future__ import annotations

import argparse
from pathlib import Path

from hwpx import ObjectFinder, TextExtractor


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract text and inspect table count from an HWPX document."
    )
    parser.add_argument(
        "input_hwpx",
        nargs="?",
        default=str(Path(__file__).resolve().parent / "out" / "01_created.hwpx"),
        help="Input .hwpx path (default: examples/out/01_created.hwpx)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    input_path = Path(args.input_hwpx).resolve()

    # 문서 전체 텍스트를 추출한다.
    with TextExtractor(str(input_path)) as extractor:
        text = extractor.extract_text(include_nested=True)

    # 문서 내부의 표 개수를 확인한다.
    finder = ObjectFinder(str(input_path))
    tables = finder.find_all(tag="tbl")

    print("[TEXT]")
    print(text)
    print()
    print(f"[TABLES] {len(tables)}")


if __name__ == "__main__":
    main()
