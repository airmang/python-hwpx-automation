# SPDX-License-Identifier: Apache-2.0
"""Small MarkItDown-style ingest dispatcher.

Moved from python-hwpx ``hwpx.ingest.base`` (7.0 keeps the engine only). Every
name of that module is here; the source info, results and errors are defined in
the leaf module :mod:`hwpx_automation.ingest._types` (so converters do not import
this dispatcher) and served from here unchanged.
"""

from __future__ import annotations

from io import BytesIO, TextIOBase
import mimetypes
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from hwpx.errors import HwpxError

from ._types import (
    ConversionAttempt,
    DocumentConverter,
    DocumentIngestError,
    DocumentIngestResult,
    DocumentSourceInfo,
    UnsupportedDocumentFormat,
    normalize_markdown,
)

__all__ = [
    "ConversionAttempt",
    "DocumentConverter",
    "DocumentIngestError",
    "DocumentIngestResult",
    "DocumentIngestor",
    "DocumentSourceInfo",
    "UnsupportedDocumentFormat",
    "normalize_markdown",
]


class DocumentIngestor:
    """Priority-ordered converter dispatcher."""

    def __init__(self, converters: Iterable[DocumentConverter] | None = None) -> None:
        self._converters: list[tuple[float, int, DocumentConverter]] = []
        self._sequence = 0
        if converters is not None:
            for converter in converters:
                self.register_converter(converter)

    @classmethod
    def default(cls) -> "DocumentIngestor":
        from .hwpx_converter import HwpxMarkdownConverter

        ingestor = cls()
        ingestor.register_converter(HwpxMarkdownConverter(), priority=0.0)
        return ingestor

    def register_converter(self, converter: DocumentConverter, *, priority: float = 0.0) -> None:
        self._converters.append((priority, self._sequence, converter))
        self._sequence += 1

    def convert(
        self,
        source: str | Path | bytes | BinaryIO,
        *,
        source_info: DocumentSourceInfo | None = None,
        **kwargs: Any,
    ) -> DocumentIngestResult:
        stream, inferred = _source_to_stream(source)
        info = inferred if source_info is None else inferred.copy_and_update(source_info)
        attempts: list[ConversionAttempt] = []
        errors: dict[int, BaseException] = {}
        start_pos = stream.tell()

        for _priority, _seq, converter in sorted(self._converters, key=lambda item: (item[0], item[1])):
            name = getattr(converter, "name", type(converter).__name__)
            stream.seek(start_pos)
            try:
                accepted = bool(converter.accepts(stream, info))
            except Exception as exc:
                attempts.append(
                    ConversionAttempt(
                        converter=name,
                        accepted=False,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue
            finally:
                stream.seek(start_pos)

            attempts.append(ConversionAttempt(converter=name, accepted=accepted))
            if not accepted:
                continue

            try:
                result = converter.convert(stream, info, **kwargs)
            except Exception as exc:
                attempts[-1] = ConversionAttempt(
                    converter=name,
                    accepted=True,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    code=getattr(exc, "code", None) if isinstance(exc, HwpxError) else None,
                    suggestion=getattr(exc, "suggestion", None) if isinstance(exc, HwpxError) else None,
                )
                errors[len(attempts) - 1] = exc
                stream.seek(start_pos)
                continue
            result.markdown = normalize_markdown(result.markdown)
            result.attempts = attempts
            return result

        failed = [index for index, attempt in enumerate(attempts) if attempt.accepted and attempt.message]
        if failed:
            # 받은 변환기가 실패했으면 그 사유를 문구에 싣는다. attempts를 보지 않는
            # 호출자(로더, 일괄 처리)도 왜 못 읽었는지 알 수 있다. 원래 오류의 code는
            # context["cause_code"]에, suggestion은 그대로 싣는다.
            last = attempts[failed[-1]]
            error = UnsupportedDocumentFormat(
                f"{last.converter} could not convert the document: {last.message}",
                attempts=attempts,
            )
            if last.code:
                error.context["cause_code"] = last.code
            if last.suggestion:
                error.suggestion = last.suggestion
            raise error from errors.get(failed[-1])
        raise UnsupportedDocumentFormat("no registered converter accepted the document", attempts=attempts)


def _source_to_stream(source: str | Path | bytes | BinaryIO) -> tuple[BinaryIO, DocumentSourceInfo]:
    if isinstance(source, bytes):
        return BytesIO(source), DocumentSourceInfo()
    if isinstance(source, Path):
        return _path_to_stream(source)
    if isinstance(source, str):
        if source.startswith(("http:", "https:", "file:", "data:")):
            raise UnsupportedDocumentFormat("URI sources are not implemented in python-hwpx ingest")
        return _path_to_stream(Path(source))
    if hasattr(source, "read") and callable(source.read) and not isinstance(source, TextIOBase):
        stream = source
        if not stream.seekable():
            stream = BytesIO(stream.read())
        return stream, DocumentSourceInfo()
    raise TypeError(f"unsupported document source type: {type(source).__name__}")


def _path_to_stream(path: Path) -> tuple[BinaryIO, DocumentSourceInfo]:
    resolved = path.expanduser().resolve()
    mimetype, charset = mimetypes.guess_type(str(resolved), strict=False)
    info = DocumentSourceInfo(
        mimetype=mimetype,
        charset=charset,
        extension=resolved.suffix.lower() or None,
        filename=resolved.name,
        local_path=str(resolved),
    )
    return BytesIO(resolved.read_bytes()), info
