# SPDX-License-Identifier: Apache-2.0
"""Converters for documents other than HWPX/HWP (optional MarkItDown).

:class:`MarkItDownAdapter` hands a non-HWPX source to Microsoft MarkItDown
(``pip install "python-hwpx-automation[ingest]"``). MarkItDown is imported only
when a conversion runs, so importing this module stays light.

This was ``hwpx_automation.ingest_adapters`` before 8.0; that path still
works for one major (it is this module).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from ._types import (
    DocumentIngestError,
    DocumentIngestResult,
    DocumentSourceInfo,
)

__all__ = ["MarkItDownAdapter", "MissingMarkItDownDependency"]

#: Sources that belong to :class:`~hwpx_automation.ingest.HwpxMarkdownConverter`.
#: When python-hwpx cannot open one (HWP 3.x, a password, a damaged file) the
#: conversion must fail with that reason; MarkItDown would read the bytes as
#: text and return them as "Markdown".
_HWP_EXTENSIONS = frozenset({".hwpx", ".hwp"})
_HWP_MIMETYPES = frozenset({"application/hwp+zip", "application/x-hwp+zip"})


class MissingMarkItDownDependency(DocumentIngestError):
    """Raised when the optional MarkItDown runtime is not installed."""


class MarkItDownAdapter:
    """Fallback converter that delegates non-HWPX sources to Microsoft MarkItDown.

    ``.hwpx`` and ``.hwp`` sources are never accepted: they are python-hwpx's,
    and a file it cannot open is reported as such instead of being converted
    as text.
    """

    name = "MarkItDownAdapter"

    def accepts(self, file_stream: BinaryIO, source_info: DocumentSourceInfo) -> bool:
        del file_stream
        extension = (source_info.extension or "").lower()
        mimetype = (source_info.mimetype or "").lower()
        return extension not in _HWP_EXTENSIONS and mimetype not in _HWP_MIMETYPES

    def convert(
        self,
        file_stream: BinaryIO,
        source_info: DocumentSourceInfo,
        **kwargs: Any,
    ) -> DocumentIngestResult:
        del kwargs
        markitdown_cls = _load_markitdown_class()
        with _source_path(file_stream, source_info) as source_path:
            result = markitdown_cls().convert(str(source_path))
        markdown = _extract_markdown(result)
        return DocumentIngestResult(
            markdown=markdown,
            source_info=source_info,
            source_format=(source_info.extension or "unknown").lstrip(".") or "unknown",
            engine="markitdown",
            metadata={"converter": self.name},
            warnings=[
                "Converted by optional MarkItDown adapter; layout fidelity is not claimed.",
            ],
            lossiness="unknown",
        )


def _load_markitdown_class() -> type:
    try:
        from markitdown import MarkItDown  # pyright: ignore[reportMissingImports] - optional dependency, guarded
    except ImportError as exc:
        raise MissingMarkItDownDependency(
            "install python-hwpx-automation[ingest] (or hwpx-mcp-server[ingest]) "
            "to enable non-HWPX document ingest"
        ) from exc
    return MarkItDown


@contextlib.contextmanager
def _source_path(file_stream: BinaryIO, source_info: DocumentSourceInfo) -> Iterator[Path]:
    """The source as a file MarkItDown can open: its own path, or a temporary
    copy of the stream that is removed when the conversion ends."""

    if source_info.local_path:
        yield Path(source_info.local_path)
        return

    suffix = source_info.extension or ""
    # delete=False: on Windows a NamedTemporaryFile cannot be opened again by
    # name while it is open, so it is closed first and removed here.
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        start_pos = file_stream.tell()
        tmp.write(file_stream.read())
        file_stream.seek(start_pos)
    try:
        yield Path(tmp.name)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)


def _extract_markdown(result: Any) -> str:
    for attr in ("text_content", "markdown", "text"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
    if isinstance(result, str):
        return result
    raise ValueError("MarkItDown result did not include Markdown text")
