# SPDX-License-Identifier: Apache-2.0
"""Atomic, allow-listed mutation commands for the semantic agent interface.

The public contract in :mod:`hwpx.agent.model` deliberately has no raw XML or
package-part escape hatch.  This module is the only compiler from that compact
command vocabulary to the existing python-hwpx editing primitives.  A batch is
applied to one disposable in-memory document, serialized once, and handed to
the normal :class:`~hwpx.quality.SavePipeline` exactly once.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hwpx.document import HwpxDocument
from hwpx.oxml.objects import wrap_object
from hwpx.quality import SavePipeline

from ._batch_publication import BatchPublication
from ._text_scope import TextScope
from ...upstream import content_seed
from .catalog import catalog_hash
from .document import HwpxAgentDocument, NodeRecord, TextRange, place
from .model import (
    AGENT_COMMAND_SCHEMA_V1,
    CONTRACT_CHANGED_INDEX,
    CONTRACT_CHANGED_RUN,
    CONTRACT_CHANGED_RUN_ANCHOR,
    NODE_PROPERTY_CATALOG_V2,
    AgentBatchResult,
    AgentContractError,
    contract_changed,
    validate_agent_batch,
)
from .path import parse_path
from .story import (
    HEADER_STORY_EDITABLE_PROPERTIES,
    HEADER_STORY_KIND,
    HeaderStoryBinding,
    try_parse_header_story_path,
)
# Verification/orchestration primitives for apply_document_commands live in
# _batch_verification (split out to keep this file under its line-count
# ratchet). _error_from_exception/_member_diff/_quality_policy/_revision are
# re-exported here (explicit `as` aliases) because blueprint/replay.py still
# imports them from this module.
from ._batch_verification import (
    DomainVerifier,
    FaultInjector,
    IdempotencyStore,
    _EMPTY_REVISION,
    _apply_commands_build_candidate_report,
    _apply_commands_domain_verification,
    _apply_commands_idempotency_lookup,
    _apply_commands_run_save_pipeline,
    _call_fault,
    _error_from_exception as _error_from_exception,
    _failure_result,
    _member_diff as _member_diff,
    _quality_policy as _quality_policy,
    _request_hash,
    _require_candidate_structural_safety,
    _revision as _revision,
    _validate_apply_commands_input,
)

_HWP_UNITS_PER_MM = 7200 / 25.4
_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PARAGRAPH_ALIGNMENTS = frozenset(
    {"LEFT", "CENTER", "RIGHT", "JUSTIFY", "DISTRIBUTE", "DISTRIBUTE_SPACE"}
)
_TABLE_ALIGNMENTS = frozenset({"LEFT", "CENTER", "RIGHT", "INSIDE", "OUTSIDE"})
_VERTICAL_ALIGNMENTS = frozenset({"TOP", "CENTER", "BOTTOM"})
#: Notes sit in an hp:ctrl: Hancom drops a note outside one and crashes on an empty one.
_NOTE_TAGS = frozenset({"footNote", "endNote"})
_SHAPE_KINDS = frozenset({"line", "rect", "ellipse", "arc", "polygon", "curve", "connectLine"})

# Creation needs a few geometry fields that are readable, rather than editable,
# after the node exists.  Everything else comes directly from the property catalog.
_CREATE_PROPERTIES: dict[str, frozenset[str]] = {
    "section": frozenset({"pageWidthMm", "pageHeightMm"}),
    "paragraph": frozenset(NODE_PROPERTY_CATALOG_V2["paragraph"]["editable"]),
    "text": frozenset(NODE_PROPERTY_CATALOG_V2["text"]["editable"]),
    "footnote": frozenset({"text"}),
    "endnote": frozenset({"text"}),
    "table": frozenset({"rowCount", "columnCount", "caption", "widthMm", "alignment"}),
    "row": frozenset({"cellCount", "heightMm"}),
}

_ADD_PARENTS = {
    "section": "document",
    "paragraph": "section",
    "text": "paragraph",
    "table": "paragraph",
    "footnote": "paragraph",
    "endnote": "paragraph",
    "row": "table",
}

_MOVE_COPY_PARENTS = {
    "paragraph": "section",
    "text": "paragraph",
    "table": "paragraph",
    "row": "table",
    "picture": "paragraph",
    "shape": "paragraph",
    "memo": "section",
    "footnote": "paragraph",
    "endnote": "paragraph",
}

# --- agent-command v2: character-offset places (hwpx-automation 8.0) ---------------------------
# A run is no longer placed by its order among its siblings: text is added, removed, moved and
# copied as a range of ``paragraph.text`` (the ``text`` node), and a table, picture or shape sits
# at a character offset of its paragraph.  These go through python-hwpx's own range and placement
# calls (``insert_text``, ``delete_range``, ``move_range``/``copy_range``, ``replace_range``,
# ``format_range``, ``move_to``/``copy_to(offset=)``, ``obj.offset``); none writes the tree.

#: Objects placed at a character offset of their paragraph (notes wait for asks10c).
_OFFSET_KINDS = frozenset({"table", "picture", "shape", "footnote", "endnote"})
#: What a place in a paragraph may be given before or after.
_ANCHOR_KINDS = frozenset({"table", "picture", "shape", "footnote", "endnote", "form-field"})

_FORMAT_NAMES = {
    "bold": "bold",
    "italic": "italic",
    "underline": "underline",
    "fontName": "font",
    "fontSizePt": "size",
    "color": "color",
}

# python-hwpx range refusals -> the agent error a caller can act on.
_RANGE_CODES = {
    "paragraph-range-holds-objects": "unsupported_content",
    "paragraph-range-splits-field": "unsupported_content",
    "paragraph-range-splits-mark": "unsupported_content",
    "paragraph-range-crosses-element": "unsupported_content",
    "paragraph-range-into-itself": "incompatible_parent",
    "paragraph-move-place-unsupported": "incompatible_parent",
    "shape-move-into-itself": "incompatible_parent",
    "shape-move-place-unsupported": "incompatible_parent",
    "shape-copy-document-unsupported": "incompatible_parent",
    "shape-group-member-unsupported": "unsupported_content",
    "shape-not-in-document": "not_found",
    "style-char-pr-missing": "not_found",
    "table-rows-invalid": "not_found",
    "table-rows-merge-crossed": "unsupported_content",
    "table-columns-differ": "incompatible_parent",
    "table-rows-other-document": "incompatible_parent",
    "table-rows-move-other-table": "incompatible_parent",
}


def _core_refusal(exc: ValueError, *, target: str | None) -> AgentContractError:
    """The agent error for a python-hwpx refusal (``HwpxValueError.code``)."""

    code = str(getattr(exc, "code", "") or "")
    agent_code = _RANGE_CODES.get(code)
    if agent_code is None:
        agent_code = "not_found" if "offset" in code or "range" in code else "unsupported_content"
    suggestion = getattr(exc, "suggestion", None)
    return AgentContractError(
        agent_code, str(exc) or code, target=target, suggestion=str(suggestion) if suggestion else None
    )


def _format_changes(document: HwpxDocument, properties: Mapping[str, Any], *, target: str) -> dict[str, Any]:
    """``format_range``/``insert_text`` keyword arguments for the character properties given."""

    changes = {_FORMAT_NAMES[name]: value for name, value in properties.items() if name in _FORMAT_NAMES}
    face = changes.get("font")
    if face is not None and not _font_is_declared(document, face):
        raise AgentContractError(
            "not_found", f"font is not declared by the document: {face!r}", target=f"{target}.fontName"
        )
    return changes


def _object_wrapper(view: HwpxAgentDocument, record: NodeRecord) -> Any:
    """The python-hwpx object of a table, picture or shape record (a picture is projected as its element)."""

    if record.kind == "picture":
        paragraph = view.resolve_record(str(record.parent_path)).native
        return wrap_object(record.native, paragraph)
    return record.native


def _object_offset(view: HwpxAgentDocument, record: NodeRecord) -> int:
    native = _object_wrapper(view, record) if record.kind in _OFFSET_KINDS else record.native
    offset = getattr(native, "offset", None)
    if offset is None and record.place is not None:
        offset = record.place.get("offset")
    if offset is None:
        raise AgentContractError("not_found", "the anchor is not in a paragraph's text", target=record.path)
    return int(offset)


def _offset_in(view: HwpxAgentDocument, paragraph: NodeRecord, position: Mapping[str, Any]) -> tuple[int, NodeRecord | None]:
    """The character offset *position* names in *paragraph*, and its before/after anchor."""

    length = len(paragraph.native.text or "")
    mode = position["mode"]
    if mode == "append":
        return length, None
    if mode == "prepend":
        return 0, None
    if mode == "offset":
        offset = int(position["offset"])
        if offset > length:
            raise AgentContractError(
                "not_found",
                f"offset {offset} is past the paragraph's {length} characters",
                target=paragraph.path,
            )
        return offset, None
    if mode == "index":  # preflight refuses it; kept for a direct caller
        raise AgentContractError("invalid_syntax", "index is not a place in a paragraph", target=paragraph.path)
    anchor = view.resolve_record(str(position["path"]))
    if anchor.parent_path != paragraph.path or anchor.kind not in _ANCHOR_KINDS:
        raise AgentContractError(
            "incompatible_parent",
            "position anchor must be a table, picture, shape, note or form field of the same paragraph",
            target=anchor.path,
        )
    return _object_offset(view, anchor), anchor


# --- text ranges -----------------------------------------------------------------------------


def _paragraph_path(view: HwpxAgentDocument, paragraph: Any) -> str:
    for record in view.records:
        if record.kind == "paragraph" and record.native.element is paragraph.element:
            return record.path
    raise AgentContractError("not_found", "the paragraph left the document")


def _add_text(
    document: HwpxDocument,
    view: HwpxAgentDocument,
    paragraph: NodeRecord,
    properties: Mapping[str, Any],
    position: Mapping[str, Any],
) -> TextRange:
    offset, _anchor = _offset_in(view, paragraph, position)
    native = paragraph.native
    changes = _format_changes(document, properties, target="text")
    before = len(native.text or "")
    try:
        native.insert_text(offset, str(properties.get("text", "")), **changes)
    except ValueError as exc:
        raise _core_refusal(exc, target=paragraph.path) from exc
    return TextRange(native, offset, offset + len(native.text or "") - before)


def _set_text(document: HwpxDocument, record: NodeRecord, properties: Mapping[str, Any]) -> TextRange:
    span: TextRange = record.native
    paragraph = span.paragraph
    end = span.end
    try:
        if "text" in properties:
            before = len(paragraph.text or "")
            paragraph.replace_range(span.start, span.end, str(properties["text"]))
            end = span.end + len(paragraph.text or "") - before
        changes = _format_changes(document, properties, target="text")
        if changes and end > span.start:
            paragraph.format_range(span.start, end, **changes)
    except ValueError as exc:
        raise _core_refusal(exc, target=record.path) from exc
    return TextRange(paragraph, span.start, end)


def _remove_text(record: NodeRecord) -> None:
    span: TextRange = record.native
    try:
        span.paragraph.delete_range(span.start, span.end)
    except ValueError as exc:
        raise _core_refusal(exc, target=record.path) from exc


def _place_text(
    view: HwpxAgentDocument,
    record: NodeRecord,
    paragraph: NodeRecord,
    position: Mapping[str, Any],
    *,
    copy: bool,
) -> TextRange:
    span: TextRange = record.native
    offset, _anchor = _offset_in(view, paragraph, position)
    call = span.paragraph.copy_range if copy else span.paragraph.move_range
    try:
        start, end = call(span.start, span.end, to=paragraph.native, offset=offset)
    except ValueError as exc:
        raise _core_refusal(exc, target=record.path) from exc
    return TextRange(paragraph.native, start, end)


def _text_path(view: HwpxAgentDocument, span: TextRange) -> tuple[str, str]:
    """(path, paragraph path) of a text range after the command."""

    paragraph_path = _paragraph_path(view, span.paragraph)
    return f"{paragraph_path}/text[{span.start}:{span.end}]", paragraph_path


# --- objects at an offset --------------------------------------------------------------------


def _same_offset_followers(
    view: HwpxAgentDocument, paragraph: NodeRecord, offset: int, anchor: NodeRecord
) -> list[Any]:
    """The objects at *offset* of *paragraph* from *anchor* on, in their order (to put back after)."""

    found: list[Any] = []
    seen_anchor = False
    for record in view.records:
        if record.parent_path != paragraph.path or record.kind not in _ANCHOR_KINDS:
            continue
        if record.path == anchor.path:
            seen_anchor = True
        if not seen_anchor:
            continue
        if record.kind not in _OFFSET_KINDS:
            raise AgentContractError(
                "incompatible_parent",
                "only a table, picture or shape can stand behind the new place; give an offset instead",
                target=record.path,
            )
        if _object_offset(view, record) == offset:
            found.append(_object_wrapper(view, record))
    return found


def _move_object(native: Any, paragraph: Any, offset: int | None) -> None:
    try:
        native.move_to(paragraph, offset=offset, keep_order=True)
    except TypeError:  # a table's move_to keeps its order and takes no keep_order
        native.move_to(paragraph, offset=offset)


def _check_v1_end_place(
    view: HwpxAgentDocument,
    paragraph: NodeRecord,
    kind: str,
    position: Mapping[str, Any],
    *,
    leaving: Any = None,
) -> None:
    """Take a v1 ``append``/``prepend`` in a paragraph only where its v1 place is the v2 one.

    v1 put the object after the last (before the first) object of its kind, or at the paragraph's
    end when there was none; v2 puts it at the end of the text (at offset 0), after the objects
    already there.  Where the two places differ the command is refused (``contract_changed``) with
    the offset its v1 place has, rather than done somewhere else without a word (owner, 18차).
    *leaving* is an object that is moved and so is not counted where it stands.
    """

    mode = position["mode"]
    if not position.get("_v1") or mode not in {"append", "prepend"}:
        return
    length = len(paragraph.native.text or "")
    items = [
        record
        for record in view.records
        if record.parent_path == paragraph.path
        and record.kind in _ANCHOR_KINDS
        and (leaving is None or _element(record.native) is not leaving)
    ]
    same = [record for record in items if record.kind == kind]
    if not same:  # v1 appended a new run at the paragraph's end: after everything there
        old_offset = length
        agrees = mode == "append" or length == 0
    elif mode == "append":
        old_offset = _object_offset(view, same[-1])
        agrees = old_offset == length and items[-1] is same[-1]
    else:  # v2 goes after the objects at offset 0, v1 went before the first of its kind
        old_offset = _object_offset(view, same[0])
        agrees = False
    if agrees:
        return
    anchor = same[-1 if mode == "append" else 0].path if same else None
    exact = (
        f'{{"mode": "{"after" if mode == "append" else "before"}", "path": "{anchor}"}}'
        if anchor is not None
        else f'{{"mode": "offset", "offset": {old_offset}}}'
    )
    raise AgentContractError(
        "contract_changed",
        f'position.mode "{mode}" in a paragraph means the {"end" if mode == "append" else "start"} of its text '
        f"since hwpx-automation 8.0; this v1 command's place was offset {old_offset}",
        target=paragraph.path,
        suggestion=f'Use {{"mode": "offset", "offset": {old_offset}}} (or {exact}) for the v1 place, '
        'or send schemaVersion "hwpx.agent-command/v2" for the new one',
    )


def _place_object(
    view: HwpxAgentDocument,
    native: Any,
    paragraph: NodeRecord,
    position: Mapping[str, Any],
    *,
    copy: bool,
    target: str,
) -> Any:
    """Move (or copy) the object *native* to the place *position* names in *paragraph*; return the
    object now there.  ``before`` an object puts that object, and the ones after it at the same
    place, behind the new one again (python-hwpx places after what is already there)."""

    _check_v1_end_place(
        view, paragraph, _identity_kind(_local_name(native.element)), position,
        leaving=None if copy else native.element,
    )
    offset, anchor = _offset_in(view, paragraph, position)
    followers = (
        _same_offset_followers(view, paragraph, offset, anchor)
        if anchor is not None and position["mode"] == "before"
        else []
    )
    if not copy:  # the moved object itself is not put back behind its new place
        followers = [item for item in followers if item.element is not native.element]
    try:
        if copy:
            placed = native.copy_to(paragraph.native, offset=offset)
        else:
            _move_object(native, paragraph.native, offset)
            placed = native
        for follower in followers:
            _move_object(follower, paragraph.native, offset)
    except ValueError as exc:
        raise _core_refusal(exc, target=target) from exc
    if followers and not _precedes(paragraph.native, placed.element, followers[0].element):
        raise AgentContractError(
            "incompatible_parent", "the object could not be put before its anchor", target=target
        )
    return placed


def _precedes(paragraph: Any, first: Any, second: Any) -> bool:
    order = [node for node in paragraph.element.iter() if node is first or node is second]
    return len(order) == 2 and order[0] is first


def _local_name(element: Any) -> str:
    return str(getattr(element, "tag", "")).rsplit("}", 1)[-1]


def _element(native: Any) -> Any:
    return getattr(native, "element", native)


def _require_string(value: Any, name: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise AgentContractError("invalid_syntax", f"{name} must be a string", target=name)
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise AgentContractError("invalid_syntax", f"{name} must be boolean", target=name)
    return value


def _require_number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentContractError("invalid_syntax", f"{name} must be numeric", target=name)
    result = float(value)
    if positive and result <= 0:
        raise AgentContractError("invalid_syntax", f"{name} must be positive", target=name)
    return result


def _require_integer(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgentContractError("invalid_syntax", f"{name} must be an integer", target=name)
    if positive and value <= 0:
        raise AgentContractError("invalid_syntax", f"{name} must be positive", target=name)
    return value


def _require_color(value: Any, name: str) -> str:
    color = _require_string(value, name, allow_empty=False)
    if not _COLOR_PATTERN.fullmatch(color):
        raise AgentContractError("invalid_syntax", f"{name} must be #RRGGBB", target=name)
    return color.upper()


def _require_enum(value: Any, name: str, choices: frozenset[str]) -> str:
    text = _require_string(value, name, allow_empty=False).upper()
    if text not in choices:
        raise AgentContractError(
            "invalid_syntax", f"{name} must be one of {sorted(choices)}", target=name
        )
    return text


def _validate_property_values(kind: str, properties: Mapping[str, Any], *, creating: bool) -> None:
    allowed = (
        _CREATE_PROPERTIES.get(kind, frozenset())
        if creating
        else frozenset(NODE_PROPERTY_CATALOG_V2[kind]["editable"])
    )
    unknown = sorted(set(properties) - allowed)
    if unknown:
        raise AgentContractError(
            "unknown_property",
            f"{kind} does not support properties: {unknown}",
            target=f"{kind}.{unknown[0]}",
        )
    for name, value in properties.items():
        target = f"{kind}.{name}"
        if name in {"text", "value", "altText", "caption", "fontName", "style"}:
            _require_string(value, target)
        elif name in {"bold", "italic", "underline", "breakBefore", "keepWithNext", "readOnly"}:
            _require_bool(value, target)
        elif name in {"fontSizePt", "lineSpacingPercent", "heightMm", "widthMm", "pageWidthMm", "pageHeightMm"}:
            _require_number(value, target, positive=True)
        elif name in {"rowCount", "columnCount", "cellCount"}:
            _require_integer(value, target, positive=True)
        elif name == "color" or name == "backgroundColor":
            _require_color(value, target)
        elif name == "alignment":
            _require_enum(
                value,
                target,
                _TABLE_ALIGNMENTS if kind == "table" else _PARAGRAPH_ALIGNMENTS,
            )
        elif name == "verticalAlignment":
            _require_enum(value, target, _VERTICAL_ALIGNMENTS)
        else:  # pragma: no cover - catalog additions must choose a type above
            raise AgentContractError("unknown_property", f"untyped property: {target}", target=target)


def _validate_header_story_properties(properties: Mapping[str, Any]) -> None:
    unknown = sorted(set(properties) - HEADER_STORY_EDITABLE_PROPERTIES)
    if unknown:
        raise AgentContractError(
            "unknown_property",
            f"header does not support properties: {unknown}",
            target=f"header.{unknown[0]}",
        )
    if "text" not in properties:
        raise AgentContractError(
            "invalid_syntax", "existing header set requires text", target="header.text"
        )
    _require_string(properties["text"], "header.text")


def _preflight_reference_kind(value: str, alias_kinds: Mapping[str, Mapping[str, str]]) -> str:
    if value.startswith("$"):
        command_id, field = value[1:].split(".", 1)
        try:
            return alias_kinds[command_id][field]
        except KeyError as exc:  # validate_agent_batch already checks ordering
            raise AgentContractError("not_found", f"unknown command alias: {value}") from exc
    story = try_parse_header_story_path(value)
    if story is not None:
        return story.kind
    parsed = parse_path(value)
    return parsed.segments[-1].kind if parsed.segments else "document"


def _preflight_parent_kind(value: str, alias_kinds: Mapping[str, Mapping[str, str]]) -> str:
    if value.startswith("$"):
        command_id, field = value[1:].split(".", 1)
        try:
            return alias_kinds[command_id]["parentPath" if field == "path" else field]
        except KeyError:
            return "document"
    story = try_parse_header_story_path(value)
    if story is not None:
        return "section"
    parsed = parse_path(value)
    return parsed.segments[-2].kind if len(parsed.segments) > 1 else "document"


#: Placed in a paragraph at a character offset (agent-command v2); notes keep v1 places (asks10c).
_IN_PARAGRAPH_KINDS = frozenset({"text", *_OFFSET_KINDS})


def _preflight_position(
    kind: str, destination_kind: str, command: Mapping[str, Any], alias_kinds: Mapping[str, Mapping[str, str]]
) -> None:
    """Refuse the v1 places whose meaning changed in a paragraph (design 6), and an offset elsewhere."""

    position = command.get("position") or {"mode": "append"}
    mode = position["mode"]
    in_paragraph = destination_kind == "paragraph" and kind in _IN_PARAGRAPH_KINDS
    target = f"{command['commandId']}.position"
    if mode in {"before", "after"} and _preflight_reference_kind(str(position["path"]), alias_kinds) == "run":
        raise contract_changed(CONTRACT_CHANGED_RUN_ANCHOR, target=target)
    if mode == "index" and in_paragraph:
        raise contract_changed(CONTRACT_CHANGED_INDEX, target=target)
    if mode == "offset" and not in_paragraph:
        raise AgentContractError(
            "invalid_syntax",
            f"position mode offset places text, a table, a picture or a shape in a paragraph, not a {kind}",
            target=target,
        )


def _preflight_add_command(command: Mapping[str, Any], alias_kinds: dict[str, dict[str, str]]) -> None:
    kind = command["kind"]
    if kind == "run":
        raise contract_changed(CONTRACT_CHANGED_RUN, target=command["commandId"])
    if kind not in _ADD_PARENTS:
        raise AgentContractError(
            "unsupported_operation", f"add is unsupported for {kind}", target=command["commandId"]
        )
    _validate_property_values(kind, command["properties"], creating=True)
    if kind == "table" and not {"rowCount", "columnCount"} <= set(command["properties"]):
        raise AgentContractError(
            "invalid_syntax", "table add requires rowCount and columnCount", target=command["commandId"]
        )
    if kind == "row" and "cellCount" not in command["properties"]:
        raise AgentContractError(
            "invalid_syntax", "row add requires cellCount", target=command["commandId"]
        )
    destination_kind = _preflight_reference_kind(command["parent"], alias_kinds)
    expected_parent = _ADD_PARENTS[kind]
    if destination_kind != expected_parent:
        raise AgentContractError(
            "incompatible_parent",
            f"{kind} requires a {expected_parent} parent, not {destination_kind}",
            target=command["commandId"],
        )
    _preflight_position(kind, destination_kind, command, alias_kinds)
    alias_kinds[command["commandId"]] = {
        "path": kind,
        "parentPath": destination_kind,
    }


def _preflight_mutate_command(
    op: str, command: Mapping[str, Any], alias_kinds: dict[str, dict[str, str]]
) -> None:
    source_kind = _preflight_reference_kind(command["path"], alias_kinds)
    if source_kind == HEADER_STORY_KIND:
        if op != "set":
            raise AgentContractError(
                "unsupported_operation",
                f"{op} is unsupported for {source_kind}",
                target=command["commandId"],
            )
        _validate_header_story_properties(command["properties"])
        alias_kinds[command["commandId"]] = {
            "path": source_kind,
            "parentPath": "section",
        }
        return
    if source_kind == "run" and op in {"remove", "copy"}:
        raise contract_changed(CONTRACT_CHANGED_RUN, target=command["commandId"])
    if op not in NODE_PROPERTY_CATALOG_V2[source_kind]["operations"]:
        raise AgentContractError(
            "unsupported_operation",
            f"{op} is unsupported for {source_kind}",
            target=command["commandId"],
        )
    if op == "set":
        _validate_property_values(source_kind, command["properties"], creating=False)
    destination_kind = _preflight_parent_kind(command["path"], alias_kinds)
    if op in {"move", "copy"}:
        destination_kind = _preflight_reference_kind(command["parent"], alias_kinds)
        move_parent = _MOVE_COPY_PARENTS.get(source_kind)
        if destination_kind != move_parent:
            raise AgentContractError(
                "incompatible_parent",
                f"{source_kind} requires a {move_parent} parent, not {destination_kind}",
                target=command["commandId"],
            )
        _preflight_position(source_kind, destination_kind, command, alias_kinds)
    alias_kinds[command["commandId"]] = {
        "path": source_kind,
        "parentPath": destination_kind,
    }


def _preflight(batch: Mapping[str, Any]) -> None:
    """Reject the complete static command matrix before the first mutation."""

    alias_kinds: dict[str, dict[str, str]] = {}

    for command in batch["commands"]:
        op = command["op"]
        if op == "add":
            _preflight_add_command(command, alias_kinds)
            continue
        _preflight_mutate_command(op, command, alias_kinds)


def _resolve_alias(value: str, aliases: Mapping[str, Mapping[str, str]]) -> str:
    if not value.startswith("$"):
        return value
    command_id, field = value[1:].split(".", 1)
    try:
        return aliases[command_id][field]
    except KeyError as exc:
        raise AgentContractError(
            "not_found", f"command alias is unavailable: {value}", target=value
        ) from exc


def _resolved_position(
    position: Mapping[str, Any], aliases: Mapping[str, Mapping[str, str]], command: Mapping[str, Any]
) -> dict[str, Any]:
    result = dict(position)
    if "path" in result:
        result["path"] = _resolve_alias(str(result["path"]), aliases)
    if command.get("schemaVersion") == AGENT_COMMAND_SCHEMA_V1:
        result["_v1"] = True  # private: the command was written in agent-command v1
    return result


def _record_for_native(view: HwpxAgentDocument, native_or_element: Any) -> NodeRecord:
    target = _element(native_or_element)
    for record in view.records:
        if _element(record.native) is target:
            return record
    raise AgentContractError("not_found", "mutated node was not present after projection")


def _ensure_operation(record: NodeRecord, operation: str) -> None:
    if operation not in NODE_PROPERTY_CATALOG_V2[record.kind]["operations"]:
        raise AgentContractError(
            "unsupported_operation",
            f"{operation} is unsupported for {record.kind}",
            target=record.path,
        )


def _ensure_parent(record: NodeRecord, *, source_kind: str, operation: str) -> None:
    expected = _ADD_PARENTS.get(source_kind) if operation == "add" else _MOVE_COPY_PARENTS.get(source_kind)
    if expected != record.kind:
        raise AgentContractError(
            "incompatible_parent",
            f"{source_kind} requires a {expected} parent, not {record.kind}",
            target=record.path,
        )


def _sibling_elements(view: HwpxAgentDocument, parent: NodeRecord, kind: str) -> list[Any]:
    return [
        _element(record.native)
        for record in view.records
        if record.parent_path == parent.path and record.kind == kind
    ]


def _insertion_index(
    view: HwpxAgentDocument,
    parent: NodeRecord,
    kind: str,
    position: Mapping[str, Any],
    *,
    siblings: list[Any] | None = None,
) -> int:
    siblings = list(siblings if siblings is not None else _sibling_elements(view, parent, kind))
    mode = position["mode"]
    if mode == "append":
        return len(siblings)
    if mode == "prepend":
        return 0
    if mode == "index":
        index = int(position["index"])
        if index > len(siblings) + 1:
            raise AgentContractError(
                "not_found", f"one-based insertion index {index} is out of range", target=parent.path
            )
        return index - 1
    anchor = view.resolve_record(str(position["path"]))
    if anchor.parent_path != parent.path or anchor.kind != kind:
        raise AgentContractError(
            "incompatible_parent", "position anchor is not a compatible sibling", target=anchor.path
        )
    try:
        index = siblings.index(_element(anchor.native))
    except ValueError as exc:
        raise AgentContractError("not_found", "position anchor is unavailable", target=anchor.path) from exc
    return index + (1 if mode == "after" else 0)


def _move_paragraph_into_place(
    view: HwpxAgentDocument, parent: NodeRecord, paragraph: Any, position: Mapping[str, Any]
) -> None:
    """Put *paragraph* (just appended to *parent*) at *position* among the parent's paragraphs.

    python-hwpx's ``move_before``/``move_after`` move it; before a section's first paragraph the
    section settings (``hp:secPr``) go along to the new first paragraph, as Hancom keeps them.
    """

    siblings = [
        record.native for record in view.records if record.parent_path == parent.path and record.kind == "paragraph"
    ]
    index = _insertion_index(
        view, parent, "paragraph", position, siblings=[_element(sibling) for sibling in siblings]
    )
    if index < len(siblings):
        paragraph.move_before(siblings[index])
    elif siblings and siblings[-1] != paragraph:
        paragraph.move_after(siblings[-1])


def _table_caption(table: Any, value: str) -> None:
    """Set a table's caption text through python-hwpx's own text setters.

    A missing caption is created by ``table.set_caption``. An existing one keeps
    its paragraph, run and controls (the ``표 1`` auto number): the first run
    that holds text takes the value through ``HwpxOxmlRun.text`` and every other
    text run is emptied. Those setters write a line break as ``hp:lineBreak``
    and a tab as ``hp:tab``, strip characters XML cannot carry, and drop the
    caption paragraph's line layout cache (audit ENG-08) -- a cache measured
    for the old caption makes Hancom squeeze the new text into the old lines.
    """

    caption = table.caption
    if caption is None:
        table.set_caption(value)
        table.mark_dirty()
        return
    text_runs = [run for paragraph in caption.paragraphs for run in paragraph.runs if run.has_text_element]
    if not text_runs:
        raise AgentContractError("unsupported_content", "table caption has no editable text node")
    text_runs[0].text = value
    for run in text_runs[1:]:
        if run.text:
            run.text = ""
    for paragraph in caption.paragraphs:
        # The setters clear the cache only when the text changed; a caption is
        # rewritten here on request, so never leave a cache behind it (nor in the paragraph holding the table).
        paragraph.clear_layout_cache()
    table.mark_dirty()


def _global_paragraph_index(document: HwpxDocument, paragraph: Any) -> int:
    try:
        return document.paragraphs.index(paragraph)  # paragraph objects are equal per element
    except ValueError:
        raise AgentContractError("not_found", "paragraph is detached") from None


def _style_id(document: HwpxDocument, value: str) -> str:
    if value in document.styles:
        return value
    matches = [style_id for style_id, style in document.styles.items() if style.name == value]
    if len(matches) != 1:
        raise AgentContractError(
            "not_found" if not matches else "ambiguous_target",
            f"paragraph style is not uniquely resolvable: {value!r}",
            target="paragraph.style",
        )
    return matches[0]


def _apply_header_story_set(
    binding: HeaderStoryBinding, properties: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply the bounded existing-header mutation through its OXML owner."""

    _validate_header_story_properties(properties)
    try:
        binding.native.set_simple_text_preserving(properties["text"])
    except AgentContractError:
        raise
    except ValueError as exc:
        # The OXML owner uses ValueError for rich/control-bearing or otherwise
        # structurally unsafe headers.  Do not let it degrade to the generic
        # invariant envelope or fall back to the destructive whole-story setter.
        message = str(exc) or "header content cannot be edited losslessly"
        lowered = message.lower()
        code = (
            "ambiguous_target"
            if "ambiguous" in lowered
            else "not_found"
            if "not found" in lowered
            else "unsupported_content"
        )
        raise AgentContractError(
            code,
            message,
            target=binding.path,
        ) from exc
    return {
        "text": {
            "before": binding.text,
            "after": properties["text"],
        }
    }


_LINE_BREAKS = re.compile("\r\n|\r|\n")


def _set_paragraph_text(native: Any, value: str) -> None:
    """Replace a paragraph's text, keeping its runs: python-hwpx writes a tab as ``hp:tab`` and a
    line break as ``hp:lineBreak`` (asks10b, N11) and drops the paragraph's line layout cache."""

    native.set_text_preserving_runs(_LINE_BREAKS.sub("\n", value))


def _apply_set_paragraph(document: HwpxDocument, native: Any, properties: Mapping[str, Any]) -> None:
    if "text" in properties:
        try:
            _set_paragraph_text(native, properties["text"])
        except ValueError as exc:
            raise AgentContractError(
                "unsupported_content", str(exc), target="paragraph.text"
            ) from exc
    if "style" in properties:
        native.style_id_ref = _style_id(document, properties["style"])
    format_kwargs: dict[str, Any] = {}
    if "alignment" in properties:
        format_kwargs["alignment"] = properties["alignment"]
    if "lineSpacingPercent" in properties:
        format_kwargs["line_spacing"] = properties["lineSpacingPercent"]
    if "keepWithNext" in properties:
        format_kwargs["keep_with_next"] = properties["keepWithNext"]
    if "breakBefore" in properties:
        format_kwargs["page_break_before"] = properties["breakBefore"]
    if format_kwargs:
        document.styles.apply_paragraph_format(
            paragraph=_global_paragraph_index(document, native), **format_kwargs
        )


_FONT_LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")


def _font_is_declared(document: HwpxDocument, face: str) -> bool:
    """Whether any language block of the document declares *face*."""

    target = str(face).strip()
    return bool(target) and any(
        font.face == target for lang in _FONT_LANGS for font in document.styles.fonts(lang).values()
    )


def _apply_set_run(document: HwpxDocument, native: Any, properties: Mapping[str, Any]) -> None:
    if "text" in properties:
        native.text = properties["text"]
    style = native.style
    child_attrs = style.child_attributes if style is not None else {}
    flags = {
        "bold": "bold" in child_attrs,
        "italic": "italic" in child_attrs,
        "underline": child_attrs.get("underline", {}).get("type", "NONE").upper() != "NONE",
    }
    for name in flags:
        if name in properties:
            flags[name] = properties[name]
    if set(properties) - {"text"}:
        requested_font = properties.get("fontName")
        if requested_font is not None and not _font_is_declared(document, requested_font):
            raise AgentContractError(
                "not_found", f"font is not declared by the document: {requested_font!r}", target="run.fontName"
            )
        style_id = document.styles.ensure_run(
            **flags,
            color=properties.get("color"),
            font=requested_font,
            size=properties.get("fontSizePt"),
            base_char_pr_id_ref=native.char_pr_id_ref,
        )
        native.char_pr_id_ref = style_id


def _apply_set_table(native: Any, properties: Mapping[str, Any], record: NodeRecord) -> None:
    if "caption" in properties:
        _table_caption(native, properties["caption"])
    if "alignment" in properties:
        try:
            native.set_position(horizontal_alignment=properties["alignment"].upper())
        except ValueError as exc:  # python-hwpx's HwpxValueError
            if getattr(exc, "code", None) == "shape-position-unsupported":
                raise AgentContractError(
                    "unsupported_content", "table has no position element", target=record.path
                ) from exc
            raise


def _apply_set_row(native: Any, properties: Mapping[str, Any]) -> None:
    height = round(_require_number(properties["heightMm"], "row.heightMm", positive=True) * _HWP_UNITS_PER_MM)
    for cell in native.cells:
        cell.set_size(height=height)


def _apply_set_cell(native: Any, properties: Mapping[str, Any], record: NodeRecord) -> None:
    if "text" in properties:
        native.text = properties["text"]
    if "verticalAlignment" in properties:
        if not native.paragraphs:  # a cell without hp:subList: refused as before (the setter would add one)
            raise AgentContractError("unsupported_content", "cell has no subList", target=record.path)
        native.vertical_alignment = properties["verticalAlignment"].upper()
        native.table.mark_dirty()  # as before: the section is written again even when the value was already set
    if "backgroundColor" in properties:
        row, column = native.address
        native.table.set_cell_shading(row, column, properties["backgroundColor"])


def _apply_set_form_field(document: HwpxDocument, native: Any, properties: Mapping[str, Any], record: NodeRecord) -> None:
    if "value" in properties:
        document.fields.fill(properties["value"], index=int(native["index"]))
    if "readOnly" in properties:
        form_field = native.get("_field")
        if form_field is None:
            raise AgentContractError(
                "unsupported_content", "form-field control is incomplete", target=record.path
            )
        # python-hwpx writes Hancom's own editable="1"/"0" and marks the part changed.
        form_field.editable = not properties["readOnly"]


def _apply_set_picture_shape(view: HwpxAgentDocument | None, record: NodeRecord, properties: Mapping[str, Any]) -> None:
    """Alternative text through python-hwpx's ``description``: ``hp:shapeComment`` where Hancom
    writes it (after ``outMargin``/``caption``); a group member is refused, as Hancom keeps none."""

    if view is None:
        raise AgentContractError("unsupported_operation", "altText needs the projected document", target=record.path)
    try:
        _object_wrapper(view, record).description = properties["altText"]
    except ValueError as exc:
        raise _core_refusal(exc, target=record.path) from exc


def _set_result_summary(record: NodeRecord, properties: Mapping[str, Any]) -> dict[str, Any]:
    return {name: {"before": record.summary.get(name), "after": value} for name, value in properties.items()}


def _apply_set(
    document: HwpxDocument,
    record: NodeRecord,
    properties: Mapping[str, Any],
    view: HwpxAgentDocument | None = None,
) -> dict[str, Any]:
    _ensure_operation(record, "set")
    _validate_property_values(record.kind, properties, creating=False)
    native = record.native
    kind = record.kind

    if kind == "paragraph":
        _apply_set_paragraph(document, native, properties)
    elif kind == "run":
        _apply_set_run(document, native, properties)
    elif kind == "table":
        _apply_set_table(native, properties, record)
    elif kind == "row":
        _apply_set_row(native, properties)
    elif kind == "cell":
        _apply_set_cell(native, properties, record)
    elif kind == "form-field":
        _apply_set_form_field(document, native, properties, record)
    elif kind in {"picture", "shape"}:
        _apply_set_picture_shape(view, record, properties)
    elif kind == "memo":
        native.text = properties["text"]
    elif kind in {"footnote", "endnote"}:
        native.text = properties["text"]
    else:
        raise AgentContractError("unsupported_operation", f"set is unsupported for {kind}", target=record.path)
    return _set_result_summary(record, properties)


def _apply_create_properties(
    document: HwpxDocument, record: NodeRecord, properties: Mapping[str, Any]
) -> dict[str, Any]:
    # Geometry used to create tables/rows/sections is already present.  Apply the
    # remaining editable subset through the exact same set compiler.
    editable = set(NODE_PROPERTY_CATALOG_V2[record.kind]["editable"])
    setters = {name: value for name, value in properties.items() if name in editable}
    return _apply_set(document, record, setters) if setters else {}


def _add_in_paragraph(
    document: HwpxDocument,
    view: HwpxAgentDocument,
    parent: NodeRecord,
    kind: str,
    properties: Mapping[str, Any],
    position: Mapping[str, Any],
) -> Any:
    """Text goes in with ``insert_text`` (N1). python-hwpx puts a note's mark at the paragraph's end
    (asks10c, N6); another place moves it there as a move does (before an object puts the objects at
    that place behind it again)."""

    if kind == "text":
        return _add_text(document, view, parent, properties, position)
    add = document.notes.add_footnote if kind == "footnote" else document.notes.add_endnote
    try:
        created = add(str(properties.get("text", "")), paragraph=parent.native)
    except ValueError as exc:
        raise _core_refusal(exc, target=parent.path) from exc
    if position["mode"] != "append":
        _place_object(view, created, parent, position, copy=False, target=parent.path)
    return created


def _add(
    document: HwpxDocument,
    view: HwpxAgentDocument,
    parent: NodeRecord,
    kind: str,
    properties: Mapping[str, Any],
    position: Mapping[str, Any],
) -> Any:
    _ensure_parent(parent, source_kind=kind, operation="add")
    if kind == "section":
        if position["mode"] != "append":
            raise AgentContractError(
                "unsupported_operation", "section insertion is append-only in v1", target=parent.path
            )
        created = document.add_section()
        size_kwargs: dict[str, int] = {}
        if "pageWidthMm" in properties:
            size_kwargs["width"] = round(properties["pageWidthMm"] * _HWP_UNITS_PER_MM)
        if "pageHeightMm" in properties:
            size_kwargs["height"] = round(properties["pageHeightMm"] * _HWP_UNITS_PER_MM)
        if size_kwargs:
            created.properties.set_page_size(
                width=size_kwargs.get("width"),
                height=size_kwargs.get("height"),
            )
        return created
    if kind == "paragraph":
        created = parent.native.add_paragraph(str(properties.get("text", "")))
        # add_paragraph appends; move it for all other positions.
        if position["mode"] != "append":
            _move_paragraph_into_place(view, parent, created, position)
        return created
    if kind in {"text", "footnote", "endnote"}:  # placed at a character offset (agent-command v2)
        return _add_in_paragraph(document, view, parent, kind, properties, position)
    if kind == "table":
        _check_v1_end_place(view, parent, "table", position)
        created = parent.native.add_table(
            int(properties["rowCount"]),
            int(properties["columnCount"]),
            width=(round(properties["widthMm"] * _HWP_UNITS_PER_MM) if "widthMm" in properties else None),
        )
        if position["mode"] != "append":
            _place_object(view, created, parent, position, copy=False, target=parent.path)
        return created
    if kind == "row":
        table = parent.native
        if int(properties["cellCount"]) != table.column_count:
            raise AgentContractError(
                "incompatible_parent", "row cellCount must equal table columnCount", target=parent.path
            )
        # python-hwpx inserts an empty row as Hancom's 줄 추가 does: its cells take the format of
        # the row beside it, and rowCnt, cell addresses and merged cells follow.
        index = _insertion_index(view, parent, kind, position)
        if index <= 0:
            table.insert_rows(0, side="above")
        else:
            table.insert_rows(index - 1, side="below")
        return table.rows[max(index, 0)].element
    raise AgentContractError("unsupported_operation", f"add is unsupported for {kind}")


def _table_has_vertical_merge(table: Any) -> bool:
    return any(cell.span[0] > 1 for row in table.rows for cell in row.cells)


def _remove(view: HwpxAgentDocument, record: NodeRecord) -> None:
    _ensure_operation(record, "remove")
    native = record.native
    if record.kind == "paragraph":
        native.remove()
    elif record.kind == "text":
        _remove_text(record)
    elif record.kind == "table":
        native.remove(remove_orphaned=False)
    elif record.kind == "row":
        table = native.table
        if len(table.rows) <= 1:
            raise AgentContractError("invariant_violation", "a table must retain one row", target=record.path)
        if _table_has_vertical_merge(table):
            raise AgentContractError(
                "unsupported_content", "row removal with vertical merges is unsupported", target=record.path
            )
        table.delete_rows(table.rows.index(native))
    elif record.kind == "picture":
        # python-hwpx removes it as Hancom does (an emptied run goes, the caches of the paragraphs
        # holding it go); the image stays in the package as before (N15).
        try:
            _object_wrapper(view, record).remove(remove_orphaned=False)
        except ValueError as exc:
            raise _core_refusal(exc, target=record.path) from exc
    elif record.kind == "shape":
        native.remove(remove_orphaned=False)
    elif record.kind == "memo":
        native.remove()
    elif record.kind in {"footnote", "endnote"}:
        native.remove()
    else:
        raise AgentContractError(
            "unsupported_operation", f"remove is unsupported for {record.kind}", target=record.path
        )


def _move_paragraph(
    view: HwpxAgentDocument,
    source: NodeRecord,
    parent: NodeRecord,
    siblings: list[Any],
    anchor_index: int,
) -> Any:
    """Move a section paragraph beside one of *parent*'s other paragraphs with python-hwpx.

    ``move_before``/``move_after`` keep the section settings (``hp:secPr``) in each section's first
    paragraph, as Hancom reads them: the first paragraph hands them to the next one when it leaves,
    and a paragraph moved in front of the first takes them. They also drop the moved paragraph's
    line layout cache. The only paragraph of its section stays put. A refusal (the last paragraph of a section) is an ``incompatible_parent``.
    """

    paragraphs = {
        _element(record.native): record.native
        for record in view.records
        if record.parent_path == parent.path and record.kind == "paragraph"
    }
    try:
        if not siblings:  # the section's only paragraph stays where it is
            return _element(source.native)
        if anchor_index >= len(siblings):
            source.native.move_after(paragraphs[siblings[-1]])
        else:
            source.native.move_before(paragraphs[siblings[anchor_index]])
    except ValueError as exc:  # python-hwpx HwpxValueError
        if getattr(exc, "code", None) is None:
            raise
        raise AgentContractError("incompatible_parent", str(exc), target=source.path) from exc
    parent.native.mark_dirty()
    return _element(source.native)


def _move_in_paragraph(
    view: HwpxAgentDocument, source: NodeRecord, parent: NodeRecord, position: Mapping[str, Any]
) -> Any:
    """Move text or an object to a character offset (agent-command v2) with python-hwpx."""

    if source.kind == "text":
        return _place_text(view, source, parent, position, copy=False)
    native = _object_wrapper(view, source)
    _place_object(view, native, parent, position, copy=False, target=source.path)
    return native


def _move(
    view: HwpxAgentDocument,
    source: NodeRecord,
    parent: NodeRecord,
    position: Mapping[str, Any],
) -> Any:
    _ensure_operation(source, "move")
    _ensure_parent(parent, source_kind=source.kind, operation="move")
    if source.kind in _IN_PARAGRAPH_KINDS:
        return _move_in_paragraph(view, source, parent, position)
    if source.path == parent.path or parent.path.startswith(source.path.rstrip("/") + "/"):
        raise AgentContractError(
            "incompatible_parent", "a node cannot move into its own subtree", target=parent.path
        )
    if source.kind == "row":
        return _move_row(view, source, parent, position)

    element = _element(source.native)
    siblings = _sibling_elements(view, parent, source.kind)
    # Resolve before detaching so before/after anchors still exist.  Moving to an
    # explicit index uses the final sibling list after the source disappears.
    anchor_index = _insertion_index(view, parent, source.kind, position, siblings=siblings)
    if element in siblings:
        old_index = siblings.index(element)
        siblings.pop(old_index)
        if position["mode"] in {"append", "prepend", "index"}:
            anchor_index = _insertion_index(view, parent, source.kind, position, siblings=siblings)
        elif old_index < anchor_index:
            anchor_index -= 1
    return _move_paragraph(view, source, parent, siblings, anchor_index)


def _row_place(
    view: HwpxAgentDocument, source: NodeRecord, parent: NodeRecord, position: Mapping[str, Any]
) -> int:
    """The row number of *parent* a row goes in front of, counted before it leaves (python-hwpx ``to``).

    ``index`` is the one-based place among the rows once the row has left (v1's meaning); the other
    modes name a place among the rows as they are."""

    siblings = _sibling_elements(view, parent, "row")
    element = _element(source.native)
    if position["mode"] != "index" or element not in siblings:
        return _insertion_index(view, parent, "row", position, siblings=siblings)
    old_index = siblings.index(element)
    final = _insertion_index(view, parent, "row", position, siblings=[row for row in siblings if row is not element])
    return final if final < old_index else final + 1


def _move_row(
    view: HwpxAgentDocument, source: NodeRecord, parent: NodeRecord, position: Mapping[str, Any]
) -> Any:
    """Move a row with python-hwpx (asks10d, N10): ``move_rows`` in its table (the row keeps its ids);
    into another table of the same columns, ``copy_rows(source=)`` and then ``delete_rows`` -- the two
    steps python-hwpx gives for it, so that row's cells get fresh ids there, as a copy's do."""

    table = source.native.table
    row = table.rows.index(source.native)
    to = _row_place(view, source, parent, position)
    try:
        if _element(parent.native) is _element(table):
            return table.move_rows(row, to=to)[0]
        placed = parent.native.copy_rows(row, to=to, source=table)
        table.delete_rows(row)
    except ValueError as exc:
        raise _core_refusal(exc, target=source.path) from exc
    return placed[0]


def _identity_kind(local: str) -> str:
    return {
        "p": "paragraph",
        "tbl": "table",
        "pic": "picture",
        "memo": "memo",
        "footNote": "footnote",
        "endNote": "endnote",
        "fieldBegin": "form-field",
    }.get(local, "shape" if local in _SHAPE_KINDS else local)


def _identity_attribute_names(local: str, node: Any) -> tuple[str, ...]:
    if local in {"p", "tbl", "pic", "memo", "fieldBegin", *_SHAPE_KINDS}:
        return tuple(name for name in ("id", "instid", "instId") if node.get(name) is not None)
    if local in {"footNote", "endNote"}:
        # 정본 속성명은 실한컴이 쓰는 소문자 "instid"; "instId"는 과거 코어
        # 저작이 방출한 카멜케이스 산출물 호환(재발급 대상 유지). #101
        return tuple(
            name for name in ("instid", "instId", "id") if node.get(name) is not None
        )
    return ()


def _identities(root: Any) -> list[tuple[str, str, str]]:
    """(local name, attribute, value) of the copyable identities under *root*, in document order
    (nothing inside a note: Hancom keeps its paragraphs at id 0)."""

    found: list[tuple[str, str, str]] = []

    def walk(node: Any, inside_note: bool) -> None:
        local = _local_name(node)
        if not inside_note:
            found.extend((local, name, str(node.get(name))) for name in _identity_attribute_names(local, node))
        for child in node:
            walk(child, inside_note or local in _NOTE_TAGS)

    walk(root, False)
    return found


def _copied_identities(source: Any, copy: Any) -> list[dict[str, str]]:
    """The fresh ids python-hwpx gave a copy (N14), paired in order with the source's, for
    ``generatedIdentities`` as the v1 copy reported them."""

    changes: list[dict[str, str]] = []
    for (local, name, old), (copy_local, copy_name, new) in zip(_identities(source), _identities(copy)):
        if (local, name) != (copy_local, copy_name):
            break
        if old != new:
            changes.append({"kind": _identity_kind(local), "attribute": name, "old": old, "new": new})
    return changes


def _copy_node(
    document: HwpxDocument,
    view: HwpxAgentDocument,
    source: NodeRecord,
    parent: NodeRecord,
    position: Mapping[str, Any],
) -> tuple[Any, list[dict[str, str]]]:
    _ensure_operation(source, "copy")
    _ensure_parent(parent, source_kind=source.kind, operation="copy")
    if source.kind == "text":
        return _place_text(view, source, parent, position, copy=True), []
    if source.kind in _OFFSET_KINDS:
        original = _object_wrapper(view, source)
        copied = _place_object(view, original, parent, position, copy=True, target=source.path)
        return copied, _copied_identities(original.element, copied.element)
    if source.kind == "paragraph":
        return _copy_paragraph(view, source, parent, position)
    if source.kind == "memo":
        return _copy_memo(document, source, parent)
    if source.kind != "row":
        raise AgentContractError("unsupported_operation", f"copy is unsupported for {source.kind}")
    # python-hwpx copies the row with fresh ids for what it holds (asks10d, N10); a merged cell
    # crossing the row's edge or the place is refused there (table-rows-merge-crossed).
    table = source.native.table
    to = _insertion_index(view, parent, "row", position)
    try:
        placed = parent.native.copy_rows(
            table.rows.index(source.native),
            to=to,
            source=None if _element(parent.native) is _element(table) else table,
        )
    except ValueError as exc:
        raise _core_refusal(exc, target=source.path) from exc
    return placed[0], _copied_identities(_element(source.native), _element(placed[0]))


def _copy_paragraph(
    view: HwpxAgentDocument, source: NodeRecord, parent: NodeRecord, position: Mapping[str, Any]
) -> tuple[Any, list[dict[str, str]]]:
    """Copy a section paragraph beside one of *parent*'s paragraphs with python-hwpx's
    ``copy_to`` (N9): fresh ids for it and what it holds, no line layout cache, a memo of its own."""

    siblings = [
        record.native for record in view.records if record.parent_path == parent.path and record.kind == "paragraph"
    ]
    index = _insertion_index(view, parent, "paragraph", position, siblings=[_element(item) for item in siblings])
    try:
        if index < len(siblings):
            copied = source.native.copy_to(siblings[index], before=True)
        else:
            copied = source.native.copy_to(siblings[-1])
    except ValueError as exc:
        raise _core_refusal(exc, target=source.path) from exc
    return copied, _copied_identities(_element(source.native), _element(copied))


def _copy_memo(
    document: HwpxDocument, source: NodeRecord, parent: NodeRecord
) -> tuple[Any, list[dict[str, str]]]:
    """Copy a memo as a new memo on the same paragraph.

    python-hwpx 7.0 keeps a memo only in its MEMO field (as Hancom 2024 does) and
    refuses to save one that is not anchored, so a copy is a second memo field on
    the source memo's paragraph, made by ``doc.notes.add_memo``. The 6.x copy, an
    ``hp:memogroup`` entry with no field, is one Hancom drops on its next save.
    """

    memo = source.native
    anchor = memo.paragraph
    if anchor is None:
        raise AgentContractError(
            "unsupported_content", "a memo that is not anchored to a paragraph cannot be copied", target=source.path
        )
    if anchor.section is not parent.native:
        raise AgentContractError(
            "incompatible_parent", "a memo copy stays in the section of its paragraph", target=parent.path
        )
    attributes = memo.attributes
    author = attributes.get("Author") or attributes.get("author") or None
    copied = document.notes.add_memo(memo.text, paragraph=anchor, author=author)
    identity_map = [{"kind": "memo", "attribute": "id", "old": str(memo.id or ""), "new": str(copied.id or "")}]
    return copied.element, identity_map


def _dispatch_command_op(
    document: HwpxDocument,
    view: HwpxAgentDocument,
    command: Mapping[str, Any],
    aliases: dict[str, dict[str, str]],
    input_revision: str,
) -> tuple[str | None, str | None, dict[str, Any], list[dict[str, str]], Any, HeaderStoryBinding | None]:
    """Apply one command's op and return its raw effects.

    Returns (resolved_path, parent_path, changed, generated, target_native, story_before).
    """

    op = command["op"]
    resolved_path: str | None = None
    parent_path: str | None = None
    changed: dict[str, Any] = {}
    generated: list[dict[str, str]] = []
    target_native: Any | None = None
    story_before: HeaderStoryBinding | None = None
    if op == "set":
        resolved_path = _resolve_alias(command["path"], aliases)
        story_path = try_parse_header_story_path(resolved_path)
        if story_path is not None:
            story_before = view._resolve_header_story(story_path, expected_revision=input_revision)
            changed = _apply_header_story_set(story_before, command["properties"])
        else:
            record = view.resolve_record(resolved_path, expected_revision=input_revision)
            if record.kind == "text":
                _ensure_operation(record, "set")
                _validate_property_values("text", command["properties"], creating=False)
                target_native = _set_text(document, record, command["properties"])
                changed = _set_result_summary(record, command["properties"])
            else:
                changed = _apply_set(document, record, command["properties"], view)
                target_native = record.native
    elif op == "add":
        parent_path = _resolve_alias(command["parent"], aliases)
        parent = view.resolve_record(parent_path, expected_revision=input_revision)
        position = _resolved_position(command["position"], aliases, command)
        target_native = _add(document, view, parent, command["kind"], command["properties"], position)
        if not isinstance(target_native, TextRange):  # a text range is made with its properties
            created_view = HwpxAgentDocument.from_document(document, revision=input_revision)
            created_record = _record_for_native(created_view, target_native)
            changed = _apply_create_properties(document, created_record, command["properties"])
    elif op == "remove":
        resolved_path = _resolve_alias(command["path"], aliases)
        record = view.resolve_record(resolved_path, expected_revision=input_revision)
        parent_path = record.parent_path
        _remove(view, record)
        target_native = None
    elif op == "move":
        resolved_path = _resolve_alias(command["path"], aliases)
        parent_path = _resolve_alias(command["parent"], aliases)
        source = view.resolve_record(resolved_path, expected_revision=input_revision)
        parent = view.resolve_record(parent_path, expected_revision=input_revision)
        position = _resolved_position(command["position"], aliases, command)
        target_native = _move(view, source, parent, position)
    else:  # copy
        resolved_path = _resolve_alias(command["path"], aliases)
        parent_path = _resolve_alias(command["parent"], aliases)
        source = view.resolve_record(resolved_path, expected_revision=input_revision)
        parent = view.resolve_record(parent_path, expected_revision=input_revision)
        position = _resolved_position(command["position"], aliases, command)
        target_native, generated = _copy_node(document, view, source, parent, position)
    return resolved_path, parent_path, changed, generated, target_native, story_before


def _finalize_command_result(
    view: HwpxAgentDocument,
    command: Mapping[str, Any],
    command_id: str,
    op: str,
    resolved_path: str | None,
    parent_path: str | None,
    target_native: Any,
    story_before: HeaderStoryBinding | None,
    story_expectations: dict[str, Mapping[str, str]],
) -> tuple[str, str, str | None]:
    """Return (result_path, result_parent, result_stable_id) for one applied command."""

    result_stable_id: str | None = None
    if isinstance(target_native, TextRange):
        result_path, result_parent = _text_path(view, target_native)
    elif story_before is not None and resolved_path is not None:
        target_story = view._resolve_header_story(resolved_path)
        if target_story.stable_id != story_before.stable_id:
            raise AgentContractError(
                "invariant_violation",
                "header story identity changed during text edit",
                target=resolved_path,
            )
        result_path = target_story.path
        result_parent = target_story.parent_path
        result_stable_id = target_story.stable_id
        story_expectations[target_story.binding_key] = {
            "commandId": command_id,
            "path": target_story.path,
            "stableId": target_story.stable_id,
            "pageType": target_story.page_type,
            "text": command["properties"]["text"],
        }
    elif op == "set" and resolved_path is not None:
        # Some native bindings (notably form fields) are request-local
        # match dictionaries.  A property edit is non-structural, so
        # its canonical path is the durable post-edit lookup key.
        target_record = view.resolve_record(resolved_path)
        result_path = target_record.path
        result_parent = target_record.parent_path or "/"
    elif target_native is not None:
        target_record = _record_for_native(view, target_native)
        result_path = target_record.path
        result_parent = target_record.parent_path or "/"
    else:
        result_path = resolved_path or parent_path or "/"
        result_parent = parent_path or "/"
    return result_path, result_parent, result_stable_id


def _result_place(view: HwpxAgentDocument, op: str, path: str, target_native: Any) -> dict[str, Any] | None:
    """Where the command's node now stands in its paragraph's text (agent-command v2, N8)."""

    if op == "remove":
        return None
    if isinstance(target_native, TextRange):
        paragraph_path = path.rsplit("/", 1)[0]
        return place(paragraph_path, target_native.start, target_native.end - target_native.start)
    try:
        value = view.resolve_record(path).place
    except AgentContractError:
        return None
    return dict(value) if value is not None else None


def command_seed(data: bytes) -> int:
    """The id seed a command batch opens its document with: ``upstream.content_seed`` of the input
    (the first 8 hex digits of its sha256, as school's ``open_seeded``).  Same file, same commands,
    same bytes; the batch's order or content is not mixed in."""

    return content_seed(data)


def _text_only_batch_keeps_projection(text_scope: TextScope) -> bool:
    """Whether one projection can serve every command of the batch.

    Re-projecting the whole document after each command made a 50-cell form
    fill project the document 51 times (audit EFF-17). The projection is only
    reused for the narrow case that is provably unaffected by the commands
    themselves: every command is a text-only ``set`` on an existing paragraph,
    run or cell, and :class:`TextScope` has already refused targets that
    contain one another. Such an edit changes text inside its own target; the
    paths, identities and native bindings of every *other* target stay exactly
    as projected, and a repeated target keeps its element. Form fields and
    header stories (which add mirror controls) and every structural command
    still re-project after each command. ``TextScope.verify`` afterwards
    compares the whole candidate against the input outside those targets.
    """

    targets = text_scope.targets
    return targets is not None and all(
        target.kind in {"paragraph", "run", "cell"} for target in targets
    )


def apply_document_commands(
    batch: Mapping[str, Any],
    *,
    idempotency_store: IdempotencyStore | None = None,
    fault_injector: FaultInjector | None = None,
    domain_verifier: DomainVerifier | None = None,
    save_pipeline: SavePipeline | None = None,
) -> AgentBatchResult:
    """Validate and atomically apply one ``hwpx.agent-batch/v2`` request (v1 read as it was where it means the same).

    ``idempotency_store`` is explicitly caller-owned.  The core keeps no hidden
    resident state in Leap A; MCP/CLI adapters may supply their existing scoped
    stores.  Any failure returns a structured rolled-back result and leaves the
    declared output untouched.
    """

    normalized: Mapping[str, Any] | None = None
    publication: BatchPublication | None = None
    input_revision = _EMPTY_REVISION
    command_results: list[Mapping[str, Any]] = []
    verification: dict[str, Any] = {}
    try:
        normalized = validate_agent_batch(batch)
        _preflight(normalized)
        verification.update(
            {
                "schemaVersion": normalized["schemaVersion"],
                "catalogHash": catalog_hash(),
                "requirements": list(normalized["verificationRequirements"]),
            }
        )
        request_hash = _request_hash(normalized)
        key = normalized["idempotencyKey"]
        cached_result = _apply_commands_idempotency_lookup(
            verification, idempotency_store, key=key, request_hash=request_hash
        )
        if cached_result is not None:
            return cached_result

        input_path = Path(normalized["input"]["filename"])
        output_path = Path(normalized["output"]["filename"])
        publication = BatchPublication(input_path, output_path)
        input_data = publication.input_data
        input_revision = _revision(input_data)
        _validate_apply_commands_input(normalized, verification, input_data, input_revision, output_path)

        aliases: dict[str, dict[str, str]] = {}
        identity_changes: list[Mapping[str, str]] = []
        semantic_changes: list[Mapping[str, Any]] = []
        story_expectations: dict[str, Mapping[str, str]] = {}
        _call_fault(fault_injector, "before_open")
        with HwpxDocument.open(input_data, seed=command_seed(input_data)) as document:
            view = HwpxAgentDocument.from_document(document, revision=input_revision)
            text_scope = TextScope.bind(view, normalized["commands"])
            keep_view = _text_only_batch_keeps_projection(text_scope)
            for index, command in enumerate(normalized["commands"]):
                _call_fault(fault_injector, "before_command", index)
                command_id = command["commandId"]
                op = command["op"]
                resolved_path, parent_path, changed, generated, target_native, story_before = _dispatch_command_op(
                    document, view, command, aliases, input_revision
                )
                identity_changes.extend(generated)

                _call_fault(fault_injector, "after_command", index)
                if not keep_view:
                    view = HwpxAgentDocument.from_document(document, revision=input_revision)
                result_path, result_parent, result_stable_id = _finalize_command_result(
                    view,
                    command,
                    command_id,
                    op,
                    resolved_path,
                    parent_path,
                    target_native,
                    story_before,
                    story_expectations,
                )
                aliases[command_id] = {"path": result_path, "parentPath": result_parent}
                result = {
                    "commandId": command_id,
                    "op": op,
                    "ok": True,
                    "path": result_path,
                    "parentPath": result_parent,
                    "changedProperties": changed,
                    "generatedIdentities": generated,
                    "warnings": [],
                }
                result_place = _result_place(view, op, result_path, target_native)
                if result_place is not None:
                    result["place"] = result_place
                if result_stable_id is not None:
                    # Command results are already an untyped JSON mapping.  This
                    # story-only receipt carries the actual stable identity
                    # without changing AgentBatchResult or the ToolSpec schema.
                    result["stableId"] = result_stable_id
                command_results.append(result)
                semantic_changes.append(
                    {
                        "commandId": command_id,
                        "op": op,
                        "beforePath": resolved_path,
                        "afterPath": None if op == "remove" else result_path,
                        "changedProperties": changed,
                    }
                )

            _call_fault(fault_injector, "before_serialize")
            candidate_data = document.to_bytes()
            _call_fault(fault_injector, "after_serialize")

            candidate_revision, semantic_diff, safety, byte_report = _apply_commands_build_candidate_report(
                input_data,
                candidate_data,
                input_revision,
                semantic_changes,
                identity_changes,
                story_expectations,
                verification,
            )
            text_scope.verify(input_data, candidate_data, verification)
            requirements = set(normalized["verificationRequirements"])
            _apply_commands_domain_verification(candidate_data, normalized, requirements, domain_verifier, verification)
            _require_candidate_structural_safety(safety, byte_report)

            _call_fault(fault_injector, "before_save")
            _apply_commands_run_save_pipeline(
                candidate_data,
                input_path,
                output_path,
                document,
                normalized,
                requirements,
                save_pipeline,
                verification,
                publication,
            )

        batch_result = AgentBatchResult(
            ok=True,
            rolled_back=False,
            dry_run=normalized["dryRun"],
            input_revision=input_revision,
            document_revision=candidate_revision,
            output_filename=str(output_path),
            command_results=tuple(command_results),
            semantic_diff=semantic_diff,
            verification_report=verification,
        )
        if key is not None and idempotency_store is not None:
            idempotency_store[key] = {"requestHash": request_hash, "result": batch_result}
        return batch_result
    except BaseException as exc:  # fail closed; caller receives a stable error contract
        if publication is not None:
            publication.rollback(verification)
        return _failure_result(
            exc=exc,
            batch=normalized or batch,
            input_revision=input_revision,
            command_results=command_results,
            verification=verification,
        )


__all__ = [
    "DomainVerifier",
    "FaultInjector",
    "IdempotencyStore",
    "apply_document_commands",
]
