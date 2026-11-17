# SPDX-License-Identifier: Apache-2.0
"""Typed, deterministic document/subtree blueprint projection."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hwpx.oxml.namespaces import HH, OPF_NS

from ..catalog import catalog_hash
from ..document import HwpxAgentDocument, NodeRecord
from hwpx.oxml.text_offsets import offset_of

from ..model import AGENT_CATALOG_SCHEMA_V2, NODE_KINDS, AgentContractError
from .bundle import (
    ALLOWED_MEDIA_TYPES,
    build_blueprint_bundle,
    read_blueprint_bundle,
    write_blueprint_bundle,
)
from .model import (
    BLUEPRINT_MODES,
    BLUEPRINT_SCHEMA,
    MAX_BLUEPRINT_DEPTH,
    MAX_BLUEPRINT_NODES,
    blueprint_limits,
    validate_blueprint_manifest,
    with_blueprint_hash,
)


@dataclass(frozen=True, slots=True)
class BlueprintDumpResult:
    """One dump receipt plus the validated in-memory artifact."""

    manifest: Mapping[str, Any]
    assets: Mapping[str, bytes]
    bundle_bytes: bytes
    bundle_sha256: str
    output_filename: str | None

    def to_dict(self, *, include_manifest: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": True,
            "schemaVersion": self.manifest["schemaVersion"],
            "blueprintHash": self.manifest["blueprintHash"],
            "bundleSha256": self.bundle_sha256,
            "bundleBytes": len(self.bundle_bytes),
            "outputFilename": self.output_filename,
            "mode": self.manifest["mode"],
            "root": dict(self.manifest["root"]),
            "nodeCount": len(self.manifest["nodes"]),
            "dependencyCount": (
                len(self.manifest["styles"])
                + len(self.manifest["numbering"])
                + len(self.manifest["resources"])
            ),
            "assetCount": len(self.assets),
            "unsupported": list(self.manifest["unsupported"]),
            "fidelity": dict(self.manifest["fidelity"]),
        }
        if include_manifest:
            result["manifest"] = dict(self.manifest)
        return result


def _local_name(element: Any) -> str:
    return str(getattr(element, "tag", "")).rsplit("}", 1)[-1]


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dependency(kind: str, properties: Mapping[str, Any], *, name: str | None = None) -> dict[str, Any]:
    detached = dict(properties)
    digest = _canonical_digest(detached)
    result: dict[str, Any] = {
        "key": f"{kind}:{digest}",
        "kind": kind,
        "signature": f"sha256:{digest}",
        "properties": detached,
    }
    if name:
        result["name"] = str(name)[:512]
    return result


def _semantic_generic(value: Any) -> dict[str, Any]:
    """Convert a parsed definition to typed semantics without tags or native IDs."""

    attributes = {
        str(key): str(item)
        for key, item in sorted(getattr(value, "attributes", {}).items())
        if "id" not in str(key).casefold() and "ref" not in str(key).casefold()
    }
    result: dict[str, Any] = {"kind": str(getattr(value, "name", "definition"))}
    if attributes:
        result["properties"] = attributes
    text = getattr(value, "text", None)
    if text:
        result["text"] = str(text)[:16_384]
    children = [_semantic_generic(child) for child in getattr(value, "children", [])]
    if children:
        result["children"] = children
    return result


def _numbering_properties(agent: HwpxAgentDocument, record: NodeRecord) -> dict[str, Any] | None:
    if record.kind != "paragraph":
        return None
    paragraph = record.native
    para_pr = agent.document.styles.paragraph_property(paragraph.para_pr_id_ref)
    heading = para_pr.heading if para_pr is not None else None
    if heading is None or not heading.type or str(heading.type).upper() == "NONE":
        return None
    properties: dict[str, Any] = {
        "type": str(heading.type),
        "level": heading.level,
    }
    ref = heading.id_ref
    if ref is not None and agent.document.oxml.headers:
        styles = agent.document.styles
        if str(heading.type).upper() == "BULLET":
            for bullet in styles.bullets.values():
                raw_id = getattr(bullet, "attributes", {}).get("id")
                if raw_id is not None and str(raw_id) == str(ref):
                    properties["definition"] = _semantic_generic(bullet)
                    break
        else:
            numbering = _numbering_element(agent, str(ref))
            if numbering is not None:
                properties["definition"] = _semantic_element(numbering)
    return properties


def _numbering_element(agent: HwpxAgentDocument, ref: str) -> Any | None:
    """The first header's ``hh:numbering`` whose id is *ref* as written, else ``None``.

    python-hwpx 7.0 reads ``doc.styles.numberings`` as typed ``NumberingInfo`` values
    (6.x: the parsed XML elements), which no longer carry the definition's attributes
    and children; the blueprint keeps describing the definition as it is written, so
    it reads the header XML here.
    """

    numberings = agent.document.oxml.headers[0].element.find(f"{HH}refList/{HH}numberings")
    if numberings is None:
        return None
    return next(
        (
            child
            for child in numberings
            if _local_name(child) == "numbering" and child.get("id") is not None and str(child.get("id")) == ref
        ),
        None,
    )


def _semantic_element(node: Any) -> dict[str, Any]:
    """:func:`_semantic_generic` of an XML element as written (local names, no native IDs)."""

    attributes = {
        str(key): str(item)
        for key, item in sorted(node.attrib.items())
        if "id" not in str(key).casefold() and "ref" not in str(key).casefold()
    }
    result: dict[str, Any] = {"kind": _local_name(node)}
    if attributes:
        result["properties"] = attributes
    if node.text:
        result["text"] = str(node.text)[:16_384]
    children = [_semantic_element(child) for child in node if isinstance(child.tag, str)]
    if children:
        result["children"] = children
    return result


def _style_dependency(agent: HwpxAgentDocument, record: NodeRecord) -> dict[str, Any] | None:
    if record.kind == "paragraph":
        paragraph = record.native
        style = agent.document.styles.get(paragraph.style_id_ref)
        properties = {
            "category": "paragraph",
            "name": record.summary.get("style"),
            "type": getattr(style, "type", None),
            "englishName": getattr(style, "eng_name", None),
            "lockForm": getattr(style, "lock_form", None),
            "alignment": record.summary.get("alignment"),
            "breakBefore": record.summary.get("breakBefore"),
            "keepWithNext": record.summary.get("keepWithNext"),
            "lineSpacingPercent": record.summary.get("lineSpacingPercent"),
        }
        return _dependency("style", properties, name=str(record.summary.get("style") or "paragraph"))
    if record.kind == "run":
        properties = {"category": "character"}
        properties.update({key: value for key, value in record.summary.items() if key != "text"})
        return _dependency("char", properties, name="character-format")
    return None


def _manifest_image_item(agent: HwpxAgentDocument, item_id: str) -> tuple[str, str] | None:
    matches: list[tuple[str, str]] = []
    for item in agent.document.package.manifest_tree().findall(f"./{{{OPF_NS}}}manifest/{{{OPF_NS}}}item"):
        if str(item.get("id") or "") == item_id:
            matches.append((str(item.get("href") or ""), str(item.get("media-type") or "")))
    if len(matches) > 1:
        raise AgentContractError(
            "invariant_violation", "picture resource identity is duplicated", target=item_id
        )
    return matches[0] if matches else None


def _picture_resource_from_element(
    agent: HwpxAgentDocument, element: Any, *, name: str = "image"
) -> tuple[dict[str, Any], bytes] | None:
    image = next((child for child in element.iter() if _local_name(child) == "img"), None)
    item_id = str(image.get("binaryItemIDRef") or "") if image is not None else ""
    if not item_id:
        return None
    manifest_item = _manifest_image_item(agent, item_id)
    if manifest_item is None:
        return None
    package_name, media_type = manifest_item
    media_type = media_type.casefold()
    if media_type not in ALLOWED_MEDIA_TYPES:
        return None
    suffix = Path(package_name).suffix.casefold().lstrip(".")
    if suffix not in ALLOWED_MEDIA_TYPES[media_type]:
        return None
    payload = agent.document.package.read(package_name)
    digest = hashlib.sha256(payload).hexdigest()
    resource = {
        "key": f"resource:{digest}",
        "sha256": f"sha256:{digest}",
        "mediaType": media_type,
        "size": len(payload),
        "assetPath": f"assets/{digest}.{suffix}",
        "name": name[:512],
    }
    return resource, payload


def _picture_resource(
    agent: HwpxAgentDocument, record: NodeRecord
) -> tuple[dict[str, Any], bytes] | None:
    if record.kind != "picture":
        return None
    return _picture_resource_from_element(
        agent, record.native, name=str(record.summary.get("name") or "image")
    )


def _unprojected_pictures(agent: HwpxAgentDocument, root: NodeRecord, selected: set[int]) -> list[Any]:
    """Find pictures hidden in containers without claiming replay support."""
    roots = (
        [section.element for section in agent.document.sections]
        if root.kind == "document"
        else [getattr(root.native, "element", root.native)]
    )
    return [
        element
        for native_root in roots
        for element in native_root.iter()
        if _local_name(element) == "pic" and id(element) not in selected
    ]


def _collect_unprojected_picture_assets(
    agent: HwpxAgentDocument,
    root: NodeRecord,
    ordered: list[tuple[NodeRecord, int]],
    resources: dict[str, dict[str, Any]],
    assets: dict[str, bytes],
    unsupported: list[dict[str, str]],
    *,
    include_assets: bool,
) -> None:
    """Bundle group-contained image bytes without implying portable replay."""
    if not include_assets:
        return
    projected = {id(record.native) for record, _ in ordered if record.kind == "picture"}
    for picture in _unprojected_pictures(agent, root, projected):
        extracted = _picture_resource_from_element(agent, picture)
        if extracted is None:
            unsupported.append({
                "path": root.path,
                "kind": "resource",
                "reason": "unprojected picture resource is missing or not allow-listed",
            })
            continue
        resource, payload = extracted
        resources.setdefault(str(resource["key"]), resource)
        assets.setdefault(str(resource["assetPath"]), payload)


def _first_descendant(element: Any, kind: str) -> Any | None:
    return next((child for child in element.iter() if _local_name(child) == kind), None)


def _portable_properties(record: NodeRecord) -> dict[str, Any]:
    properties = dict(record.summary)
    if record.kind == "section":
        # The section part filename is an implementation/package coordinate,
        # and its one-based index is a source-document coordinate. Neither is
        # a portable construction property: replay may append the section at a
        # different target index.
        properties.pop("partId", None)
        properties.pop("index", None)
    elif record.kind == "cell":
        # Row/column are source-document addresses. The graph order and spans
        # carry the portable structure, while replay may insert the cell's row
        # at a different target address.
        properties.pop("row", None)
        properties.pop("column", None)
    elif record.kind == "row":
        # Like cell addresses, the row index is determined by the target
        # insertion point and is not part of the portable row payload.
        properties.pop("index", None)
    elif record.kind == "picture":
        pos = _first_descendant(record.native, "pos")
        if pos is not None:
            properties["treatAsChar"] = str(pos.get("treatAsChar", "1")) not in {"0", "false", "False"}
            properties["alignment"] = pos.get("horzAlign")
    elif record.kind == "shape":
        element = record.native.element
        pos = _first_descendant(element, "pos")
        line = _first_descendant(element, "lineShape")
        fill = _first_descendant(element, "winBrush")
        properties.update(
            {
                "treatAsChar": (
                    str(pos.get("treatAsChar", "1")) not in {"0", "false", "False"}
                    if pos is not None
                    else True
                ),
                "lineColor": line.get("color") if line is not None else None,
                "lineWidth": line.get("width") if line is not None else None,
                "fillColor": fill.get("faceColor") if fill is not None else None,
                "ratio": element.get("ratio") if _local_name(element) == "rect" else None,
            }
        )
    elif record.kind == "form-field":
        properties["hasEnd"] = bool(record.native.get("has_end"))
    return properties


def _native_element(record: NodeRecord) -> Any | None:
    native = record.native
    if record.kind == "form-field":
        return None
    return getattr(native, "element", native)


_OFFSET_KINDS = frozenset({"table", "picture", "shape", "footnote", "endnote"})


def _v2_placement(record: NodeRecord) -> dict[str, int] | str:
    """Where an object, note or form field stands in its paragraph's text (blueprint v2): ``offset``, or
    a form field's ``start``/``end`` (its begin's and end's offsets, python-hwpx #778); a reason string
    when a form field's end is not in its paragraph (v1 refused that one too)."""

    if record.kind in _OFFSET_KINDS:
        return {"offset": int(record.place["offset"])} if record.place is not None else {}
    if record.kind != "form-field":
        return {}
    begin = record.native.get("_field_begin")
    paragraph = record.native.get("_paragraph")
    if begin is None or paragraph is None:
        return "form field has no begin in a paragraph"
    end = next(
        (
            node
            for node in paragraph.element.iter()
            if str(getattr(node, "tag", "")).endswith("}fieldEnd") and node.get("beginIDRef") == begin.get("id")
        ),
        None,
    )
    start_offset = offset_of(begin, paragraph.element)
    end_offset = offset_of(end, paragraph.element) if end is not None else None
    if start_offset is None or end_offset is None:
        return "form field does not end in its own paragraph"
    return {"start": int(start_offset), "end": int(end_offset)}


def _ordered_subtree(
    agent: HwpxAgentDocument, root: NodeRecord
) -> list[tuple[NodeRecord, int]]:
    by_path = {record.path: record for record in agent.records}
    ordered: list[tuple[NodeRecord, int]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(record: NodeRecord, depth: int) -> None:
        if depth > MAX_BLUEPRINT_DEPTH:
            raise AgentContractError("resource_limit", "blueprint subtree exceeds depth limit", target=record.path)
        if record.path in visiting:
            raise AgentContractError("invariant_violation", "semantic projection contains a cycle", target=record.path)
        if record.path in visited:
            raise AgentContractError(
                "invariant_violation", "semantic projection contains multiple parents", target=record.path
            )
        visiting.add(record.path)
        visited.add(record.path)
        ordered.append((record, depth))
        if len(ordered) > MAX_BLUEPRINT_NODES:
            raise AgentContractError("resource_limit", "blueprint subtree exceeds node limit", target=record.path)
        for child_path in record.child_paths:
            child = by_path.get(child_path)
            if child is None:
                raise AgentContractError("invariant_violation", "semantic child binding is missing", target=child_path)
            visit(child, depth + 1)
        visiting.remove(record.path)

    visit(root, 0)
    return ordered


def _make_manifest(
    agent: HwpxAgentDocument,
    *,
    root_path: str,
    source_label: str,
    mode: str,
    include_assets: bool,
    require_replayable: bool,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if mode not in BLUEPRINT_MODES:
        raise AgentContractError("invalid_syntax", "unsupported blueprint mode", target="mode")
    root_record = agent.resolve_record(root_path, expected_revision=agent.revision)
    ordered = _ordered_subtree(agent, root_record)
    logical_ids = {record.path: f"n{index:06d}" for index, (record, _) in enumerate(ordered, start=1)}
    styles: dict[str, dict[str, Any]] = {}
    numbering: dict[str, dict[str, Any]] = {}
    resources: dict[str, dict[str, Any]] = {}
    assets: dict[str, bytes] = {}
    unsupported: list[dict[str, str]] = []
    references: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []

    for record, _depth in ordered:
        style_refs: list[str] = []
        numbering_refs: list[str] = []
        resource_refs: list[str] = []
        node_references: list[str] = []
        dependency = _style_dependency(agent, record)
        if dependency is not None:
            styles.setdefault(str(dependency["key"]), dependency)
            style_refs.append(str(dependency["key"]))
        numbering_properties = _numbering_properties(agent, record)
        if numbering_properties is not None:
            definition = _dependency("numbering", numbering_properties, name=str(numbering_properties["type"]))
            numbering.setdefault(str(definition["key"]), definition)
            numbering_refs.append(str(definition["key"]))

        node_unsupported: list[str] = []
        for kind, count in sorted(record.unsupported_child_kinds.items()):
            reason = f"unprojected semantic child ({count})"
            unsupported.append({"path": record.path, "kind": str(kind), "reason": reason})
            node_unsupported.append(reason)

        if record.kind == "picture":
            extracted = _picture_resource(agent, record) if include_assets else None
            if extracted is None:
                reason = "picture resource is missing, disabled, or not allow-listed"
                unsupported.append({"path": record.path, "kind": "resource", "reason": reason})
                node_unsupported.append(reason)
            else:
                resource, payload = extracted
                resources.setdefault(str(resource["key"]), resource)
                assets.setdefault(str(resource["assetPath"]), payload)
                resource_refs.append(str(resource["key"]))

        if record.kind == "shape":
            shape_type = str(record.summary.get("shapeType") or "")
            if shape_type not in {"rect", "ellipse"} or not _portable_properties(record).get("treatAsChar"):
                reason = "only inline rectangle/ellipse shapes are portable in blueprint v1"
                unsupported.append({"path": record.path, "kind": "shape", "reason": reason})
                node_unsupported.append(reason)

        placement = _v2_placement(record)
        if isinstance(placement, str):
            unsupported.append({"path": record.path, "kind": record.kind, "reason": placement})
            node_unsupported.append(placement)
            placement = {}

        replayable = not node_unsupported
        native_id = record.attributes.get("id") or record.stable_id
        node = {
            "blueprintId": logical_ids[record.path],
            "kind": record.kind,
            "properties": {**_portable_properties(record), **placement},
            "children": [logical_ids[path] for path in record.child_paths],
            "styleRefs": sorted(style_refs),
            "numberingRefs": sorted(numbering_refs),
            "resourceRefs": sorted(resource_refs),
            "references": sorted(node_references),
            "sourceHint": {"nativeId": native_id, "path": record.path},
            "support": {
                "replayable": replayable,
                "fidelity": "exact" if replayable else "unsupported",
            },
        }
        nodes.append(node)

    _collect_unprojected_picture_assets(
        agent, root_record, ordered, resources, assets, unsupported,
        include_assets=include_assets,
    )

    if root_record.kind in {"cell", "form-field"}:
        reason = f"standalone {root_record.kind} insertion is unavailable in blueprint v1"
        unsupported.append({"path": root_record.path, "kind": root_record.kind, "reason": reason})
        nodes[0]["support"] = {"replayable": False, "fidelity": "unsupported"}
    all_replayable = not unsupported and all(node["support"]["replayable"] for node in nodes)
    if require_replayable and not all_replayable:
        first = unsupported[0] if unsupported else {"path": root_record.path, "reason": "not replayable"}
        raise AgentContractError(
            "unsupported_content",
            f"strict blueprint dump is not replayable: {first['reason']}",
            target=str(first["path"]),
        )

    kind_order = {kind: index for index, kind in enumerate(NODE_KINDS)}
    manifest: dict[str, Any] = {
        "schemaVersion": BLUEPRINT_SCHEMA,
        "catalogVersion": AGENT_CATALOG_SCHEMA_V2,
        "catalogHash": catalog_hash(),
        "source": {"revision": agent.revision, "label": source_label[:512]},
        "mode": mode,
        "root": {
            "blueprintId": logical_ids[root_record.path],
            "kind": root_record.kind,
            "sourcePath": root_record.path,
            "sourceStability": root_record.stability,
        },
        "nodes": nodes,
        "styles": [styles[key] for key in sorted(styles)],
        "numbering": [numbering[key] for key in sorted(numbering)],
        "resources": [resources[key] for key in sorted(resources)],
        "references": references,
        "unsupported": unsupported,
        "capabilities": {
            "dump": True,
            "replay": all_replayable,
            "kinds": sorted({node["kind"] for node in nodes}, key=lambda kind: kind_order[kind]),
        },
        "limits": blueprint_limits(),
        "fidelity": {
            "replayable": all_replayable,
            "ceiling": "exact" if all_replayable else "unsupported",
            "reasons": [item["reason"] for item in unsupported],
        },
        "blueprintHash": None,
    }
    return validate_blueprint_manifest(with_blueprint_hash(manifest)), assets


def dump_document_blueprint(
    source: str | os.PathLike[str] | bytes,
    *,
    path: str = "/",
    mode: str = "portable",
    expected_revision: str | None = None,
    output: str | os.PathLike[str] | None = None,
    overwrite: bool = False,
    include_assets: bool = True,
    require_replayable: bool = True,
) -> BlueprintDumpResult:
    """Dump one revision-bound semantic subtree to a validated typed bundle."""

    source_label = "memory.hwpx" if isinstance(source, bytes) else Path(source).name
    with HwpxAgentDocument.open(source) as agent:
        if expected_revision is not None and expected_revision != agent.revision:
            raise AgentContractError(
                "stale_revision", "document revision does not match", target=path
            )
        manifest, assets = _make_manifest(
            agent,
            root_path=path,
            source_label=source_label,
            mode=mode,
            include_assets=include_assets,
            require_replayable=require_replayable,
        )
    if output is None:
        bundle_bytes = build_blueprint_bundle(manifest, assets)
        bundle = read_blueprint_bundle(bundle_bytes)
        output_filename = None
    else:
        bundle = write_blueprint_bundle(output, manifest, assets, overwrite=overwrite)
        bundle_bytes = Path(output).read_bytes()
        output_filename = str(output)
    return BlueprintDumpResult(
        manifest=bundle.manifest,
        assets=bundle.assets,
        bundle_bytes=bundle_bytes,
        bundle_sha256=bundle.bundle_sha256,
        output_filename=output_filename,
    )


__all__ = ["BlueprintDumpResult", "dump_document_blueprint"]
