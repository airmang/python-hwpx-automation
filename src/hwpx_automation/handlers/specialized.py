# SPDX-License-Identifier: Apache-2.0
"""Stateless specialized automation handlers for the optional MCP adapter."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal, cast

from ..core.content import (
    collect_full_text,
)
from ..core.document import open_doc
from ..office.authoring.advanced_generators import (
    build_image_grid as build_hwpx_image_grid,
)
from ..office.authoring.advanced_generators import (
    build_meeting_nameplates as build_hwpx_meeting_nameplates,
)
from ..office.authoring.advanced_generators import (
    build_organization_chart as build_hwpx_organization_chart,
)
from ..office.compliance import DEFAULT_POLICY, detect_pii, mask_value
from ..office.house_style import load_bank, load_genres
from ..office.house_style.composition import (
    compose_section_chip as compose_house_section_chip,
)
from ..office.house_style.gianmun import (
    HIDDEN_LABELS as HOUSE_HIDDEN_LABELS,
    SHOWN_LABELS as HOUSE_SHOWN_LABELS,
    compose_official_draft as compose_house_official_draft,
    compose_simple_draft as compose_house_simple_draft,
)
from ..office.house_style.org_chart import lower_boxed_org_chart
from ..office.document_ops import (
    build_mail_merge as build_hwpx_mail_merge,
)
from ..office.document_ops import (
    inspect_mail_merge_placeholders as inspect_hwpx_mail_merge_placeholders,
)
from ..office.exam import (
    ExamParseError,
    FormProfileError,
    compose_exam_into_form,
    measure_question_splits,
)
from ..office.form_fill.fit import FitPolicy as _FitPolicy
from ..office.form_fill.fit import seal as seal_ops
from ..office.form_fill.fit.wordbox import (
    OracleUnavailable,
    extract_image_boxes,
    render_glyph_boxes,
)
from ..office.rendering import NullOracle
from ..office.rendering import resolve_hancom_oracle as resolve_oracle
from ..storage import (
    build_hwpx_open_safety_report,
)
from ..utils.helpers import resolve_path
from ._shared import (
    _decode_image_base64,
    _id_integrity_payload,
    _revision_guard,
    _save_doc_verification,
    _with_dry_run_verification,
    _with_save_verification,
)

# Retain the established handler-module binding used by ownership consumers.
FitPolicy = _FitPolicy


def inspect_mail_merge_placeholders(filename: str) -> dict:
    """메일머지 템플릿의 placeholder key를 확인합니다."""
    if inspect_hwpx_mail_merge_placeholders is None:
        raise RuntimeError("installed python-hwpx does not provide mail merge tools")
    return inspect_hwpx_mail_merge_placeholders(resolve_path(filename))


def _mail_merge_data_source(
    data_rows: list | dict | None, data_filename: str | None
) -> Any:
    if data_rows is not None:
        return data_rows
    if data_filename:
        return resolve_path(data_filename)
    raise ValueError("provide data_rows or data_filename")


def _mail_merge_open_safety_summary(report: dict) -> dict:
    row_reports = list(report.get("rows") or [])
    checked = 0
    failures: list[dict[str, Any]] = []
    for row in row_reports:
        open_safety = row.get("openSafety")
        if not isinstance(open_safety, dict):
            continue
        checked += 1
        if not bool(open_safety.get("ok")):
            failures.append(
                {
                    "rowIndex": row.get("rowIndex"),
                    "filename": row.get("filename"),
                    "summary": open_safety.get("summary"),
                }
            )
    return {
        "ok": checked == int(report.get("createdCount", 0)) and not failures,
        "checkedCount": checked,
        "failureCount": len(failures),
        "failures": failures,
    }


def mail_merge(
    template_filename: str,
    data_rows: list | dict = None,  # type: ignore[assignment]  # Frozen ToolSpec default.
    data_filename: str = None,
    output_dir: str = None,
    filename_pattern: str = "{index:03d}.hwpx",
    zip_filename: str = None,
    strict: bool = False,
    split_newlines: bool = True,
    fit_mode: str | None = None,
    max_lines: int = 1,
) -> dict:
    """템플릿 HWPX와 CSV/JSON/XLSX(명부)/rows 데이터로 N부를 생성합니다.

    ``fit_mode`` (keep·wrap·shrink·wrap_then_shrink·expand_row·truncate_with_report·
    fail_on_overflow)를 주면 **fit-aware** 배치가 됩니다: 각 placeholder 슬롯을 템플릿에서
    한 번 측정(template-once-measure)하고, 슬롯을 넘치거나 필수값이 빠진 레코드를
    ``needsReview[]``/``skipped[]`` 로 격리합니다(나머지 배치는 안전). zip/openSafety
    evidence 동봉.
    """
    if build_hwpx_mail_merge is None:
        raise RuntimeError("installed python-hwpx does not provide mail merge tools")
    data_source = _mail_merge_data_source(data_rows, data_filename)
    report = build_hwpx_mail_merge(
        resolve_path(template_filename),
        data_source,
        output_dir=resolve_path(output_dir) if output_dir else None,
        filename_pattern=filename_pattern,
        zip_path=resolve_path(zip_filename) if zip_filename else None,
        strict=strict,
        split_newlines=split_newlines,
        fit_mode=fit_mode,
        max_lines=max_lines,
    )
    open_safety = _mail_merge_open_safety_summary(report)
    report["openSafety"] = open_safety
    report["verification"] = {
        "openSafety": open_safety,
        "createdCount": report.get("createdCount", 0),
        "rowCount": report.get("rowCount", 0),
        "rowsWithIssues": report.get("rowsWithIssues", []),
        "zip": report.get("zip"),
    }
    return report


def _single_block_plan(block: dict, *, title: str = "") -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v2",
        "title": title,
        "sections": [{"blocks": [block]}],
    }


def build_image_grid(
    images: list,
    columns: int = 2,
    image_width_mm: float = None,
    title: str = "사진대지",
) -> dict:
    """사진 목록을 plan v2 image_grid block과 생성 가능한 document_plan으로 변환합니다."""
    if build_hwpx_image_grid is None:
        raise RuntimeError(
            "installed python-hwpx does not provide image_grid generator"
        )
    block = build_hwpx_image_grid(
        images or [],
        columns=columns,
        image_width_mm=image_width_mm,
    )
    return {
        "block": block,
        "document_plan": _single_block_plan(block, title=title),
        "next_tool": "create_document_from_plan",
    }


def build_meeting_nameplates(
    names: list[str],
    size: str = "150x70",
    columns: int = 2,
    title: str = "회의 명패",
) -> dict:
    """참석자 명단을 회의 명패 table block과 document_plan으로 변환합니다."""
    if build_hwpx_meeting_nameplates is None:
        raise RuntimeError(
            "installed python-hwpx does not provide meeting nameplate generator"
        )
    block = build_hwpx_meeting_nameplates(names or [], size=size, columns=columns)
    return {
        "block": block,
        "document_plan": _single_block_plan(block, title=title),
        "next_tool": "create_document_from_plan",
    }


def build_organization_chart(
    hierarchy: dict | list,
    max_depth: int = 3,
    title: str = "조직도",
) -> dict:
    """2~3단 계층 데이터를 표 기반 조직도 block과 document_plan으로 변환합니다."""
    if build_hwpx_organization_chart is None:
        raise RuntimeError(
            "installed python-hwpx does not provide organization chart generator"
        )
    block = build_hwpx_organization_chart(hierarchy or {}, max_depth=max_depth)
    return {
        "block": block,
        "document_plan": _single_block_plan(block, title=title),
        "next_tool": "create_document_from_plan",
    }


def add_boxed_org_chart(
    filename: str,
    hierarchy: dict,
    accent_color: str = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """계층 트리를 실물 관례의 박스 조직도(표 캔버스+병합 박스+셀 테두리
    커넥터)로 문서 끝에 그립니다. 각 노드는 {"label", "sublabel"?,
    "children"?[]} 매핑이며 깊이 4·박스 40 초과는 typed 거부.
    accent_color는 루트 박스 배경색. dry_run=True이면 저장하지 않습니다."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    doc = open_doc(path)
    summary = lower_boxed_org_chart(doc, hierarchy or {}, accent_color=accent_color)
    result = {"orgChart": summary}
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    verification = _save_doc_verification(doc, path)
    return _with_save_verification(result, verification)


def compose_official_draft(plan: dict) -> dict:
    """일반기안문(별지 제1호서식)을 범용 document_plan block으로 합성합니다.

    「행정업무의 운영 및 혁신에 관한 규정 시행규칙」 별지 제1호서식의 공개
    구조를 두문/본문/결문 순서로 낮춥니다. 파일은 쓰지 않습니다 — 반환 blocks를
    document_plan에 넣어 create_document_from_plan으로 생성하십시오.

    규정에서 오는 계약 3가지: ①결재란 칸 수는 approvers 목록 길이입니다
    (규칙 제7조제4항 — 서명·전결 표시를 하지 않는 사람의 서명란은 만들지
    않습니다). ②행정기관명·발신명·기안자/검토자/결재권자·직위(직급) 서명·
    주소·공개 구분 등의 용어(라벨)는 인쇄하지 않고 값만 적습니다(서식 비고).
    ③선택 항목에 체크박스 개체를 쓰지 않습니다 — 별표 4 제10호가 `[  ]`+√
    텍스트를 규정합니다. 내부결재문서는 internal_only=true로 발신명의를
    생략합니다."""
    blocks = compose_house_official_draft(plan)
    return {
        "blocks": blocks,
        "genre": "official_draft",
        "next_tool": "validate_document_plan",
        "labelPolicy": {
            "hidden": list(HOUSE_HIDDEN_LABELS),
            "shown": list(HOUSE_SHOWN_LABELS),
        },
    }


def compose_simple_draft(plan: dict) -> dict:
    """간이기안문(별지 제2호서식)을 범용 document_plan block으로 합성합니다.

    보고서·계획서·검토서 등 발신할 필요가 없는 **내부결재문서 전용**입니다
    (규칙 제3조제3항 — 시행문으로 변환할 수 없습니다). 일반기안문과 달리
    두문·발신명의·시행/접수·주소가 없고, 문서등록 블록과 결재란이 상단에,
    제목·(선택)요약설명문·작성일·작성기관이 그 아래 중앙에 옵니다. 결재란 칸
    수는 approvers 목록 길이입니다(규칙 제7조제4항)."""
    blocks = compose_house_simple_draft(plan)
    return {
        "blocks": blocks,
        "genre": "simple_draft",
        "next_tool": "validate_document_plan",
    }


def compose_section_chip(
    number: str,
    title: str,
    style: str = "box",
    accent_color: str = None,
) -> dict:
    """운영계획 장르의 섹션 구분자(섹션칩)를 범용 document_plan block으로
    합성합니다. style="box"(1×3 accent 칩) 또는 "inline"(번호 제목 헤딩).
    파일은 쓰지 않습니다 — 반환 block을 document_plan에 끼워 넣으십시오."""
    if style not in ("box", "inline"):
        raise ValueError('style must be "box" or "inline"')
    chip_style = cast('Literal["box", "inline"]', style)
    block = compose_house_section_chip(
        number, title, style=chip_style, accent_color=accent_color
    )
    return {"block": block, "next_tool": "validate_document_plan"}


def get_genre_grammar(genre: str) -> dict:
    """장르 구조 문법·타이포 역할(하우스 스타일 뱅크)을 반환하는 read-only
    조회입니다. 스킬이 per-문서 인스턴스화(번호 체계·칩 렌더·블록 선택·색)
    판단에 사용합니다. 미보유 장르는 사용 가능 목록과 함께 typed 거부."""
    catalog = load_genres()
    genres = catalog.genres if hasattr(catalog, "genres") else {}
    if genre not in genres:
        raise ValueError(
            f"unknown genre {genre!r}; available: {sorted(genres)}"
        )
    bank = load_bank()
    entry = genres[genre]
    payload = entry if isinstance(entry, dict) else entry.model_dump()
    inherits = None
    typography = payload.get("typography") if isinstance(payload, dict) else None
    if isinstance(typography, dict):
        inherits = typography.get("inherits")
    profiles = bank.profiles if hasattr(bank, "profiles") else {}
    inherited_profile = None
    if inherits and inherits in profiles:
        base = profiles[inherits]
        inherited_profile = base if isinstance(base, dict) else base.model_dump()
    return {
        "genre": genre,
        "grammar": payload,
        "inheritedProfile": {"name": inherits, "profile": inherited_profile}
        if inherited_profile
        else None,
        "sectionChipTool": "compose_section_chip",
        "orgChartTool": "add_boxed_org_chart",
    }


def scan_personal_info(filename: str | None = None, text: str | None = None) -> dict:
    """문서/텍스트의 개인정보(PII)를 탐지하는 read-only 감사 (원본값 미노출).

    기계검증 세트(주민등록번호·휴대폰·이메일·카드)는 항상 high-confidence, 맥락형(계좌·주소·이름)은
    라벨 게이트 low-confidence. 반환은 유형별 건수 + **마스킹된 예시만** — 원본 PII는 절대 반환하지 않습니다.
    마스킹은 따로 하지 않고 이 도구는 탐지/감사만 합니다(마스킹은 fill/merge/extract 도구의 `mask` 기본 ON).
    """
    if text is None:
        if not filename:
            return {"error": "filename 또는 text 중 하나가 필요합니다."}
        text = collect_full_text(open_doc(resolve_path(filename)))
    spans = detect_pii(text or "", DEFAULT_POLICY)
    by_type: dict[str, dict] = {}
    for span in spans:
        kind = span["type"]
        bucket = by_type.setdefault(
            kind,
            {
                "type": kind,
                "confidence": span["confidence"],
                "count": 0,
                "maskedExamples": [],
            },
        )
        bucket["count"] += 1
        if len(bucket["maskedExamples"]) < 3:
            bucket["maskedExamples"].append(
                mask_value(span["value"], kind, DEFAULT_POLICY)
            )
    return {
        "report_version": "pii-scan-v1",
        "total": len(spans),
        "byType": list(by_type.values()),
        "machineSet": ["rrn", "phone", "email", "card"],
        "note": "기계세트=high-confidence 항상 탐지; 맥락형(account/address/name)=라벨게이트 low-confidence. 원본값 미반환(마스킹 예시만).",
    }


def _nearest_rect(rects: list, center: tuple[float, float]):
    cx, cy = center
    return min(
        rects,
        key=lambda r: ((r.x0 + r.x1) / 2 - cx) ** 2 + ((r.y0 + r.y1) / 2 - cy) ** 2,
    )


def _check_seal_compliance_impl(
    path: str,
    sender_text: str,
    *,
    tol_pt: float,
    expected_center: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Render *path* via the Hancom oracle and decide the 직인 rule (pass/fail).

    The seal is a picture, so it is located with ``extract_image_boxes`` (not text);
    the 발신명의 anchor is found in the same render. Degrades to
    ``renderChecked=False`` when no oracle is reachable — never a silent pass.
    """

    fd, pdf = tempfile.mkstemp(prefix="seal_verify_", suffix=".pdf")
    os.close(fd)
    try:
        boxes, _sizes, backend = render_glyph_boxes(path, out_pdf=pdf)
        seal_rects = extract_image_boxes(pdf)
    except OracleUnavailable as exc:
        return {
            "ok": False,
            "renderChecked": False,
            "note": "한컴 오라클이 없어 직인 배치를 검증할 수 없습니다.",
            "reason": str(exc),
        }
    finally:
        try:
            os.unlink(pdf)
        except OSError:
            pass

    if not seal_rects:
        return {
            "ok": False,
            "renderChecked": True,
            "note": "렌더에 직인 이미지가 없습니다 (isEmbeded 누락 또는 미배치).",
        }
    anchor = seal_ops.find_seal_anchor(boxes, sender_text)
    center = expected_center or (anchor.center if anchor is not None else None)
    seal_rect = (
        _nearest_rect(seal_rects, center) if center is not None else seal_rects[-1]
    )
    verdict = seal_ops.check_seal_placement(
        boxes, seal_rect, sender_text, tol_pt=tol_pt
    )
    out: dict[str, Any] = {"ok": verdict.ok, "renderChecked": True, "backend": backend}
    out.update(verdict.to_dict())
    return out


def place_seal(
    filename: str,
    sender_text: str,
    image_base64: str,
    image_format: str = "png",
    seal_width_mm: float = 25.0,
    seal_height_mm: float | None = None,
    anchor_x: float | None = None,
    anchor_y: float | None = None,
    anchor_page: int | None = None,
    verify: bool = True,
    tol_pt: float = 6.0,
    output: str | None = None,
    dry_run: bool = False,
    expected_revision: str = None,
) -> dict:
    """발신명의(issuer line) 끝글자에 직인/관인을 floating으로 찍습니다 (FR-003).

    한컴 렌더 오라클로 발신명의 위치(앵커)를 찾아 직인을 그 위에 스탬프합니다
    (textWrap=IN_FRONT_OF_TEXT — 겹친 글자를 밀지 않음). 오라클이 없으면 ``anchor_x``/
    ``anchor_y`` 로 PDF 포인트 앵커를 직접 지정할 수 있고, 둘 다 없으면
    ``renderChecked=false`` 로 정직하게 degrade 합니다(임의 배치 금지). ``verify=True``
    이면 저장 후 재렌더로 직인이 발신명의에 규칙대로 찍혔는지 검증합니다.
    """
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        return guard
    target_path = resolve_path(output) if output else path
    image_data = _decode_image_base64(image_base64)

    # 1) locate the 발신명의 anchor — explicit override, else the render oracle.
    if anchor_x is not None and anchor_y is not None:
        anchor_center = (float(anchor_x), float(anchor_y))
        anchor_page_resolved = anchor_page
        anchor_source = "explicit"
    else:
        try:
            boxes, _sizes, backend = render_glyph_boxes(path)
        except OracleUnavailable as exc:
            return {
                "ok": False,
                "filename": filename,
                "renderChecked": False,
                "note": "한컴 오라클이 없어 발신명의 위치를 찾을 수 없습니다. anchor_x/anchor_y(PDF pt)로 직접 지정하세요.",
                "reason": str(exc),
            }
        anchor = seal_ops.find_seal_anchor(boxes, sender_text)
        if anchor is None:
            return {
                "ok": False,
                "filename": filename,
                "renderChecked": True,
                "note": f"발신명의 '{sender_text}'를 렌더에서 찾지 못했습니다.",
            }
        anchor_center = anchor.center
        anchor_page_resolved = anchor.glyph.page
        anchor_source = backend

    # 2) stamp the floating seal on the anchor.
    doc = open_doc(path)
    placement = seal_ops.place_seal(
        doc,
        image_data=image_data,
        image_format=image_format,
        sender_text=sender_text,
        anchor_center_pt=anchor_center,
        seal_width_mm=seal_width_mm,
        seal_height_mm=seal_height_mm,
        page=anchor_page_resolved,
    )
    if not placement.placed:
        return {
            "ok": False,
            "filename": filename,
            "placement": placement.to_dict(),
            "note": placement.note or "발신명의 문단을 찾지 못했습니다.",
        }

    result = {
        "ok": True,
        "filename": filename,
        "outputPath": target_path,
        "anchorSource": anchor_source,
        "placement": placement.to_dict(),
        "idIntegrity": _id_integrity_payload(doc),
    }
    if dry_run:
        return _with_dry_run_verification(result, doc, target_path)
    verification = _save_doc_verification(doc, target_path)
    result = _with_save_verification(result, verification)

    # 3) optional oracle re-verify against the realized seal center.
    if verify:
        expected_center = (
            (placement.horz_offset + placement.seal_width_hu / 2) / 100.0,
            (placement.vert_offset + placement.seal_height_hu / 2) / 100.0,
        )
        result["sealVerdict"] = _check_seal_compliance_impl(
            target_path, sender_text, tol_pt=tol_pt, expected_center=expected_center
        )
    return result


def check_seal_compliance(
    filename: str,
    sender_text: str,
    tol_pt: float = 6.0,
) -> dict:
    """직인이 발신명의 끝글자에 규칙대로 찍혔는지 pass/fail 검사 (FR-003).

    한컴으로 렌더해 직인 이미지의 실제 위치를 발신명의 앵커와 비교합니다(중심 tol 이내 +
    의도치 않은 글자 가림 없음). 평가자가 그대로 돌릴 수 있는 차별적 검사 — 잘 찍힌 직인은
    pass, 어긋난 직인은 fail. 오라클이 없으면 ``renderChecked=false`` 로 degrade 합니다.
    """
    path = resolve_path(filename)
    return _check_seal_compliance_impl(path, sender_text, tol_pt=tol_pt)


def compose_exam(
    form_filename: str,
    output: str,
    exam_md: str | None = None,
    exam_md_filename: str | None = None,
    max_rounds: int = 2,
    verify: bool = True,
    role_style_names: dict[str, str] | None = None,
) -> dict:
    """출제 md를 학교 양식 .hwpx에 그 양식의 기존 스타일로 재조판합니다 (시험지 조판).

    각 문항이 단/쪽 경계에서 잘리지 않게(keep-together) 하고, 관리박스·머리글/꼬리글은
    무손실 보존하며, [그림N]/[표N]/[식N]은 텍스트 placeholder로 남깁니다(사람이 그림을
    나중에 삽입). ``exam_md``(인라인 문자열) 또는 ``exam_md_filename``(경로) 중 정확히
    하나를 줍니다. ``verify=True``(기본)면 한컴 렌더로 문항-split/overflow/placeholder를
    검증하고 — 오라클이 없으면 ``renderChecked=false`` 로 정직하게 degrade — ``verify=False``
    면 렌더 없이 조판만 합니다. 한컴이 본문을 벡터 커브로 export 하는 양식은
    ``splits=null`` + ``needsReview=true`` 로 정직 보고합니다(렌더 이미지로 시각 검증 필요).
    잘못된 md/양식은 조용히 틀린 문서를 내지 않고 ``ok=false`` 로 실패합니다.
    """
    if compose_exam_into_form is None:
        return {
            "ok": False,
            "filename": form_filename,
            "renderChecked": False,
            "needsReview": True,
            "note": "이 python-hwpx 빌드에는 hwpx.exam 조판 모듈이 없습니다.",
        }
    if (exam_md is None) == (exam_md_filename is None):
        return {
            "ok": False,
            "filename": form_filename,
            "renderChecked": False,
            "needsReview": True,
            "note": "exam_md(인라인) 또는 exam_md_filename(경로) 중 정확히 하나를 지정하세요.",
        }

    form_path = resolve_path(form_filename)
    if exam_md_filename is not None:
        try:
            exam_md = Path(resolve_path(exam_md_filename)).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {
                "ok": False,
                "filename": form_filename,
                "renderChecked": False,
                "needsReview": True,
                "error": type(exc).__name__,
                "note": f"exam_md_filename을 읽을 수 없습니다: {exc}",
            }
    out_path = resolve_path(output)
    oracle = None if verify else NullOracle()
    assert exam_md is not None  # narrowed by the XOR guard and file-load branch
    try:
        result = compose_exam_into_form(
            form_path,
            exam_md,
            out_path,
            oracle=oracle,
            max_rounds=max_rounds,
            role_style_names=role_style_names,
        )
    except (ExamParseError, FormProfileError) as exc:
        return {
            "ok": False,
            "filename": form_filename,
            "renderChecked": False,
            "needsReview": True,
            "error": type(exc).__name__,
            "note": str(exc),
        }

    payload = {
        "ok": True,
        "filename": form_filename,
        "outputPath": out_path,
        "renderChecked": result.render_checked,
        "splits": result.splits,
        "overflow": result.overflow,
        "placeholdersOk": result.placeholders_ok,
        "rounds": result.rounds,
        "needsReview": result.needs_review,
        "notes": list(result.notes),
    }
    payload["openSafety"] = build_hwpx_open_safety_report(Path(out_path))
    return payload


def verify_question_splits(
    filename: str,
    valid_question_numbers: list[str] | None = None,
    marker_regex: str | None = None,
) -> dict:
    """한컴 렌더로 시험지 .hwpx의 문항이 단/쪽 경계에서 잘렸는지(문항-split) 검증합니다.

    오라클이 없으면 ``renderChecked=false`` 로 정직하게 degrade 합니다(임의 0 금지).
    한컴이 본문을 벡터 커브로 export 해 추출 텍스트에 조판 문항이 0개면(학교 원안지
    양식에서 관측) ``splits=null`` + ``needsReview=true`` 로 보고하고 렌더 이미지 기반
    시각 검증을 요구합니다. ``valid_question_numbers`` 로 측정 대상 문항을 한정하면 양식
    chrome(예: "2026." 연도)이 가짜 문항 블록을 열지 않습니다.
    """
    if measure_question_splits is None:
        return {
            "ok": False,
            "filename": filename,
            "renderChecked": False,
            "needsReview": True,
            "note": "이 python-hwpx 빌드에는 hwpx.exam 조판/측정 모듈이 없습니다.",
        }
    marker_re = None
    if marker_regex:
        try:
            marker_re = re.compile(marker_regex)
        except re.error as exc:
            return {
                "ok": False,
                "filename": filename,
                "renderChecked": False,
                "splits": None,
                "needsReview": True,
                "error": "InvalidRegex",
                "note": f"marker_regex가 올바른 정규식이 아닙니다: {exc}",
            }
    path = resolve_path(filename)
    oracle = resolve_oracle()
    if not oracle.available():
        return {
            "ok": True,
            "filename": filename,
            "renderChecked": False,
            "splits": None,
            "needsReview": True,
            "note": "한컴 오라클이 없어 문항 split을 측정할 수 없습니다 (renderChecked=false).",
        }
    pdf = oracle.render_pdf(path)
    if not pdf:
        return {
            "ok": False,
            "filename": filename,
            "renderChecked": False,
            "splits": None,
            "needsReview": True,
            "note": "한컴 렌더가 PDF를 생성하지 못했습니다 (renderChecked=false).",
        }
    kwargs: dict[str, Any] = {}
    if valid_question_numbers is not None:
        kwargs["valid_ids"] = {str(n) for n in valid_question_numbers}
    if marker_re is not None:
        kwargs["marker_re"] = marker_re
    report = measure_question_splits(pdf, **kwargs)
    if report.n_blocks == 0:
        return {
            "ok": True,
            "filename": filename,
            "renderChecked": True,
            "splits": None,
            "needsReview": True,
            "nBlocks": 0,
            "note": (
                "추출 가능한 텍스트 레이어에서 조판 문항을 찾지 못했습니다(벡터 커브 export 양식"
                " 추정). 문항-split은 텍스트 게이트로 검증할 수 없습니다 — 렌더 이미지로 시각"
                " 검증이 필요합니다."
            ),
        }
    return {
        "ok": True,
        "filename": filename,
        "renderChecked": True,
        "splits": report.n_splits,
        "kinds": dict(report.kinds),
        "splitIds": list(report.split_ids),
        "nBlocks": report.n_blocks,
        "nGlyphs": report.n_glyphs,
        "needsReview": report.n_splits > 0,
    }


__all__ = [
    "build_image_grid",
    "build_meeting_nameplates",
    "build_organization_chart",
    "check_seal_compliance",
    "compose_exam",
    "inspect_mail_merge_placeholders",
    "mail_merge",
    "place_seal",
    "scan_personal_info",
    "verify_question_splits",
]
