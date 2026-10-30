# SPDX-License-Identifier: Apache-2.0
"""#178: automation reaches core objects through public members only.

The product-boundary gate counts ``obj._name`` uses whose name automation
never defines; each one left is a bounded exception. The blueprint style
bridge, which used to hand-build ``hh:style`` through header privates, now
goes through ``doc.styles``.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from hwpx import HwpxDocument

from hwpx_automation.office.agent.blueprint.native import create_paragraph_style
from hwpx_automation.office.agent.model import AgentContractError

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = runpy.run_path(str(ROOT / "scripts" / "check_product_boundary.py"))
_HH = "{http://www.hancom.co.kr/hwpml/2011/head}"

def _gate(tmp_path: Path, source: str, exceptions: dict | None = None) -> list[str]:
    path = tmp_path / "src" / "hwpx_automation" / "mod.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return BOUNDARY["_private_member_violations"](tmp_path, [path], exceptions or {})


def test_the_shipped_tree_passes_the_gate() -> None:
    files = sorted((ROOT / "src" / "hwpx_automation").rglob("*.py"))
    assert BOUNDARY["_private_member_violations"](ROOT, files) == []


def test_a_new_private_core_member_use_fails(tmp_path: Path) -> None:
    violations = _gate(tmp_path, "def f(doc):\n    return doc._root.headers\n")
    assert len(violations) == 1
    assert "src/hwpx_automation/mod.py -> ._root (x1)" in violations[0]


def test_own_names_self_dunders_and_lxml_types_are_not_counted(tmp_path: Path) -> None:
    source = (
        "from lxml import etree\n"
        "class A:\n"
        "    def _helper(self):\n"
        "        return self._state\n"
        "def f(a: A, el: etree._Element):\n"
        "    return a._helper(), a.__class__\n"
    )
    assert _gate(tmp_path, source) == []


def test_an_exception_may_not_grow_or_go_stale(tmp_path: Path) -> None:
    key = ("src/hwpx_automation/mod.py", "_root")
    grown = _gate(tmp_path, "def f(d):\n    return d._root, d._root\n", {key: {"count": 1}})
    assert grown and "grew past its exception" in grown[0]
    stale = _gate(tmp_path, "def f(d):\n    return d\n", {key: {"count": 1}})
    assert stale and "is stale" in stale[0]
    exact = _gate(tmp_path, "def f(d):\n    return d._root\n", {key: {"count": 1}})
    assert exact == []


def test_every_exception_names_its_reason_upstream_contract_and_removal() -> None:
    for entry in BOUNDARY["CORE_PRIVATE_MEMBER_EXCEPTIONS"].values():
        assert {"count", "reason", "upstream", "removeWhen"} <= set(entry)
        assert all(str(entry[key]).strip() for key in ("reason", "upstream", "removeWhen"))


def _style_element(doc: HwpxDocument, style_id: str):
    styles = doc.oxml.headers[0].element.find(f"{_HH}refList/{_HH}styles")
    return styles, next(item for item in styles if item.get("id") == style_id)


def test_blueprint_style_is_minted_through_core() -> None:
    doc = HwpxDocument.new()
    before = len(doc.styles)
    created = create_paragraph_style(
        doc,
        {"name": "청사진", "alignment": "CENTER", "keepWithNext": True, "lockForm": True},
        source_key="style:abcdef0123",
    )

    styles, element = _style_element(doc, created["styleIDRef"])
    assert created["name"] == "청사진"
    assert len(doc.styles) == before + 1
    assert styles.get("itemCnt") == str(len(styles.findall(f"{_HH}style")))
    assert element.get("type") == "PARA"
    assert element.get("engName") == "청사진"
    assert element.get("paraPrIDRef") == created["paraPrIDRef"]
    assert element.get("charPrIDRef") == "0"
    assert element.get("nextStyleIDRef") == created["styleIDRef"]
    assert element.get("langID") == "0"
    assert element.get("lockForm") in ("1", "true")  # core writes the OWPML literal
    assert doc.styles.paragraph_property(created["paraPrIDRef"]).align.horizontal == "CENTER"

    reopened = HwpxDocument.open(doc.to_bytes())
    assert reopened.styles.resolve("청사진").id == int(created["styleIDRef"])


def test_name_collisions_never_update_an_existing_style() -> None:
    doc = HwpxDocument.new()
    taken = next(style for style in doc.styles.values() if style.name)
    first = create_paragraph_style(doc, {"name": taken.name}, source_key="style:0123456789")
    second = create_paragraph_style(doc, {"name": taken.name}, source_key="style:0123456789")

    assert first["name"] == f"{taken.name}__bp_01234567"
    assert second["name"] == f"{taken.name}__bp_01234567_2"
    assert len({str(taken.id), first["styleIDRef"], second["styleIDRef"]}) == 3
    _styles, original = _style_element(doc, str(taken.id))
    assert original.get("name") == taken.name


def test_a_document_without_a_header_is_refused_before_anything_changes() -> None:
    doc = HwpxDocument.new()
    doc.oxml._headers.clear()  # test-only: what a package without header.xml leaves
    with pytest.raises(AgentContractError) as caught:
        create_paragraph_style(doc, {"name": "x"}, source_key="style:1")
    assert caught.value.code == "unsupported_content"
