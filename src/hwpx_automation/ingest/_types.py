# SPDX-License-Identifier: Apache-2.0
"""What the ingest dispatcher and its converters exchange: source info, results, errors.

Moved from python-hwpx ``hwpx.ingest.base`` (7.0 keeps the engine only). The
names are served from :mod:`hwpx_automation.ingest.base` and the package root as
before; they sit in this leaf module so that a converter can build a result
without importing the dispatcher that registers it. The errors stay
python-hwpx's :class:`hwpx.errors.HwpxError` family with the same codes, so
callers that catch ``HwpxError`` keep working.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, BinaryIO, Iterable, Protocol

from hwpx.errors import HwpxError


@dataclass(frozen=True, kw_only=True)
class DocumentSourceInfo:
    """Metadata known or inferred about an input document."""

    mimetype: str | None = None
    extension: str | None = None
    charset: str | None = None
    filename: str | None = None
    local_path: str | None = None
    url: str | None = None

    def copy_and_update(self, *others: "DocumentSourceInfo", **kwargs: Any) -> "DocumentSourceInfo":
        data = asdict(self)
        for other in others:
            data.update({key: val for key, val in asdict(other).items() if val is not None})
        data.update({key: val for key, val in kwargs.items() if val is not None})
        return DocumentSourceInfo(**data)


@dataclass(frozen=True, kw_only=True)
class ConversionAttempt:
    """One converter decision or failure."""

    converter: str
    accepted: bool
    error_type: str | None = None
    message: str | None = None
    #: 실패한 변환의 오류가 ``HwpxError`` 이면 그 code와 suggestion.
    code: str | None = None
    suggestion: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: val for key, val in asdict(self).items() if val is not None}


@dataclass(kw_only=True)
class DocumentIngestResult:
    """Normalized Markdown plus structured conversion metadata."""

    markdown: str
    source_info: DocumentSourceInfo
    source_format: str
    engine: str
    engine_version: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    attempts: list[ConversionAttempt] = field(default_factory=list)
    lossiness: str = "unknown"

    @property
    def text_content(self) -> str:
        """Compatibility alias matching common Markdown conversion APIs."""

        return self.markdown

    def flat_metadata(self) -> dict[str, str | int]:
        """글자·숫자 값만 담은 메타데이터.

        벡터 저장소 가운데는 목록이나 사전 값을 받지 않는 것이 있다. 검색 결과에
        붙여 둘 만한 것(출처, 형식, 제목, 개수, 손실 정도)만 한 겹으로 담고,
        경고는 줄바꿈으로 이은 글 하나로 싣는다.
        """

        data: dict[str, str | int] = {
            "source_format": self.source_format,
            "engine": self.engine,
            "lossiness": self.lossiness,
        }
        source = self.source_info.local_path or self.source_info.filename
        if source:
            data["source"] = source
        if self.engine_version:
            data["engine_version"] = self.engine_version
        if self.title:
            data["title"] = self.title
        for key in ("section_count", "paragraph_count", "table_count"):
            value = self.metadata.get(key)
            if isinstance(value, int):
                data[key] = value
        if self.warnings:
            data["warnings"] = "\n".join(self.warnings)
        return data

    def as_dict(self) -> dict[str, Any]:
        return {
            "markdown": self.markdown,
            "sourceInfo": asdict(self.source_info),
            "sourceFormat": self.source_format,
            "engine": self.engine,
            "engineVersion": self.engine_version,
            "title": self.title,
            "metadata": self.metadata,
            "sections": self.sections,
            "tables": self.tables,
            "warnings": self.warnings,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "lossiness": self.lossiness,
        }


class DocumentIngestError(HwpxError, RuntimeError):
    """Base class for ingest failures with converter-attempt diagnostics."""

    default_code = "ingest-failed"

    def __init__(self, message: str, *, attempts: Iterable[ConversionAttempt] = ()) -> None:
        super().__init__(message)
        self.attempts = list(attempts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": type(self).__name__,
            "message": str(self),
            "attempts": [attempt.as_dict() for attempt in self.attempts],
        }


class UnsupportedDocumentFormat(DocumentIngestError):
    """Raised when no registered converter accepts the source."""

    default_code = "ingest-format-unsupported"


class DocumentConverter(Protocol):
    """Converter contract for a specific source family."""

    name: str

    def accepts(self, file_stream: BinaryIO, source_info: DocumentSourceInfo) -> bool:
        """Return True if this converter should attempt conversion."""
        ...

    def convert(
        self,
        file_stream: BinaryIO,
        source_info: DocumentSourceInfo,
        **kwargs: Any,
    ) -> DocumentIngestResult:
        """Convert the source into normalized Markdown."""
        ...


def normalize_markdown(markdown: str) -> str:
    """Normalize whitespace in generated Markdown without changing content meaning."""

    text = "\n".join(line.rstrip() for line in re.split(r"\r?\n", markdown or ""))
    return re.sub(r"\n{3,}", "\n\n", text).strip()
