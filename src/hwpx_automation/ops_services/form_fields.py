# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from hwpx.quality.rendering import RenderBackend

from ..office.form_fill import (
    inspect_fill_residue as inspect_form_fill_residue,
)
from ..office.form_fill import (
    scan_form_guidance as scan_canonical_form_guidance,
)
from ..office.form_fill import (
    score_form_fill as score_canonical_form_fill,
)
from ..office.rendering import resolve_hancom_backend
from ..storage import LocalDocumentStorage
from ..workspace import (
    WorkspaceMissingParentGuard,
    WorkspaceOutputGuard,
)
from .context import DocumentContext
from .save_policy import SavePolicy
from .transactions import TransactionService

logger = logging.getLogger("hwpx_automation.hwpx_ops")


def _form_field_to_legacy_dict(field: Any, *, index: int | None = None) -> dict[str, Any]:
    """Rebuild the 5.x form-field dict shape from a 6.0 ``FormField``.

    ``FormField`` (design §2.3) is a living view with no ``to_dict()`` — it
    consolidated the 5.x dict's three id aliases / two prompt aliases / two
    type aliases / five index keys into single attributes. This
    automation-owned reconstruction restores the old dict shape (aliases
    included) that existing callers/tests still depend on. ``dirty`` comes
    straight off the wrapped element (the escape hatch), since it has no
    dedicated attribute on FormField.
    """

    location = field.location
    return {
        "index": index,
        "field_id": field.field_id,
        "id": field.field_id,
        "fieldid": field.field_id,
        "name": field.name,
        "prompt": field.prompt,
        "instruction": field.prompt,
        "memo": field.memo,
        "dirty": field.element.get("dirty", ""),
        "is_placeholder": field.is_placeholder,
        "current_value": field.value,
        "field_type": field.field_type,
        "control_type": field.field_type,
        "section_index": location.section_index,
        "paragraph_index": location.paragraph_index,
        "paragraph_index_in_section": location.paragraph_index_in_section,
        "run_index": location.run_index,
        "child_index": location.child_index,
        "has_end": field.has_end,
        "parameters": [parameter.to_dict() for parameter in field.parameters],
    }


def _note_preservation_contradiction(
    payload: dict[str, Any],
    domain_result: Mapping[str, Any],
    produced_differs: bool,
) -> None:
    """Record a domain receipt that disagrees with the bytes it describes.

    The publish decision reads ``byteIdentical`` from the domain result. A
    result describing only part of the run therefore suppressed the write
    entirely: an in-place evaluation-plan fill once reported ok alongside
    twenty-six filled regions and left the file untouched, because the flag
    came from the structural step taken before the content fills ran.

    The bytes are authoritative. When the receipt disagrees with them, say so
    rather than silently preferring one.
    """

    claimed_identical = domain_result.get("byteIdentical")
    if claimed_identical is None:
        return
    if bool(claimed_identical) is not produced_differs:
        return
    payload.setdefault("warnings", []).append(
        f"domain payload byteIdentical={claimed_identical!r} contradicts the "
        "produced bytes; the produced bytes are authoritative"
    )


class FormFieldService:
    def __init__(
        self,
        context: DocumentContext,
        save: SavePolicy,
        transactions: TransactionService,
        *,
        render_backend_factory: Callable[[], RenderBackend] | None = None,
    ) -> None:
        self._context = context
        self._save = save
        self._transactions = transactions
        self._render_backend_factory = render_backend_factory

    def _resolve_render_backend(self) -> RenderBackend:
        """Return the application-owned renderer for every core fill verdict.

        Core intentionally does not discover Hancom.  Keeping the factory at
        this service boundary makes all three form-fill paths use the same
        fail-closed injection seam, while tests can supply an observable
        backend without replacing core's ``verify_fill`` judgement.
        """

        factory = self._render_backend_factory or resolve_hancom_backend
        return factory()

    def list_form_fields(
        self,
        path: str,
    ) -> dict[str, Any]:
        document, _resolved = self._context._open_document(path)
        # fields.all now returns tuple[FormField, ...] rather than
        # list[dict] (design §2.3/§2.5) — reconstruct this op's established
        # dict shape since FormField has no to_dict() of its own.
        fields = [
            _form_field_to_legacy_dict(field, index=index)
            for index, field in enumerate(document.fields.all)
        ]
        return {
            "fieldCount": len(fields),
            "fields": fields,
            "fallback": "table-label" if not fields else None,
        }

    def add_form_field(
        self,
        path: str,
        *,
        name: str,
        prompt: str = "",
        memo: str = "",
        paragraph_index: int | None = None,
        table_index: int | None = None,
        row: int | None = None,
        col: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        document, resolved = self._context._open_document(path)
        cell_parts = (table_index, row, col)
        use_cell = any(part is not None for part in cell_parts)
        if use_cell and not all(part is not None for part in cell_parts):
            raise self._context._new_error(
                "FORM_FIELD_TARGET_INVALID",
                "provide tableIndex, row, and col together for a cell target",
            )
        if use_cell and paragraph_index is not None:
            raise self._context._new_error(
                "FORM_FIELD_TARGET_INVALID",
                "paragraphIndex cannot be combined with a cell target",
            )
        paragraph = None
        if table_index is not None and row is not None and col is not None:
            tables = self._context._iter_tables(document)
            try:
                table = tables[table_index]
            except IndexError as exc:
                raise self._context._new_error(
                    "TABLE_INDEX_OUT_OF_RANGE",
                    "tableIndex out of range",
                    details={"tableIndex": table_index},
                ) from exc
            try:
                paragraph = table.cell(row, col).paragraphs[-1]
            except (IndexError, ValueError) as exc:
                raise self._context._new_error(
                    "TABLE_CELL_OPERATION_FAILED",
                    f"failed to resolve table cell for the form field: {exc}",
                ) from exc
        elif paragraph_index is not None:
            try:
                paragraph = document.paragraphs[paragraph_index]
            except IndexError as exc:
                raise self._context._new_error(
                    "PARAGRAPH_INDEX_OUT_OF_RANGE",
                    "paragraphIndex out of range",
                    details={"paragraphIndex": paragraph_index},
                ) from exc
        # fields.add now returns a FormField living view rather than a dict
        # (design §2.3) — reconstruct the established response shape.
        field = document.fields.add(
            name, prompt=prompt, memo=memo, paragraph=paragraph
        )
        result = {
            "ok": True,
            "filename": path,
            "field": _form_field_to_legacy_dict(field),
        }
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )

    def fill_form_field(
        self,
        path: str,
        *,
        value: str,
        field_index: int | None = None,
        field_id: str | None = None,
        name: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        document, resolved = self._context._open_document(path)
        # fields.fill now returns a frozen FieldFillResult rather than a
        # dict (design §2.3) — its own to_dict() uses camelCase keys and a
        # bare field_id string for "field", which does not match this op's
        # established snake_case/nested-dict contract, so rebuild it here.
        fill_result = document.fields.fill(
            value,
            field_index=field_index,
            field_id=field_id,
            name=name,
        )
        result: dict[str, Any] = {
            "ok": True,
            "filename": path,
            "field": _form_field_to_legacy_dict(fill_result.field),
            "before_value": fill_result.before,
            "after_value": fill_result.after,
            "style_preserved": fill_result.style_preserved,
            "style_before": list(fill_result.style_before),
            "style_after": list(fill_result.style_after),
        }
        return self._transactions._with_transaction_verification(
            result, document, resolved, dry_run=dry_run
        )

    def run_edit_plan(
        self,
        plan: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """선언적 편집 계획(hwpx.edit-plan/v1)을 core 실행기로 위임한다.

        원자성(전 step 성공+최종 검증 후 단 1회 쓰기, 실패 시 무접촉)은 core
        `hwpx.plan`이 소유한다 — 여기서는 typed 오류 어휘로만 감싼다. 실행
        실패는 예외가 아니라 ok=False 리포트로 돌아온다(failedStepId 참조).
        """

        from hwpx.plan import PlanValidationError, apply_edit_plan

        try:
            report = apply_edit_plan(plan, dry_run=dry_run)
        except PlanValidationError as exc:
            raise self._context._new_error(
                "EDIT_PLAN_INVALID",
                exc.message,
                details=exc.to_dict(),
                hint=exc.suggestion,
            ) from exc
        return report.to_dict()

    def apply_table_ops(
        self,
        path: str,
        ops: Sequence[dict[str, Any]],
        *,
        output: str | None = None,
        render_check: str = "off",
        dry_run: bool = False,
        output_guard: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        publication_sink: Callable[[WorkspaceOutputGuard], None] | None = None,
    ) -> dict[str, Any]:
        """Byte-preserving structural form-fill: apply cell fills + table structure
        ops (delete_column/row/table, insert_row_by_clone, insert_block_by_clone)
        preserving every untouched byte. Cells/tables may be addressed by
        tableAnchor/cellAnchor (unique-or-skip) as well as index. Optional
        real-Hancom render gate.

        dryRun=true: identical pipeline (resolution/validation/fail-closed all
        real) but writes NOTHING — returns transcript (per-op resolution + before/
        after dims) and applied old→new texts as approval evidence for the user
        consult loop. renderCheck still works on the would-be bytes."""
        try:
            from hwpx.table_patch import apply_table_ops as _apply
        except Exception as exc:  # pragma: no cover - dependency compatibility
            raise self._context._new_error(
                "TABLE_OPS_UNAVAILABLE",
                "installed python-hwpx does not provide hwpx.table_patch.apply_table_ops",
            ) from exc

        source_path = self._context._resolve_path(path)
        self._context._require_hwpx_package(source_path, output)
        output_precondition = None
        if isinstance(self._context.storage, LocalDocumentStorage):
            output_precondition = (
                output_guard
                or self._context.storage.capture_output_precondition(
                    output if output else source_path
                )
            )
            target_path = output_precondition.path
        else:
            target_path = (
                self._context._resolve_path(output, must_exist=False)
                if output and dry_run
                else self._context._resolve_output_path(output)
                if output
                else source_path
            )
        result = _apply(source_path, list(ops), dry_run=dry_run)
        payload = result.to_dict()
        if dry_run:
            payload["dryRun"] = True
            payload["outputPath"] = None
        else:
            payload["outputPath"] = str(target_path)

        if render_check and render_check != "off":
            try:
                from hwpx.table_patch import verify_fill

                report = verify_fill(
                    source_path,
                    result.data,
                    oracle=self._resolve_render_backend(),
                    require=(render_check == "required"),
                )
                payload["renderVerdict"] = {
                    "renderChecked": report.render_checked,
                    "ok": report.ok,
                    "overflowDetected": report.overflow_detected,
                    "overlapDetected": report.overlap_detected,
                    "pageCountChanged": report.page_count_changed,
                    "warnings": list(report.warnings),
                    "errors": list(report.errors),
                }
                if report.render_checked and not report.ok:
                    payload["ok"] = False
                    if render_check == "required":
                        raise self._context._new_error(
                            "RENDER_CHECK_REQUIRED_FAILED",
                            "required render detected overflow, overlap, or layout regression",
                        )
            except Exception as exc:
                if render_check == "required":
                    raise self._context._new_error(
                        "RENDER_CHECK_REQUIRED_FAILED", str(exc)
                    ) from exc
                payload["renderVerdict"] = {"renderChecked": False, "note": str(exc)}
        # A required render is a pre-publication gate: only replace the
        # destination after the candidate has passed it.
        if (
            payload.get("ok") is not False
            and not dry_run
            and (
                not result.byte_identical
                or target_path.resolve(strict=False)
                != source_path.resolve(strict=False)
            )
        ):
            payload = self._save._write_patched(
                target_path,
                result.data,
                payload,
                output_guard=output_guard,
                output_precondition=output_precondition,
                publication_sink=publication_sink,
            )
        return payload

    def verify_form_fill(
        self,
        path: str,
        before_path: str,
        *,
        require: bool = False,
    ) -> dict[str, Any]:
        """Render before/after in REAL Hancom and judge overflow/overlap/layout.
        Honest degrade (renderChecked=false) with no oracle unless require=true."""
        try:
            from hwpx.table_patch import verify_fill
        except Exception as exc:  # pragma: no cover - dependency compatibility
            raise self._context._new_error(
                "VERIFY_UNAVAILABLE",
                "installed python-hwpx does not provide hwpx.table_patch.verify_fill",
            ) from exc
        after = self._context._resolve_path(path)
        before = self._context._resolve_path(before_path)
        report = verify_fill(
            before,
            after,
            oracle=self._resolve_render_backend(),
            require=require,
        )
        return {
            "renderChecked": report.render_checked,
            "ok": report.ok,
            "overflowDetected": report.overflow_detected,
            "overlapDetected": report.overlap_detected,
            "pageCountChanged": report.page_count_changed,
            "warnings": list(report.warnings),
            "errors": list(report.errors),
        }

    def score_form_fill(
        self,
        path: str,
        gold_path: str,
        blank_path: str,
        *,
        run_render: bool = True,
        expected_pages: int | None = None,
    ) -> dict[str, Any]:
        """Score a filled evaluation-plan form against a gold reference on 5 axes
        (A render cleanliness / B byte fidelity vs blank / C structure vs gold /
        D content completeness / E compliance) -> weighted 0-100 + per-axis gap
        report. The fitness function of the form-fill quality loop.

        ``path`` = produced fill, ``goldPath`` = accepted reference of the same
        form family, ``blankPath`` = the empty province form. A requires a real
        Hancom render (renderCheck); with no oracle A is ``unverified`` (never a
        silent pass). Set runRender=false for a fast structural-only pass."""
        produced = self._context._resolve_path(path)
        gold = self._context._resolve_path(gold_path)
        blank = self._context._resolve_path(blank_path)
        card = score_canonical_form_fill(
            produced,
            gold,
            blank,
            run_render=run_render,
            expected_pages=expected_pages,
        )
        return card.to_dict()

    def apply_body_ops(
        self,
        path: str,
        ops: Sequence[dict[str, Any]],
        *,
        output: str | None = None,
        dry_run: bool = False,
        output_guard: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        publication_sink: Callable[[WorkspaceOutputGuard], None] | None = None,
    ) -> dict[str, Any]:
        """Byte-preserving BODY(표 밖 직속 문단) ops — Stage 2 결정표의 본문 어휘.

        ops: replace_text{find,replace,count=1: <hp:t> 텍스트 안에서만, 개수 불일치
        refuse} · delete_paragraph{index: 표 품은 문단 refuse} ·
        insert_paragraph_by_clone{ref_index,count,texts?: 참조 문단 서식 verbatim
        상속} · reorder_paragraphs{start,end,order}. index는 op 실행 시점 기준.
        dryRun=true면 아무것도 쓰지 않고 transcript만(승인 근거)."""
        try:
            from hwpx.body_patch import apply_body_ops as _apply
        except Exception as exc:  # pragma: no cover - dependency compatibility
            raise self._context._new_error(
                "BODY_OPS_UNAVAILABLE",
                "installed python-hwpx does not provide hwpx.body_patch.apply_body_ops",
            ) from exc
        source_path = self._context._resolve_path(path)
        self._context._require_hwpx_package(source_path, output)
        output_precondition = None
        if isinstance(self._context.storage, LocalDocumentStorage):
            output_precondition = (
                output_guard
                or self._context.storage.capture_output_precondition(
                    output if output else source_path
                )
            )
            target_path = output_precondition.path
        else:
            target_path = (
                self._context._resolve_path(output, must_exist=False)
                if output and dry_run
                else self._context._resolve_output_path(output)
                if output
                else source_path
            )
        result = _apply(source_path, list(ops), dry_run=dry_run)
        payload = result.to_dict()
        if dry_run:
            payload["dryRun"] = True
            payload["outputPath"] = None
        else:
            payload["outputPath"] = str(target_path)
            if not result.byte_identical or target_path.resolve(
                strict=False
            ) != source_path.resolve(strict=False):
                payload = self._save._write_patched(
                    target_path,
                    result.data,
                    payload,
                    output_guard=output_guard,
                    output_precondition=output_precondition,
                    publication_sink=publication_sink,
                )
        return payload

    def inspect_fill_residue(
        self,
        path: str,
        *,
        blank_path: str | None = None,
    ) -> dict[str, Any]:
        """채움본 잔존물 zero-체크(비변형) — 제출 전 기계 게이트(Stage 3).

        blank를 주면 범례 기반 신호까지: 삭제색 잔존·미수정 샘플(수정색이 blank와
        동일=prose 샘플 미교체) = ERROR. placeholder ◯◯◯/□□□=ERROR, **=각주와
        중의적이라 needs_review, 고아 마커=needs_review. ok=true는 필요조건일 뿐 —
        제출 확언은 렌더 PDF를 사람이 전 페이지 본 뒤에만."""
        produced = self._context._resolve_path(path)
        blank = self._context._resolve_path(blank_path) if blank_path else None
        return inspect_form_fill_residue(produced, blank=blank).to_dict()

    def scan_form_guidance(self, path: str, *, max_items: int = 60) -> dict[str, Any]:
        """Recon an unfamiliar form (NON-MUTATING) — universal form-fill Stage 1.

        Walks every run INCLUDING table-cell interiors and table captions, parses
        the form's own colour legend (e.g. "검정 유지/파랑 수정/빨강 삭제"), and
        reports candidates with table_patch-compatible addresses: delete candidates
        (legend-delete colour + guidance keywords), modify targets, placeholder
        tokens (◯◯◯/**/□□□), conditional-choice blocks, empty cells with neighbour
        label + charPr format context, and an honest question list. Candidates are
        proposals — destructive ops still require user approval."""
        resolved = self._context._resolve_path(path)
        report = scan_canonical_form_guidance(resolved)
        limit = max(1, int(max_items))

        def _cand(c) -> dict[str, Any]:
            cell = None
            if c.cell is not None:
                cell = {
                    "tableIndex": c.cell.table_index,
                    "row": c.cell.row,
                    "col": c.cell.col,
                }
            return {
                "location": c.location,
                "signals": c.signals,
                "confidence": c.confidence,
                "textPreview": c.text_preview,
                "cell": cell,
            }

        def _cap(items) -> list[dict[str, Any]]:
            return [_cand(c) for c in items[:limit]]

        return {
            "legend": [
                {
                    "colorWord": b.color_word,
                    "family": b.family,
                    "exactHex": b.exact_hex,
                    "action": b.action,
                    "sourceText": b.source_text,
                }
                for b in report.legend
            ],
            "colorInventory": report.color_inventory,
            "deleteCandidates": _cap(report.delete_candidates),
            "deleteCandidatesTotal": len(report.delete_candidates),
            "modifyCandidatesByTable": report.modify_candidates_by_table,
            "emptyCellCandidates": _cap(report.empty_cell_candidates),
            "emptyCellTotal": len(report.empty_cell_candidates),
            "placeholderCandidates": _cap(report.placeholder_candidates),
            "conditionalChoices": _cap(report.conditional_choices),
            "questions": report.questions,
            "stats": report.stats,
            "limitations": report.limitations,
            "markdownReport": report.to_markdown(),
        }

    _EVALPLAN_PHASES = ("structural", "all", "clean")

    def apply_evalplan_fill(
        self,
        path: str,
        review_md: str,
        *,
        phase: str = "all",
        output: str | None = None,
        render_check: str = "off",
        score_gold_path: str | None = None,
        expected_pages: int | None = None,
        output_guard: (
            WorkspaceOutputGuard | WorkspaceMissingParentGuard | None
        ) = None,
        publication_sink: Callable[[WorkspaceOutputGuard], None] | None = None,
    ) -> dict[str, Any]:
        """Whole-form 평가계획 fill: {blank province form + review markdown} ->
        byte-preserving gold-quality 채움본 in ONE call. Runs the structure-driven
        recipe (delete red/optional tables + 정기시험 column, fill 운영계획/성취기준/
        성취수준/성취율/반영비율/rubrics incl. 채점기준 ladder/prose sections),
        preserving the blank's formatting (never regenerates). Works on BOTH the
        2015-개정 and 2022-개정 form families (auto-detected from the blank + review).

        ``path`` = blank form, ``reviewMd`` = the structured review markdown
        (Ⅰ 운영계획 + [1]~[11]). ``phase`` selects how far the recipe runs:
        ``"structural"`` = confident deletions only, ``"all"`` (default; the prior
        behaviour) = structural + per-region content fills, ``"clean"`` = ``"all"``
        plus core's deterministic post-fill cleanup (title/teacher/정의적 fills,
        instruction-scaffolding + orphan prune, red-strip, blue->black recolor,
        caption strip) that yields a submittable 채움본 with no bespoke driver; the
        cleanup report is surfaced under ``contentReport.finalize``. Returns the
        produced path + per-region contentReport with rubricNeedsReview (honest-defer
        count, never silent). Set renderCheck='required' to gate on a real Hancom
        render; pass scoreGoldPath (an accepted form of the same family) to also
        return the 5-axis scorecard."""
        if phase not in self._EVALPLAN_PHASES:
            raise self._context._new_error(
                "EVALPLAN_PHASE_INVALID",
                f"phase must be one of {self._EVALPLAN_PHASES}, got {phase!r}",
            )
        try:
            from hwpx_automation.office.evalplan import (
                expected_skeleton,
                fill_evalplan,
                parse_review_file,
            )
        except Exception as exc:  # pragma: no cover - broken package guard
            raise self._context._new_error(
                "EVALPLAN_FILL_UNAVAILABLE",
                "installed python-hwpx-automation does not provide the evalplan runtime",
            ) from exc

        blank = self._context._resolve_path(path)
        self._context._require_hwpx_package(blank, output)
        md = self._context._resolve_path(review_md)
        output_precondition = None
        if isinstance(self._context.storage, LocalDocumentStorage):
            output_precondition = (
                output_guard
                or self._context.storage.capture_output_precondition(
                    output if output else blank
                )
            )
            target_path = output_precondition.path
        else:
            target_path = (
                self._context._resolve_output_path(output) if output else blank
            )
        content = parse_review_file(md)
        res = fill_evalplan(blank, content, phase=phase)
        data = res["_data"]

        report = res.get("content_report", {})
        rubric_nr = [
            s
            for s in report.get("rubrics", {}).get("skipped", [])
            if "NEEDS_REVIEW" in s
        ]
        payload: dict[str, Any] = {
            "ok": bool(res.get("ok")),
            "outputPath": str(target_path),
            "byteIdentical": bool(res.get("byteIdentical")),
            "transcript": res.get("transcript", []),
            "expectedSkeleton": res.get("expected_skeleton"),
            "contentReport": report,
            "rubricNeedsReview": len(rubric_nr),
            "needsReviewNotes": rubric_nr,
            "changedParts": res.get("changedParts", []),
            "skipped": res.get("skipped", []),
        }
        if render_check and render_check != "off":
            try:
                from hwpx.table_patch import verify_fill

                verdict = verify_fill(
                    blank,
                    data,
                    oracle=self._resolve_render_backend(),
                    require=(render_check == "required"),
                )
                payload["renderVerdict"] = {
                    "renderChecked": verdict.render_checked,
                    "ok": verdict.ok,
                    "overflowDetected": verdict.overflow_detected,
                    "overlapDetected": verdict.overlap_detected,
                    "pageCountChanged": verdict.page_count_changed,
                    "warnings": list(verdict.warnings),
                    "errors": list(verdict.errors),
                }
                if verdict.render_checked and not verdict.ok:
                    payload["ok"] = False
                    if render_check == "required":
                        raise self._context._new_error(
                            "RENDER_CHECK_REQUIRED_FAILED",
                            "required evalplan render detected overflow, overlap, or layout regression",
                        )
            except Exception as exc:
                if render_check == "required":
                    raise self._context._new_error(
                        "RENDER_CHECK_REQUIRED_FAILED", str(exc)
                    ) from exc
                payload["renderVerdict"] = {"renderChecked": False, "note": str(exc)}

        # Do not publish a partial/failed domain result. Required rendering is
        # evaluated against candidate bytes before the atomic destination swap.
        #
        # ``byteIdentical`` is read straight from the domain payload, so a
        # payload that describes only part of the run silently suppresses the
        # write: an in-place call once reported ok with twenty-six content fills
        # and left the file untouched, because the flag came from the structural
        # step taken before the content fills ran. Compare the produced bytes
        # against the source directly so this decision cannot be poisoned by a
        # stale field again.
        in_place = target_path.resolve(strict=False) == blank.resolve(strict=False)
        produced_differs = data != blank.read_bytes()
        _note_preservation_contradiction(payload, res, produced_differs)
        if payload["ok"] and (produced_differs or not in_place):
            payload = self._save._write_patched(
                target_path,
                data,
                payload,
                output_guard=output_guard,
                output_precondition=output_precondition,
                publication_sink=publication_sink,
            )

        if score_gold_path:
            try:
                card = score_canonical_form_fill(
                    target_path,
                    self._context._resolve_path(score_gold_path),
                    blank,
                    content=md,
                    expected_skeleton=expected_skeleton(content, blank),
                    run_render=bool(render_check and render_check != "off"),
                    expected_pages=expected_pages,
                )
                payload["scorecard"] = card.to_dict()
            except Exception as exc:  # pragma: no cover - scoring optional
                payload["scorecard"] = {"error": str(exc)}
        return payload
