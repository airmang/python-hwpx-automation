# SPDX-License-Identifier: Apache-2.0
"""텍스트 추가/치환 시 병적인 음수 자간이 새 내용에 전파되지 않는지 검증한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import hwpx_automation.server as server
from hwpx.tools.package_validator import validate_editor_open_safety
from hwpx_automation.core.document import open_doc, save_doc
from hwpx_automation.upstream import (
    HH_NS,
    HP_NS,
    append_xml_child,
    repair_pathological_text_spacing,
)


_SPACING_KEYS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")


def _char_pr_element(doc: Any, char_pr_id_ref: str | int):
    target = str(char_pr_id_ref)
    ref_list = doc.parts.headers[0].element.find(f"{HH_NS}refList")
    assert ref_list is not None
    char_properties = ref_list.find(f"{HH_NS}charProperties")
    assert char_properties is not None
    element = char_properties.find(f"{HH_NS}charPr[@id='{target}']")
    assert element is not None
    return element


def _spacing(doc: Any, char_pr_id_ref: str | int) -> dict[str, int]:
    element = _char_pr_element(doc, char_pr_id_ref)
    spacing = element.find(f"{HH_NS}spacing")
    assert spacing is not None
    return {key: int(spacing.get(key, "0")) for key in _SPACING_KEYS}


def _add_char_pr(doc: Any, *, spacing_value: int, preferred_id: str) -> str:
    def modifier(element):
        element.set("textColor", "#123456")
        spacing = element.find(f"{HH_NS}spacing")
        if spacing is None:
            spacing = append_xml_child(element, f"{HH_NS}spacing")
        for key in _SPACING_KEYS:
            spacing.set(key, str(spacing_value))

    element = doc.parts.headers[0].ensure_char_property(
        predicate=lambda _element: False,
        modifier=modifier,
        base_char_pr_id="0",
        preferred_id=preferred_id,
    )
    char_pr_id = element.get("id")
    assert char_pr_id
    return char_pr_id


def _append_paragraph(
    doc: Any,
    text: str,
    char_pr_id_ref: str,
    *,
    with_layout_cache: bool = False,
):
    paragraph = doc.add_paragraph(
        text,
        char_pr_id_ref=char_pr_id_ref,
        inherit_style=False,
    )
    if with_layout_cache:
        append_xml_child(paragraph.element, f"{HP_NS}lineSegArray")
    return paragraph


def _assert_open_safe(path: Path) -> None:
    report = validate_editor_open_safety(path)
    assert getattr(report, "ok", False), getattr(report, "issues", None)


def test_replace_remaps_only_touched_pathological_run(tmp_path: Path) -> None:
    target = tmp_path / "replace-overprint.hwpx"
    server.create_document(str(target))
    doc = open_doc(str(target))
    bad_ref = _add_char_pr(doc, spacing_value=-50, preferred_id="999")
    untouched = _append_paragraph(doc, "기존 압축 문구", bad_ref)
    replaced = _append_paragraph(doc, "${name}", bad_ref, with_layout_cache=True)
    save_doc(doc, str(target))

    result = server.search_and_replace(str(target), "${name}", "교체된 긴 본문은 겹치면 안 됩니다")

    assert result["replaced_count"] == 1
    assert result["openSafety"]["ok"] is True
    doc = open_doc(str(target))
    untouched = next(para for para in doc.paragraphs if para.text == "기존 압축 문구")
    replaced = next(para for para in doc.paragraphs if "교체된 긴 본문" in (para.text or ""))
    untouched_ref = str(untouched.runs[0].char_pr_id_ref)
    safe_ref = str(replaced.runs[0].char_pr_id_ref)

    assert untouched_ref == bad_ref
    assert safe_ref != bad_ref
    assert min(_spacing(doc, bad_ref).values()) == -50
    assert min(_spacing(doc, safe_ref).values()) > -40
    assert _char_pr_element(doc, safe_ref).get("textColor") == "#123456"
    assert not any(child.tag.rsplit("}", 1)[-1].lower() == "linesegarray" for child in replaced.element)
    _assert_open_safe(target)


def test_add_paragraph_repairs_inherited_pathological_spacing(tmp_path: Path) -> None:
    target = tmp_path / "add-overprint.hwpx"
    server.create_document(str(target))
    doc = open_doc(str(target))
    bad_ref = _add_char_pr(doc, spacing_value=-50, preferred_id="999")
    _append_paragraph(doc, "압축된 마지막 문구", bad_ref)
    save_doc(doc, str(target))

    result = server.add_paragraph(str(target), "추가된 긴 본문도 겹치면 안 됩니다")

    assert result["openSafety"]["ok"] is True
    doc = open_doc(str(target))
    previous = next(para for para in doc.paragraphs if para.text == "압축된 마지막 문구")
    added = next(para for para in doc.paragraphs if "추가된 긴 본문" in (para.text or ""))
    assert str(previous.runs[0].char_pr_id_ref) == bad_ref
    assert str(added.runs[0].char_pr_id_ref) != bad_ref
    assert min(_spacing(doc, added.runs[0].char_pr_id_ref).values()) > -40
    _assert_open_safe(target)


def test_replace_in_paragraph_repairs_pathological_spacing(tmp_path: Path) -> None:
    target = tmp_path / "replace-one-paragraph.hwpx"
    server.create_document(str(target))
    doc = open_doc(str(target))
    bad_ref = _add_char_pr(doc, spacing_value=-50, preferred_id="999")
    paragraph = _append_paragraph(doc, "항목: ${value}", bad_ref)
    paragraph_index = doc.paragraphs.index(paragraph)
    save_doc(doc, str(target))

    server.replace_in_paragraph(
        str(target),
        "${value}",
        "교체된 본문",
        paragraph_index=paragraph_index,
    )

    doc = open_doc(str(target))
    paragraph = doc.paragraphs[paragraph_index]
    assert paragraph.text == "항목: 교체된 본문"
    assert str(paragraph.runs[0].char_pr_id_ref) != bad_ref
    assert min(_spacing(doc, paragraph.runs[0].char_pr_id_ref).values()) > -40
    _assert_open_safe(target)


def test_set_cell_text_repairs_pathological_spacing(tmp_path: Path) -> None:
    target = tmp_path / "replace-cell-overprint.hwpx"
    server.create_document(str(target))
    server.add_table(str(target), 1, 1, [["${value}"]])
    doc = open_doc(str(target))
    bad_ref = _add_char_pr(doc, spacing_value=-50, preferred_id="999")
    table = next(table for paragraph in doc.paragraphs for table in paragraph.tables)
    table.rows[0].cells[0].paragraphs[0].runs[0].char_pr_id_ref = bad_ref
    save_doc(doc, str(target))

    server.set_table_cell_text(str(target), 0, 0, 0, "표 안의 교체 본문")

    doc = open_doc(str(target))
    table = next(table for paragraph in doc.paragraphs for table in paragraph.tables)
    run = table.rows[0].cells[0].paragraphs[0].runs[0]
    assert run.text == "표 안의 교체 본문"
    assert str(run.char_pr_id_ref) != bad_ref
    assert min(_spacing(doc, run.char_pr_id_ref).values()) > -40
    _assert_open_safe(target)


def test_insert_inherits_target_not_unrelated_last_paragraph(tmp_path: Path) -> None:
    target = tmp_path / "insert-neighbor-style.hwpx"
    server.create_document(str(target))
    doc = open_doc(str(target))
    safe_target = _append_paragraph(doc, "삽입 기준 문단", "0")
    bad_ref = _add_char_pr(doc, spacing_value=-50, preferred_id="999")
    _append_paragraph(doc, "문서 끝 압축 문단", bad_ref)
    target_index = doc.paragraphs.index(safe_target)
    save_doc(doc, str(target))

    server.insert_paragraph(str(target), target_index, "기준 문단 앞 삽입")

    doc = open_doc(str(target))
    inserted = next(para for para in doc.paragraphs if para.text == "기준 문단 앞 삽입")
    assert str(inserted.runs[0].char_pr_id_ref) == "0"
    assert str(inserted.runs[0].char_pr_id_ref) != bad_ref
    _assert_open_safe(target)


@pytest.mark.parametrize("spacing_value", [-37, -20, 0])
def test_replace_preserves_non_pathological_template_spacing(
    tmp_path: Path,
    spacing_value: int,
) -> None:
    target = tmp_path / f"preserve-spacing-{spacing_value}.hwpx"
    server.create_document(str(target))
    doc = open_doc(str(target))
    original_ref = _add_char_pr(doc, spacing_value=spacing_value, preferred_id="999")
    _append_paragraph(doc, "${value}", original_ref)
    save_doc(doc, str(target))

    server.search_and_replace(str(target), "${value}", "정상 범위 자간 유지")

    doc = open_doc(str(target))
    paragraph = next(para for para in doc.paragraphs if para.text == "정상 범위 자간 유지")
    assert str(paragraph.runs[0].char_pr_id_ref) == original_ref
    assert set(_spacing(doc, original_ref).values()) == {spacing_value}
    _assert_open_safe(target)


@pytest.mark.parametrize("fallback", [20, 85, 100])
def test_the_fallback_spacing_is_kept_up_to_the_engine_range(tmp_path: Path, fallback: int) -> None:
    """자간 is -50..100 (Hancom keeps 51..100 when it saves a file again; python-hwpx #801). The repair
    used to clip the fallback it copies at 50, so a paragraph set at +85 came back at +50."""

    target = tmp_path / "wide.hwpx"
    server.create_document(str(target))
    doc = open_doc(str(target))
    pathological = _add_char_pr(doc, spacing_value=-50, preferred_id="901")
    wide = _add_char_pr(doc, spacing_value=fallback, preferred_id="902")
    paragraph = _append_paragraph(doc, "겹쳐 찍히는 글", pathological)

    assert repair_pathological_text_spacing(doc, paragraph=paragraph, fallback_char_pr_id=wide) == 1

    repaired = str(paragraph.runs[-1].char_pr_id_ref)
    assert repaired != pathological
    assert set(_spacing(doc, repaired).values()) == {fallback}
    save_doc(doc, str(target))
    _assert_open_safe(target)

