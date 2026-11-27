# SPDX-License-Identifier: Apache-2.0
"""Mail merge refuses a run whose rows would be written to the same file.

``filename_pattern="{name}.hwpx"`` with two rows of one name used to write the second row's
document over the first one and still report every row as created. The run is now refused
before anything is written: the error names the file and the rows, and the output folder is
left as it was. A file that was already in the output folder is still kept as ``.bak`` and
replaced (that rule did not change).
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

import pytest

from hwpx_automation import mail_merge as mail_merge_module
from hwpx_automation import server
from hwpx_automation.mail_merge import merge_template_rows
from hwpx_automation.runtime import _classified_error_payload
from hwpx_automation.upstream import HwpxDocument

CODE = "MAIL_MERGE_FILENAME_COLLISION"


def _template(path: Path) -> Path:
    with HwpxDocument.new() as document:
        document.add_paragraph("name: {{name}} / group: {{group}}")
        document.save(path)
    return path


def _listing(folder: Path) -> dict[str, str]:
    """Every file under *folder* with the digest of its bytes."""

    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _refusal(call: Any) -> dict[str, Any]:
    with pytest.raises(Exception) as caught:  # noqa: PT011 - the payload is what is checked
        call()
    return _classified_error_payload(caught.value)


def _text(path: Path) -> str:
    with HwpxDocument.open(path) as document:
        return "\n".join(paragraph.text for paragraph in document.paragraphs)


def test_rows_of_one_name_are_refused_and_nothing_is_written(tmp_path: Path) -> None:
    template = _template(tmp_path / "template.hwpx")
    out = tmp_path / "out"
    before = _listing(tmp_path)

    error = _refusal(
        lambda: server.mail_merge(
            str(template),
            data_rows=[
                {"name": "kim", "group": "one"},
                {"name": "lee", "group": "two"},
                {"name": "kim", "group": "three"},
            ],
            output_dir=str(out),
            filename_pattern="{name}.hwpx",
        )
    )

    assert error["code"] == CODE
    assert error["category"] == "validation"
    assert error["details"]["collisions"] == [{"filename": "kim.hwpx", "rowIndexes": [1, 3]}]
    assert "filename_pattern" in error["suggestion"]
    # Nothing was written: not the first row's document, not even the output folder.
    assert not out.exists()
    assert _listing(tmp_path) == before


def test_an_existing_output_folder_is_left_as_it_was(tmp_path: Path) -> None:
    template = _template(tmp_path / "template.hwpx")
    out = tmp_path / "out"
    out.mkdir()
    # A document already at the colliding name, and another one beside it.
    server.mail_merge(
        str(template),
        data_rows=[{"name": "kim", "group": "zero"}, {"name": "park", "group": "zero"}],
        output_dir=str(out),
        filename_pattern="{name}.hwpx",
    )
    before = _listing(out)
    assert sorted(before) == ["kim.hwpx", "park.hwpx"]

    error = _refusal(
        lambda: server.mail_merge(
            str(template),
            data_rows=[{"name": "kim", "group": "one"}, {"name": "kim", "group": "two"}],
            output_dir=str(out),
            filename_pattern="{name}.hwpx",
        )
    )

    assert error["code"] == CODE
    assert _listing(out) == before  # same bytes, and no .bak


@pytest.mark.parametrize(
    ("names", "pattern", "filenames"),
    [
        (["Kim", "kim"], "{name}.hwpx", ["Kim.hwpx", "kim.hwpx"]),  # case only: one file on Windows
        (["kim", "kim.hwpx"], "{name}", ["kim.hwpx"]),  # the suffix is added to the first
        (["kim.HWPX", "kim.hwpx"], "{name}", ["kim.HWPX", "kim.hwpx"]),
        (["a/kim", "b/kim"], "{name}.hwpx", ["kim.hwpx"]),  # only the file name is kept
        (["kim?", "kim*"], "{name}.hwpx", ["kim_.hwpx"]),  # unsafe characters become "_"
    ],
)
def test_names_that_are_one_file_on_windows_collide(
    names: list[str], pattern: str, filenames: list[str], tmp_path: Path
) -> None:
    template = _template(tmp_path / "template.hwpx")
    out = tmp_path / "out"

    with pytest.raises(mail_merge_module.MailMergeFilenameCollisionError) as caught:
        merge_template_rows(
            template,
            [{"name": name, "group": "g"} for name in names],
            output_dir=out,
            filename_pattern=pattern,
        )

    assert isinstance(caught.value, ValueError)
    assert caught.value.code == CODE
    (collision,) = caught.value.collisions
    assert collision["rowIndexes"] == [1, 2]
    assert collision["filename"] == filenames[0]
    assert collision.get("filenames", [collision["filename"]]) == filenames
    assert "filename_pattern" in str(caught.value) and "{index" in str(caught.value)
    assert not out.exists()


def test_the_archive_is_not_written_either(tmp_path: Path) -> None:
    template = _template(tmp_path / "template.hwpx")
    out = tmp_path / "out"
    archive = tmp_path / "merged.zip"

    error = _refusal(
        lambda: server.mail_merge(
            str(template),
            data_rows=[{"name": "kim", "group": "one"}, {"name": "kim", "group": "two"}],
            output_dir=str(out),
            filename_pattern="{name}.hwpx",
            zip_filename=str(archive),
        )
    )

    assert error["code"] == CODE
    assert not archive.exists() and not out.exists()


def test_an_archive_at_the_name_of_a_row_document_is_refused(tmp_path: Path) -> None:
    template = _template(tmp_path / "template.hwpx")
    out = tmp_path / "out"
    before = _listing(tmp_path)

    error = _refusal(
        lambda: server.mail_merge(
            str(template),
            data_rows=[{"name": "kim", "group": "one"}, {"name": "lee", "group": "two"}],
            output_dir=str(out),
            filename_pattern="{name}.hwpx",
            zip_filename=str(out / "LEE.hwpx"),
        )
    )

    assert error["code"] == CODE
    assert error["details"]["collisions"] == [
        {"filename": "lee.hwpx", "filenames": ["lee.hwpx", "LEE.hwpx"], "rowIndexes": [2], "archive": True}
    ]
    assert not out.exists()
    assert _listing(tmp_path) == before


def test_rows_a_strict_run_skips_do_not_collide(tmp_path: Path) -> None:
    template = _template(tmp_path / "template.hwpx")
    out = tmp_path / "out"

    report = server.mail_merge(
        str(template),
        data_rows=[{"name": "kim", "group": "one"}, {"name": "kim", "group": ""}],
        output_dir=str(out),
        filename_pattern="{name}.hwpx",
        strict=True,
    )

    # The second row is never written (its group is missing), so nothing is replaced.
    assert report["createdCount"] == 1
    assert [row["rowIndex"] for row in report["skipped"]] == [2]
    assert sorted(_listing(out)) == ["kim.hwpx"]
    assert "group: one" in _text(out / "kim.hwpx")


def test_distinct_names_are_written_and_an_older_file_is_kept_as_bak(tmp_path: Path) -> None:
    template = _template(tmp_path / "template.hwpx")
    out = tmp_path / "out"
    out.mkdir()
    older = out / "kim.hwpx"
    with HwpxDocument.new() as document:
        document.add_paragraph("OLDER synthetic document")
        document.save(older)
    older_bytes = older.read_bytes()
    archive = tmp_path / "merged.zip"

    report = server.mail_merge(
        str(template),
        data_rows=[{"name": "kim", "group": "one"}, {"name": "lee", "group": "two"}],
        output_dir=str(out),
        filename_pattern="{name}.hwpx",
        zip_filename=str(archive),
    )

    assert report["ok"] is True and report["createdCount"] == 2
    assert sorted(_listing(out)) == ["kim.hwpx", "kim.hwpx.bak", "lee.hwpx"]
    assert (out / "kim.hwpx.bak").read_bytes() == older_bytes
    assert "group: one" in _text(out / "kim.hwpx")
    with zipfile.ZipFile(archive) as bundle:
        assert sorted(bundle.namelist()) == ["kim.hwpx", "lee.hwpx"]
