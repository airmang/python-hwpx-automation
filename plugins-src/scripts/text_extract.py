#!/usr/bin/env python3
"""text_extract.py

Extract text from an HWPX document using python-hwpx TextExtractor.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hwpx import TextExtractor


def extract_plain_text(
    input_hwpx: str | Path,
    *,
    include_nested: bool = False,
) -> str:
    with TextExtractor(str(input_hwpx)) as extractor:
        return extractor.extract_text(include_nested=include_nested)


def extract_paragraphs_json(
    input_hwpx: str | Path,
    *,
    include_nested: bool = False,
) -> dict[str, object]:
    paragraphs = []
    with TextExtractor(str(input_hwpx)) as extractor:
        for paragraph in extractor.iter_document_paragraphs(include_nested=include_nested):
            paragraphs.append(
                {
                    "section_index": paragraph.section.index,
                    "paragraph_index": paragraph.index,
                    "path": paragraph.path,
                    "tag": paragraph.tag,
                    "is_nested": paragraph.is_nested,
                    "text": paragraph.text(),
                }
            )

    return {
        "source": str(input_hwpx),
        "include_nested": include_nested,
        "paragraphs": paragraphs,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract text from an HWPX document with python-hwpx TextExtractor."
    )
    parser.add_argument("input_hwpx", help="Input .hwpx path")
    parser.add_argument("--out", dest="output_path", default=None, help="Write result to a file")
    parser.add_argument(
        "--format",
        choices=("plain", "json"),
        default="plain",
        help="Output format (default: plain)",
    )
    parser.add_argument(
        "--include-nested",
        action="store_true",
        help="Include nested paragraphs such as paragraphs inside tables",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    input_path = Path(args.input_hwpx).resolve()
    if not input_path.exists():
        print(f"[ERR] file not found: {input_path}", file=sys.stderr)
        return 2

    try:
        if args.format == "json":
            payload = extract_paragraphs_json(
                input_path,
                include_nested=args.include_nested,
            )
            output = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            output = extract_plain_text(
                input_path,
                include_nested=args.include_nested,
            )
    except Exception as exc:
        print(f"[ERR] extract failed: {exc}", file=sys.stderr)
        return 1

    if args.output_path:
        output_path = Path(args.output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"[OK] wrote: {output_path}")
    else:
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
