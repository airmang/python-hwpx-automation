# SPDX-License-Identifier: Apache-2.0
"""Harvest a profile from a real Hancom-saved document (plan §2 Phase E, task 1).

Given a genuine ``.hwpx`` it writes, under ``profiles/<id>/``:

* ``template.hwpx`` — a **body-stripped skeleton**: the real document reduced to
  its first section, whose body is a single ``secPr``-carrying paragraph. ``header.xml``
  (every style/font/borderFill) and the page setup survive untouched, so the
  committed artifact is small and carries no document content (no PII), yet is
  genuinely Hancom-derived — never imagined XML.
* ``fragments.hwpx`` — the skeleton with the real paragraphs (and the paragraph holding
  a table) harvested from the source copied in after its first paragraph, their text
  **sanitised to placeholders** (the style is kept, the content dropped).
* ``profile.json`` — the manifest the loader reads (``hwpx.design.profile.v2``).

This is an authoring-time tool (run once per profile); the committed artifacts are
what production uses.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from hwpx.document import HwpxDocument
from hwpx.oxml.namespaces import OPF_NS

import hwpx_automation.office.authoring.design._support as S
from .profile import FRAGMENTS_DOCUMENT, PROFILE_SCHEMA_V2

PROFILE_SCHEMA = PROFILE_SCHEMA_V2

_PLACEHOLDER = {
    "title": "{{title}}",
    "heading": "{{heading}}",
    "body": "{{body}}",
}


def _font_height(doc, ref) -> int:
    style = doc.styles.char_property(ref)
    if style is None:
        return 0
    try:
        return int(style.attributes.get("height") or 0)
    except ValueError:
        return 0


def _text_paragraphs(doc):
    out = []
    for index, para in enumerate(doc.sections[0].paragraphs):
        if getattr(para, "tables", []):
            continue
        text = (para.text or "").strip()
        if not text:
            continue
        runs = para.runs
        cref = runs[0].char_pr_id_ref if runs else "0"
        out.append(
            {
                "index": index,
                "para": para.para_pr_id_ref,
                "char": cref,
                "h": _font_height(doc, cref),
                "len": len(text),
                "paragraph": para,
            }
        )
    return out


def _pick_fragments(doc) -> dict[str, Any]:
    """The source paragraph picked for each role (``info_table``: the paragraph holding the table)."""
    tps = _text_paragraphs(doc)
    if not tps:
        raise ValueError("no text paragraphs to harvest")
    prose = [t for t in tps if t["len"] >= 8] or tps

    title = max(tps, key=lambda t: t["h"])
    combo = Counter((t["para"], t["char"]) for t in prose)
    body_key = combo.most_common(1)[0][0]
    body = next(t for t in prose if (t["para"], t["char"]) == body_key)
    head_pool = [
        t for t in tps
        if (t["para"], t["char"]) != body_key
        and Counter((x["para"], x["char"]) for x in tps)[(t["para"], t["char"])] >= 2
        and t["h"] >= body["h"]
    ]
    heading = max(head_pool, key=lambda t: t["h"], default=title)

    picks = {"title": title, "heading": heading, "body": body}
    fragments: dict[str, Any] = {role: p["paragraph"] for role, p in picks.items()}

    info = _pick_info_table(doc)
    if info is not None:
        fragments["info_table"] = info
    return fragments


def _sanitise_fragment(role: str, paragraph: Any) -> None:
    """Drop the source's content from a copied fragment: its text becomes the role placeholder
    (a table's cells each ``{{cell}}``); the shapes stay."""

    if role == "info_table":
        for table in paragraph.tables:
            for row in table.rows:
                for cell in row.cells:
                    for cell_paragraph in cell.paragraphs:
                        cell_paragraph.text = "{{cell}}"
        return
    paragraph.text = _PLACEHOLDER[role]


def _write_fragments_document(
    skeleton: Path,
    groups: list[tuple[str, list[Any]]],
    out_path: Path,
    sanitise: Any = None,
) -> dict[str, dict[str, int]]:
    """Write ``fragments.hwpx``: the skeleton with each group's paragraphs copied in after its
    page-setup paragraph (python-hwpx ``paragraph.copy_to``, which brings the shapes they use
    along), and return ``{role: {"start": i, "count": n}}``."""

    from ...rendering import save_gate_report

    places: dict[str, dict[str, int]] = {}
    # The copies get new ids: from a fixed seed, so the same source harvests to the same bytes.
    with S.open_seeded(skeleton, S.HARVEST_SEED) as document:  # type: ignore[attr-defined]
        last = document.sections[0].paragraphs[-1]
        index = len(document.sections[0].paragraphs)
        for role, paragraphs in groups:
            places[role] = {"start": index, "count": len(paragraphs)}
            for source in paragraphs:
                last = source.copy_to(last)
                if sanitise is not None:
                    sanitise(role, last)
                index += 1
        save_gate_report(document, out_path)
    return places


def _references_binary(element: etree._Element) -> bool:
    """True if *element* embeds an image / binary (so harvesting would dangle)."""

    for node in element.iter():
        if S.ln(node.tag).lower() in ("pic", "img", "image", "ole", "drawing"):
            return True
        for key in node.attrib:
            if "binaryitemidref" in S.ln(key).lower() or "bindata" in S.ln(key).lower():
                return True
    return False


def _is_simple_grid(table_element: etree._Element) -> bool:
    """True if every cell is 1×1 (no row/col merges) — safe to row-clone."""

    for tc in S.iter_local(table_element, "tc"):
        span = next((c for c in tc if S.ln(c.tag) == "cellSpan"), None)
        if span is not None:
            if int(span.get("rowSpan", "1")) > 1 or int(span.get("colSpan", "1")) > 1:
                return False
    return True


def _pick_info_table(doc) -> Any | None:
    best = None
    for para in doc.sections[0].paragraphs:
        for table in getattr(para, "tables", []):
            rows, cols = table.row_count, table.column_count
            if not (2 <= cols <= 4 and 2 <= rows <= 12):
                continue
            if _references_binary(table.element):
                continue  # text-only key-value tables, never image grids
            if not _is_simple_grid(table.element):
                continue  # merge-free grids only — the composer row-clones them
            score = rows * cols
            if best is None or score < best[0]:
                best = (score, table)
    if best is None:
        return None
    # Harvest the *paragraph* that wraps the table — a table is not a valid
    # section child on its own; it must ride inside an <hp:p>. Its cells are
    # sanitised to a neutral placeholder once copied (_sanitise_fragment).
    return best[1].paragraph


def _build_skeleton(source: Path, out_path: Path) -> dict:
    doc: Any = S.open_seeded(source, S.HARVEST_SEED)  # any id made here comes from the fixed seed
    # Only the first section's page setup is reused; later sections would ride
    # into every composed document with the source's text.
    _drop_later_sections(doc)
    section = doc.sections[0]
    # python-hwpx blanks the section down to its page setup: the first paragraph's
    # section settings (and its columns), no header or footer, no body.
    try:
        section.clear_body(keep_headers=False, on_control_content="strip")
    except ValueError as exc:  # python-hwpx HwpxValueError
        doc.close()
        if getattr(exc, "code", None) == "section-clear-no-section-properties":
            raise ValueError("template has no secPr (page setup)") from exc
        raise
    # Hancom drops the page settings of a section whose first paragraph has no column definition.
    S.ensure_section_columns(doc, section.paragraphs[0])

    stripped = _strip_binaries(doc)
    _scrub_metadata(doc)

    page = {}
    try:
        ps, pm = section.properties.page_size, section.properties.page_margins
        page = {
            "width": ps.width, "height": ps.height, "orientation": ps.orientation,
            "margins": {"left": pm.left, "right": pm.right, "top": pm.top, "bottom": pm.bottom},
        }
    except Exception:  # pragma: no cover - diagnostics only
        page = {}

    from ...rendering import save_gate_report

    report = save_gate_report(doc, out_path)
    style_count = len(doc.styles.char_properties)
    doc.close()
    return {
        "page": page,
        "char_pr_count": style_count,
        "open_safe": report.open_safety.ok,
        "stripped_parts": stripped,
    }


def _drop_later_sections(doc) -> None:
    """Remove every section after the first, part and manifest item included.

    Older cores remove the section from the document tree but keep its part,
    which would still be saved with the source text in it.
    """

    dropped = [section.part_name for section in doc.sections[1:]]
    for extra in reversed(doc.sections[1:]):
        doc.remove_section(extra)
    package = doc.package
    for item in list(package.manifest_tree().findall(f"./{{{OPF_NS}}}manifest/{{{OPF_NS}}}item")):
        href = item.get("href", "") or ""
        if any(name.endswith(href) for name in dropped if href) and item.get("id"):
            package.remove_manifest_item(item.get("id"))
    for name in dropped:
        if package.has_part(name):
            package.delete(name)


def _strip_binaries(doc) -> list[str]:
    """Drop embedded images + the source preview (size + PII) from the skeleton.

    The body is already reduced to one empty paragraph, so nothing references
    these parts; removing them (and their manifest items) keeps the committed
    skeleton small and content-free while leaving every style in header.xml.
    """

    package = doc.package
    removed: list[str] = []
    # Image fills defined in header.xml (borderFill imgBrush) are styles, not
    # body content: dropping their binaries would leave dangling references.
    kept_ids = _header_binary_refs(package)
    kept_parts: set[str] = set()

    for item in list(package.manifest_tree().findall(f"./{{{OPF_NS}}}manifest/{{{OPF_NS}}}item")):
        href = item.get("href", "") or ""
        media = item.get("media-type", "") or ""
        base = href.rsplit("/", 1)[-1]
        if (
            "BinData/" in href
            or base.startswith("PrvImage")
            or media.lower().startswith("image/")
        ):
            item_id = item.get("id")
            if item_id in kept_ids:
                kept_parts.add(href)
                continue
            if item_id:
                package.remove_manifest_item(item_id)

    for name in list(package.part_names()):
        if any(name.endswith(href) for href in kept_parts):
            continue
        if name.startswith("BinData/") or name.startswith("Preview/PrvImage"):
            try:
                package.delete(name)
                removed.append(name)
            except Exception:  # pragma: no cover - defensive
                pass

    # clear source text (PII): PrvText.txt becomes empty bytes (the preview images went above)
    doc.parts.clear_preview()
    return removed


def _header_binary_refs(package) -> set[str]:
    refs: set[str] = set()
    for path in package.header_paths():
        for node in package.get_xml(path).iter():
            for key, value in node.attrib.items():
                if S.ln(key) == "binaryItemIDRef":
                    refs.add(value)
    return refs


# Manifest (content.hpf) metadata that carries source PII — author, the person who
# last saved, the source title, and timestamps. Cleared so generated docs inherit
# nothing identifying.
_SCRUB_META_NAMES = {
    "creator", "lastsaveby", "subject", "description", "keyword",
    "date", "CreatedDate", "ModifiedDate",
}


def _scrub_metadata(doc) -> None:
    """Blank source-identifying OPF metadata in Contents/content.hpf (PII)."""

    package = doc.package
    try:
        tree = package.manifest_tree()
    except Exception:  # pragma: no cover - defensive
        return
    for element in tree.iter():
        name = S.ln(element.tag)
        if name == "title":
            element.text = ""
        elif name == "meta" and element.get("name") in _SCRUB_META_NAMES:
            element.text = ""
    package.set_part(package.main_content.full_path, tree)


def harvest_profile(source: str | Path, profile_id: str, out_root: str | Path) -> dict:
    """Harvest *source* into ``<out_root>/<profile_id>/`` and return the manifest."""

    source = Path(source)
    out_dir = Path(out_root) / profile_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # The skeleton (a copy of the source blanked to its page setup), then the fragments:
    # the picked source paragraphs copied into a copy of the skeleton, text sanitised.
    skel = _build_skeleton(source, out_dir / "template.hwpx")
    with HwpxDocument.open(source) as doc:
        fragments = _pick_fragments(doc)
        places = _write_fragments_document(
            out_dir / "template.hwpx",
            [(role, [paragraph]) for role, paragraph in fragments.items()],
            out_dir / FRAGMENTS_DOCUMENT,
            sanitise=_sanitise_fragment,
        )

    manifest = {
        "schemaVersion": PROFILE_SCHEMA,
        "id": profile_id,
        "template": "template.hwpx",
        "fragments_document": FRAGMENTS_DOCUMENT,
        "fragments": places,
        "page": skel["page"],
        "char_pr_count": skel["char_pr_count"],
        "style_coverage_threshold": 0.98,
        "source_basename": source.name,
    }
    (out_dir / "profile.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        **manifest,
        "skeleton_open_safe": skel["open_safe"],
        "stripped_parts": skel.get("stripped_parts", []),
    }


__all__ = ["harvest_profile", "PROFILE_SCHEMA"]
