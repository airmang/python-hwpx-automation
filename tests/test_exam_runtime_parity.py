# SPDX-License-Identifier: Apache-2.0
"""Parity between the MCP exam owner and core's frozen 4.x exam shape.

``hwpx.exam`` (and its ``ir``/``parser``/``profile``/``measure``/``compose``
submodules) is scheduled for physical deletion from core once python-hwpx is
reduced to a library, so this file no longer imports it. Instead:

- Structural claims (exports, signatures, and all ten dataclasses' field
  shapes — ``Placeholder``/``Question``/``QuestionSet``/``ExamDoc``,
  ``ResolvedStyle``/``FormProfile``, ``SplitReport``,
  ``ParaSpec``/``ComposePlan``/``ComposeResult``) compare the live MCP
  module's ``tests.parity_fingerprint.fingerprint()`` against
  ``tests/parity_fingerprints/exam.json``, frozen from core while it still
  existed. Not covered: each dataclass's ``__dataclass_params__`` (e.g.
  ``frozen=True``/``slots=True``) — ``fingerprint()`` captures field
  name/type/has-default, not the dataclass decorator's own flags.
- Behavioural claims that need an actual computed value (markdown parsing,
  the parse-error shape, the geometry helpers, ``profile_form``, and
  ``compose_exam_into_form``'s result + output bytes) compare against
  ``tests/parity_fingerprints/exam.golden.json`` — values captured from that
  same frozen core commit and confirmed identical to MCP's own output at
  freeze time. The composed output's full zip bytes were not embedded
  (uncompressed, it is >1 MB of duplicate form imagery) — its per-entry
  SHA-256 hashes are, which still catches a byte-level regression.

``hwpx.oxml.document``, ``hwpx.document`` and ``hwpx.tools.package_validator``
are not being deleted and stay imported live, unchanged from before.
``WordBox`` comes from the automation owner: core keeps the neutral fit contract —
policy, measure, engine, report, apply — but ``form_fit.wordbox`` is the
application half, since reading a PDF needs an imaging stack. ``hwpx.visual.oracle`` *is* scheduled for
deletion, but this file only ever used its ``NullOracle`` as an inert
constructor argument — the automation owner's own ``NullOracle`` fills that role
just as well, so this file does not need visual.oracle frozen at all.

Every assertion the pre-freeze version of this file made is still made here;
none needed dropping. The fixtures (``A_form.hwpx``, ``sample_exam.md``) are
read from the core repository, which is resolved without importing the removed
package — see
that directory's ``NOTICE.md`` for provenance — because the original path
derivation via ``Path(core_ir.__file__)`` no longer works without importing
core's ``hwpx.exam.ir``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import zipfile
from pathlib import Path
from random import Random
from uuid import UUID

import hwpx
import hwpx.oxml.document as oxml_document
import pytest
from hwpx.document import HwpxDocument
from hwpx.tools.package_validator import validate_editor_open_safety
from parity_fingerprint import fingerprint

from hwpx_automation.office import exam as mcp_exam
from hwpx_automation.office.exam import compose as mcp_compose
from hwpx_automation.office.exam import ir as mcp_ir
from hwpx_automation.office.exam import measure as mcp_measure
from hwpx_automation.office.exam import parser as mcp_parser
from hwpx_automation.office.exam import profile as mcp_profile
from hwpx_automation.office.form_fill.fit.wordbox import WordBox
from hwpx_automation.office.rendering.oracle import NullOracle
from hwpx_automation.upstream import same_but_save_dates

# The exam corpus lives in the core repository and is read from there rather
# than copied. hwpx.exam.ir is going away, so its __file__ can no longer locate
# the fixtures — but the core *repository* is resolved independently of that, the
# same way tests/conftest.py and test_form_fill_wild_safety.py already resolve it.
# Copying would have duplicated a vendored real-world school document into a
# second public repository, which is a redistribution decision this file has no
# business making on its own.
FIXTURES = Path(hwpx.__file__).resolve().parents[2] / "tests" / "fixtures" / "exam"
_PARITY_FIXTURES = Path(__file__).parent / "parity_fingerprints"
FROZEN = json.loads((_PARITY_FIXTURES / "exam.json").read_text(encoding="utf-8"))[
    "modules"
]
GOLDEN = json.loads(
    (_PARITY_FIXTURES / "exam.golden.json").read_text(encoding="utf-8")
)["calls"]

MODULE_PAIRS = (
    ("hwpx.exam", mcp_exam),
    ("hwpx.exam.ir", mcp_ir),
    ("hwpx.exam.parser", mcp_parser),
    ("hwpx.exam.profile", mcp_profile),
    ("hwpx.exam.measure", mcp_measure),
    ("hwpx.exam.compose", mcp_compose),
)


def _glyph(text: str, x: float, y: float, *, line: int) -> WordBox:
    return WordBox(
        x0=x,
        y0=y,
        x1=x + 8,
        y1=y + 12,
        text=text,
        page=0,
        block=0,
        line=line,
        word_no=0,
    )


def _block_projection(blocks: list) -> list:
    return [[block.id, [glyph.text for glyph in block.glyphs]] for block in blocks]


def _jsonify(value: object) -> object:
    """Round-trip through JSON so tuples (dataclasses.asdict keeps them as
    ``tuple``) compare equal to GOLDEN, which already went through JSON and
    came back as ``list``. GOLDEN is the frozen reference shape; this makes
    the live side's Python-only distinctions (tuple vs list) match it
    instead of the other way around.
    """

    return json.loads(json.dumps(value, ensure_ascii=False))


def test_owned_exports_signatures_and_ten_dataclasses_match_frozen_core() -> None:
    for core_name, mcp_module in MODULE_PAIRS:
        assert fingerprint(mcp_module) == FROZEN[core_name]


def test_parser_ir_lowering_and_errors_match_frozen_core() -> None:
    markdown = """# 중간고사

## 1. (3점)
다음 중 옳은 것은? [그림1]
① 가
② 나

## 2∼3. 세트
공통 지문
### 2.
둘째 발문
① 다
### 3. (2점)
셋째 발문
① 라
"""
    mcp_doc = mcp_parser.parse_exam_markdown(markdown)
    assert _jsonify(dataclasses.asdict(mcp_doc)) == GOLDEN["parseGoodMarkdown"]["docAsDict"]
    assert [question.number for question in mcp_doc.iter_questions()] == (
        GOLDEN["parseGoodMarkdown"]["questionNumbers"]
    )

    bad = "본문이 문항 헤더 없이 먼저 나온다.\n## 1.\n발문\n"
    with pytest.raises(mcp_parser.ExamParseError) as mcp_error:
        mcp_parser.parse_exam_markdown(bad)
    payload = {
        "str": str(mcp_error.value),
        "lineNo": mcp_error.value.line_no,
        "text": mcp_error.value.text,
        "reason": mcp_error.value.reason,
    }
    assert payload == GOLDEN["parseBadMarkdownError"]


def test_measurement_and_profile_projections_match_frozen_core() -> None:
    glyphs = [
        _glyph("1", 10, 10, line=0),
        _glyph(".", 18, 10, line=0),
        _glyph("①", 10, 30, line=1),
        _glyph("가", 18, 30, line=1),
        _glyph("2", 330, 10, line=2),
        _glyph(".", 338, 10, line=2),
    ]
    bounds = [list(pair) for pair in mcp_measure.column_x_bounds(glyphs)]
    assert bounds == GOLDEN["columnXBounds"]
    assert _block_projection(mcp_measure.group_question_blocks(glyphs)) == (
        GOLDEN["groupQuestionBlocks"]
    )

    mcp_profile_value = mcp_profile.profile_form(
        HwpxDocument.open(FIXTURES / "A_form.hwpx")
    )
    assert _jsonify(dataclasses.asdict(mcp_profile_value)) == GOLDEN["profileFormAsDict"]


#: python-hwpx #780 (asks10b, 9720bf7c) writes a new style's attributes in Hancom's order (langID before
#: nextStyleIDRef). The composed header.xml is then these bytes; it is the frozen one but for that order
#: (a canonical XML comparison finds them equal). Both are accepted, as for core #659/#677 in evalplan.
CORE_780_HEADER_SHA256 = "e35a10afcebc99f19740cade3298fb8e532ff4fa99e3c11444e47046f66dfe36"
# 8.0 (owner 18차): compose_exam_into_form opens the form seeded from its bytes, so the ids it mints
# come from that seed rather than the patched uuid4; ids only differ (gate_classify: id-only).
SEEDED_SECTION_SHA256 = "f7a1f32842ea325d27e2b963a010c84f79daee3af58a8f23be43ed631c9ba630"


def test_fixture_composition_bytes_reopen_and_open_safety_match_frozen_core(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markdown = (FIXTURES / "sample_exam.md").read_text(encoding="utf-8")
    source = FIXTURES / "A_form.hwpx"
    mcp_out = tmp_path / "mcp.hwpx"

    def deterministic_uuid4(seed: int):
        rng = Random(seed)
        return lambda: UUID(int=rng.getrandbits(128))

    monkeypatch.setattr(oxml_document, "uuid4", deterministic_uuid4(103))
    mcp_result = mcp_compose.compose_exam_into_form(
        str(source),
        markdown,
        str(mcp_out),
        oracle=NullOracle(),
    )
    mcp_projection = dataclasses.asdict(mcp_result)
    mcp_projection["out_path"] = "<output>"
    assert _jsonify(mcp_projection) == GOLDEN["composeResult"]["resultProjection"]

    with zipfile.ZipFile(mcp_out) as mcp_zip:
        names = sorted(mcp_zip.namelist())
        assert names == GOLDEN["composeResult"]["zipEntryNames"]
        hashes = {
            name: hashlib.sha256(mcp_zip.read(name)).hexdigest() for name in names
        }
        expected = dict(GOLDEN["composeResult"]["zipEntrySha256"])
        if hashes.get("Contents/header.xml") == CORE_780_HEADER_SHA256:
            expected["Contents/header.xml"] = CORE_780_HEADER_SHA256
        if hashes.get("Contents/section0.xml") == SEEDED_SECTION_SHA256:
            expected["Contents/section0.xml"] = SEEDED_SECTION_SHA256
        # The composition is a save of the form: content.hpf takes the save's dates (ModifiedDate
        # now, CreatedDate kept, as Hangul writes them) and is otherwise the form's own bytes.
        written_hpf = mcp_zip.read("Contents/content.hpf")
        with zipfile.ZipFile(source) as form_zip:
            form_hpf = form_zip.read("Contents/content.hpf")
        assert hashlib.sha256(form_hpf).hexdigest() == expected.pop("Contents/content.hpf")
        assert same_but_save_dates(form_hpf, written_hpf)
        hashes.pop("Contents/content.hpf")
        assert hashes == expected

    assert validate_editor_open_safety(mcp_out).ok is True
