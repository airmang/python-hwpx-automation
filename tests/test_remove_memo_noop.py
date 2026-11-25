# SPDX-License-Identifier: Apache-2.0
"""``remove_memo`` says what it did.

On a paragraph with no memo it used to answer ``memo_removed: true``, write the file again and
move the backups up one step (so ``undo_last_edit`` no longer returned to the edit before it).
Now it answers ``memo_removed: false`` and leaves the document and its folder as they were.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from hwpx_automation import server
from hwpx_automation.core.document import open_doc


def _listing(folder: Path) -> dict[str, str]:
    """Every file under *folder* with the digest of its bytes."""

    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _document_with_one_memo(folder: Path) -> Path:
    """Paragraph 1 carries a memo; paragraph 2 and the table cell do not."""

    target = folder / "memo.hwpx"
    server.create_document(str(target))
    server.add_paragraph(str(target), "synthetic line with a memo")
    server.add_paragraph(str(target), "synthetic line without a memo")
    server.add_table(str(target), 1, 2, [["label", "value"]])
    server.add_memo(str(target), 1, "synthetic memo")
    assert len(open_doc(str(target)).notes.memos) == 1
    return target


def test_no_memo_on_the_paragraph_writes_nothing(tmp_path: Path) -> None:
    target = _document_with_one_memo(tmp_path)
    before = _listing(tmp_path)
    assert f"{target.name}.bak" in before  # the earlier edits left a backup to keep in place
    revision = server.get_document_info(str(target))["document_revision"]

    result = server.remove_memo(str(target), 2)

    assert result["memo_removed"] is False
    assert result["removed_count"] == 0
    assert result["dryRun"] is False
    assert result["paragraph_index"] == 2
    assert result["document_revision"] == revision
    assert "verificationReport" not in result and "backup" not in result
    assert _listing(tmp_path) == before  # same document bytes, same backups, nothing new
    assert len(open_doc(str(target)).notes.memos) == 1


def test_no_memo_in_the_table_cell_writes_nothing(tmp_path: Path) -> None:
    target = _document_with_one_memo(tmp_path)
    before = _listing(tmp_path)
    location = {"kind": "table_cell_paragraph", "table_index": 0, "row": 0, "col": 1, "cell_paragraph_index": 0}

    result = server.remove_memo(str(target), location=location)

    assert result["memo_removed"] is False
    assert _listing(tmp_path) == before


def test_dry_run_gives_the_same_answer_and_writes_nothing(tmp_path: Path) -> None:
    target = _document_with_one_memo(tmp_path)
    before = _listing(tmp_path)

    nothing = server.remove_memo(str(target), 2, dry_run=True)
    something = server.remove_memo(str(target), 1, dry_run=True)

    assert nothing["memo_removed"] is False and nothing["dryRun"] is True
    assert something["memo_removed"] is True and something["dryRun"] is True
    assert _listing(tmp_path) == before


def test_a_memo_that_is_there_is_removed_as_before(tmp_path: Path) -> None:
    target = _document_with_one_memo(tmp_path)
    before = _listing(tmp_path)

    result = server.remove_memo(str(target), 1)

    assert result["memo_removed"] is True
    assert result["removed_count"] == 1
    assert result["dryRun"] is False
    assert result["verificationReport"]["filePath"] == str(target)
    assert result["backup"]["created"] is True
    after = _listing(tmp_path)
    assert after[target.name] != before[target.name]
    # The bytes from just before this write are the backup now.
    assert after[f"{target.name}.bak"] == before[target.name]
    assert len(open_doc(str(target)).notes.memos) == 0

    # Asked again, there is nothing left to remove: no write, no backup moved.
    again = server.remove_memo(str(target), 1)
    assert again["memo_removed"] is False
    assert _listing(tmp_path) == after
