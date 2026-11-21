# SPDX-License-Identifier: Apache-2.0
"""Leaf table extraction and classification policy shared by form workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hwpx.table_patch import (
    build_grid,
    iter_table_spans,
    read_source_bytes,
    section_parts,
    table_text,
)


@dataclass
class _Table:
    section: str
    index: int
    bytes: bytes
    rows: int
    cols: int
    first_row: list[str]
    heading: str
    text: str


def _tables(source: str | Path | bytes) -> list[_Table]:
    data = read_source_bytes(source)
    out: list[_Table] = []
    for section_path, section in sorted(section_parts(data).items()):
        spans = iter_table_spans(section)
        for table_index, (start, end) in enumerate(spans):
            table = section[start:end]
            grid, report = build_grid(table)
            first: list[str] = []
            for column in range(report.col_count):
                cell = grid.get((0, column))
                first.append(
                    " ".join(
                        table_text(table[cell.start : cell.end]).split()
                    )
                    if cell
                    else ""
                )
            deduplicated: list[str] = []
            for cell_text in first:
                if not deduplicated or deduplicated[-1] != cell_text:
                    deduplicated.append(cell_text)
            window_start = max(0, start - 8000)
            heading = " ".join(
                table_text(section[window_start:start]).split()
            )[-80:]
            out.append(
                _Table(
                    section=section_path,
                    index=table_index,
                    bytes=table,
                    rows=report.row_count,
                    cols=report.col_count,
                    first_row=deduplicated,
                    heading=heading,
                    text=" ".join(table_text(table).split()),
                )
            )
    return out


def _classify(table: _Table) -> str:
    """Coarse table type from its first-row and heading signature."""

    first_row = " | ".join(table.first_row)
    text = table.text
    if (
        table.rows == 1
        and table.first_row
        and table.first_row[0].strip().isdigit()
    ):
        return "other"
    if "석차등급" in first_row and "원점수" in first_row:
        return "seokcha"
    if "제출" in first_row and ("모아찍기" in text or "인쇄물" in text):
        return "submit"
    if table.rows == 1 and table.cols == 1 and table.text.startswith("★유의"):
        return "notice_star"
    if first_row.startswith("교육과정 성취기준") and "평가기준" in first_row:
        return "achievement"
    if first_row.startswith("성취수준") and "일반적 특성" in first_row:
        return "level"
    if first_row.startswith("교육과정성취기준"):
        return "rubric"
    if "최소 능력" in first_row or "최소 성취수준" in first_row:
        return "minlevel"
    if "성취기준별 성취수준" in first_row and "최소" not in first_row:
        return "achievement"
    if "학기 단위 성취수준" in first_row:
        return "level"
    if first_row.startswith("평가 영역명") and "영역 만점" in first_row:
        return "rubric"
    if "평가 종류" in first_row or (
        "수행평가" in first_row and "합계" in first_row
    ):
        return "ratio"
    if "성취율" in first_row and "성취도" in first_row:
        return "achieve_rate"
    return "other"
