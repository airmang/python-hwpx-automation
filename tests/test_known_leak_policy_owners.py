# SPDX-License-Identifier: Apache-2.0
"""Canonical policy owners preserve6.x reports while using neutral core seams."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

from lxml import etree
import pytest

from hwpx.document import HwpxDocument

core_diff = import_module("hwpx.tools.doc_diff")


@pytest.mark.parametrize("kind", ["text", "path", "document", "mapping"])
def test_comparison_preserves_generic_source_whitespace(kind, tmp_path):
    from hwpx_automation.office.document_ops.comparison import (
        build_comparison_table_plan,
    )

    old, new = " A ", "A"
    if kind in {"document", "path"}:
        documents = []
        for index, text in enumerate((old, new)):
            document = HwpxDocument.new()
            document.add_paragraph(text)
            if kind == "path":
                path = tmp_path / f"{index}.hwpx"
                document.save_to_path(path)
                documents.append(path)
            else:
                documents.append(document)
        old, new = documents
    elif kind == "mapping":
        old, new = {"text": old}, {"text": new}
    rows = build_comparison_table_plan(old, new)["sections"][0]["blocks"][1]["rows"]
    assert ["변경", " A ", "A"] in rows
    assert ["동일", "A", "A"] not in rows


@pytest.mark.parametrize("plan", [None, "sections", [], 3])
def test_plan_reader_rejects_non_mapping_inputs(plan):
    from hwpx_automation.office.document_ops import paragraph_plan_to_paragraphs

    with pytest.raises(TypeError, match="plan must be a mapping"):
        paragraph_plan_to_paragraphs(plan)


@pytest.mark.parametrize(
    "plan,expected",
    [
        ({"sections": []}, []),
        (
            {
                "sections": [
                    None,
                    {
                        "blocks": [
                            None,
                            {"type": "heading", "text": " A "},
                            {"type": "paragraph", "text": ""},
                            {
                                "type": "table",
                                "rows": [[" B ", None, 0], "skip", b"skip"],
                            },
                        ]
                    },
                ]
            },
            ["A", "B None 0"],
        ),
        (
            {
                "sections": [
                    {
                        "blocks": [],
                        "children": [{"type": "paragraph", "text": "ignored"}],
                    }
                ]
            },
            [],
        ),
        (
            {
                "sections": [
                    {
                        "children": [
                            {"type": "heading", "text": 123},
                            {"type": "paragraph", "text": False},
                        ]
                    }
                ]
            },
            ["123"],
        ),
    ],
)
def test_application_plan_reader_keeps_exact_input_precedence(plan, expected):
    from hwpx_automation.office.document_ops import paragraph_plan_to_paragraphs

    assert paragraph_plan_to_paragraphs(plan) == expected


@pytest.mark.parametrize(
    "source",
    [
        [],
        ["붙임2참조", "표1", "표3", "그림2", "붙임1. 계획서1부."],
        ["첨부 계획1부.", "첨부2. 계획1부.", "첨부3관련", "Table2", "Figure3"],
        {"paragraphs": ["붙임2 참조"], "text": "ignored", "sections": []},
        {"text": "A\nB", "sections": []},
        {"sections": [{"blocks": [{"type": "paragraph", "text": "표3"}]}]},
    ],
)
def test_reference_reports_match_frozen_core_compatibility(source):
    from hwpx_automation.office.compliance import inspect_reference_consistency

    assert inspect_reference_consistency(
        source
    ) == core_diff.inspect_reference_consistency(source)


def test_reference_handler_binds_the_application_owner():
    from hwpx_automation.handlers import quality_render
    from hwpx_automation.office.compliance import inspect_reference_consistency

    assert (
        quality_render.inspect_hwpx_reference_consistency
        is inspect_reference_consistency
    )
    assert inspect_reference_consistency.__module__.startswith(
        "hwpx_automation.office.compliance"
    )
    assert quality_render.inspect_reference_consistency(paragraphs=["표3"])[
        "violations"
    ]


def test_comparison_normalizes_plans_before_core_diff(monkeypatch):
    from hwpx_automation.office.document_ops import comparison

    captured = []

    def neutral_diff(old, new):
        captured.append((old, new))
        assert isinstance(old, list) and isinstance(new, list)
        return core_diff.doc_diff(old, new)

    monkeypatch.setattr(comparison, "doc_diff", neutral_diff)
    plan = {"sections": [{"children": [{"type": "paragraph", "text": "A"}]}]}
    result = comparison.build_comparison_table_plan(plan, ["B"])
    assert captured == [(["A"], ["B"])] and result["sections"][0]["blocks"][1][
        "rows"
    ] == [["변경", "A", "B"]]


@pytest.mark.parametrize(
    "text",
    [
        "Ⅰ. 제목",
        "1. 제목",
        "1. " + "가" * 36,
        "1. " + "가" * 37,
        "**1. 제목**",
        "<b>Ⅰ. 제목</b>",
        "가. 제목",
        "ordinary",
        "1. 123",
    ],
)
def test_application_markdown_detector_matches_frozen_core_rule(text):
    from hwpx.tools.markdown_export import _detect_heading
    from hwpx_automation.office.authoring.report_parser import detect_markdown_heading

    assert detect_markdown_heading(text) == _detect_heading(text)


def test_ingest_supplies_application_detector_instead_of_core_default(
    tmp_path, monkeypatch
):
    from hwpx_automation.handlers import read_export
    from hwpx.tools import markdown_export

    document = HwpxDocument.new()
    document.add_paragraph("Ⅰ. 기본 제목")
    path = tmp_path / "report.hwpx"
    document.save_to_path(path)
    monkeypatch.setattr(read_export, "resolve_path", lambda _: path)

    def forbidden(_):
        raise AssertionError("core default heading policy was called")

    monkeypatch.setattr(markdown_export, "_detect_heading", forbidden)
    _, result = read_export._ingest_local_document(str(path))
    assert "# Ⅰ. 기본 제목" in result.markdown


def _caption_source(text):
    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    document = HwpxDocument.new()
    table = document.add_table(1, 1)
    table.cell(0, 0).text = "cell"
    paragraph = table.element.getparent().getparent()
    run = etree.SubElement(paragraph, hp + "run", charPrIDRef="0")
    etree.SubElement(run, hp + "t").text = text
    etree.SubElement(paragraph, hp + "linesegarray")
    return document.to_bytes()


@pytest.mark.parametrize(
    "text", ["(1) alpha", "(12) 가나다", "ordinary body", "(1) long-label", "(1) A&B"]
)
def test_evalplan_caption_policy_keeps_legacy_plain_text_outputs(text):
    from hwpx.table_patch import strip_trailing_table_captions
    from hwpx_automation.office.evalplan import strip_evalplan_table_captions

    source = _caption_source(text)
    actual, old = (
        strip_evalplan_table_captions(source),
        strip_trailing_table_captions(source),
    )
    assert actual.data == old.data and actual.to_dict() == old.to_dict()


def test_external_document_reference_reports_match():
    from hwpx_automation.office.compliance import inspect_reference_consistency
    import os

    path = (
        Path(os.environ["PYTHON_HWPX_REPO"])
        / "tests/fixtures/m2_corpus/public_official_table.hwpx"
    )
    assert inspect_reference_consistency(
        path
    ) == core_diff.inspect_reference_consistency(path)
