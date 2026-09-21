# SPDX-License-Identifier: Apache-2.0
"""Bounded command-policy verification of existing text-only edits.

This reads the candidate; mutation and serialization remain core-owned. A
section part is not an authorization boundary: all non-target nodes and all
shared definitions are checked. Other command families are explicitly unscoped.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, NoReturn

from hwpx.opc.security import guard_zip_file, parse_xml_stdlib, read_member

from .document import HwpxAgentDocument
from .model import AgentContractError
from .story import try_parse_header_story_path

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _children(node: Any) -> list[Any]:
    return [child for child in node if child.tag != HP + "linesegarray"]


def _tree(node: Any) -> tuple[Any, ...]:
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text or "",
        node.tail or "",
        tuple(_tree(child) for child in _children(node)),
    )


def _locations(root: Any, path: tuple[int, ...] = ()) -> dict[Any, tuple[int, ...]]:
    result = {root: path}
    for index, child in enumerate(_children(root)):
        result.update(_locations(child, (*path, index)))
    return result


def _at(root: Any, path: tuple[int, ...]) -> Any:
    for index in path:
        root = _children(root)[index]
    return root


def _chars(node: Any) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    runs = [node] if node.tag == HP + "run" else node.findall(HP + "run")
    return [
        (char, tuple(sorted(run.attrib.items())))
        for run in runs
        for text in run.findall(HP + "t")
        for char in text.text or ""
    ]


def _controls(node: Any) -> list[tuple[Any, ...]]:
    if node.tag == HP + "run":
        return [_tree(child) for child in _children(node) if child.tag != HP + "t"]
    return [_tree(child) for child in _children(node) if child.tag != HP + "run"] + [
        _tree(child)
        for run in node.findall(HP + "run")
        for child in run
        if child.tag != HP + "t"
    ]


def _text_skeleton(node: Any) -> tuple[Any, ...]:
    clone = deepcopy(node)
    for text in clone.iter(HP + "t"):
        text.text = "authorized-text"
    return _tree(clone)


def _paragraph_format(before: Any, after: Any) -> bool:
    if (
        before.attrib != after.attrib
        or before.tail != after.tail
        or _controls(before) != _controls(after)
        or _text_skeleton(before) != _text_skeleton(after)
    ):
        return False
    left, right = _chars(before), _chars(after)
    styles = {style for _, style in left}
    # Empty text runs still provide the style for a newly populated field.
    if not styles:
        runs = [before] if before.tag == HP + "run" else before.findall(HP + "run")
        styles = {tuple(sorted(run.attrib.items())) for run in runs}
    if styles and any(style not in styles for _, style in right):
        return False
    matcher = SequenceMatcher(
        a=[c for c, _ in left], b=[c for c, _ in right], autojunk=False
    )
    return all(
        [s for _, s in left[a : a + n]] == [s for _, s in right[b : b + n]]
        for a, b, n in matcher.get_matching_blocks()
    )


def _text(node: Any) -> str:
    if node.tag == HP + "tc":
        return "\n".join(
            _text(p) for p in node.findall("./" + HP + "subList/" + HP + "p")
        )
    return "".join(c for c, _ in _chars(node))


def _target_format(before: Any, after: Any) -> bool:
    if before.tag != HP + "tc":
        return _paragraph_format(before, after)
    left_attrs, right_attrs = dict(before.attrib), dict(after.attrib)
    left_attrs.pop("dirty", None)
    right_attrs.pop("dirty", None)
    if left_attrs != right_attrs:
        return False
    left, right = before.find(HP + "subList"), after.find(HP + "subList")
    if left is None or right is None or left.attrib != right.attrib:
        return False
    if [_tree(e) for e in before if e.tag != HP + "subList"] != [
        _tree(e) for e in after if e.tag != HP + "subList"
    ]:
        return False
    old_paras, new_paras = left.findall(HP + "p"), right.findall(HP + "p")
    if not old_paras:
        return not new_paras
    # Cell.text intentionally replaces the cell's text paragraphs. Require the
    # retained base paragraph format and preserve any embedded controls.
    if any(_controls(p) for p in old_paras + new_paras):
        return False
    return all(_paragraph_format(old_paras[0], p) for p in new_paras)


@dataclass(frozen=True)
class TextTarget:
    member: str
    location: tuple[int, ...]
    value: str
    path: str
    kind: str = "text"
    extra_locations: tuple[tuple[int, ...], ...] = ()


class TextScope:
    def __init__(self, targets: Sequence[TextTarget] | None) -> None:
        self.targets = targets

    @classmethod
    def bind(
        cls, view: HwpxAgentDocument, commands: Sequence[Mapping[str, Any]]
    ) -> TextScope:
        if not commands or any(
            c["op"] != "set" or set(c["properties"]) not in ({"text"}, {"value"})
            for c in commands
        ):
            return cls(None)
        sections = [
            (section.part_name, _locations(section.element))
            for section in view.document.sections
        ]
        aliases: dict[str, str] = {}
        targets: dict[str, TextTarget] = {}
        for command in commands:
            path = str(command["path"])
            path = aliases.get(path, path)
            header_path = try_parse_header_story_path(path)
            if header_path is not None:
                header_binding = view._resolve_header_story(path)
                section = view.document.sections[header_path.section_index - 1]
                positions = dict(sections)[section.part_name]
                nodes = [node for node in section.element.iter()
                         if node.tag == HP + "header" and node.get("id") == header_binding.native_id]
                if not nodes or any(node not in positions for node in nodes):
                    return cls(None)
                targets[path] = TextTarget(section.part_name, positions[nodes[0]],
                                           command["properties"]["text"], path,
                                           "header", tuple(positions[node] for node in nodes[1:]))
                aliases["$" + command["commandId"] + ".path"] = path
                continue
            record = view.resolve_record(path)
            if record.kind == "form-field":
                native = record.native
                paragraph = native["_paragraph"]
                element = paragraph.element
                field_binding = next(((member, positions[element], positions)
                                for member, positions in sections if element in positions), None)
                if field_binding is None or not native.get("_text_nodes") or native.get("is_placeholder"):
                    return cls(None)
                nodes = native["_text_nodes"]
                begin = native.get("_field_begin")
                if begin is None or any(node not in field_binding[2] for node in [begin, *nodes]):
                    return cls(None)
                targets[path] = TextTarget(field_binding[0], field_binding[1],
                                           command["properties"]["value"], path,
                                           "field", (field_binding[2][begin], *(field_binding[2][node] for node in nodes)))
                aliases["$" + command["commandId"] + ".path"] = path
                continue
            if record.kind not in {"paragraph", "run", "cell"}:
                return cls(None)
            element = record.native.element
            element_binding = next(
                (
                    (member, positions[element])
                    for member, positions in sections
                    if element in positions
                ),
                None,
            )
            if element_binding is None:
                return cls(None)
            targets[path] = TextTarget(
                element_binding[0], element_binding[1], command["properties"]["text"], path
            )
            aliases["$" + command["commandId"] + ".path"] = path
        bound = tuple(targets.values())
        for index, first in enumerate(bound):
            for second in bound[index + 1:]:
                if first.member != second.member:
                    continue
                locations = (first.location, *first.extra_locations)
                others = (second.location, *second.extra_locations)
                if any(a[:len(b)] == b or b[:len(a)] == a for a in locations for b in others):
                    raise AgentContractError(
                        "unsupported_content", "overlapping text targets need separate batches",
                        target=second.path,
                    )
        return cls(bound)

    def verify(self, before: bytes, after: bytes, verification: dict[str, Any]) -> None:
        report: dict[str, Any] = {
            "scope": "paragraph/run/cell/field/existing-header text-only batches",
            "ok": None,
            "status": "not-applicable",
        }
        verification["scopePreservation"] = report
        if self.targets is None:
            return
        report.update(ok=False, status="checked", targetCount=len(self.targets))
        with (
            zipfile.ZipFile(io.BytesIO(before)) as a,
            zipfile.ZipFile(io.BytesIO(after)) as b,
        ):
            guard_zip_file(a)
            guard_zip_file(b)
            if sorted(a.namelist()) != sorted(b.namelist()) or len(b.namelist()) != len(
                set(b.namelist())
            ):
                self._fail("package member set changed")
            members = {target.member for target in self.targets}
            for name in a.namelist():
                if name not in members and read_member(a, name) != read_member(b, name):
                    self._fail("non-target package payload changed", name)
            for member in members:
                old = parse_xml_stdlib(read_member(a, member), part_name=member)
                new = parse_xml_stdlib(read_member(b, member), part_name=member)
                for target in (t for t in self.targets if t.member == member):
                    left, right = _at(old, target.location), _at(new, target.location)
                    if target.kind == "header":
                        self._verify_header(old, new, target)
                        continue
                    if target.kind == "field":
                        self._verify_field(old, new, target)
                        continue
                    if left.tag != right.tag or _text(right) != target.value or not _target_format(left, right):
                        self._fail("target value, control, or formatting does not match the text edit", target.path)
                    # Keep the enclosing node/position while masking its already
                    # verified authorized content. No other node is masked.
                    for node in (left, right):
                        node.clear()
                        node.tag = "authorized-text-target"
                if _tree(old) != _tree(new):
                    self._fail("non-target content or formatting changed", member)
        report.update(ok=True)
        verification["semanticDiff"].update(ok=True, basis="verified-text-scope")

    def _verify_header(self, old: Any, new: Any, target: TextTarget) -> None:
        for location in (target.location, *target.extra_locations):
            before, after = _at(old, location), _at(new, location)
            if before.tag != HP + "header" or after.tag != before.tag:
                self._fail("header story changed structure", target.path)
            old_texts = before.findall("./" + HP + "subList/" + HP + "p/" + HP + "run/" + HP + "t")
            new_texts = after.findall("./" + HP + "subList/" + HP + "p/" + HP + "run/" + HP + "t")
            if len(old_texts) != 1 or len(new_texts) != 1 or new_texts[0].text != target.value:
                self._fail("header story text or structure changed unexpectedly", target.path)
            old_texts[0].text = new_texts[0].text = "authorized-text"
        # Core adds a control mirror when the existing logical story lacked
        # one. Verify that the sole addition is a byte-equivalent mirror of
        # the edited story, then remove it from the comparison tree.
        existing = len((target.location, *target.extra_locations))
        matching = [node for node in new.iter(HP + "header")
                    if node.get("id") == _at(new, target.location).get("id")]
        if len(matching) == existing + 1:
            mirror = next((node for node in matching if node not in
                           [_at(new, location) for location in (target.location, *target.extra_locations)]), None)
            if mirror is None:
                self._fail("header mirror is ambiguous", target.path)
            texts = mirror.findall("./" + HP + "subList/" + HP + "p/" + HP + "run/" + HP + "t")
            if len(texts) != 1 or texts[0].text != target.value:
                self._fail("header mirror text changed", target.path)
            texts[0].text = "authorized-text"
            if _tree(mirror) != _tree(_at(new, target.location)):
                self._fail("header mirror differs from logical story", target.path)
            locations = _locations(new)
            mirror_path = locations[mirror]
            if len(mirror_path) < 2:
                self._fail("header mirror location is invalid", target.path)
            control = _at(new, mirror_path[:-1])
            run = _at(new, mirror_path[:-2])
            if (control.tag != HP + "ctrl" or len(control) != 1
                    or run.tag != HP + "run" or mirror_path[:-2] not in _locations(old).values()):
                self._fail("header mirror changed unrelated structure", target.path)
            run.remove(control)
        elif len(matching) != existing:
            self._fail("header story count changed unexpectedly", target.path)
        # The caller compares the entire section tree, including all controls,
        # sibling stories, attributes and styles after these exact leaves mask.

    def _verify_field(self, old: Any, new: Any, target: TextTarget) -> None:
        begin_location, *text_locations = target.extra_locations
        before_begin, after_begin = _at(old, begin_location), _at(new, begin_location)
        if before_begin.tag != HP + "fieldBegin" or after_begin.tag != before_begin.tag:
            self._fail("field control changed structure", target.path)
        if after_begin.get("dirty") != "1":
            self._fail("field dirty marker missing", target.path)
        before_begin.set("dirty", "1")
        before_texts = [_at(old, location) for location in text_locations]
        after_texts = [_at(new, location) for location in text_locations]
        if any(a.tag != HP + "t" or b.tag != a.tag for a, b in zip(before_texts, after_texts)):
            self._fail("field text node changed structure", target.path)
        if "".join(node.text or "" for node in after_texts) != target.value:
            self._fail("field value does not match", target.path)
        for before_text, after_text in zip(before_texts, after_texts):
            before_text.text = after_text.text = "authorized-text"
        # Field controls and every sibling in the paragraph remain visible to
        # the final full-section comparison; only value text and dirty differ.

    @staticmethod
    def _fail(message: str, target: str | None = None) -> NoReturn:
        raise AgentContractError("verification_failed", message, target=target)
