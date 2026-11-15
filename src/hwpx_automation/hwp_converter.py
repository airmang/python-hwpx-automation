# SPDX-License-Identifier: Apache-2.0
"""HWP(.hwp) -> HWPX(.hwpx) 변환 유틸리티.

python-hwpx(6.6.0+)가 HWP 5.0 문서를 표·서식까지 직접 읽는다. 변환은 그 문서
모델을 HWPX로 저장하는 일이다. 예전 경로(외부 ``hwp5proc`` 명령의 XML에서
글과 표 칸 글만 옮겨 새 문서에 다시 쓰기)는 서식을 잃었고, 선언하지 않은
외부 프로그램이 없으면 늘 실패했다.

``ConversionResult``의 모양과 ``HwpxOps.convert_hwp_to_hwpx``의 결과 키는 그대로다.
``skipped_elements``는 본체의 ``conversion_report``가 센 "옮기지 못한 것"이다.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping

from hwpx.document import HwpxDocument

from .core.document import save_doc


class HwpConversionError(RuntimeError):
    """HWP 변환 과정에서 발생하는 오류."""


@dataclass(slots=True)
class TablePayload:
    """변환 대상 표 데이터.

    The core-backed converter keeps tables in the document model and no longer
    builds these; the class stays importable for callers of earlier releases.
    """

    rows: List[List[str]]


@dataclass(slots=True)
class ConversionResult:
    """HWP -> HWPX 변환 결과 요약."""

    success: bool
    output_path: str
    paragraphs_converted: int
    tables_converted: int
    skipped_elements: List[str]
    warnings: List[str]
    verification: dict[str, Any]
    open_safety: dict[str, Any]


def _report_items(report: Any) -> tuple[List[str], List[str]]:
    """``(skipped_elements, warnings)`` from python-hwpx's conversion report."""

    skipped: List[str] = []
    notes: List[str] = []
    unconverted: Mapping[str, int] = getattr(report, "unconverted", None) or {}
    dropped: Mapping[str, int] = getattr(report, "dropped", None) or {}
    for kind, count in sorted(unconverted.items()):
        skipped.append(f"{kind} ({count})")
    for kind, count in sorted(dropped.items()):
        skipped.append(f"{kind} ({count})")
    if unconverted:
        notes.append(
            "아직 옮기지 못한 내용(HWPX로 담을 수 있으나 변환이 만들지 않음): "
            + ", ".join(f"{kind} {count}개" for kind, count in sorted(unconverted.items()))
        )
    if dropped:
        notes.append(
            "HWPX에 대응 요소가 없어 버린 데이터: "
            + ", ".join(f"{kind} {count}개" for kind, count in sorted(dropped.items()))
        )
    return skipped, notes


def _counts(document: HwpxDocument) -> tuple[int, int]:
    """Top-level non-blank paragraphs and top-level tables, as before."""

    paragraphs = 0
    tables = 0
    for paragraph in document.paragraphs:
        paragraph_tables = list(paragraph.tables)
        tables += len(paragraph_tables)
        if not paragraph_tables and (paragraph.text or "").strip():
            paragraphs += 1
    return paragraphs, tables


def convert_hwp_to_hwpx(hwp_path: str, output_path: str) -> ConversionResult:
    source = Path(hwp_path).expanduser().resolve()
    target = Path(output_path).expanduser().resolve()

    if source.suffix.lower() != ".hwp":
        raise HwpConversionError("source는 .hwp 파일이어야 합니다")
    if not source.exists():
        raise HwpConversionError(f"입력 파일이 존재하지 않습니다: {source}")

    try:
        with warnings.catch_warnings():
            # The conversion report below carries what the open would warn about.
            warnings.simplefilter("ignore")
            document = HwpxDocument.open(str(source))
    except Exception as exc:
        raise HwpConversionError(f"python-hwpx가 HWP 문서를 열지 못했습니다: {exc}") from exc

    try:
        skipped_elements, notes = _report_items(getattr(document, "conversion_report", None))
        paragraphs, tables = _counts(document)
        target.parent.mkdir(parents=True, exist_ok=True)
        verification = save_doc(document, str(target))
    finally:
        document.close()

    result_warnings: List[str] = list(notes)
    if skipped_elements:
        result_warnings.append("변환 제외 요소: " + ", ".join(skipped_elements))

    return ConversionResult(
        success=True,
        output_path=str(target),
        paragraphs_converted=paragraphs,
        tables_converted=tables,
        skipped_elements=skipped_elements,
        warnings=result_warnings,
        verification=verification,
        open_safety=verification["openSafety"],
    )
