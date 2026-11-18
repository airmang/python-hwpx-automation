# SPDX-License-Identifier: Apache-2.0
"""The dates a document this package writes carries (``content.hpf``): Hangul's on a save.

Owner decisions 8.0 23차·24차: the real time, fixed only in reproducibility tests and comparisons
(:func:`fixed_save_time`). Kept apart from :mod:`hwpx_automation.upstream` so the light layer
(``markdown``) can date the documents it makes without importing the rest of the package.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from hwpx.document import HwpxDocument

#: How Hangul writes ``CreatedDate``/``ModifiedDate`` in ``content.hpf``: UTC with a ``Z``
#: (``2026-11-18T01:46:14Z``), the same form python-hwpx gives a new document.
_SAVE_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_fixed_save_time: list[datetime] = []


def save_time() -> datetime:
    """The moment a document this package writes is dated with (UTC).

    The clock, unless a reproducibility test or comparison fixed it (:func:`fixed_save_time`) or
    ``SOURCE_DATE_EPOCH`` is set (as python-hwpx's ``HwpxDocument.new`` reads it).
    """

    if _fixed_save_time:
        return _fixed_save_time[-1]
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    return datetime.now(timezone.utc)


@contextmanager
def fixed_save_time(moment: datetime) -> Iterator[datetime]:
    """Date the documents written inside the block with *moment* instead of the clock.

    For reproducibility tests and output comparisons only (owner 8.0 23차): a document a tool
    writes is otherwise dated with the real time. A naive *moment* is local time.
    """

    fixed = (moment if moment.tzinfo is not None else moment.astimezone()).astimezone(timezone.utc)
    _fixed_save_time.append(fixed)
    try:
        yield fixed
    finally:
        _fixed_save_time.pop()


def stamp_save_dates(document: HwpxDocument) -> None:
    """Date *document* the way Hangul does when it saves: ``ModifiedDate`` is the save time, and
    ``CreatedDate`` is kept as the document had it, or set to the save time when it is empty or
    missing. The free-form ``date`` (Hangul's Korea-time text of the creation moment) is kept, or
    written for ``CreatedDate``'s moment when it is empty, so the three name one instant as in a
    document Hangul made (Hangul fills an empty ``date`` with its own save time).

    Hangul's re-saves keep ``CreatedDate`` and write the save time to ``ModifiedDate``. A new
    document (``HwpxDocument.new``, :func:`date_new_document`) already holds its creation time.
    Names (``creator``/``lastsaveby``) are not touched here.
    """

    parts = getattr(document, "parts", None)
    if parts is None:  # not a python-hwpx document (a test double): nothing to date
        return
    moment = save_time()
    stamp = moment.strftime(_SAVE_TIME_FORMAT)
    metadata = parts.metadata
    created = metadata.created_date if metadata is not None else None
    created_moment = _parse_save_time(created) if created else moment
    fields: dict[str, Any] = {"modified_date": stamp}
    if not created:
        fields["created_date"] = stamp
    if not (metadata is not None and metadata.date) and created_moment is not None:
        fields["date"] = created_moment
    document.parts.set_document_metadata(**fields)  # python-hwpx: only the written fields' text


def date_new_document(document: HwpxDocument) -> None:
    """Make *document* -- opened from a file this package ships (python-hwpx's blank skeleton, a
    design profile) to be a new document -- one made now: no names from that file
    (``creator``/``lastsaveby`` cleared) and ``CreatedDate``, ``ModifiedDate`` and ``date`` all the
    moment it is made (:func:`save_time`)."""

    moment = save_time()
    stamp = moment.strftime(_SAVE_TIME_FORMAT)
    document.parts.clear_document_authors()
    document.parts.set_document_metadata(created_date=stamp, modified_date=stamp, date=moment)


def _parse_save_time(text: str) -> datetime | None:
    try:
        moment = datetime.strptime(text.strip(), _SAVE_TIME_FORMAT)
    except ValueError:
        return None
    return moment.replace(tzinfo=timezone.utc)


_SAVE_DATE_META = re.compile(
    rb'(<opf:meta name="(CreatedDate|ModifiedDate|date)" content="text")(?:/>|>[^<]*</opf:meta>)'
)


def same_but_save_dates(before: bytes, after: bytes) -> bool:
    """Whether two ``content.hpf`` payloads differ in nothing but the dates :func:`stamp_save_dates`
    writes (``CreatedDate``/``ModifiedDate``/``date``, given or added): a check that keeps the parts a command
    did not touch byte for byte lets the save's own dates through, and nothing else."""

    if before == after:
        return True
    return _SAVE_DATE_META.sub(b"", before) == _SAVE_DATE_META.sub(b"", after)


__all__ = [
    "date_new_document",
    "fixed_save_time",
    "same_but_save_dates",
    "save_time",
    "stamp_save_dates",
]
