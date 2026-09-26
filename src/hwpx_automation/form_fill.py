"""High-level HWPX form-fill workflow helpers.

The public MCP surface is intentionally two-phase:
``analyze_form_fill`` is non-mutating and ``apply_form_fill`` owns copy,
mutation, re-read, and validation evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from .office.compliance import DEFAULT_POLICY, mask_pii

try:  # python-hwpx >= 2.10.3
    from hwpx.tools.package_validator import validate_package
except ImportError as exc:  # pragma: no cover - expected only on dependency skew
    validate_package = None
    _PACKAGE_VALIDATOR_IMPORT_ERROR: Exception | None = exc
else:
    _PACKAGE_VALIDATOR_IMPORT_ERROR = None

try:  # python-hwpx >= 2.10.3
    from hwpx.tools.repair import repair_repack
except ImportError as exc:  # pragma: no cover - expected only on dependency skew
    repair_repack = None
    _REPAIR_REPACK_IMPORT_ERROR: Exception | None = exc
else:
    _REPAIR_REPACK_IMPORT_ERROR = None

from . import quality as quality_contract
from .core.content import get_table_data, get_table_map_in_doc, set_cell_text
from .core.document import open_doc
from .core.formatting import list_styles_in_doc
from .storage import build_hwpx_open_safety_report
from .upstream import repair_pathological_text_spacing, validate_document_path
from .utils.helpers import resolve_path

_FORM_FILL_SCHEMA_VERSION = "hwpx.formfill.v1"
_DOCX_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TABLE_DIRECTIONS = {"right", "down"}
_FORM_FILL_PLANS: dict[str, dict[str, Any]] = {}
_CONFIDENCE_LABEL_EXACT = "label-exact"
_CONFIDENCE_LABEL_FUZZY = "label-fuzzy"
_CONFIDENCE_POSITION_GUESS = "position-guess"
_FUZZY_MATCH_THRESHOLD = 0.72


class _FormFillModel(BaseModel):
    """Typed MCP boundary while preserving forward-compatible plan metadata."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class FormFillSourceInput(_FormFillModel):
    type: str = "structured"
    path: str | None = None
    sha256: str | None = None


class FormFillTargetInput(_FormFillModel):
    kind: Literal[
        "label-path",
        "cell",
        "coordinate",
        "form-field",
        "placeholder",
        "canonical-path",
        "body-anchor",
    ] = "label-path"
    path: str | None = None
    token: str | None = None
    table_index: int | None = None
    row: int | None = None
    col: int | None = None
    field_index: int | None = None
    field_id: str | None = None
    name: str | None = None


class FormFillFieldInput(_FormFillModel):
    key: str | None = None
    label: str | None = None
    value: str | int | float | bool | None = ""
    text: str | None = None
    target: FormFillTargetInput | None = None
    style_policy: str = Field(default="preserve-target", alias="stylePolicy")


class CanonicalFormFillInput(_FormFillModel):
    schema_version: Literal["hwpx.formfill.v1"] = Field(
        default="hwpx.formfill.v1", alias="schemaVersion"
    )
    source: FormFillSourceInput = Field(default_factory=FormFillSourceInput)
    fields: list[FormFillFieldInput] = Field(default_factory=list)
    paragraphs: list[FormFillFieldInput] = Field(default_factory=list)


class FormFillAnalyzeOptions(_FormFillModel):
    require_unique_anchors: bool = Field(default=True, alias="requireUniqueAnchors")
    allow_fuzzy_labels: bool = Field(default=True, alias="allowFuzzyLabels")
    preserve_unmapped_parts: bool = Field(default=True, alias="preserveUnmappedParts")


class FormFillPlanFile(_FormFillModel):
    filename: str | None = None
    path: str | None = None
    sha256: str | None = None
    mtime_ns: int | None = None


class FormFillResolvedMapping(_FormFillModel):
    kind: str
    key: str | None = None
    label: str | None = None
    value: str | int | float | bool | None = None
    confidence: str | None = None
    confidence_grade: str | None = Field(default=None, alias="confidenceGrade")
    method: str | None = None


class FormFillMappingSet(_FormFillModel):
    resolved: list[FormFillResolvedMapping] = Field(default_factory=list)
    unresolved: list[FormFillResolvedMapping] = Field(default_factory=list)


class FormFillPlanInput(_FormFillModel):
    """Serializable output of analyze_form_fill accepted by apply_form_fill."""

    plan_id: str
    schema_version: Literal["hwpx.formfill.v1"] = Field(alias="schemaVersion")
    source: FormFillPlanFile
    destination: FormFillPlanFile
    canonical_input: CanonicalFormFillInput = Field(alias="canonicalInput")
    mappings: FormFillMappingSet
    unresolved_count: int = 0
    resolved_count: int = 0
    mutated: bool = False
    options: FormFillAnalyzeOptions = Field(default_factory=FormFillAnalyzeOptions)


def _typed_payload(value: BaseModel | dict[str, Any] | str | None) -> dict[str, Any] | str | None:
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_none=True)
    return value


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


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze_form_fill_workflow(
    *,
    source_filename: str,
    input_json: CanonicalFormFillInput | dict[str, Any] | str | None = None,
    input_json_path: str | None = None,
    input_docx: str | None = None,
    destination_filename: str | None = None,
    options: FormFillAnalyzeOptions | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-mutating form-fill analysis and serializable plan."""

    source_path = resolve_path(source_filename)
    source = Path(source_path)
    before_hash = sha256_file(source)
    destination_path = resolve_path(destination_filename) if destination_filename else None

    canonical_input = _load_canonical_input(
        input_json=_typed_payload(input_json),
        input_json_path=input_json_path,
        input_docx=input_docx,
    )
    doc = open_doc(source_path)
    table_map = get_table_map_in_doc(doc)
    styles = list_styles_in_doc(doc)
    outline = _document_outline(doc)
    mappings = _build_mapping_analysis(doc, canonical_input)
    plan_id = f"ff_{uuid.uuid4().hex[:16]}"

    analysis: dict[str, Any] = {
        "plan_id": plan_id,
        "schemaVersion": _FORM_FILL_SCHEMA_VERSION,
        "source": {
            "filename": source_filename,
            "path": source_path,
            "sha256": before_hash,
            "mtime_ns": source.stat().st_mtime_ns,
        },
        "destination": {
            "filename": destination_filename,
            "path": destination_path,
            "required": bool(destination_filename),
            "will_be_created_by": "apply_form_fill",
        },
        "canonicalInput": canonical_input,
        "document": {
            "info": {
                "sections": len(getattr(doc, "sections", [])),
                "paragraphs": len(getattr(doc, "paragraphs", [])),
                "tables": len(table_map.get("tables", [])),
            },
            "outline": outline,
            "tables": table_map.get("tables", []),
            "styles": styles,
            "styleCount": len(styles),
        },
        "formFields": mappings.get("formFields", {}),
        "mappings": mappings,
        "unresolved_count": len(mappings["unresolved"]),
        "resolved_count": len(mappings["resolved"]),
        "mutated": False,
        "next_tool": "apply_form_fill",
        "options": _typed_payload(options) or {},
    }
    _FORM_FILL_PLANS[plan_id] = copy.deepcopy(analysis)
    after_hash = sha256_file(source)
    analysis["source"]["unchanged_after_analysis"] = after_hash == before_hash
    return analysis


def apply_form_fill_workflow(
    *,
    plan_id: str | None = None,
    analysis: FormFillPlanInput | dict[str, Any] | None = None,
    source_filename: str | None = None,
    destination_filename: str | None = None,
    canonical_input: CanonicalFormFillInput | dict[str, Any] | str | None = None,
    confirm: bool = True,
    mask: bool = True,
) -> dict[str, Any]:
    """Apply a resolved form-fill plan to a copied destination and validate it."""

    if not confirm:
        raise ValueError("confirm must be true to apply form-fill mutations")

    plan = _resolve_analysis(plan_id=plan_id, analysis=analysis)
    if canonical_input is not None:
        plan["canonicalInput"] = _load_canonical_input(input_json=_typed_payload(canonical_input))
        doc_for_mapping = open_doc(_source_path_from_plan(plan, source_filename))
        plan["mappings"] = _build_mapping_analysis(doc_for_mapping, plan["canonicalInput"])

    source_path = _source_path_from_plan(plan, source_filename)
    destination_path = _destination_path_from_plan(plan, destination_filename)
    if Path(source_path).resolve(strict=False) == Path(destination_path).resolve(strict=False):
        raise ValueError("apply_form_fill refuses source-in-place edits; destination_filename must differ from source")

    unresolved = list(plan.get("mappings", {}).get("unresolved", []))
    if unresolved:
        return {
            "handoff_status": "blocked",
            "reason": "unresolved mappings remain",
            "unresolved": unresolved,
            "applied": [],
            "source": {"path": source_path, "sha256": sha256_file(source_path)},
            "destination": {"path": destination_path},
        }

    source = Path(source_path)
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_before_hash = sha256_file(source)
    source_before_mtime = source.stat().st_mtime_ns
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=destination.suffix or ".hwpx",
        dir=str(destination.parent),
    )
    tmp_destination = Path(tmp_name)
    os.close(tmp_fd)
    try:
        shutil.copy2(source, tmp_destination)
        copied_hash = sha256_file(tmp_destination)

        doc = open_doc(str(tmp_destination))
        applied: list[dict[str, Any]] = []
        for _raw_mapping in plan.get("mappings", {}).get("resolved", []):
            # PII compliance: mask the merged-in value (machine set on by
            # default) so neither the output doc nor the applied[] echo leaks raw PII.
            mapping = dict(_raw_mapping)
            if mask and mapping.get("value") is not None:
                mapping["value"] = mask_pii(str(mapping["value"]), DEFAULT_POLICY)
            if mapping.get("kind") == "form-field":
                before_fields = _document_form_fields(doc)
                before_field = _find_form_field_by_mapping(before_fields, mapping)
                # fields.fill now returns a frozen FieldFillResult rather
                # than a dict (design §2.3) — read its attributes directly
                # instead of the old after_value/style_before/... dict keys.
                fill_result = doc.fields.fill(
                    str(mapping.get("value", "")),
                    field_index=int(mapping["field_index"]),
                )
                _before_ff = before_field.get("current_value", "") if before_field else ""
                applied.append(
                    {
                        **mapping,
                        "before_text": mask_pii(_before_ff, DEFAULT_POLICY) if mask else _before_ff,
                        "after_text": fill_result.after,
                        "style_before": list(fill_result.style_before),
                        "style_after": list(fill_result.style_after),
                        "style_preserved": bool(fill_result.style_preserved),
                    }
                )
            elif mapping.get("kind") == "cell":
                table_index = int(mapping["table_index"])
                row = int(mapping["row"])
                col = int(mapping["col"])
                before_style = _cell_style_snapshot(doc, table_index, row, col)
                before_text = _cell_text(doc, table_index, row, col)
                if mask:
                    before_text = mask_pii(before_text, DEFAULT_POLICY)
                set_cell_text(doc, table_index, row, col, str(mapping.get("value", "")))
                after_style = _cell_style_snapshot(doc, table_index, row, col)
                applied.append(
                    {
                        **mapping,
                        "before_text": before_text,
                        "after_text": str(mapping.get("value", "")),
                        "style_before": before_style,
                        "style_after": after_style,
                        "style_preserved": before_style == after_style,
                    }
                )
            elif mapping.get("kind") == "placeholder":
                token = str(mapping["token"])
                value = str(mapping.get("value", ""))
                replacements = _replace_placeholder(doc, token, value)
                applied.append(
                    {
                        **mapping,
                        "replaced_count": sum(item["replace_count"] for item in replacements),
                        "replacements": replacements,
                        "style_preserved": all(item["style_preserved"] for item in replacements),
                    }
                )

        save_report = _save_form_fill_document(doc, tmp_destination)
        repair_result = _repair_repack_destination(tmp_destination)
        reread_doc = open_doc(str(tmp_destination))
        touched = _reread_touched(reread_doc, applied)
        validation = _runtime_validation(str(tmp_destination))
        source_after_hash = sha256_file(source)
        source_after_mtime = source.stat().st_mtime_ns
        output_hash = sha256_file(tmp_destination)
        ok = bool(
            validation["validate_structure"]["ok"]
            and validation["validate_package"]["ok"]
            and validation["validate_document"]["ok"]
            and validation["openSafety"]["ok"]
        )
        if ok:
            os.replace(tmp_destination, destination)

        return {
            "handoff_status": "ready" if ok else "blocked",
            "plan_id": plan.get("plan_id"),
            "source": {
                "path": str(source),
                "sha256_before": source_before_hash,
                "sha256_after": source_after_hash,
                "mtime_ns_before": source_before_mtime,
                "mtime_ns_after": source_after_mtime,
                "preserved": source_before_hash == source_after_hash and source_before_mtime == source_after_mtime,
            },
            "destination": {
                "path": str(destination),
                "sha256_after_copy": copied_hash,
                "sha256_after_apply": output_hash,
                "changed": copied_hash != output_hash,
            },
            "repair": repair_result,
            "lineage_id": _lineage_id(source_before_hash, str(destination)),
            "applied": applied,
            "unresolved": [],
            "touched": touched,
            "validation": validation,
            "persisted": ok,
            "visualComplete": quality_contract.visual_complete_block(save_report),
        }
    finally:
        _cleanup_temporary_destination(tmp_destination)


def _load_canonical_input(
    *,
    input_json: dict[str, Any] | str | None = None,
    input_json_path: str | None = None,
    input_docx: str | None = None,
) -> dict[str, Any]:
    provided = [value is not None for value in (input_json, input_json_path, input_docx)].count(True)
    if provided != 1:
        raise ValueError("provide exactly one of input_json, input_json_path, or input_docx")

    if input_json_path is not None:
        payload = json.loads(Path(resolve_path(input_json_path)).read_text(encoding="utf-8"))
    elif input_docx is not None:
        payload = _canonical_input_from_docx(resolve_path(input_docx))
    elif isinstance(input_json, str):
        stripped = input_json.strip()
        possible_path = Path(stripped).expanduser()
        if possible_path.suffix.lower() == ".json" and possible_path.exists():
            payload = json.loads(possible_path.read_text(encoding="utf-8"))
        else:
            payload = json.loads(stripped)
    elif isinstance(input_json, dict):
        payload = copy.deepcopy(input_json)
    else:  # pragma: no cover - defensive, provided count catches this
        raise ValueError("input_json must be an object, JSON string, or JSON path")

    return _normalize_canonical_input(payload)


def _normalize_canonical_input(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("canonical input must be a JSON object")
    normalized = copy.deepcopy(payload)
    normalized.setdefault("schemaVersion", _FORM_FILL_SCHEMA_VERSION)
    if normalized["schemaVersion"] != _FORM_FILL_SCHEMA_VERSION:
        raise ValueError(f"unsupported form-fill schemaVersion: {normalized['schemaVersion']}")
    normalized.setdefault("source", {"type": "structured"})
    fields = normalized.setdefault("fields", [])
    if not isinstance(fields, list):
        raise ValueError("fields must be a list")
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            raise ValueError(f"fields[{index}] must be an object")
        label = str(field.get("label") or field.get("key") or "").strip()
        if not label:
            raise ValueError(f"fields[{index}] requires label or key")
        field.setdefault("key", label)
        field.setdefault("label", label)
        field.setdefault("value", "")
        field.setdefault("stylePolicy", "preserve-target")
        field.setdefault("target", {"kind": "label-path", "path": f"{label} > right"})
    paragraphs = normalized.setdefault("paragraphs", [])
    if not isinstance(paragraphs, list):
        raise ValueError("paragraphs must be a list")
    return normalized


def _canonical_input_from_docx(path: str) -> dict[str, Any]:
    docx_path = Path(path)
    if docx_path.suffix.lower() != ".docx":
        raise ValueError("input_docx must point to a .docx file")
    if not zipfile.is_zipfile(docx_path):
        raise ValueError("input_docx is not a valid DOCX zip package; provide input_json instead")
    try:
        with zipfile.ZipFile(docx_path) as archive:
            xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("input_docx does not contain word/document.xml; provide input_json instead") from exc

    root = ET.fromstring(xml)
    body = root.find(f"{_DOCX_W_NS}body")
    if body is None:
        raise ValueError("input_docx does not contain a Word document body; provide input_json instead")

    fields: list[dict[str, Any]] = []
    for child in body:
        if child.tag == f"{_DOCX_W_NS}tbl":
            for row in child.iter(f"{_DOCX_W_NS}tr"):
                cells = [_element_text(cell).strip() for cell in row.findall(f"{_DOCX_W_NS}tc")]
                cells = [cell for cell in cells if cell]
                if len(cells) >= 2:
                    label, value = cells[0], cells[1]
                    fields.append(_field_from_label_value(label, value, source="docx-table"))
        elif child.tag == f"{_DOCX_W_NS}p":
            text = _element_text(child).strip()
            if not text or "=" not in text and ":" not in text:
                continue
            label, value = re.split(r"[:=]", text, maxsplit=1)
            if label.strip() and value.strip():
                fields.append(_field_from_label_value(label.strip(), value.strip(), source="docx-paragraph"))
    if not fields:
        raise ValueError("input_docx did not contain key/value fields; provide canonical input_json")
    return {
        "schemaVersion": _FORM_FILL_SCHEMA_VERSION,
        "source": {"type": "docx", "path": path, "sha256": sha256_file(path)},
        "fields": fields,
        "paragraphs": [],
    }


def _field_from_label_value(label: str, value: str, *, source: str) -> dict[str, Any]:
    return {
        "key": _slug_key(label),
        "label": label,
        "value": value,
        "target": {"kind": "label-path", "path": f"{label} > right"},
        "stylePolicy": "preserve-target",
        "provenance": {"source": source},
    }


def _element_text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{_DOCX_W_NS}t"))


def _slug_key(label: str) -> str:
    slug = re.sub(r"\W+", "_", label.strip(), flags=re.UNICODE).strip("_")
    return slug or "field"


def _document_outline(doc: Any) -> list[dict[str, Any]]:
    try:
        from .core.formatting import outline_style_levels

        style_levels = outline_style_levels(doc)
    except Exception:
        style_levels = {}
    outline = []
    for index, para in enumerate(getattr(doc, "paragraphs", [])):
        text = (getattr(para, "text", None) or "").strip()
        if not text:
            continue
        level = 1 if len(text) < 80 else 0
        style_ref = getattr(para, "style_id_ref", None)
        if style_ref is not None and str(style_ref) in style_levels:
            level = style_levels[str(style_ref)]
        elif text.startswith("#"):
            level = min(6, len(text) - len(text.lstrip("#")))
        if level:
            outline.append({"level": level, "text": text, "paragraph_index": index})
    return outline


def _build_mapping_analysis(doc: Any, canonical_input: dict[str, Any]) -> dict[str, Any]:
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    form_fields = _document_form_fields(doc)
    form_field_strategy = {
        "available": bool(form_fields),
        "count": len(form_fields),
        "fields": form_fields,
        "fallback": None if form_fields else "table-label",
    }
    for field in _iter_fill_items(canonical_input):
        target = field.get("target") or {}
        kind = target.get("kind", "label-path")
        if kind == "form-field":
            mapping = _resolved_explicit_form_field_mapping(field, target, form_fields)
            if mapping is None:
                unresolved.append(
                    {
                        "kind": "form-field",
                        "key": field.get("key"),
                        "label": field.get("label"),
                        "value": str(field.get("value", "")),
                        "reason": "form field not found",
                        "candidate_count": len(form_fields),
                        "candidates": form_fields,
                        "next_action": "provide field_index, field_id, or name from list_form_fields",
                    }
                )
            else:
                resolved.append(mapping)
            continue
        if kind in {"cell", "coordinate"} or {"table_index", "row", "col"}.issubset(target):
            resolved.append(_resolved_cell_mapping(field, target, method="explicit-coordinate"))
            continue
        if kind == "label-path":
            label, direction = _label_and_direction(field, target)
            native_mapping = _resolved_form_field_mapping(field, form_fields, label)
            if native_mapping is not None:
                resolved.append(native_mapping)
                continue
            matches = doc.tables.find_cell_by_label(label, direction=direction).get("matches", [])
            if len(matches) == 1:
                match = matches[0]
                cell = match["target_cell"]
                resolved.append(
                    {
                        "kind": "cell",
                        "key": field.get("key"),
                        "label": label,
                        "value": str(field.get("value", "")),
                        "table_index": match["table_index"],
                        "row": cell["row"],
                        "col": cell["col"],
                        "current_text": cell.get("text", ""),
                        "stylePolicy": field.get("stylePolicy", "preserve-target"),
                        "confidence": "high",
                        "confidenceGrade": _CONFIDENCE_LABEL_EXACT,
                        "method": "label-path",
                    }
                )
            elif not matches:
                fuzzy_matches = _find_fuzzy_table_label_matches(doc, label, direction)
                if len(fuzzy_matches) == 1:
                    match = fuzzy_matches[0]
                    cell = match["target_cell"]
                    resolved.append(
                        {
                            "kind": "cell",
                            "key": field.get("key"),
                            "label": label,
                            "matched_label": match["label_cell"].get("text", ""),
                            "match_score": match["score"],
                            "value": str(field.get("value", "")),
                            "table_index": match["table_index"],
                            "row": cell["row"],
                            "col": cell["col"],
                            "current_text": cell.get("text", ""),
                            "stylePolicy": field.get("stylePolicy", "preserve-target"),
                            "confidence": "medium",
                            "confidenceGrade": _CONFIDENCE_LABEL_FUZZY,
                            "method": "label-path-fuzzy",
                        }
                    )
                else:
                    unresolved.append(
                        {
                            "kind": "cell",
                            "key": field.get("key"),
                            "label": label,
                            "value": str(field.get("value", "")),
                            "reason": "label not found",
                            "candidates": fuzzy_matches,
                            "candidate_count": len(fuzzy_matches),
                            "next_action": "provide explicit table_index/row/col target",
                        }
                    )
            else:
                unresolved.append(
                    {
                        "kind": "cell",
                        "key": field.get("key"),
                        "label": label,
                        "value": str(field.get("value", "")),
                        "reason": "label not found" if not matches else "ambiguous label",
                        "candidates": matches,
                        "candidate_count": len(matches),
                        "next_action": "provide explicit table_index/row/col target",
                    }
                )
            continue
        if kind == "placeholder":
            token = target.get("token")
            if not token:
                unresolved.append({"kind": "placeholder", "key": field.get("key"), "reason": "missing token"})
            else:
                resolved.append(
                    {
                        "kind": "placeholder",
                        "key": field.get("key"),
                        "token": str(token),
                        "value": str(field.get("value", "")),
                        "stylePolicy": field.get("stylePolicy", "preserve-placeholder"),
                        "confidence": "high",
                        "confidenceGrade": _CONFIDENCE_LABEL_EXACT,
                        "method": "placeholder",
                    }
                )
            continue
        unresolved.append({"kind": kind, "key": field.get("key"), "reason": f"unsupported target kind: {kind}"})
    return {"resolved": resolved, "unresolved": unresolved, "formFields": form_field_strategy}


def _form_field_to_legacy_dict(field: Any, *, index: int) -> dict[str, Any]:
    """Rebuild the 5.x form-field dict shape from a 6.0 ``FormField`` view.

    Mirrors ``ops_services.form_fields._form_field_to_legacy_dict`` — kept
    local (not imported) since this lower-level workflow module sits below
    the service layer and importing from it would invert that dependency
    direction. ``index`` is load-bearing here: downstream mapping resolution
    (``_resolved_explicit_form_field_mapping``/``_find_form_field_by_mapping``)
    matches on ``field["index"]`` to build ``field_index=`` fill targets.
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


def _document_form_fields(doc: Any) -> list[dict[str, Any]]:
    # fields.all now returns tuple[FormField, ...] rather than list[dict]
    # (design §2.3/§2.5) — reconstruct the established dict shape since
    # FormField has no to_dict() of its own.
    return [
        _form_field_to_legacy_dict(field, index=index)
        for index, field in enumerate(doc.fields.all)
    ]


def _normalize_match_text(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    while normalized.endswith((":", "：")):
        normalized = normalized[:-1].rstrip()
    return normalized


def _form_field_labels(field: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in ("name", "prompt", "instruction", "field_id", "id", "fieldid"):
        value = str(field.get(key) or "").strip()
        if value:
            labels.append(value)
    for param in field.get("parameters", []) or []:
        if isinstance(param, dict):
            value = str(param.get("value") or "").strip()
            if value:
                labels.append(value)
    return labels


def _resolved_form_field_mapping(
    field: dict[str, Any],
    form_fields: list[dict[str, Any]],
    label: str,
) -> dict[str, Any] | None:
    if not form_fields:
        return None
    wanted = _normalize_match_text(field.get("label") or label or field.get("key"))
    exact = [
        item
        for item in form_fields
        if wanted and wanted in {_normalize_match_text(label_value) for label_value in _form_field_labels(item)}
    ]
    if len(exact) == 1:
        return _form_field_mapping(field, exact[0], label, confidence_grade=_CONFIDENCE_LABEL_EXACT, score=1.0)
    if len(exact) > 1:
        return None

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in form_fields:
        scores = [
            SequenceMatcher(None, wanted, _normalize_match_text(candidate)).ratio()
            for candidate in _form_field_labels(item)
            if _normalize_match_text(candidate)
        ]
        if scores:
            scored.append((max(scores), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored or scored[0][0] < _FUZZY_MATCH_THRESHOLD:
        return None
    if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.03:
        return None
    return _form_field_mapping(
        field,
        scored[0][1],
        label,
        confidence_grade=_CONFIDENCE_LABEL_FUZZY,
        score=round(scored[0][0], 3),
    )


def _resolved_explicit_form_field_mapping(
    field: dict[str, Any],
    target: dict[str, Any],
    form_fields: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not form_fields:
        return None
    field_index = target.get("field_index", target.get("fieldIndex"))
    if field_index is not None:
        for item in form_fields:
            if int(item.get("index", -1)) == int(field_index):
                return _form_field_mapping(
                    field,
                    item,
                    str(field.get("label") or field.get("key") or ""),
                    confidence_grade=_CONFIDENCE_POSITION_GUESS,
                    score=None,
                    method="form-field-index",
                )
        return None
    selector = target.get("field_id", target.get("fieldId")) or target.get("name")
    if not selector:
        return None
    wanted = _normalize_match_text(selector)
    matches = [
        item
        for item in form_fields
        if wanted and wanted in {_normalize_match_text(label) for label in _form_field_labels(item)}
    ]
    if len(matches) != 1:
        return None
    return _form_field_mapping(
        field,
        matches[0],
        str(field.get("label") or field.get("key") or ""),
        confidence_grade=_CONFIDENCE_LABEL_EXACT,
        score=1.0,
        method="form-field-selector",
    )


def _form_field_mapping(
    field: dict[str, Any],
    form_field: dict[str, Any],
    label: str,
    *,
    confidence_grade: str,
    score: float | None,
    method: str = "form-field",
) -> dict[str, Any]:
    mapping = {
        "kind": "form-field",
        "key": field.get("key"),
        "label": label,
        "value": str(field.get("value", "")),
        "field_index": int(form_field["index"]),
        "field_id": form_field.get("field_id", ""),
        "name": form_field.get("name", ""),
        "prompt": form_field.get("prompt", ""),
        "instruction": form_field.get("instruction", ""),
        "current_text": form_field.get("current_value", ""),
        "stylePolicy": field.get("stylePolicy", "preserve-target"),
        "confidence": "high" if confidence_grade == _CONFIDENCE_LABEL_EXACT else "medium",
        "confidenceGrade": confidence_grade,
        "method": method,
    }
    if score is not None:
        mapping["match_score"] = score
    return mapping


def _find_form_field_by_mapping(
    form_fields: list[dict[str, Any]],
    mapping: dict[str, Any],
) -> dict[str, Any] | None:
    field_index = mapping.get("field_index")
    field_id = str(mapping.get("field_id") or "")
    name = _normalize_match_text(mapping.get("name"))
    for field in form_fields:
        if field_index is not None and int(field.get("index", -1)) == int(field_index):
            return field
        if field_id and field_id in {field.get("field_id"), field.get("id"), field.get("fieldid")}:
            return field
        if name and name == _normalize_match_text(field.get("name")):
            return field
    return None


def _table_cell_lookup(table: dict[str, Any], row: int, col: int) -> dict[str, Any] | None:
    for cell in table.get("cells", []) or []:
        if int(cell.get("row", -1)) == row and int(cell.get("col", -1)) == col:
            return cell
    return None


def _find_fuzzy_table_label_matches(doc: Any, label: str, direction: str) -> list[dict[str, Any]]:
    wanted = _normalize_match_text(label)
    if not wanted:
        return []
    row_delta, col_delta = (0, 1) if direction == "right" else (1, 0)
    matches: list[dict[str, Any]] = []
    for table in get_table_map_in_doc(doc).get("tables", []):
        for cell in table.get("cells", []) or []:
            cell_text = str(cell.get("text", ""))
            normalized = _normalize_match_text(cell_text)
            if not normalized or normalized == wanted:
                continue
            score = SequenceMatcher(None, wanted, normalized).ratio()
            if score < _FUZZY_MATCH_THRESHOLD:
                continue
            target = _table_cell_lookup(
                table,
                int(cell.get("row", 0)) + row_delta,
                int(cell.get("col", 0)) + col_delta,
            )
            if target is None:
                continue
            matches.append(
                {
                    "table_index": table["table_index"],
                    "label_cell": {"row": cell["row"], "col": cell["col"], "text": cell_text},
                    "target_cell": {
                        "row": target["row"],
                        "col": target["col"],
                        "text": target.get("text", ""),
                    },
                    "score": round(score, 3),
                }
            )
    matches.sort(key=lambda item: item["score"], reverse=True)
    if len(matches) > 1 and abs(matches[0]["score"] - matches[1]["score"]) < 0.03:
        return matches[:2]
    return matches[:1]


def _iter_fill_items(canonical_input: dict[str, Any]) -> list[dict[str, Any]]:
    items = list(canonical_input.get("fields", []))
    for paragraph in canonical_input.get("paragraphs", []):
        if isinstance(paragraph, dict):
            items.append(
                {
                    "key": paragraph.get("key"),
                    "label": paragraph.get("label") or paragraph.get("key"),
                    "value": paragraph.get("value", paragraph.get("text", "")),
                    "target": paragraph.get("target"),
                    "stylePolicy": paragraph.get("stylePolicy", "preserve-placeholder"),
                }
            )
    return items


def _resolved_cell_mapping(field: dict[str, Any], target: dict[str, Any], *, method: str) -> dict[str, Any]:
    return {
        "kind": "cell",
        "key": field.get("key"),
        "label": field.get("label"),
        "value": str(field.get("value", "")),
        "table_index": int(target.get("table_index", target.get("tableIndex", 0))),
        "row": int(target["row"]),
        "col": int(target["col"]),
        "stylePolicy": field.get("stylePolicy", "preserve-target"),
        "confidence": "explicit",
        "method": method,
    }


def _label_and_direction(field: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    path = str(target.get("path") or f"{field.get('label')} > right")
    parts = [part.strip() for part in path.split(">") if part.strip()]
    label = parts[0] if parts else str(field.get("label") or field.get("key"))
    direction = parts[1].casefold() if len(parts) > 1 else "right"
    if direction not in _TABLE_DIRECTIONS:
        raise ValueError("label-path target currently supports right or down as the first direction")
    return label, direction


def _resolve_analysis(
    *,
    plan_id: str | None,
    analysis: FormFillPlanInput | dict[str, Any] | None,
) -> dict[str, Any]:
    if analysis is not None:
        payload = _typed_payload(analysis)
        if not isinstance(payload, dict):  # pragma: no cover - type contract guard
            raise ValueError("analysis must be a typed form-fill plan object")
        return copy.deepcopy(payload)
    if plan_id is None:
        raise ValueError("provide plan_id or analysis")
    try:
        return copy.deepcopy(_FORM_FILL_PLANS[plan_id])
    except KeyError as exc:
        raise ValueError(f"unknown form-fill plan_id: {plan_id}") from exc


def _source_path_from_plan(plan: dict[str, Any], override: str | None) -> str:
    if override:
        return resolve_path(override)
    source = plan.get("source") or {}
    path = source.get("path") or source.get("filename")
    if not path:
        raise ValueError("source_filename is required")
    return resolve_path(str(path))


def _destination_path_from_plan(plan: dict[str, Any], override: str | None) -> str:
    if override:
        return resolve_path(override)
    destination = plan.get("destination") or {}
    path = destination.get("path") or destination.get("filename")
    if not path:
        raise ValueError("destination_filename is required")
    return resolve_path(str(path))


def _cell_style_snapshot(doc: Any, table_index: int, row: int, col: int) -> dict[str, Any]:
    cell = _cell(doc, table_index, row, col)
    paragraph = cell.paragraphs[0] if getattr(cell, "paragraphs", []) else None
    return _paragraph_style_snapshot(paragraph)


def _paragraph_style_snapshot(paragraph: Any) -> dict[str, Any]:
    run = paragraph.runs[0] if paragraph is not None and getattr(paragraph, "runs", []) else None
    return {
        "para_pr_id_ref": getattr(paragraph, "para_pr_id_ref", None),
        "style_id_ref": getattr(paragraph, "style_id_ref", None),
        "char_pr_id_ref": getattr(paragraph, "char_pr_id_ref", None),
        "run_char_pr_id_ref": getattr(run, "char_pr_id_ref", None),
    }


def _cell_text(doc: Any, table_index: int, row: int, col: int) -> str:
    return _cell(doc, table_index, row, col).text or ""


def _cell(doc: Any, table_index: int, row: int, col: int) -> Any:
    tables: list[Any] = []
    for paragraph in doc.paragraphs:
        tables.extend(getattr(paragraph, "tables", []))
    return tables[table_index].rows[row].cells[col]


def _replace_placeholder(doc: Any, token: str, value: str) -> list[dict[str, Any]]:
    replacements: list[dict[str, Any]] = []
    for paragraph_index, paragraph in enumerate(doc.paragraphs):
        before_text = paragraph.text or ""
        if token not in before_text:
            continue
        before_style = _paragraph_style_snapshot(paragraph)
        replace_count = 0
        changed_runs: list[Any] = []
        for run in paragraph.runs:
            text = run.text or ""
            if token in text:
                replace_count += text.count(token)
                run.text = text.replace(token, value)
                if run.text:
                    changed_runs.append(run)
        if replace_count:
            repair_pathological_text_spacing(
                doc,
                paragraph=paragraph,
                runs=changed_runs,
            )
            _clear_paragraph_layout_cache(paragraph)
        after_style = _paragraph_style_snapshot(paragraph)
        replacements.append(
            {
                "paragraph_index": paragraph_index,
                "before_text": before_text,
                "after_text": paragraph.text or "",
                "replace_count": replace_count,
                "style_before": before_style,
                "style_after": after_style,
                "style_preserved": before_style == after_style,
            }
        )
    return replacements


def _reread_touched(doc: Any, applied: list[dict[str, Any]]) -> list[dict[str, Any]]:
    touched = []
    for item in applied:
        if item.get("kind") == "form-field":
            field = _find_form_field_by_mapping(_document_form_fields(doc), item)
            touched.append(
                {
                    "kind": "form-field",
                    "field_index": item.get("field_index"),
                    "field_id": item.get("field_id"),
                    "name": item.get("name"),
                    "text": field.get("current_value", "") if field else "",
                    "field": field or {},
                }
            )
        elif item.get("kind") == "cell":
            table_index = int(item["table_index"])
            row = int(item["row"])
            col = int(item["col"])
            data = get_table_data(doc, table_index)
            touched.append(
                {
                    "kind": "cell",
                    "table_index": table_index,
                    "row": row,
                    "col": col,
                    "text": data["data"][row][col],
                    "style": _cell_style_snapshot(doc, table_index, row, col),
                }
            )
        elif item.get("kind") == "placeholder":
            for replacement in item.get("replacements", []):
                paragraph_index = int(replacement["paragraph_index"])
                paragraph = doc.paragraphs[paragraph_index]
                touched.append(
                    {
                        "kind": "placeholder",
                        "paragraph_index": paragraph_index,
                        "text": paragraph.text or "",
                        "style": _paragraph_style_snapshot(paragraph),
                    }
                )
    return touched


def _runtime_validation(path: str) -> dict[str, Any]:
    document_report = validate_document_path(path)
    structure_issues = [
        {
            "part": getattr(issue, "part_name", None),
            "message": getattr(issue, "message", str(issue)),
            "severity": getattr(issue, "severity", "error"),
        }
        for issue in getattr(document_report, "issues", ())
    ]
    # a schema warning from python-hwpx does not block the hand-off; only its errors do
    structure = {
        "ok": not any(issue["severity"] == "error" for issue in structure_issues),
        "issues": structure_issues,
    }
    if validate_package is None:
        package = _dependency_unavailable_report(
            "python-hwpx>=2.10.3 is required for HWPX package validation",
            _PACKAGE_VALIDATOR_IMPORT_ERROR,
        )
    else:
        package = _package_report(validate_package(path))
    open_safety = build_hwpx_open_safety_report(Path(path))
    return {
        "validate_structure": structure,
        "validate_package": package,
        "validate_document": _document_report(document_report),
        "openSafety": open_safety,
    }


def _save_form_fill_document(doc: Any, destination: Path, *, quality: Any = None) -> Any:
    # Phase F: form fill funnels through the one SavePipeline gate too, and
    # returns the VisualCompleteReport so the response can carry the block.
    quality_contract.assert_write_capability()
    return quality_contract.save_through_pipeline(doc, destination, quality=quality)


def _cleanup_temporary_destination(destination: Path) -> None:
    destination.unlink(missing_ok=True)
    destination.with_suffix(destination.suffix + ".bak").unlink(missing_ok=True)


def _repair_repack_destination(destination: Path) -> dict[str, Any]:
    if repair_repack is None:
        detail = (
            str(_REPAIR_REPACK_IMPORT_ERROR)
            if _REPAIR_REPACK_IMPORT_ERROR is not None
            else "hwpx.tools.repair.repair_repack is unavailable"
        )
        raise RuntimeError(
            "python-hwpx>=2.10.3 is required for HWPX repair/open-safety handoff: "
            + detail
        )
    repaired = destination.with_name(f".{destination.name}.repair.hwpx")
    try:
        result = repair_repack(destination, repaired, overwrite=True)
        shutil.move(str(repaired), str(destination))
        return {
            "reordered": result.reordered,
            "crc_ok": result.crc_ok,
            "output_path": str(destination),
            "openSafety": result.open_safety,
        }
    finally:
        repaired.unlink(missing_ok=True)


def _package_report(report: Any) -> dict[str, Any]:
    return {
        "ok": bool(getattr(report, "ok", False)),
        "checked_parts": list(getattr(report, "checked_parts", ())),
        "issues": [_issue_payload(issue) for issue in getattr(report, "issues", ())],
    }


def _dependency_unavailable_report(message: str, error: Exception | None) -> dict[str, Any]:
    detail = f"{message}: {error}" if error is not None else message
    return {
        "ok": False,
        "checked_parts": [],
        "issues": [{"part": None, "message": detail, "level": "error"}],
    }


def _document_report(report: Any) -> dict[str, Any]:
    return {
        "ok": bool(getattr(report, "ok", False)),
        "validated_parts": list(getattr(report, "validated_parts", ())),
        "issues": [_issue_payload(issue) for issue in getattr(report, "issues", ())],
    }


def _issue_payload(issue: Any) -> dict[str, Any]:
    return {
        "part": getattr(issue, "part_name", None),
        "message": getattr(issue, "message", str(issue)),
        "level": getattr(issue, "severity", "error"),
    }


def _lineage_id(source_hash: str, destination: str) -> str:
    return hashlib.sha256(f"{source_hash}:{destination}".encode("utf-8")).hexdigest()[:16]
