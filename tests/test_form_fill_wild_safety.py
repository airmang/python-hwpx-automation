# SPDX-License-Identifier: Apache-2.0
"""Checked-in wild-form parity, immutability, and open-safety gates."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import hwpx
import pytest

from hwpx_automation.office.form_fill.fill_residue import (
    inspect_fill_residue,
)
from hwpx_automation.office.form_fill.guidance import scan_form_guidance
from hwpx_automation.office.form_fill.quality import score_form_fill
from hwpx_automation.storage import build_hwpx_open_safety_report


CORE_ROOT = Path(hwpx.__file__).resolve().parents[2]

# The core 4.x guidance/residue/score callables produced these outputs on the
# checked-in wild forms, recorded while those modules still existed. Comparing
# against the record rather than a live copy is what keeps this gate meaningful
# once core stops shipping the application half — a parity test whose other side
# has been deleted proves nothing.
PARITY_GOLDEN = json.loads(
    (Path(__file__).parent / "parity_golden" / "form_fill_wild_forms.json").read_text(
        encoding="utf-8"
    )
)["forms"]


def _portable(value: Any) -> Any:
    """Rewrite absolute fixture paths so the record is machine-independent.

    These reports embed the source path they were given. Freezing that verbatim
    would pin the golden to one checkout — it would fail on any other machine, and
    the public-hygiene gate rejects workstation-shaped paths in tracked files for
    exactly that reason. Both sides are normalised, so the comparison still covers
    the path field's shape without pinning its prefix.
    """

    if isinstance(value, str):
        marker = "/tests/fixtures/"
        # A Windows checkout reports the path with backslashes.
        normalized = value.replace("\\", "/")
        if marker in normalized:
            return "<core-repo>/tests/fixtures/" + normalized.split(marker, 1)[1]
        return value
    if isinstance(value, dict):
        return {k: _portable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_portable(v) for v in value]
    return value
WILD_FORMS = (
    (
        CORE_ROOT
        / "tests"
        / "fixtures"
        / "m105_evalplan"
        / "blank_form_3hak.hwpx",
        True,
    ),
    (
        CORE_ROOT
        / "tests"
        / "fixtures"
        / "m2_corpus"
        / "public_official_table.hwpx",
        True,
    ),
    (
        CORE_ROOT
        / "tests"
        / "fixtures"
        / "reader_robustness"
        / "irb_form_blank.hwpx",
        False,
    ),
)
pytestmark = pytest.mark.skipif(
    not all(path.is_file() for path, _expected in WILD_FORMS),
    reason="checked-in python-hwpx wild-form fixtures are unavailable",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: _plain(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


@pytest.mark.parametrize(
    ("source", "expected_open_safety"),
    WILD_FORMS,
    ids=[path.stem for path, _expected in WILD_FORMS],
)
def test_wild_form_read_only_behavior_is_exact_and_non_mutating(
    source: Path,
    expected_open_safety: bool,
) -> None:
    before = (_sha256(source), source.stat().st_mtime_ns)

    frozen = PARITY_GOLDEN[source.name]

    canonical_guidance = _plain(scan_form_guidance(source))
    canonical_residue = inspect_fill_residue(source, source).to_dict()
    canonical_score = score_form_fill(
        source,
        source,
        source,
        run_render=False,
    ).to_dict()

    assert _portable(canonical_guidance) == _portable(frozen["guidance"])
    assert _portable(canonical_residue) == _portable(frozen["residue"])
    assert _portable(canonical_score) == _portable(frozen["score"])
    assert (_sha256(source), source.stat().st_mtime_ns) == before
    assert build_hwpx_open_safety_report(source)["ok"] is expected_open_safety
