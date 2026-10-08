# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, cast

from ..core.resources import (
    DocumentMetadataResource,
    DocumentParagraphsResource,
    DocumentTablesResource,
    ParagraphResourceEntry,
    TableResourceEntry,
)
from ..upstream import (
    AnnotationOptions,
    create_object_finder,
    create_text_extractor,
    hwp5_conversion_report,
)

from .context import DocumentContext

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class ReadQueryService:
    def __init__(self, context: DocumentContext) -> None:
        self._context = context

    def get_metadata_by_handle(self, handle_id: str) -> Dict[str, Any]:
        handle = self._context.get_registered_handle(handle_id)
        payload = self.open_info(handle.path)
        model = DocumentMetadataResource(
            handleId=handle.handle_id,
            locator=handle.model_dump(by_alias=True),
            meta=payload["meta"],
            sectionCount=payload["sectionCount"],
            paragraphCount=payload["paragraphCount"],
            headerCount=payload["headerCount"],
        )
        return model.model_dump(by_alias=True)

    def get_paragraphs_by_handle(self, handle_id: str) -> Dict[str, Any]:
        handle = self._context.get_registered_handle(handle_id)
        resolved = self._context._resolve_path(handle.path)
        if self._context._is_legacy_hwp(resolved):
            paragraphs, _, _ = self._context._read_only_hwp_paragraphs(handle.path)
            hwp_serialized = [
                ParagraphResourceEntry(paragraphIndex=index, text=text)
                for index, text in enumerate(paragraphs)
            ]
            model = DocumentParagraphsResource(
                handleId=handle.handle_id, paragraphs=hwp_serialized
            )
            return model.model_dump(by_alias=True)

        serialized: List[ParagraphResourceEntry] = []
        with create_text_extractor(self._context._text_source(resolved)) as extractor:
            for paragraph in extractor.iter_document_paragraphs():
                serialized.append(
                    ParagraphResourceEntry(
                        paragraphIndex=paragraph.index,
                        text=paragraph.text(preserve_breaks=True),
                    )
                )
        model = DocumentParagraphsResource(
            handleId=handle.handle_id, paragraphs=serialized
        )
        return model.model_dump(by_alias=True)

    def get_tables_by_handle(self, handle_id: str) -> Dict[str, Any]:
        handle = self._context.get_registered_handle(handle_id)
        resolved = self._context._resolve_path(handle.path)
        if self._context._is_legacy_hwp(resolved):
            model = DocumentTablesResource(handleId=handle.handle_id, tables=[])
            return model.model_dump(by_alias=True)

        document, _ = self._context._open_document(handle.path)
        tables = self._context._iter_tables(document)
        serialized = [
            TableResourceEntry(
                tableIndex=index,
                rowCount=len(table.rows),
                columnCount=table.column_count,
            )
            for index, table in enumerate(tables)
        ]
        model = DocumentTablesResource(handleId=handle.handle_id, tables=serialized)
        return model.model_dump(by_alias=True)

    def open_info(self, path: str) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        if self._context._is_legacy_hwp(resolved):
            paragraphs, _, source = self._context._read_only_hwp_paragraphs(path)
            stat = resolved.stat()
            meta = {
                "path": self._context._relative_path(resolved),
                "absolutePath": str(resolved),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "format": "hwp",
                "readOnly": True,
                "extractionSource": source,
            }
            return {
                "meta": meta,
                "sectionCount": 0,
                "paragraphCount": len(paragraphs),
                "headerCount": 0,
            }

        document, resolved = self._context._open_document(path)
        sections = document.sections
        section_count = len(sections)
        paragraph_count = sum(len(section.paragraphs) for section in sections)
        header_count = len(document.parts.headers)
        stat = resolved.stat()
        meta = {
            "path": self._context._relative_path(resolved),
            "absolutePath": str(resolved),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
        conversion = hwp5_conversion_report(document)
        if conversion is not None:
            meta["format"] = "hwp"
            meta["hwpConversion"] = conversion
        return {
            "meta": meta,
            "sectionCount": section_count,
            "paragraphCount": paragraph_count,
            "headerCount": header_count,
        }

    def list_sections(self, path: str) -> Dict[str, Any]:
        document, _ = self._context._open_document(path)
        sections: List[Dict[str, Any]] = []
        for index, section in enumerate(document.sections):
            sections.append(
                {
                    "index": index,
                    "paragraphCount": len(section.paragraphs),
                    "partName": getattr(section, "part_name", None),
                }
            )
        return {"sections": sections}

    def list_headers(self, path: str) -> Dict[str, Any]:
        document, _ = self._context._open_document(path)
        headers: List[Dict[str, Any]] = []
        has_master_page = bool(document.parts.master_pages)
        for index, header in enumerate(document.parts.headers):
            headers.append(
                {
                    "index": index,
                    "styleCount": len(header.styles),
                    "bulletCount": len(header.bullets),
                    "hasMasterPage": has_master_page,
                    "partName": getattr(header, "part_name", None),
                }
            )
        return {"headers": headers}

    def read_text(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: Optional[int] = None,
        with_highlights: bool = False,
        with_footnotes: bool = False,
    ) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        if self._context._is_legacy_hwp(resolved):
            hwp_paragraphs, _, _ = self._context._read_only_hwp_paragraphs(path)
            effective_limit = (
                self._context.paging_limit if limit is None else max(1, limit)
            )
            start = max(0, offset)
            chunk = hwp_paragraphs[start : start + effective_limit]
            hwp_next_offset = None
            if start + effective_limit < len(hwp_paragraphs):
                hwp_next_offset = start + effective_limit
            return {"textChunk": "\n".join(chunk), "nextOffset": hwp_next_offset}

        if limit is None:
            effective_limit = self._context.paging_limit
        else:
            effective_limit = max(1, limit)
        annotations = None
        if with_highlights or with_footnotes:
            annotations = AnnotationOptions(
                highlight="markers" if with_highlights else "ignore",
                footnote="inline" if with_footnotes else "ignore",
                endnote="inline" if with_footnotes else "ignore",
            )
        paragraphs: List[str] = []
        next_offset: Optional[int] = None
        start = max(0, offset)
        with create_text_extractor(self._context._text_source(resolved)) as extractor:
            paragraph_iter = extractor.iter_document_paragraphs()
            sentinel = object()

            skip_exhausted = False
            for _ in range(start):
                if next(paragraph_iter, sentinel) is sentinel:
                    skip_exhausted = True
                    break

            if not skip_exhausted:
                while len(paragraphs) < effective_limit:
                    paragraph = next(paragraph_iter, sentinel)
                    if paragraph is sentinel:
                        break
                    paragraphs.append(
                        cast(Any, paragraph).text(annotations=annotations, preserve_breaks=True)
                    )

                if len(paragraphs) == effective_limit:
                    if next(paragraph_iter, sentinel) is not sentinel:
                        next_offset = start + len(paragraphs)

        return {"textChunk": "\n".join(paragraphs), "nextOffset": next_offset}

    def get_paragraphs(
        self,
        path: str,
        paragraph_indexes: Sequence[int],
        *,
        with_highlights: bool = False,
        with_footnotes: bool = False,
    ) -> Dict[str, Any]:
        if not paragraph_indexes:
            return {"paragraphs": []}
        normalized_indexes: List[int] = []
        unique_indexes: set[int] = set()
        for index in paragraph_indexes:
            if index < 0:
                raise ValueError("paragraphIndexes must contain non-negative integers")
            normalized_indexes.append(int(index))
            unique_indexes.add(int(index))

        resolved = self._context._resolve_path(path)
        if self._context._is_legacy_hwp(resolved):
            paragraphs, _, _ = self._context._read_only_hwp_paragraphs(path)
            hwp_collected = {
                idx: paragraphs[idx] for idx in unique_indexes if idx < len(paragraphs)
            }
            missing = [index for index in normalized_indexes if index not in hwp_collected]
            if missing:
                raise ValueError(
                    "paragraphIndexes out of range: "
                    + ", ".join(str(idx) for idx in sorted(set(missing)))
                )
            return {
                "paragraphs": [
                    {"paragraphIndex": index, "text": hwp_collected[index]}
                    for index in normalized_indexes
                ]
            }

        annotations = None
        if with_highlights or with_footnotes:
            annotations = AnnotationOptions(
                highlight="markers" if with_highlights else "ignore",
                footnote="inline" if with_footnotes else "ignore",
                endnote="inline" if with_footnotes else "ignore",
            )

        collected: Dict[int, str] = {}
        with create_text_extractor(self._context._text_source(resolved)) as extractor:
            for paragraph in extractor.iter_document_paragraphs():
                para_index = paragraph.index
                if para_index in unique_indexes and para_index not in collected:
                    collected[para_index] = paragraph.text(
                        annotations=annotations, preserve_breaks=True
                    )
                    if len(collected) == len(unique_indexes):
                        break

        missing = [index for index in normalized_indexes if index not in collected]
        if missing:
            raise ValueError(
                "paragraphIndexes out of range: "
                + ", ".join(str(idx) for idx in sorted(set(missing)))
            )

        return {
            "paragraphs": [
                {"paragraphIndex": index, "text": collected[index]}
                for index in normalized_indexes
            ]
        }

    def text_extract_report(self, path: str, mode: str = "plain") -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        if self._context._is_legacy_hwp(resolved):
            paragraphs, _, source = self._context._read_only_hwp_paragraphs(path)
            return {
                "content": "\n".join(paragraphs)
                + f"\n\n[HWP read-only mode] extraction_source={source}; annotations/structure are unavailable."
            }

        annotations = None
        if mode == "with_annotations":
            annotations = AnnotationOptions(
                highlight="markers",
                footnote="inline",
                endnote="inline",
                control="placeholder",
            )
        with create_text_extractor(self._context._text_source(resolved)) as extractor:
            content = extractor.extract_text(
                annotations=annotations,
                include_nested=True,
            )
        return {"content": content}

    def analyze_template_structure(
        self,
        path: str,
        *,
        placeholder_patterns: Optional[Sequence[str]] = None,
        lock_keywords: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        if self._context._is_legacy_hwp(resolved):
            paragraphs, _, source = self._context._read_only_hwp_paragraphs(path)
        else:
            paragraphs = []
            with create_text_extractor(self._context._text_source(resolved)) as extractor:
                for paragraph in extractor.iter_document_paragraphs():
                    paragraphs.append(paragraph.text(preserve_breaks=True))
            source = "hwpx.text_extractor"

        paragraph_count = len(paragraphs)
        if paragraph_count == 0:
            return {
                "summary": {
                    "isTemplate": False,
                    "paragraphCount": 0,
                    "placeholderCount": 0,
                    "extractionSource": source,
                },
                "regions": [],
                "placeholders": [],
            }

        top_band = max(1, min(3, max(1, paragraph_count // 10)))
        bottom_band = max(1, min(3, max(1, paragraph_count // 10)))
        if top_band + bottom_band > paragraph_count:
            bottom_band = max(1, paragraph_count - top_band)

        header_range = (0, max(0, top_band - 1))
        body_range = (top_band, max(top_band, paragraph_count - bottom_band - 1))
        footer_range = (max(0, paragraph_count - bottom_band), paragraph_count - 1)

        default_placeholder_patterns = [
            r"\{\{[^{}]+\}\}",
            r"\[[^\[\]]*(입력|작성|기재)[^\[\]]*\]",
            r"(본문 영역|제목을 입력하세요|날짜를 입력하세요|제20\d{2}년)",
        ]
        default_lock_keywords = [
            "로고",
            "교훈",
            "연락처",
            "슬로건",
            "학교장",
            "직인",
        ]

        compiled_patterns = [
            re.compile(pattern)
            for pattern in (placeholder_patterns or default_placeholder_patterns)
        ]
        lock_terms = [
            term.strip()
            for term in (lock_keywords or default_lock_keywords)
            if term and term.strip()
        ]

        def paragraph_zone(index: int) -> str:
            if header_range[0] <= index <= header_range[1]:
                return "header"
            if footer_range[0] <= index <= footer_range[1]:
                return "footer"
            return "body"

        placeholders: List[Dict[str, Any]] = []
        locked_indexes: set[int] = set()
        for index, text in enumerate(paragraphs):
            stripped = text.strip()
            if not stripped:
                continue

            zone = paragraph_zone(index)
            contains_lock_keyword = any(keyword in stripped for keyword in lock_terms)
            if zone in {"header", "footer"} or contains_lock_keyword:
                locked_indexes.add(index)

            for pattern in compiled_patterns:
                for match in pattern.finditer(stripped):
                    token = match.group(0)
                    placeholders.append(
                        {
                            "token": token,
                            "paragraphIndex": index,
                            "zone": zone,
                            "editable": index not in locked_indexes,
                            "context": stripped[:200],
                        }
                    )

        is_template = bool(placeholders) or any(
            index in locked_indexes for index in range(paragraph_count)
        )
        regions = [
            {
                "name": "header",
                "startParagraph": header_range[0],
                "endParagraph": header_range[1],
                "editable": False,
                "reason": "상단 고정 영역(휴리스틱)",
            },
            {
                "name": "body",
                "startParagraph": body_range[0],
                "endParagraph": body_range[1],
                "editable": True,
                "reason": "본문 편집 가능 영역(휴리스틱)",
            },
            {
                "name": "footer",
                "startParagraph": footer_range[0],
                "endParagraph": footer_range[1],
                "editable": False,
                "reason": "하단 고정 영역(휴리스틱)",
            },
        ]

        return {
            "summary": {
                "isTemplate": is_template,
                "paragraphCount": paragraph_count,
                "placeholderCount": len(placeholders),
                "lockedParagraphCount": len(locked_indexes),
                "extractionSource": source,
            },
            "regions": regions,
            "placeholders": placeholders,
        }

    def find(
        self,
        path: str,
        query: str,
        *,
        is_regex: bool = False,
        max_results: int = 100,
        context_radius: int = 80,
    ) -> Dict[str, Any]:
        if not query:
            raise ValueError("query must be a non-empty string")
        resolved = self._context._resolve_path(path)
        matches: List[Dict[str, Any]] = []
        radius = max(0, context_radius)

        def build_context(text: str, start: int, end: int) -> str:
            context_start = max(0, start - radius)
            context_end = min(len(text), end + radius)
            snippet = text[context_start:context_end]
            if context_start > 0:
                snippet = "..." + snippet
            if context_end < len(text):
                snippet = snippet + "..."
            return snippet

        pattern = re.compile(query) if is_regex else None
        if self._context._is_legacy_hwp(resolved):
            paragraphs, _, _ = self._context._read_only_hwp_paragraphs(path)
            for para_index, text in enumerate(paragraphs):
                if is_regex:
                    for match in pattern.finditer(text):  # type: ignore[union-attr]
                        matches.append(
                            {
                                "paragraphIndex": para_index,
                                "start": match.start(),
                                "end": match.end(),
                                "context": build_context(
                                    text, match.start(), match.end()
                                ),
                            }
                        )
                        if len(matches) >= max_results:
                            return {"matches": matches}
                else:
                    start = 0
                    while True:
                        found = text.find(query, start)
                        if found == -1:
                            break
                        matches.append(
                            {
                                "paragraphIndex": para_index,
                                "start": found,
                                "end": found + len(query),
                                "context": build_context(
                                    text, found, found + len(query)
                                ),
                            }
                        )
                        if len(matches) >= max_results:
                            return {"matches": matches}
                        start = found + len(query)
            return {"matches": matches}

        with create_text_extractor(self._context._text_source(resolved)) as extractor:
            for paragraph in extractor.iter_document_paragraphs():
                text = paragraph.text()
                if is_regex:
                    for match in pattern.finditer(text):  # type: ignore[union-attr]
                        matches.append(
                            {
                                "paragraphIndex": paragraph.index,
                                "start": match.start(),
                                "end": match.end(),
                                "context": build_context(
                                    text, match.start(), match.end()
                                ),
                            }
                        )
                        if len(matches) >= max_results:
                            return {"matches": matches}
                else:
                    start = 0
                    while True:
                        found = text.find(query, start)
                        if found == -1:
                            break
                        matches.append(
                            {
                                "paragraphIndex": paragraph.index,
                                "start": found,
                                "end": found + len(query),
                                "context": build_context(
                                    text, found, found + len(query)
                                ),
                            }
                        )
                        if len(matches) >= max_results:
                            return {"matches": matches}
                        start = found + len(query)
        return {"matches": matches}

    def object_find_by_tag(
        self,
        path: str,
        tag_name: str,
        *,
        max_results: int = 200,
    ) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        finder = create_object_finder(self._context._text_source(resolved))
        objects = []
        for found in finder.iter(tag=tag_name, limit=max_results):
            element = found.element
            objects.append(
                {
                    "type": element.tag,
                    "text": element.text or "",
                    "attrs": dict(element.attrib),
                    "path": found.path,
                }
            )
        return {"objects": objects}

    def object_find_by_attr(
        self,
        path: str,
        element_type: str | None,
        attr: str,
        value: str | None,
        *,
        max_results: int = 200,
    ) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        finder = create_object_finder(self._context._text_source(resolved))
        tag_filter = None if element_type in {None, "", "*"} else element_type
        attr_matcher: Any = value if value is not None else (lambda _: True)
        objects = []
        for found in finder.iter(
            tag=tag_filter, attrs={attr: attr_matcher}, limit=max_results
        ):
            element = found.element
            objects.append(
                {
                    "type": element.tag,
                    "text": element.text or "",
                    "attrs": dict(element.attrib),
                    "path": found.path,
                }
            )
        return {"objects": objects}
