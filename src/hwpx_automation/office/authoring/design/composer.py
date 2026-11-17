# SPDX-License-Identifier: Apache-2.0
"""Compose a new document from a profile + plan (plan §2 Phase E, task 2/3).

``compose`` lowers a :class:`~hwpx.design.plan.DocumentPlan` onto a verified
Hancom-saved skeleton: it copies the harvested fragment paragraphs (real paragraphs
and tables with real styles) out of the profile's fragments document with python-hwpx's
``paragraph.copy_to`` -- which brings the shapes they use along and gives the copies
fresh ids -- fills their text/cells through the document API, keeps the template's
page setup, checks ``styleCoverage``, and saves through the single
:class:`~hwpx.quality.SavePipeline`. Every byte of structure traces to a real
Hancom save — never imagined XML. Production mode forbids any minimal-XML fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from os import PathLike
from typing import Any, Mapping

from hwpx.document import HwpxDocument
from hwpx.quality import QualityPolicy

import hwpx_automation.office.authoring.design._support as S
from ...rendering import save_gate_report
from .marked import PLACEHOLDER_RE, is_marked_profile
from .plan import Block, DocumentPlan
from .profile import Profile, load_profile
from .validator import StyleCoverage, style_coverage

# Roles a paragraph block may request; unknown roles fall back to body.
_PARAGRAPH_ROLES = ("title", "heading", "subheading", "body")


class ProfileRequiredError(RuntimeError):
    """Production compose could not stay on the verified template + fragments."""


@dataclass(slots=True)
class ComposeResult:
    ok: bool
    profile: str
    output_path: str | None
    visual_complete: Any
    style_coverage: StyleCoverage
    block_count: int
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "profile": self.profile,
            "outputPath": self.output_path,
            "blockCount": self.block_count,
            "styleCoverage": self.style_coverage.to_dict(),
            "visualComplete": self.visual_complete.to_dict() if self.visual_complete else None,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def compose(
    plan: DocumentPlan | dict,
    *,
    profile: Profile | None = None,
    output_path: str | PathLike[str] | None = None,
    quality: QualityPolicy | None = None,
    production: bool = True,
) -> ComposeResult:
    """Lower *plan* onto its profile and save (or gate) through the SavePipeline."""

    if isinstance(plan, dict):
        plan = DocumentPlan.from_dict(plan)
    prof = profile or load_profile(plan.profile)
    warnings: list[str] = []

    doc = _open_seeded(prof.template_bytes)
    fragments_doc = HwpxDocument.open(prof.fragments_bytes)
    try:
        section = doc.sections[0]
        if not section.paragraphs:
            raise ProfileRequiredError(f"profile {prof.id!r} skeleton has no paragraph")
        # The skeleton's only paragraph carries the page setup (hp:secPr); it hands it to the
        # first composed paragraph at the end and goes (_Placer.finish).
        carrier = section.paragraphs[0]
        placed = _Placer(carrier)
        placed.document = doc

        new_paragraphs: list[Any] = []
        marked = is_marked_profile(prof.manifest)
        for block in plan.iter_blocks():
            if marked:
                fragments = _marked_fragment_for(prof, fragments_doc, placed, block, production, warnings)
            else:
                fragments = _fragment_for(prof, fragments_doc, placed, block, production, warnings)
            if block.page_break_before and fragments and new_paragraphs:
                # Hancom's own shape for a page break: the paragraph that
                # starts the new page carries pageBreak="1".
                fragments[0].page_break = True
            new_paragraphs.extend(fragments)

        if not new_paragraphs:
            raise ProfileRequiredError(
                f"plan produced no content for profile {prof.id!r}"
            )
        placed.finish()

        coverage = style_coverage(doc, [paragraph.element for paragraph in new_paragraphs])
        errors: list[str] = []
        if production and not coverage.meets(prof.style_coverage_threshold):
            errors.append(
                f"STYLE_COVERAGE_TOO_LOW: {coverage.coverage:.3f} < "
                f"{prof.style_coverage_threshold} (missing {coverage.missing[:5]})"
            )
            return ComposeResult(
                ok=False, profile=prof.id, output_path=None, visual_complete=None,
                style_coverage=coverage, block_count=len(new_paragraphs),
                warnings=warnings, errors=errors,
            )

        policy = quality or _default_policy()
        try:
            report = save_gate_report(doc, output_path, quality=policy)
        except ValueError as exc:
            # The save raises (not returns) when the serialized bytes fail the
            # open-safety floor — convert to the structured ok=False contract.
            return ComposeResult(
                ok=False, profile=prof.id, output_path=None, visual_complete=None,
                style_coverage=coverage, block_count=len(new_paragraphs),
                warnings=warnings, errors=[f"OPEN_SAFETY_FAILED: {exc}"],
            )
    finally:
        fragments_doc.close()
        doc.close()

    return ComposeResult(
        ok=report.ok and coverage.ok,
        profile=prof.id,
        output_path=report.output_path,
        visual_complete=report,
        style_coverage=coverage,
        block_count=len(new_paragraphs),
        warnings=warnings + list(report.warnings),
        errors=[str(e) for e in report.errors],
    )


def compose_bytes(plan: DocumentPlan | dict, **kwargs: Any) -> tuple[bytes, ComposeResult]:
    """Compose and return the serialized bytes (no file written).

    The bytes are non-empty only when ``result.ok`` — on a gate failure the
    SavePipeline withholds the output, so the returned bytes are ``b""``. Callers
    MUST check ``result.ok`` before using the bytes.
    """

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "composed.hwpx"
        result = compose(plan, output_path=out, **kwargs)
        data = out.read_bytes() if out.exists() else b""
    return data, result


#: The ids the copied fragments get come from this seed, so the same plan composes to the
#: same document (python-hwpx ``HwpxDocument.open(seed=)``).
_COMPOSE_SEED = S.COMPOSE_SEED


def _open_seeded(data: bytes) -> HwpxDocument:
    return S.open_seeded(data, _COMPOSE_SEED)  # type: ignore[return-value]


def _default_policy() -> QualityPolicy:
    # Structural-tier strict (no render here; the oracle gate runs separately):
    # open-safety + reference + layout lint on, render off.
    return QualityPolicy(
        require_open_safety=True,
        require_reference_integrity=True,
        require_visual_complete=False,
        render_check="off",
        layout_lint="strict",
        overflow_policy="warn",
    )


class _Placer:
    """Copies fragment paragraphs into the new document, one after another, after the
    skeleton's page-setup paragraph (*carrier*). :meth:`finish` then moves the first copy in
    front of the carrier -- python-hwpx hands it the section settings -- and removes the
    carrier. The copies are filled before that, so the text goes into the fragment's own
    runs, not the run the section settings come in."""

    def __init__(self, carrier: Any) -> None:
        self._carrier = carrier
        self._last = carrier
        self._first: Any | None = None
        self.document: Any = None

    def copy(self, paragraphs: list[Any]) -> list[Any]:
        copies: list[Any] = []
        for source in paragraphs:
            self._last = source.copy_to(self._last)
            if self._first is None:
                self._first = self._last
            copies.append(self._last)
        return copies

    def finish(self) -> None:
        if self._first is None:
            return
        self._first.move_before(self._carrier)
        self._carrier.remove()
        # Hancom keeps a section's settings in a run of their own at the start of the first paragraph,
        # in the character shape of the text that follows (python-hwpx tests/fixtures/hancom_saved: in
        # all 188 first paragraphs with text, 177 of them in the text's shape).
        runs = list(self._first.runs)
        settings = next((run for run in runs if any(item.kind == "section_properties" for item in run.content)), None)
        text = next((run for run in runs if run.text), None)
        if settings is not None and text is not None and settings != text and not settings.text:
            settings.char_pr_id_ref = text.char_pr_id_ref
        S.ensure_section_columns(self.document, self._first)



def _fragment_for(
    prof: Profile,
    fragments_doc: Any,
    placer: _Placer,
    block: Block,
    production: bool,
    warnings: list[str],
) -> list[Any]:
    if block.type == "table":
        width = len(block.columns) or max((len(row) for row in block.rows), default=0)
        reason = ""
        if not prof.has_role("info_table"):
            reason = f"'{prof.id}' 프로필에 표 조각이 없어 기본 표로 지음"
        elif width != (grid := _fragment_table_columns(prof, fragments_doc)):
            # More columns would be cut off, fewer would leave blank columns in the grid.
            reason = f"'{prof.id}' 프로필의 표 조각은 {grid}칸이고 계획의 표는 {width}칸이라 기본 표로 지음"
        if reason:
            # The plan's table is written whole as a plain table in the profile's body paragraph,
            # never cut down to the fragment's grid; the result says so.
            if not prof.has_role("body"):
                _forbid_fallback(production, f"profile {prof.id!r} has no table or body fragment", warnings)
                return []
            warnings.append(f"{TABLE_FALLBACK_NOTICE}: {reason}")
            copies = placer.copy(prof.fragment_paragraphs(fragments_doc, "body"))
            _plain_table(copies[0], block, prof, placer.document)
            return copies[:1]
        copies = placer.copy(prof.fragment_paragraphs(fragments_doc, "info_table"))
        _fill_table(copies[0], block.columns, block.rows, prof.id, warnings, production)
        if not block.show_header and len(list(copies[0].tables[0].rows)) > 1:
            copies[0].tables[0].delete_rows([0])
        return copies

    role = block.role if prof.has_role(block.role) else "body"
    if not prof.has_role(role):
        _forbid_fallback(production, f"profile {prof.id!r} has no {role!r} fragment", warnings)
        return []
    copies = placer.copy(prof.fragment_paragraphs(fragments_doc, role))
    copies[0].text = S.clean_text(block.text)
    return copies


def _marked_fragment_for(
    prof: Profile,
    fragments_doc: Any,
    placer: _Placer,
    block: Block,
    production: bool,
    warnings: list[str],
) -> list[Any]:
    """Copy the author-named role and fill its slots (marked-template profiles)."""

    if not prof.has_role(block.role):
        _forbid_fallback(
            production, f"marked profile {prof.id!r} has no role {block.role!r}", warnings
        )
        return []
    values = dict(block.values)
    slots = prof.manifest.get("slots", {}).get(block.role, [])
    # Plain ``text`` fills the unnamed slot, or the only slot a role has.
    if block.text and "" in slots and "" not in values:
        values[""] = block.text
    elif block.text and len(slots) == 1 and slots[0] not in values:
        values[slots[0]] = block.text
    elif block.text:
        values.setdefault("", block.text)  # nowhere to go: reported just below
    unknown = [slot for slot in values if slot not in slots]
    if unknown:
        # The template has no placeholder for these; dropping them loses content.
        _forbid_fallback(
            production,
            f"MARKED_VALUE_UNKNOWN: role {block.role!r} has slots {slots}, "
            f"plan gave {unknown}",
            warnings,
        )
    paragraphs = placer.copy(prof.fragment_paragraphs(fragments_doc, block.role))
    unfilled = fill_placeholders(paragraphs, block.role, values)
    if not values:
        # A block with no text and no values asks for the role as is (a page
        # break line, a separator) -- blank slots are what it wants.
        return paragraphs
    for slot in unfilled:
        name = f"{block.role}.{slot}" if slot else block.role
        warnings.append(f"MARKED_SLOT_EMPTY: no value for {{{{{name}}}}}; left blank")
    return paragraphs


def _forbid_fallback(production: bool, message: str, warnings: list[str]) -> None:
    if production:
        raise ProfileRequiredError("PROFILE_REQUIRED: " + message)
    warnings.append("debug fallback: " + message)


#: Starts the warning that a plan table was written as a plain table (no fitting table fragment).
TABLE_FALLBACK_NOTICE = "PROFILE_TABLE_FALLBACK"
_PLAIN_TABLE_BORDER = "#000000"
_PLAIN_TABLE_HEADER_FILL = "#F2F2F2"


def _fragment_table_columns(prof: Profile, fragments_doc: Any) -> int:
    paragraphs = prof.fragment_paragraphs(fragments_doc, "info_table")
    tables = list(paragraphs[0].tables) if paragraphs else []
    if not tables or not tables[0].rows:
        return 0
    return len(tables[0].rows[0].cells)


def _plain_table(host: Any, block: Block, prof: Profile, document: HwpxDocument) -> None:
    """Write *block* as a plain table (thin black lines, a shaded header row unless the plan hides
    it) in *host*, a copy of the profile's body paragraph, as wide as the page's text."""

    host.text = ""
    runs = list(host.runs)
    char_pr = runs[0].char_pr_id_ref if runs else None
    columns = list(block.columns) or [""] * max((len(row) for row in block.rows), default=1)
    rows = ([columns] if block.show_header else []) + [list(row) for row in block.rows]
    if not rows:
        rows = [columns]
    page = prof.manifest.get("page") or {}
    margins = page.get("margins") or {}
    width = int(page.get("width") or 59528) - int(margins.get("left") or 0) - int(margins.get("right") or 0)
    shape = document.styles.paragraph_property(host.para_pr_id_ref)
    indent = getattr(shape, "margin", None)
    if indent is not None:  # the host paragraph's own left/right margins narrow the line the table sits on
        width -= max(int(indent.left or 0), 0) + max(int(indent.right or 0), 0)
    line = document.styles.ensure_border_fill(border_color=_PLAIN_TABLE_BORDER, border_width_mm=0.12)
    table = host.add_table(len(rows), len(columns), width=width, border_fill_id_ref=line, char_pr_id_ref=char_pr)
    for row_index, values in enumerate(rows):
        for col_index in range(len(columns)):
            value = values[col_index] if col_index < len(values) else ""
            table.cell(row_index, col_index).text = S.clean_text(str(value))
    if block.show_header:
        shaded = document.styles.ensure_border_fill(
            border_color=_PLAIN_TABLE_BORDER, border_width_mm=0.12, fill_color=_PLAIN_TABLE_HEADER_FILL
        )
        for col_index in range(len(columns)):
            table.cell(0, col_index).border_fill_id_ref = shaded
        table.mark_dirty()


# --------------------------------------------------------------------------- #
# Table filling (row-fit the harvested fragment to the plan's rows).
# --------------------------------------------------------------------------- #
def _fill_table(
    paragraph: Any,
    columns: list[str],
    rows: list[list[str]],
    profile_id: str = "",
    warnings: list[str] | None = None,
    production: bool = True,
) -> None:
    warnings = warnings if warnings is not None else []
    tables = list(paragraph.tables)
    if not tables:
        return
    table = tables[0]
    if not table.rows:
        return
    col_count = len(table.rows[0].cells)

    # The harvested grid has a fixed width; a plan asking for MORE columns would
    # silently lose data (fewer just leaves blank trailing cells). Surface it —
    # and in production refuse the lossy case rather than drop the user's content.
    want = len(columns) or max((len(r) for r in rows), default=0)
    if want > col_count:
        message = (
            f"TABLE_COLUMN_MISMATCH: plan asks for {want} columns but the "
            f"{profile_id!r} info_table grid has {col_count}; extra columns dropped"
        )
        if production:
            raise ProfileRequiredError("PROFILE_REQUIRED: " + message)
        warnings.append("debug fallback: " + message)
    elif 0 < want < col_count:
        warnings.append(
            f"table column-count mismatch: plan has {want} columns, "
            f"{profile_id!r} grid has {col_count}; trailing columns left blank"
        )

    # Rows: the header, then one copy of the harvested data row (the header when the
    # fragment has no other) for each data row of the plan. python-hwpx keeps rowCnt,
    # cell addresses and the table height right.
    data_rows = rows or [["" for _ in range(col_count)]]
    if len(table.rows) > 2:
        table.delete_rows(list(range(2, len(table.rows))))
    if len(table.rows) == 1:
        table.insert_rows(0, len(data_rows), side="below", copy_content=True)
    elif len(data_rows) > 1:
        table.insert_rows(1, len(data_rows) - 1, side="below", copy_content=True)

    # Always re-fill the header (even when columns is empty) so the harvested
    # {{cell}} placeholder never ships in the output.
    _fill_row(table.rows[0], columns)
    for row, values in zip(table.rows[1:], data_rows):
        _fill_row(row, values)


def _fill_row(row: Any, values: list[str]) -> None:
    for col_index, cell in enumerate(row.cells):
        value = values[col_index] if col_index < len(values) else ""
        # A cell takes the value as its only paragraph, in its first run's shape.
        cell.text = S.clean_text(value)


# --------------------------------------------------------------------------- #
# Placeholder filling (marked profiles).
# --------------------------------------------------------------------------- #
def fill_placeholders(paragraphs: list[Any], role: str, values: Mapping[str, str]) -> list[str]:
    """Replace ``{{role}}``/``{{role.slot}}`` text in *paragraphs* (and the paragraphs of
    their tables) in place; return the slots no value was given for.

    The value goes where the placeholder starts, in that run's shape: a placeholder
    Hancom split across runs (the character shape changed inside it) loses only its own
    characters from the later runs; the rest of those runs, and their shapes, stay. A
    value's line breaks and tabs are written as Hancom writes them. Missing values
    become empty text so a placeholder never ships.
    """

    unfilled: list[str] = []
    for root in paragraphs:
        for paragraph in (root, *(place.paragraph for place in root.iter_paragraphs())):
            _fill_paragraph_placeholders(paragraph, role, values, unfilled)
    return list(dict.fromkeys(unfilled))


def _fill_paragraph_placeholders(
    paragraph: Any, role: str, values: Mapping[str, str], unfilled: list[str]
) -> None:
    matches = [match for match in PLACEHOLDER_RE.finditer(paragraph.text) if match.group(1) == role]
    if not matches:
        return
    # Where each run's text starts in paragraph.text (a run's text counts as paragraph.text does).
    run_ends: list[int] = []
    position = 0
    for run in paragraph.runs:
        position += len(run.text or "")
        run_ends.append(position)
    # Right to left, so an earlier match's offsets still hold.
    for match in reversed(matches):
        slot = match.group(2) or ""
        if slot not in values:
            unfilled.append(slot)
        value = S.clean_text(str(values.get(slot, "")))
        first_end = next((end for end in run_ends if end > match.start()), match.end())
        cut = min(first_end, match.end())
        if cut < match.end():
            paragraph.replace_range(cut, match.end(), "")  # the placeholder's characters in later runs
        paragraph.replace_range(match.start(), cut, value)


__all__ = ["compose", "compose_bytes", "ComposeResult", "ProfileRequiredError"]
