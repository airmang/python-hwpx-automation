# SPDX-License-Identifier: Apache-2.0
"""Layout and style automation handlers for the optional MCP adapter."""

from __future__ import annotations

from typing import Any

from ..office.authoring.style_profile import (
    apply_style_profile_to_plan as apply_hwpx_style_profile_to_plan,
    compare_style_profiles as compare_hwpx_style_profiles,
    extract_style_profile as extract_hwpx_style_profile,
)

from ..core.content import (
    add_memo_to_doc,
    remove_memo_from_doc,
)
from ..core.document import open_doc
from ..core.formatting import (
    create_style_in_doc,
    format_text_range,
    list_styles_in_doc,
)
from ..core.locations import location_from_anchor
from ..utils.helpers import resolve_path
from ._shared import (
    _revision_guard,
    _save_doc_verification,
    _with_document_state,
    _with_dry_run_verification,
    _with_save_verification,
)


def extract_style_profile(filename: str) -> dict:
    """참조 HWPX의 페이지·폰트·표 프로파일을 plan 적용용 JSON으로 추출합니다."""
    if extract_hwpx_style_profile is None:
        raise RuntimeError("installed python-hwpx does not provide style profile tools")
    return extract_hwpx_style_profile(resolve_path(filename))


def apply_style_profile_to_plan(
    document_plan: dict,
    style_profile: dict = None,
    reference_filename: str = None,
    overwrite: bool = True,
) -> dict:
    """style_profile 또는 reference HWPX 서식을 document_plan v2에 적용합니다."""
    if apply_hwpx_style_profile_to_plan is None:
        raise RuntimeError("installed python-hwpx does not provide style profile tools")
    profile = style_profile
    if profile is None:
        if not reference_filename:
            raise ValueError("provide style_profile or reference_filename")
        if extract_hwpx_style_profile is None:
            raise RuntimeError(
                "installed python-hwpx does not provide style profile extraction"
            )
        profile = extract_hwpx_style_profile(resolve_path(reference_filename))
    return {
        "document_plan": apply_hwpx_style_profile_to_plan(
            document_plan or {},
            profile,
            overwrite=overwrite,
        ),
        "style_profile": profile,
        "next_tool": "create_document_from_plan",
    }


def compare_style_profiles(
    reference_filename: str = None,
    candidate_filename: str = None,
    reference_profile: dict = None,
    candidate_profile: dict = None,
    margin_tolerance_mm: float = 1.0,
    table_weight_tolerance: float = 0.10,
) -> dict:
    """참조/후보 HWPX 또는 style_profile의 페이지·표 프로파일 유사성을 비교합니다."""
    if compare_hwpx_style_profiles is None:
        raise RuntimeError(
            "installed python-hwpx does not provide style profile comparison"
        )
    reference = reference_profile or (
        resolve_path(reference_filename) if reference_filename else None
    )
    candidate = candidate_profile or (
        resolve_path(candidate_filename) if candidate_filename else None
    )
    if reference is None or candidate is None:
        raise ValueError("provide reference/candidate filenames or profiles")
    return compare_hwpx_style_profiles(
        reference,
        candidate,
        margin_tolerance_mm=margin_tolerance_mm,
        table_weight_tolerance=table_weight_tolerance,
    )


def _toc_format_guard(filename: str, path: str) -> dict | None:
    if str(path).lower().endswith((".hwpx", ".hwpxml")):
        return None
    return {
        "ok": False,
        "error": "native TOC/cross-reference tools support HWPX only",
        "filename": filename,
        "path": path,
        "errors": [
            {"code": "unsupported_format", "message": "HWPX(.hwpx)만 지원합니다"}
        ],
    }


def add_toc(
    filename: str,
    level: int = 2,
    leader: int = 3,
    hyperlink: bool = False,
    at_index: int = 0,
    dry_run: bool = False,
) -> dict:
    """개요 스타일 제목들로 한컴 네이티브 차례(TABLEOFCONTENTS 필드)를 삽입합니다.

    고정 텍스트 목차가 아니라 한컴이 인식·재계산하는 필드입니다. dirty=1로
    방출되므로 한컴이 처음 여는 순간 항목·스타일·쪽번호를 스스로 재계산합니다
    (방출 시점의 쪽번호는 추정치 — 응답의 cachedPagesAreEstimates 참조).
    본문 문단은 본문(스타일 1) 등 비수집 스타일이어야 항목으로 끌려가지
    않습니다(바탕글=스타일 0은 수집 대상)."""
    from hwpx.tools.toc_author import add_native_toc

    path = resolve_path(filename)
    guard = _toc_format_guard(filename, path)
    if guard is not None:
        return guard
    doc = open_doc(path)
    try:
        summary = add_native_toc(
            doc, at_index=at_index, level=level, leader=leader, hyperlink=hyperlink
        )
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "hint": "개요 1~10 스타일의 제목 문단이 필요합니다 (add_heading 사용)",
            "errors": [{"code": "no_outline_headings", "message": str(exc)}],
        }
    if dry_run:
        return _with_dry_run_verification(
            {"ok": True, "dryRun": True, **summary}, doc, path
        )
    verification = _save_doc_verification(doc, path)
    return _with_save_verification({"ok": True, **summary}, verification)


def add_cross_reference(
    filename: str,
    paragraph_index: int,
    target_heading_text: str,
    cached_page: int = 1,
    dry_run: bool = False,
) -> dict:
    """지정 문단 끝에 특정 제목의 '쪽 번호' 상호참조(CROSSREF 필드)를 추가합니다.

    캐시 쪽번호는 추정치여도 됩니다 — 한컴이 문서를 열거나 편집/저장할 때
    자동으로 재계산합니다(실측 의미론)."""
    from hwpx.tools.toc_author import add_page_crossref

    path = resolve_path(filename)
    guard = _toc_format_guard(filename, path)
    if guard is not None:
        return guard
    doc = open_doc(path)
    paragraphs = [p for s in doc.sections for p in s.paragraphs]
    if not (0 <= paragraph_index < len(paragraphs)):
        return {
            "ok": False,
            "error": f"paragraph_index {paragraph_index} out of range (total {len(paragraphs)})",
            "errors": [
                {
                    "code": "paragraph_index_out_of_range",
                    "message": str(paragraph_index),
                }
            ],
        }
    needle = target_heading_text.strip()
    target = next((p for p in paragraphs if (p.text or "").strip() == needle), None)
    if target is None:
        target = next(
            (p for p in paragraphs if needle and needle in (p.text or "")), None
        )
    if target is None:
        return {
            "ok": False,
            "error": f"target heading not found: {target_heading_text!r}",
            "errors": [{"code": "target_not_found", "message": target_heading_text}],
        }
    result = add_page_crossref(
        doc, paragraphs[paragraph_index], target, cached_page=cached_page
    )
    if dry_run:
        return _with_dry_run_verification(
            {"ok": True, "dryRun": True, **result}, doc, path
        )
    verification = _save_doc_verification(doc, path)
    return _with_save_verification({"ok": True, **result}, verification)


def verify_toc(
    filename: str,
    refresh: bool = False,
    verify_render: bool = False,
) -> dict:
    """네이티브 차례/상호참조의 캐시 쪽번호를 검증합니다.

    verify_render=True면 실제 한컴 렌더로 캐시 vs 실제 페이지를 대조해
    toc_correctness_ratio를 산출합니다(오라클 없으면 정직하게 unverified).
    refresh=True면 검증 전에 한컴을 열어 dirty 필드를 재계산·저장합니다
    (macOS GUI 오라클 필요; dirty 재생성 직후 같은 세션 렌더는 이 한컴
    빌드가 크래시하므로 refresh와 render는 별도 세션으로 수행됩니다)."""
    from hwpx.tools.toc_fidelity import structural_report, toc_verify

    path = resolve_path(filename)
    guard = _toc_format_guard(filename, path)
    if guard is not None:
        return guard

    oracle = None
    refreshed = None
    if refresh or verify_render:
        try:
            from ..office.rendering import resolve_hancom_oracle

            oracle = resolve_hancom_oracle()
        except Exception:  # pragma: no cover - oracle stack unavailable
            oracle = None
    if refresh:
        refresher = getattr(oracle, "refresh_document", None)
        refreshed = bool(refresher and refresher(path))

    if verify_render and oracle is not None and oracle.available():
        # Core matches headings but does not read PDFs; the imaging stack is
        # this layer's, so the extractor is injected alongside the oracle.
        from ..office.form_fill.fit.wordbox import extract_word_boxes

        report = toc_verify(path, oracle=oracle, extract=extract_word_boxes)
    else:
        structural = structural_report(path)
        report = {
            "structural": structural,
            "render_checked": False,
            "toc_correctness_ratio": None,
            "stale_entries": [],
            "crossref_correctness_ratio": None,
            "verdict": (
                "stale_detected_structurally"
                if not structural["internally_consistent"]
                else "unverified"
            ),
        }
    if refreshed is not None:
        report["refreshed"] = refreshed
    report["ok"] = report["verdict"] in ("verified", "unverified")
    return report


def set_paragraph_format(
    filename: str,
    paragraph_index: int | None = None,
    paragraph_indexes: list[int] | None = None,
    alignment: str | None = None,
    line_spacing_percent: float | None = None,
    indent_left_mm: float | None = None,
    indent_right_mm: float | None = None,
    first_line_indent_mm: float | None = None,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
    outline_level: int | None = None,
    keep_with_next: bool | None = None,
    keep_lines: bool | None = None,
    page_break_before: bool | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """기존 문단의 정렬, 줄간격(%), 들여쓰기(mm), 문단 간격(pt), 개요 수준을 변경합니다.

    keep_with_next/keep_lines/page_break_before로 문단의 keep-together(다음 문단과
    붙임·문단 줄바꿈 금지·앞에서 쪽 나눔) 플래그를 설정합니다 — 시험지 조판 등에서
    한 문항이 단/쪽 경계에서 잘리지 않게 할 때 씁니다.
    """
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    # apply_paragraph_format now returns a frozen ParagraphFormatResult
    # (design §2.4) rather than a dict — .to_dict() keeps this handler's own
    # dict-shaped response (filename merged below) unchanged.
    result = doc.styles.apply_paragraph_format(
        paragraph=paragraph_index,
        paragraphs=paragraph_indexes,
        alignment=alignment,
        line_spacing=line_spacing_percent,
        indent_left_mm=indent_left_mm,
        indent_right_mm=indent_right_mm,
        first_line_indent_mm=first_line_indent_mm,
        spacing_before_pt=spacing_before_pt,
        spacing_after_pt=spacing_after_pt,
        outline_level=outline_level,
        keep_with_next=keep_with_next,
        keep_lines=keep_lines,
        page_break_before=page_break_before,
    ).to_dict()
    result["filename"] = filename
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def set_page_setup(
    filename: str,
    paper_size: str | None = None,
    width_mm: float | None = None,
    height_mm: float | None = None,
    orientation: str | None = None,
    margins_mm: dict[str, float] | None = None,
    margin_left_mm: float | None = None,
    margin_right_mm: float | None = None,
    margin_top_mm: float | None = None,
    margin_bottom_mm: float | None = None,
    header_margin_mm: float | None = None,
    footer_margin_mm: float | None = None,
    gutter_mm: float | None = None,
    columns: int | None = None,
    column_gap_mm: float | None = None,
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """용지/방향/여백을 mm 단위로 설정하고 선택적으로 단 구성을 적용합니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    # page.setup now returns a frozen PageSetup (design §2.4) rather than a
    # dict — .to_dict() keeps this handler's own dict-shaped response
    # (filename merged below) unchanged.
    result = doc.page.setup(
        paper_size=paper_size,
        width_mm=width_mm,
        height_mm=height_mm,
        orientation=orientation,
        margins_mm=margins_mm,
        margin_left_mm=margin_left_mm,
        margin_right_mm=margin_right_mm,
        margin_top_mm=margin_top_mm,
        margin_bottom_mm=margin_bottom_mm,
        header_margin_mm=header_margin_mm,
        footer_margin_mm=footer_margin_mm,
        gutter_mm=gutter_mm,
        columns=columns,
        column_gap_mm=column_gap_mm,
        section=section_index,
    ).to_dict()
    result["filename"] = filename
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def _header_footer_payload(
    wrapper: Any, *, kind: str, page_type: str
) -> dict[str, Any]:
    return {
        "kind": kind,
        "pageType": page_type,
        "id": getattr(wrapper, "id", None),
        "text": getattr(wrapper, "text", ""),
        "pageNumberCount": _page_number_count(wrapper),
    }


def _page_number_count(story: Any) -> int:
    """머리말·꼬리말 안(칸·글상자 속 문단까지)의 쪽 번호 컨트롤(``run.content``의 ``page_number``) 수."""

    count = 0
    for paragraph in getattr(story, "paragraphs", None) or ():
        for inner in (paragraph, *(place.paragraph for place in paragraph.iter_paragraphs())):
            for run in inner.runs:
                count += sum(1 for item in run.content if item.kind == "page_number")
    return count


def set_header_footer(
    filename: str,
    kind: str,
    text: str | None = None,
    content: list[dict[str, Any]] | None = None,
    section_index: int | None = None,
    page_type: str = "BOTH",
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """머리글 또는 바닥글을 텍스트나 rich content spec으로 추가/수정합니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    # set_header_footer is demoted in 6.0 with no namespace replacement
    # (design table row 102, kind= dispatch removed) — dispatch here
    # instead, replicating the normalization the removed method used to do.
    normalized_kind = kind.strip().lower() if isinstance(kind, str) else kind
    if normalized_kind == "header":
        wrapper = doc.page.set_header(
            text=text,
            content=content,
            section=section_index,
            page_type=page_type,
        )
    elif normalized_kind == "footer":
        wrapper = doc.page.set_footer(
            text=text,
            content=content,
            section=section_index,
            page_type=page_type,
        )
    else:
        raise ValueError("kind must be 'header' or 'footer'")
    result = {
        "filename": filename,
        "headerFooter": _header_footer_payload(wrapper, kind=kind, page_type=page_type),
    }
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def set_page_number(
    filename: str,
    target: str = "footer",
    page_type: str = "BOTH",
    format: str = "page",
    align: str = "CENTER",
    position: str = "BOTTOM_CENTER",
    prefix: str = "",
    suffix: str = "",
    format_type: str | None = None,
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """머리글/바닥글에 자동 쪽번호 필드를 추가하거나 수정합니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    wrapper = doc.page.set_page_number(
        target=target,
        page_type=page_type,
        format=format,
        alignment=align,
        position=position,
        prefix=prefix,
        suffix=suffix,
        format_type=format_type,
        section=section_index,
    )
    result = {
        "filename": filename,
        "target": target,
        "format": format,
        "headerFooter": _header_footer_payload(
            wrapper, kind=target, page_type=page_type
        ),
    }
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def set_list_format(
    filename: str,
    paragraph_index: int | None = None,
    paragraph_indexes: list[int] | None = None,
    kind: str = "bullet",
    level: int = 1,
    bullet_char: str | None = None,
    number_format: str | None = None,
    start: int | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """기존 문단에 불릿 또는 번호 목록 서식을 적용합니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    # apply_list_format now returns a frozen ListFormatResult (design §2.4)
    # rather than a dict — .to_dict() keeps this handler's own dict-shaped
    # response (filename merged below) unchanged.
    result = doc.styles.apply_list_format(
        paragraph=paragraph_index,
        paragraphs=paragraph_indexes,
        kind=kind,
        level=level,
        bullet_char=bullet_char,
        number_format=number_format,
        start=start,
    ).to_dict()
    result["filename"] = filename
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def add_memo(
    filename: str,
    paragraph_index: int | None = None,
    text: str = "",
    location: dict[str, Any] | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """본문 문단 또는 표 셀 문단에 메모를 추가합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    result = add_memo_to_doc(doc, paragraph_index, text, location=location)
    if result["location"].get("kind") == "body_paragraph":
        result["paragraph_index"] = result["location"]["paragraph_index"]
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def add_memo_by_anchor(
    filename: str,
    anchor: dict[str, Any] | str,
    text: str,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """find_text가 반환한 anchor로 메모 위치를 지정해 메모를 추가합니다."""
    return add_memo(
        filename,
        text=text,
        location=location_from_anchor(anchor),
        dry_run=dry_run,
        expected_revision=expected_revision,
    )


def remove_memo(
    filename: str,
    paragraph_index: int | None = None,
    location: dict[str, Any] | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """본문 문단 또는 표 셀 문단의 메모를 제거합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    result = remove_memo_from_doc(doc, paragraph_index, location=location)
    if result["location"].get("kind") == "body_paragraph":
        result["paragraph_index"] = result["location"]["paragraph_index"]
    if not result["memo_removed"]:
        # No memo on that paragraph: the document is the same, so it is not written again
        # (a write would move the backups up and undo_last_edit would lose the edit before).
        result["dryRun"] = bool(dry_run)
        return _with_document_state(result, path)
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def format_text(
    filename: str,
    paragraph_index: int,
    start_pos: int,
    end_pos: int,
    bold: bool = None,
    italic: bool = None,
    underline: bool = None,
    font_size: float = None,
    font_name: str = None,
    color: str = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """지정 범위 텍스트 서식을 변경합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    format_text_range(
        doc,
        paragraph_index,
        start_pos,
        end_pos,
        bold=bold,
        italic=italic,
        underline=underline,
        font_size=font_size,
        font_name=font_name,
        color=color,
    )
    result = {
        "formatted": True,
        "paragraph_index": paragraph_index,
        "range": [start_pos, end_pos],
    }
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def create_custom_style(
    filename: str,
    style_name: str,
    bold: bool = None,
    italic: bool = None,
    font_size: float = None,
    font_name: str = None,
    color: str = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """문서에 커스텀 스타일을 생성합니다. dry_run=True이면 원본을 저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    result = create_style_in_doc(
        doc,
        style_name,
        bold=bold,
        italic=italic,
        font_size=font_size,
        font_name=font_name,
        color=color,
    )
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def list_styles(filename: str) -> dict:
    """문서에 정의된 스타일 목록을 조회합니다."""
    path = resolve_path(filename)
    doc = open_doc(path)
    styles = list_styles_in_doc(doc)
    return {"styles": styles, "count": len(styles)}


__all__ = [
    "list_styles",
    "create_custom_style",
    "set_paragraph_format",
    "set_list_format",
    "format_text",
    "extract_style_profile",
    "apply_style_profile_to_plan",
    "compare_style_profiles",
    "set_page_setup",
    "set_header_footer",
    "set_page_number",
    "add_toc",
    "add_cross_reference",
    "verify_toc",
    "add_memo",
    "add_memo_by_anchor",
    "remove_memo",
]
