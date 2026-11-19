# SPDX-License-Identifier: Apache-2.0
"""LangChain document loader for ``.hwpx`` and ``.hwp`` files.

Needs ``langchain-core``: ``pip install "python-hwpx-automation[langchain]"``.

    from hwpx_automation.integrations.langchain import HwpxLoader

    docs = HwpxLoader("계획.hwpx").load()

The loader is a thin layer over :mod:`hwpx_automation.ingest`: the page content
is the Markdown that :class:`hwpx_automation.ingest.DocumentIngestor` produces
(headings, lists and tables kept), and the metadata is
:meth:`hwpx_automation.ingest.DocumentIngestResult.flat_metadata`.

Moved from python-hwpx ``hwpx.integrations.langchain``; the documents it gives
are the same.
"""

from __future__ import annotations

from os import PathLike, fspath
from typing import Any, Iterator

try:
    from langchain_core.document_loaders import BaseLoader  # pyright: ignore[reportMissingImports] - optional dependency, guarded
    from langchain_core.documents import Document  # pyright: ignore[reportMissingImports] - optional dependency, guarded
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    # ModuleNotFoundError (an ImportError) naming the missing framework, so a
    # walk over this package can tell "extra not installed" from a broken import.
    raise ModuleNotFoundError(
        "hwpx_automation.integrations.langchain needs langchain-core. "
        'Install it with: pip install "python-hwpx-automation[langchain]"',
        name=exc.name,
    ) from exc

from ..ingest import DocumentIngestor

__all__ = ["HwpxLoader"]


class HwpxLoader(BaseLoader):
    """Load one ``.hwpx`` or ``.hwp`` file as a single Markdown document.

    Splitting is left to LangChain's text splitters; the Markdown keeps ``#``
    headings, so ``MarkdownHeaderTextSplitter`` can cut along the document's
    own sections. For a folder, pass this class to ``DirectoryLoader`` as
    ``loader_cls``.

    The metadata holds only strings and integers (``source``, ``source_format``,
    ``lossiness``, paragraph and table counts, …). ``lossiness`` and ``warnings``
    say what the Markdown leaves out, such as headers or memos, so a pipeline can
    tell a complete text from a partial one.

    A file that cannot be read (a password-protected document, HWP 3.x, a
    damaged file) raises :class:`hwpx_automation.ingest.UnsupportedDocumentFormat`
    with the reason in the message.
    """

    def __init__(
        self,
        file_path: str | PathLike[str],
        *,
        markdown_options: dict[str, Any] | None = None,
    ) -> None:
        """*markdown_options* are passed to
        ``hwpx_automation.markdown.to_markdown(doc, rich=True, ...)``."""

        self.file_path = fspath(file_path)
        self.markdown_options = dict(markdown_options or {})

    def lazy_load(self) -> Iterator[Document]:
        result = DocumentIngestor.default().convert(
            self.file_path,
            markdown_options=self.markdown_options,
        )
        yield Document(page_content=result.markdown, metadata=result.flat_metadata())
