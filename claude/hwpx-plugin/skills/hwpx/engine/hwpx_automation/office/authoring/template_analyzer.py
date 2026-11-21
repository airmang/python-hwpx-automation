# SPDX-License-Identifier: Apache-2.0
"""Template analysis for form-fit planning.

Reading the package — header, fonts, run styles, page layout, tables and cell
geometry — is core's: ``hwpx.tools.template_analyzer`` is the one
implementation, re-exported here under the existing import path. This module
adds only the application projection on top: the agent-oriented schema and its
two CLI options.

``CellSummary.margin`` is the cell's *effective* inner margin, as core reads
it: the cell's own ``hp:cellMargin`` when its ``hasMargin`` is on, otherwise
the owning table's ``hp:inMargin``. Before automation delegated here it
reported ``hp:cellMargin`` unconditionally (#176). Page sizes are reported as
Hancom draws them (``landscape="WIDELY"`` is portrait; ``NARROWLY`` or no
attribute turns the page).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
from typing import Any, Sequence

from hwpx.tools.template_analyzer import (
    TEMPLATE_ANALYSIS_SCHEMA_VERSION,
    CellSummary,
    CharPropertySummary,
    ColumnWidthSummary,
    FontFaceSummary,
    HeaderSummary,
    RunStyleReference,
    SectionLayoutSummary,
    TableSummary,
    TemplateAnalysis,
    analyze_template,
    extract_template_parts,
)
from hwpx.tools.template_analyzer import main as _core_main

TEMPLATE_ANALYSIS_AGENT_SCHEMA_VERSION = "hwpx.template-analysis.agent-schema.v1"

__all__ = [
    "CellSummary",
    "CharPropertySummary",
    "ColumnWidthSummary",
    "FontFaceSummary",
    "HeaderSummary",
    "RunStyleReference",
    "SectionLayoutSummary",
    "TableSummary",
    "TemplateAnalysis",
    "analyze_template",
    "extract_template_parts",
    "main",
    "template_analysis_agent_schema",
]


def template_analysis_agent_schema() -> dict[str, Any]:
    return {
        "schemaVersion": TEMPLATE_ANALYSIS_AGENT_SCHEMA_VERSION,
        "analysisSchemaVersion": TEMPLATE_ANALYSIS_SCHEMA_VERSION,
        "description": "Agent-oriented fields for template form-fit planning.",
        "fieldGuide": {
            "section_layouts[].computed_body_width": "Writable body width in HWP units after page margins and gutter.",
            "table_summaries[].column_widths.widths": "Per-column widths reconstructed only from non-colspan cells.",
            "table_summaries[].cells[].margin": (
                "Effective cell inner margins in HWP units: the cell's own margin when hasMargin is on, "
                "otherwise the table's inner margin."
            ),
            "table_summaries[].cells[].vert_align": "Cell subList vertical alignment.",
            "table_summaries[].cells[].runs[].style": "Run charPrIDRef resolved to decoded style flags and font faces.",
            "char_properties[].flags": "Decoded bold, italic, underline, and strikeout booleans.",
        },
        "recommendedUse": [
            "Choose target cells by row/col and span before planning replacements.",
            "Use computed_body_width and column_widths to size generated tables.",
            "Preserve run charPrIDRef when replacing text in styled cells.",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze a reference HWPX template for pack-ready, template-preserving workflows"
    )
    parser.add_argument("input", help="Input HWPX path")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary")
    parser.add_argument("--output-json", help="Write the JSON summary to a file")
    parser.add_argument("--schema-json", action="store_true", help="Print the agent-friendly JSON schema")
    parser.add_argument("--output-schema-json", help="Write the agent-friendly JSON schema to a file")
    parser.add_argument(
        "--extract-dir",
        help=(
            "Create a pack-ready extracted workspace that preserves archive-relative paths "
            "and hwpx-pack metadata"
        ),
    )
    parser.add_argument("--extract-header", help="Copy the first header.xml part to a path")
    parser.add_argument("--extract-section", help="Copy the first section XML part to a path")
    parser.add_argument(
        "--extract-section-dir",
        help="Backward-compatible alias that copies section*.xml files into a directory",
    )
    return parser


def _core_argv(args: argparse.Namespace) -> list[str]:
    argv = [args.input]
    if args.json:
        argv.append("--json")
    for flag, value in (
        ("--output-json", args.output_json),
        ("--extract-dir", args.extract_dir),
        ("--extract-header", args.extract_header),
        ("--extract-section", args.extract_section),
        ("--extract-section-dir", args.extract_section_dir),
    ):
        if value:
            argv.extend((flag, value))
    return argv


def _output_schema(args: argparse.Namespace) -> None:
    if args.schema_json or args.output_schema_json:
        schema_payload = json.dumps(template_analysis_agent_schema(), ensure_ascii=False, indent=2)
        if args.schema_json:
            print(schema_payload)
        if args.output_schema_json:
            schema_path = Path(args.output_schema_json)
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.write_text(schema_payload, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Core's template-analysis CLI plus ``--schema-json`` / ``--output-schema-json``.

    The core command does the analysis, extraction and summary. The schema is
    printed after the summary and before the ``extracted:`` lines, as before.
    """

    args = _parser().parse_args(argv)
    schema_only = args.schema_json and not any(
        (
            args.json,
            args.output_json,
            args.extract_dir,
            args.extract_header,
            args.extract_section,
            args.extract_section_dir,
        )
    )
    if schema_only:
        input_path = Path(args.input)
        if not input_path.is_file():
            print(f"ERROR: file not found: {input_path}")
            return 1
        try:
            analyze_template(input_path)
        except Exception as exc:
            print(f"ERROR: {exc}")
            return 1
        _output_schema(args)
        return 0

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        status = _core_main(_core_argv(args))
    lines = captured.getvalue().splitlines()
    extracted_from = len(lines)
    while extracted_from > 0 and lines[extracted_from - 1].startswith("extracted: "):
        extracted_from -= 1
    for line in lines[:extracted_from]:
        print(line)
    if status != 0:
        return status

    _output_schema(args)

    for line in lines[extracted_from:]:
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI convenience
    raise SystemExit(main())
