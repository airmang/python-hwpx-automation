# SPDX-License-Identifier: Apache-2.0
"""문단, 표, 메모 CRUD 로직."""

from __future__ import annotations

from datetime import datetime
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree as ET

from ..compat import patch_python_hwpx
from ..storage import build_hwpx_open_safety_report, open_local_document
from ..upstream import (
    HP_NS as _HP_NS,
    HwpxDocument,
    is_hwp5_source,
    is_hwp5_target,
    repair_pathological_text_spacing,
)
from .document import save_doc
from .formatting import resolve_style_id
from .locations import resolve_paragraph_reference

logger = logging.getLogger(__name__)


def _iter_tables(doc: HwpxDocument):
    for paragraph in doc.paragraphs:
        for table in getattr(paragraph, "tables", []):
            yield table
            yield from _iter_nested_tables(table)


def _iter_nested_tables(table: Any):
    for row in getattr(table, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            for paragraph in getattr(cell, "paragraphs", []) or []:
                for nested in getattr(paragraph, "tables", []) or []:
                    yield nested
                    yield from _iter_nested_tables(nested)


def _resolve_style(doc: HwpxDocument, style: str | None) -> str | None:
    if style is None:
        return None
    return resolve_style_id(doc, style)


def _style_char_pr(doc: HwpxDocument, style_id: str | int | None) -> str | None:
    """문단 스타일(styleIDRef)이 참조하는 글자속성(charPrIDRef)을 돌려준다.

    스타일이 없거나 글자속성이 지정되지 않으면 ``None``. ``add_paragraph`` 계열이
    새 run에 스타일이 규정한 글자 크기·글꼴을 실어 주도록 하기 위한 조회 헬퍼다.
    """
    if style_id is None:
        return None
    from .formatting import list_styles_in_doc

    target = str(style_id)
    for style in list_styles_in_doc(doc):
        if str(style.get("id")) == target:
            ref = style.get("char_pr_id_ref")
            return None if ref in (None, "") else str(ref)
    return None


def _default_body_char_pr(doc: HwpxDocument) -> str | None:
    """본문(바탕글/Normal) 스타일의 글자속성을 돌려준다.

    스타일 인자가 없는 표 셀 등에 제목용 큰 글자(charPr 0)가 새어 들어가지
    않도록, 문서 기본 본문 크기를 적용하기 위한 fallback 값이다.
    """
    from .formatting import list_styles_in_doc

    fallback: str | None = None
    for style in list_styles_in_doc(doc):
        name = (style.get("name") or "").strip()
        eng = (style.get("eng_name") or "").strip()
        ref = style.get("char_pr_id_ref")
        if ref in (None, ""):
            continue
        if name in ("바탕글", "본문") or eng.lower() in ("normal", "body"):
            return str(ref)
        if fallback is None and str(style.get("id")) == "0":
            fallback = str(ref)
    return fallback


def _enforce_run_char_pr(paragraph: Any, char_ref: str | None) -> None:
    """방금 만든 문단의 run이 스타일 글자속성을 쓰도록 보정한다(회귀 가드).

    python-hwpx는 글자속성을 명시하지 않은 새 run에 ``charPrIDRef="0"``을
    박는다. 이 0번 글자속성이 본문 크기이면 문제없지만, 제목용 큰 글자
    (예: 17pt)를 0번에 둔 투고 양식에서는 본문 전체가 그 크기로 렌더된다.
    스타일을 지정해 문단을 넣었는데도 run이 스타일과 다른 글자속성을 가지면
    스타일 값으로 교정한다. 기본값(0/None) 교정은 정상 경로라 DEBUG 로깅,
    그 밖의 예상 못 한 불일치는 회귀 신호로 WARNING을 남긴다.
    """
    if char_ref is None or paragraph is None:
        return
    want = str(char_ref)
    for run in getattr(paragraph, "runs", None) or []:
        current = getattr(run, "char_pr_id_ref", None)
        if current is not None and str(current) == want:
            continue
        if current in (None, 0, "0"):
            logger.debug(
                "styled run 기본 charPr(%s) → 스타일 charPr=%s 적용", current, want
            )
        else:
            logger.warning(
                "styled run charPrIDRef=%s 가 스타일 charPr=%s 와 불일치 → 교정",
                current,
                want,
            )
        try:
            run.char_pr_id_ref = int(want) if want.isdigit() else want
        except Exception:  # pragma: no cover - 방어적
            logger.debug("run charPrIDRef 교정 실패", exc_info=True)


def _clear_paragraph_layout_cache(paragraph: Any) -> None:
    element = getattr(paragraph, "element", None)
    if element is None:
        return
    for child in list(element):
        if child.tag.rsplit("}", 1)[-1].lower() == "linesegarray":
            element.remove(child)
    section = getattr(paragraph, "section", None)
    if section is not None and hasattr(section, "mark_dirty"):
        section.mark_dirty()


# ── 문단 ──────────────────────────────────────────────

def _outline_style_for_level(doc: HwpxDocument, level: int) -> dict[str, Any] | None:
    from .formatting import list_styles_in_doc

    for style in list_styles_in_doc(doc):
        name = str(style.get("name") or "")
        eng_name = str(style.get("eng_name") or "")
        if name == f"개요 {level}" or eng_name == f"Outline {level}":
            return style
    return None


def add_heading_to_doc(doc: HwpxDocument, text: str, level: int = 1) -> int:
    """문서 끝에 제목(헤딩) 문단을 추가한다. 추가된 paragraph_index를 반환.

    제목 텍스트는 마크다운 프리픽스 없이 저장하고, 개요 수준은 템플릿 내장
    "개요 N" 문단 스타일로 표현한다. 구버전이 본문에 남긴 '#' 리터럴 헤딩은
    읽기 경로(_outline_level)가 계속 인식한다.
    """
    safe_level = min(10, max(1, int(level)))
    stripped = (text or "").strip()
    if stripped.startswith("#"):
        stripped = stripped.lstrip("#").strip()

    from ..office.authoring import DocumentStylePreset

    tokens = DocumentStylePreset().ensure_tokens(doc)
    char_ref = tokens.get(f"gov_heading_{safe_level}") or tokens.get("heading")

    outline_style = _outline_style_for_level(doc, safe_level)
    if outline_style is not None:
        doc.add_paragraph(
            stripped,
            style_id_ref=outline_style.get("id"),
            para_pr_id_ref=outline_style.get("para_pr_id_ref"),
            char_pr_id_ref=char_ref,
            inherit_style=False,
        )
    else:
        doc.add_paragraph(stripped, char_pr_id_ref=char_ref, inherit_style=False)
    return len(doc.paragraphs) - 1


def _last_paragraph_is_outline(doc: HwpxDocument) -> bool:
    paragraphs = doc.paragraphs
    if not paragraphs:
        return False
    ref = getattr(paragraphs[-1], "style_id_ref", None)
    if ref is None:
        return False
    from .formatting import outline_style_levels

    return str(ref) in outline_style_levels(doc)


def add_paragraph_to_doc(doc: HwpxDocument, text: str, style: str = None) -> int:
    """문서 끝에 일반 문단을 추가한다. 추가된 paragraph_index를 반환."""
    style_id = _resolve_style(doc, style)
    # 스타일이 규정한 글자속성(크기·글꼴)을 run에 실어 준다. 이를 넘기지 않으면
    # python-hwpx가 charPrIDRef="0"을 기본으로 박아, 0번이 제목 크기인 양식에서
    # 본문이 통째로 커진다(add_heading_to_doc는 이미 char_pr_id_ref를 넘긴다).
    char_ref = _style_char_pr(doc, style_id)
    # 직전 문단이 개요(헤딩) 스타일이면 상속을 끊는다 — 헤딩 뒤 본문이
    # 개요 수준·강조 서식을 물려받는 사고 방지.
    inherit = not (style_id is None and _last_paragraph_is_outline(doc))
    paragraph = doc.add_paragraph(
        text or "",
        style_id_ref=style_id,
        char_pr_id_ref=char_ref,
        inherit_style=inherit,
    )
    _enforce_run_char_pr(paragraph, char_ref)
    repair_pathological_text_spacing(
        doc,
        paragraph=paragraph,
        fallback_char_pr_id=char_ref or _default_body_char_pr(doc),
    )
    return len(doc.paragraphs) - 1


def insert_paragraph_to_doc(doc: HwpxDocument, paragraph_index: int, text: str, style: str = None) -> int:
    """지정 위치 앞에 문단을 삽입한다. 삽입된 paragraph_index를 반환."""
    total = len(doc.paragraphs)
    if paragraph_index < 0 or paragraph_index > total:
        raise ValueError(f"유효하지 않은 paragraph_index: {paragraph_index}")

    if paragraph_index == total:
        return add_paragraph_to_doc(doc, text, style)

    target = doc.paragraphs[paragraph_index]
    section = target.section
    style_id = _resolve_style(doc, style)
    para_pr_id_ref = None
    if style_id is None:
        # 삽입 위치와 무관한 섹션 마지막 문단이 아니라 바로 뒤 대상 문단의
        # 문단/글자 스타일을 이어받는다.
        style_id = getattr(target, "style_id_ref", None)
        para_pr_id_ref = getattr(target, "para_pr_id_ref", None)
    char_ref = _style_char_pr(doc, style_id)
    if char_ref is None and style is None:
        target_runs = list(getattr(target, "runs", None) or [])
        if target_runs:
            char_ref = getattr(target_runs[0], "char_pr_id_ref", None)
    inserted = section.add_paragraph(
        text or "",
        style_id_ref=style_id,
        para_pr_id_ref=para_pr_id_ref,
        char_pr_id_ref=char_ref,
        inherit_style=False,
    )
    _enforce_run_char_pr(inserted, char_ref)
    repair_pathological_text_spacing(
        doc,
        paragraph=inserted,
        fallback_char_pr_id=_style_char_pr(doc, style_id) or _default_body_char_pr(doc),
    )

    section_element = section.element
    try:
        target_position = list(section_element).index(target.element)
    except ValueError as exc:
        raise RuntimeError("대상 문단 요소를 섹션에서 찾을 수 없습니다.") from exc

    # add_paragraph는 항상 끝에 붙으므로, 생성한 요소를 제거한 뒤 목표 위치에 재삽입한다.
    section_element.remove(inserted.element)
    section_element.insert(target_position, inserted.element)
    return paragraph_index


def delete_paragraph_from_doc(doc: HwpxDocument, paragraph_index: int) -> int:
    """지정 문단을 실제 제거한다. 남은 문단 수를 반환."""
    paragraphs = doc.paragraphs
    total = len(paragraphs)
    if paragraph_index < 0 or paragraph_index >= total:
        raise ValueError(f"유효하지 않은 paragraph_index: {paragraph_index}")
    if total <= 1:
        # 최소 1개 문단은 유지해 문서 구조를 보존한다.
        target = paragraphs[paragraph_index]
        for run in target.runs:
            run.text = ""
        _clear_paragraph_layout_cache(target)
        return total

    try:
        # remove_paragraph is demoted in 6.0 with no namespace replacement
        # (design table row 101) — the paragraph object owns .remove() now.
        paragraphs[paragraph_index].remove()
    except (ValueError, IndexError) as exc:
        raise RuntimeError("삭제할 문단 요소를 섹션에서 찾을 수 없습니다.") from exc
    return total - 1


# ── 표 ────────────────────────────────────────────────

def add_table_to_doc(doc: HwpxDocument, rows: int, cols: int, data: list[list[str]] = None) -> int:
    """문서 끝에 표를 추가한다. 추가된 table_index를 반환."""
    if rows <= 0 or cols <= 0:
        raise ValueError("rows와 cols는 1 이상이어야 합니다.")
    table = doc.add_table(rows=rows, cols=cols)
    # 표 셀도 스타일 인자가 없으면 charPrIDRef="0"이 박혀 제목 크기가 샐 수 있다.
    # 문서 본문(바탕글) 글자속성을 셀 run에 적용해 크기 누수를 막는다.
    cell_char_ref = _default_body_char_pr(doc)
    payload = data or []
    for r in range(rows):
        row_cells = table.rows[r].cells
        row_data = (payload[r] or []) if r < len(payload) else []
        for c in range(cols):
            cell = row_cells[c]
            if c < len(row_data):
                cell.text = str(row_data[c])
            for cell_para in getattr(cell, "paragraphs", None) or []:
                _enforce_run_char_pr(cell_para, cell_char_ref)
    return len(list(_iter_tables(doc))) - 1


def get_table_data(doc: HwpxDocument, table_index: int) -> dict:
    """표의 모든 셀 텍스트를 2D 배열로 반환한다."""
    tables = list(_iter_tables(doc))
    if table_index < 0 or table_index >= len(tables):
        raise ValueError(f"유효하지 않은 table_index: {table_index}")
    table = tables[table_index]
    data = [[cell.text or "" for cell in row.cells] for row in table.rows]
    rows = len(data)
    cols = len(data[0]) if data else 0
    return {"rows": rows, "cols": cols, "data": data}


def get_table_map_in_doc(doc: HwpxDocument) -> dict:
    """문서의 표 메타데이터를 LLM 친화적인 JSON 형태로 반환한다."""
    result = doc.tables.map()
    tables = list(result.get("tables", []))
    return {"tables": tables, "count": len(tables)}


def find_cell_by_label_in_doc(doc: HwpxDocument, label_text: str, direction: str = "right") -> dict:
    """라벨 셀 기준으로 대상 셀을 찾는다."""
    return doc.tables.find_cell_by_label(label_text, direction=direction)


def fill_by_path_in_doc(doc: HwpxDocument, mappings: dict[str, str]) -> dict:
    """라벨 기반 경로 구문으로 표 셀을 채운다."""
    return doc.tables.fill_by_path(mappings)


def set_cell_text(
    doc: HwpxDocument,
    table_index: int,
    row: int,
    col: int,
    text: str,
    *,
    preserve_format: bool = True,
    split_paragraphs: bool = False,
) -> None:
    """표의 특정 셀 텍스트를 변경한다."""
    tables = list(_iter_tables(doc))
    if table_index < 0 or table_index >= len(tables):
        raise ValueError(f"유효하지 않은 table_index: {table_index}")
    table = tables[table_index]
    if row < 0 or row >= len(table.rows):
        raise ValueError(f"유효하지 않은 row: {row}")
    if col < 0 or col >= len(table.rows[row].cells):
        raise ValueError(f"유효하지 않은 col: {col}")
    try:
        table.set_cell_text(
            row,
            col,
            text or "",
            preserve_format=preserve_format,
            split_paragraphs=split_paragraphs,
        )
    except TypeError:
        table.rows[row].cells[col].text = text or ""

    cell = table.rows[row].cells[col]
    for paragraph in getattr(cell, "paragraphs", None) or []:
        repair_pathological_text_spacing(
            doc,
            paragraph=paragraph,
            fallback_char_pr_id=_default_body_char_pr(doc),
        )


def merge_cells_in_table(
    doc: HwpxDocument,
    table_index: int,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
) -> None:
    """표의 셀을 병합한다. python-hwpx 네이티브 API 사용."""
    tables = list(_iter_tables(doc))
    if table_index < 0 or table_index >= len(tables):
        raise ValueError(f"유효하지 않은 table_index: {table_index}")
    if start_row > end_row or start_col > end_col:
        raise ValueError("시작 좌표는 종료 좌표보다 작거나 같아야 합니다.")

    table = tables[table_index]
    table.merge_cells(start_row, start_col, end_row, end_col)


def split_cell_in_table(doc: HwpxDocument, table_index: int, row: int, col: int) -> dict:
    """병합된 셀을 분할한다. 원래 span 정보를 반환한다. python-hwpx 네이티브 API 사용."""
    tables = list(_iter_tables(doc))
    if table_index < 0 or table_index >= len(tables):
        raise ValueError(f"유효하지 않은 table_index: {table_index}")
    table = tables[table_index]
    if row < 0 or row >= len(table.rows):
        raise ValueError(f"유효하지 않은 row: {row}")
    if col < 0 or col >= len(table.rows[row].cells):
        raise ValueError(f"유효하지 않은 col: {col}")

    cell = table.rows[row].cells[col]
    span = cell.element.find(f"{_HP_NS}cellSpan")
    if span is None:
        return {"rowSpan": 1, "colSpan": 1}

    original = {
        "rowSpan": int(span.get("rowSpan", "1")),
        "colSpan": int(span.get("colSpan", "1")),
    }

    if original["rowSpan"] <= 1 and original["colSpan"] <= 1:
        return original

    table.split_merged_cell(row, col)
    return original


def _apply_table_border_fill(
    doc: HwpxDocument,
    table,
    border_type: str = None,
    border_color: str = None,
    border_width: str = None,
    fill_color: str = None,
    row: int = None,
    col: int = None,
) -> str:
    """테두리/음영 borderFill을 만들어 표 전체 또는 한 셀에 적용한다."""
    border_fill_id = doc.styles.ensure_border_fill(
        border_type=border_type or "SOLID",
        border_color=border_color or "#000000",
        border_width=border_width or "0.12 mm",
        fill_color=fill_color,
    )
    if row is not None:
        table.set_cell_border_fill(row, col, border_fill_id)
        return border_fill_id
    table.element.set("borderFillIDRef", str(border_fill_id))
    for table_row in table.rows:
        for cell in table_row.cells:
            cell.element.set("borderFillIDRef", str(border_fill_id))
    table.mark_dirty()
    return border_fill_id


def format_table_in_doc(
    doc: HwpxDocument,
    table_index: int,
    has_header_row: bool = None,
    border_type: str = None,
    border_color: str = None,
    border_width: str = None,
    fill_color: str = None,
    row: int = None,
    col: int = None,
) -> dict:
    """표 서식을 변경한다. 헤더 행 강조·테두리(선 종류/색/굵기)·셀 음영."""
    if (row is None) != (col is None):
        raise ValueError("row와 col은 함께 지정해야 합니다 (셀 단위 테두리 적용)")
    wants_border = any(
        value is not None for value in (border_type, border_color, border_width, fill_color)
    )
    if row is not None and not wants_border:
        raise ValueError("row/col 지정은 테두리·음영 파라미터와 함께 사용합니다")
    if has_header_row is None and not wants_border:
        return {}
    tables = list(_iter_tables(doc))
    if table_index < 0 or table_index >= len(tables):
        raise ValueError(f"유효하지 않은 table_index: {table_index}")
    table = tables[table_index]
    applied: dict = {}
    if wants_border:
        applied["border_fill_id"] = _apply_table_border_fill(
            doc,
            table,
            border_type=border_type,
            border_color=border_color,
            border_width=border_width,
            fill_color=fill_color,
            row=row,
            col=col,
        )
    if has_header_row is not None and table.rows:
        for cell in table.rows[0].cells:
            for paragraph in getattr(cell, "paragraphs", []):
                for run in paragraph.runs:
                    run.bold = bool(has_header_row)
    return applied


def copy_document_file(source: str, destination: str = None) -> str:
    """문서를 복사한다. destination이 None이면 자동 이름 생성."""
    if destination is None:
        stem, ext = source.rsplit(".", 1) if "." in source else (source, "hwpx")
        destination = f"{stem}_copy.{ext}"
    source_path = Path(source)
    destination_path = Path(destination)
    if is_hwp5_source(source_path) != is_hwp5_target(destination_path):
        # The destination extension picks the format, so a copy between .hwp
        # and .hwpx is written through the document model, not byte-copied.
        document = open_local_document(source_path, role="copy source")
        try:
            save_doc(document, str(destination_path))
        finally:
            document.close()
        return str(destination_path)
    if source_path.suffix.lower() != ".hwpx" and destination_path.suffix.lower() != ".hwpx":
        shutil.copy2(source_path, destination_path)
        return str(destination_path)

    _require_open_safe_hwpx(source_path, "source")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        suffix=destination_path.suffix or ".hwpx",
        dir=str(destination_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        os.close(tmp_fd)
        shutil.copy2(source_path, tmp_path)
        _require_open_safe_hwpx(tmp_path, "copied")
        os.replace(tmp_path, destination_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return str(destination_path)


def _require_open_safe_hwpx(path: Path, role: str) -> None:
    report = build_hwpx_open_safety_report(path)
    if not report["ok"]:
        raise ValueError(f"{role} HWPX failed open-safety verification: {report['summary']}")


# ── 메모 ──────────────────────────────────────────────

def _looks_like_mixed_xml_type_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        message = str(current)
        if "lxml.etree._Element" in message and "ElementTree.Element" in message:
            return True
        if "SubElement() argument 1 must be" in message and "xml.etree.ElementTree.Element" in message:
            return True
        current = current.__cause__
    return False


def _append_child_element(parent: Any, tag: str, attrs: dict[str, str] | None = None) -> Any:
    payload = dict(attrs or {})
    try:
        return ET.SubElement(parent, tag, payload)
    except TypeError:
        maker = getattr(parent, "makeelement", None)
        if not callable(maker):
            raise
        child = maker(tag, payload)
        parent.append(child)
        return child


def _make_element_like(parent: Any, tag: str, attrs: dict[str, str] | None = None) -> Any:
    payload = dict(attrs or {})
    maker = getattr(parent, "makeelement", None)
    if callable(maker):
        return maker(tag, payload)
    return ET.Element(tag, payload)


def _add_memo_with_anchor_fallback(paragraph: Any, text: str) -> None:
    section = paragraph.section
    section_element = section.element
    memo_group = section_element.find(f"{_HP_NS}memogroup")
    if memo_group is None:
        memo_group = _append_child_element(section_element, f"{_HP_NS}memogroup")

    memo_id = uuid4().hex[:10]
    memo_element = _append_child_element(memo_group, f"{_HP_NS}memo", {"id": memo_id})
    para_list = _append_child_element(memo_element, f"{_HP_NS}paraList")
    memo_para = _append_child_element(
        para_list,
        f"{_HP_NS}p",
        {
            "id": f"memo-{memo_id}-p",
            "paraPrIDRef": "0",
            "styleIDRef": "0",
            "pageBreak": "0",
            "columnBreak": "0",
            "merged": "0",
        },
    )

    char_ref = str(paragraph.char_pr_id_ref or "0")
    memo_run = _append_child_element(memo_para, f"{_HP_NS}run", {"charPrIDRef": char_ref})
    _append_child_element(memo_run, f"{_HP_NS}t").text = text

    field_id = uuid4().hex
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_begin = _make_element_like(paragraph.element, f"{_HP_NS}run", {"charPrIDRef": char_ref})
    ctrl_begin = _append_child_element(run_begin, f"{_HP_NS}ctrl")
    field_begin = _append_child_element(
        ctrl_begin,
        f"{_HP_NS}fieldBegin",
        {
            "id": field_id,
            "type": "MEMO",
            "editable": "true",
            "dirty": "false",
            "fieldid": field_id,
            "command": f"memoId={memo_id};",
        },
    )

    parameters = _append_child_element(field_begin, f"{_HP_NS}parameters", {"count": "5", "name": ""})
    _append_child_element(parameters, f"{_HP_NS}stringParam", {"name": "ID"}).text = memo_id
    _append_child_element(parameters, f"{_HP_NS}integerParam", {"name": "Number"}).text = "1"
    _append_child_element(parameters, f"{_HP_NS}stringParam", {"name": "CreateDateTime"}).text = created
    _append_child_element(parameters, f"{_HP_NS}stringParam", {"name": "Author"}).text = ""
    _append_child_element(parameters, f"{_HP_NS}stringParam", {"name": "MemoShapeID"}).text = ""

    sub_list = _append_child_element(
        field_begin,
        f"{_HP_NS}subList",
        {
            "id": f"memo-field-{memo_id}",
            "textDirection": "HORIZONTAL",
            "lineWrap": "BREAK",
            "vertAlign": "TOP",
        },
    )
    sub_para = _append_child_element(
        sub_list,
        f"{_HP_NS}p",
        {
            "id": f"memo-field-{memo_id}-p",
            "paraPrIDRef": "0",
            "styleIDRef": "0",
            "pageBreak": "0",
            "columnBreak": "0",
            "merged": "0",
        },
    )
    sub_run = _append_child_element(sub_para, f"{_HP_NS}run", {"charPrIDRef": char_ref})
    _append_child_element(sub_run, f"{_HP_NS}t").text = memo_id

    run_end = _make_element_like(paragraph.element, f"{_HP_NS}run", {"charPrIDRef": char_ref})
    ctrl_end = _append_child_element(run_end, f"{_HP_NS}ctrl")
    _append_child_element(ctrl_end, f"{_HP_NS}fieldEnd", {"beginIDRef": field_id, "fieldid": field_id})

    paragraph.element.insert(0, run_begin)
    paragraph.element.append(run_end)
    section.mark_dirty()


def _extract_memo_id_from_field_begin(field_begin: Any) -> str | None:
    command = (field_begin.get("command") or "")
    if "memoId=" in command:
        memo_id = command.split("memoId=", 1)[1].split(";", 1)[0].strip()
        if memo_id:
            return memo_id

    parameters = field_begin.find(f"{_HP_NS}parameters")
    if parameters is None:
        return None
    for item in parameters.findall(f"{_HP_NS}stringParam"):
        if (item.get("name") or "").strip().lower() != "id":
            continue
        memo_id = (item.text or "").strip()
        if memo_id:
            return memo_id
    return None


def _memo_anchor_runs(paragraph: Any, memo_ids: set[str]) -> list[Any]:
    if not memo_ids:
        return []

    field_ids: set[str] = set()
    runs_to_remove: list[Any] = []

    for run_element in list(paragraph.element.findall(f"{_HP_NS}run")):
        for ctrl in run_element.findall(f"{_HP_NS}ctrl"):
            field_begin = ctrl.find(f"{_HP_NS}fieldBegin")
            if field_begin is None:
                continue
            memo_id = _extract_memo_id_from_field_begin(field_begin)
            if memo_id not in memo_ids:
                continue
            field_id = (field_begin.get("id") or field_begin.get("fieldid") or "").strip()
            if field_id:
                field_ids.add(field_id)
            runs_to_remove.append(run_element)
            break

    if not field_ids:
        return runs_to_remove

    for run_element in list(paragraph.element.findall(f"{_HP_NS}run")):
        for ctrl in run_element.findall(f"{_HP_NS}ctrl"):
            field_end = ctrl.find(f"{_HP_NS}fieldEnd")
            if field_end is None:
                continue
            begin_id = (field_end.get("beginIDRef") or field_end.get("fieldid") or "").strip()
            if begin_id not in field_ids:
                continue
            runs_to_remove.append(run_element)
            break

    unique_runs: list[Any] = []
    seen: set[int] = set()
    for run_element in runs_to_remove:
        marker = id(run_element)
        if marker in seen:
            continue
        seen.add(marker)
        unique_runs.append(run_element)
    return unique_runs


def get_paragraph_text_from_doc(
    doc: HwpxDocument,
    paragraph_index: int | None = None,
    location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """본문 문단 또는 표 셀 문단 텍스트를 조회한다."""
    resolved = resolve_paragraph_reference(doc, paragraph_index=paragraph_index, location=location)
    return {"location": resolved.location, "text": resolved.paragraph.text or ""}


def add_memo_to_doc(
    doc: HwpxDocument,
    paragraph_index: int | None,
    text: str,
    location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """문단에 메모를 추가한다."""
    patch_python_hwpx()
    resolved = resolve_paragraph_reference(
        doc,
        paragraph_index=paragraph_index,
        location=location,
        create=True,
    )
    paragraph = resolved.paragraph
    memo_count_before = len(doc.notes.memos)
    try:
        doc.notes.add_memo(text or "", anchor=paragraph)
    except Exception as exc:  # noqa: BLE001
        if not _looks_like_mixed_xml_type_error(exc):
            raise
        # Clean up any partially-created memo from the failed native call
        current_memos = doc.notes.memos
        while len(current_memos) > memo_count_before:
            try:
                doc.notes.remove_memo(current_memos[-1])
            except Exception:  # noqa: BLE001
                break
            current_memos = doc.notes.memos
        logger.warning("메모 추가 중 혼합 XML 타입 충돌 감지, fallback 경로 사용: %s", exc)
        _add_memo_with_anchor_fallback(paragraph, text or "")
    return {"memo_added": True, "location": resolved.location}


def remove_memo_from_doc(
    doc: HwpxDocument,
    paragraph_index: int | None,
    location: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """문단의 메모를 제거한다."""
    patch_python_hwpx()
    resolved = resolve_paragraph_reference(doc, paragraph_index=paragraph_index, location=location)
    paragraph = resolved.paragraph

    memo_ids: set[str] = set()
    for run in paragraph.runs:
        for ctrl in run.element.findall(f"{_HP_NS}ctrl"):
            field_begin = ctrl.find(f"{_HP_NS}fieldBegin")
            if field_begin is None:
                continue
            memo_id = _extract_memo_id_from_field_begin(field_begin)
            if memo_id:
                memo_ids.add(memo_id)

    for memo in list(doc.notes.memos):
        if memo.id in memo_ids:
            doc.notes.remove_memo(memo)

    removed_anchor = False
    for run_element in _memo_anchor_runs(paragraph, memo_ids):
        paragraph.element.remove(run_element)
        removed_anchor = True
    if removed_anchor and paragraph.section is not None:
        paragraph.section.mark_dirty()
    return {"memo_removed": True, "location": resolved.location}


# ── 페이지 ────────────────────────────────────────────

def add_page_break_to_doc(doc: HwpxDocument) -> None:
    """문서 끝에 페이지 나누기를 추가한다."""
    doc.add_paragraph("", pageBreak="1")


# ── 텍스트 수집 ───────────────────────────────────────

def iter_all_paragraphs(doc: Any):
    for paragraph in doc.paragraphs:
        yield paragraph


def iter_table_texts(doc: Any):
    for table in _iter_tables(doc):
        for row in table.rows:
            for cell in row.cells:
                yield cell.text or ""


def collect_full_text(doc: Any) -> str:
    chunks: list[str] = []
    for paragraph in iter_all_paragraphs(doc):
        chunks.append(paragraph.text or "")
    for text in iter_table_texts(doc):
        if text:
            chunks.append(text)
    return "\n".join(chunks)
