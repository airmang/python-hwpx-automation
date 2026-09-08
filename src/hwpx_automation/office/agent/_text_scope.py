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
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

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


def _paragraph_format(before: Any, after: Any) -> bool:
    if (
        before.attrib != after.attrib
        or before.tail != after.tail
        or _controls(before) != _controls(after)
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


class TextScope:
    def __init__(self, targets: Sequence[TextTarget] | None) -> None:
        self.targets = targets

    @classmethod
    def bind(
        cls, view: HwpxAgentDocument, commands: Sequence[Mapping[str, Any]]
    ) -> TextScope:
        if not commands or any(
            c["op"] != "set" or set(c["properties"]) != {"text"} for c in commands
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
            if try_parse_header_story_path(path) is not None:
                return cls(None)  # Existing story preservation owns this domain.
            record = view.resolve_record(path)
            if record.kind not in {"paragraph", "run", "cell"}:
                return cls(None)
            element = record.native.element
            binding = next(
                (
                    (member, positions[element])
                    for member, positions in sections
                    if element in positions
                ),
                None,
            )
            if binding is None:
                return cls(None)
            targets[path] = TextTarget(
                binding[0], binding[1], command["properties"]["text"], path
            )
            aliases["$" + command["commandId"] + ".path"] = path
        return cls(tuple(targets.values()))

    def verify(self, before: bytes, after: bytes, verification: dict[str, Any]) -> None:
        report: dict[str, Any] = {
            "scope": "paragraph/run/cell text-only batches",
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
                    if (
                        left.tag != right.tag
                        or _text(right) != target.value
                        or not _target_format(left, right)
                    ):
                        self._fail(
                            "target value, control, or formatting does not match the text edit",
                            target.path,
                        )
                    # Keep the enclosing node/position while masking its already
                    # verified authorized content. No other node is masked.
                    for node in (left, right):
                        node.clear()
                        node.tag = "authorized-text-target"
                if _tree(old) != _tree(new):
                    self._fail("non-target content or formatting changed", member)
        report.update(ok=True)
        verification["semanticDiff"].update(ok=True, basis="verified-text-scope")

    @staticmethod
    def _fail(message: str, target: str | None = None) -> None:
        raise AgentContractError("verification_failed", message, target=target)
