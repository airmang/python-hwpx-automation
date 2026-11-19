# SPDX-License-Identifier: Apache-2.0
"""Composing a document from a design profile rewrites no entry of the profile's skeleton that the
composition does not edit: an attachment in the skeleton keeps its bytes, even one whose text looks
like an XML declaration. The packaged profiles carry Hangul's XML declaration on their XML parts
(``scripts/normalize_profile_declarations.py``), so a composed document has it without the composer
touching ZIP entries or declarations itself."""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from hwpx_automation.office.authoring.design.composer import compose_bytes
from hwpx_automation.office.authoring.design.profile import Profile, _registry_root

ROOT = Path(__file__).resolve().parents[1]
HANGUL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
ATTACHMENT = "Custom/sample.txt"
ATTACHMENT_BYTES = b"<?xml version='1.0' encoding='utf-8'?>\n literal"


def _profile_with_attachment(tmp_path: Path) -> Profile:
    folder = tmp_path / "official_notice"
    shutil.copytree(_registry_root() / "official_notice", folder)
    with zipfile.ZipFile(folder / "template.hwpx", "a") as archive:
        archive.writestr(ATTACHMENT, ATTACHMENT_BYTES, compress_type=zipfile.ZIP_DEFLATED)
    return Profile.load(folder)


def test_an_attachment_in_the_skeleton_keeps_its_bytes(tmp_path: Path) -> None:
    data, result = compose_bytes(
        {"profile": "official_notice", "title": "도서관 휴관 안내", "blocks": [{"type": "paragraph", "text": "점검으로 휴관합니다."}]},
        profile=_profile_with_attachment(tmp_path),
    )
    assert result.ok, result.errors
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.read(ATTACHMENT) == ATTACHMENT_BYTES
        for name in ("Contents/content.hpf", "Contents/section0.xml", "Contents/header.xml"):
            assert archive.read(name).startswith(HANGUL), name


def test_the_packaged_profiles_carry_hangul_declarations() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "normalize_profile_declarations.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
