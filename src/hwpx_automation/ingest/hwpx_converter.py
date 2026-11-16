# SPDX-License-Identifier: Apache-2.0
"""HWPX and HWP 5.0 ingest converter.

Moved from python-hwpx ``hwpx.ingest.hwpx_converter``. The Markdown comes from
:func:`hwpx_automation.markdown.to_markdown` (``rich=True``), the export that
python-hwpx 6.x served as ``doc.text.markdown(rich=True)``; the input checks
are python-hwpx's contract names (:mod:`hwpx.opc.security`).
"""

from __future__ import annotations

import html
import re
from typing import Any, BinaryIO, Iterable, Iterator
from zipfile import BadZipFile, ZipFile

from hwpx.document import HwpxDocument
from hwpx.errors import HwpxValueError
from hwpx.opc.package import HwpxPackage
from hwpx.opc.security import (
    MAX_ZIP_MIMETYPE_BYTES as _MAX_MIMETYPE_BYTES,
    HwpxSecurityError,
    guard_zip_file,
    read_member,
)
from hwpx.tools.exporter import table_grid_text

from ..markdown import to_markdown
from ._types import DocumentIngestResult, DocumentSourceInfo


class HwpxMarkdownConverter:
    """Convert HWPX packages and HWP 5.0 (``.hwp``) files to rich Markdown and
    lightweight structure metadata.

    An ``.hwp`` file is read through the same document model
    (:meth:`HwpxDocument.open`); the result says ``source_format="hwp"`` and
    carries what that conversion could not bring over in
    ``metadata["hwp_conversion"]``.
    """

    name = "HwpxMarkdownConverter"

    def accepts(self, file_stream: BinaryIO, source_info: DocumentSourceInfo) -> bool:
        extension = (source_info.extension or "").lower()
        if extension == ".hwpx":
            return True
        mimetype = (source_info.mimetype or "").lower()
        if mimetype in {"application/hwp+zip", "application/x-hwp+zip"}:
            return True
        # 확장자가 .hwp면 내용이 HWP 5.0이 아니어도 받는다. 그래야 HWP 3.x나
        # 암호 문서를 열 수 없는 사유가 변환 시도 기록에 남는다.
        if extension == ".hwp" or _starts_with_ole2(file_stream):
            return True
        if not extension and not mimetype:
            # 이름 없는 바이트·스트림: 받아서 열어 본다. 그래야 경로로 넘길 때처럼 못 여는
            # 사유(HWP 3.x, 빈 파일, 깨진 파일)가 남는다.
            return True
        return _looks_like_hwpx_package(file_stream)

    def convert(
        self,
        file_stream: BinaryIO,
        source_info: DocumentSourceInfo,
        **kwargs: Any,
    ) -> DocumentIngestResult:
        start_pos = file_stream.tell()
        data = file_stream.read()
        file_stream.seek(start_pos)

        markdown_kwargs = dict(kwargs.pop("markdown_options", {}) or {})
        markdown_kwargs.setdefault("detect_headings", True)
        # 읽는 쪽(LLM·색인)에는 본문 밖의 글도 문서의 글이다.
        markdown_kwargs.setdefault("headers_and_footers", True)
        markdown_kwargs.setdefault("memos", True)
        markdown_kwargs.setdefault("equations", True)
        # 목록 번호는 글의 일부다. 글자색 표시(<span>)는 읽는 쪽에 잡음이다.
        markdown_kwargs.setdefault("list_labels", True)
        markdown_kwargs.setdefault("colors", False)

        if not data:
            raise HwpxValueError(
                "빈 파일입니다. HWPX나 HWP 문서가 아닙니다.",
                context={"bytes": 0},
                suggestion="파일이 끝까지 저장·전송되었는지 확인하세요.",
            )
        doc = HwpxDocument.open(data)
        try:
            markdown = to_markdown(doc, rich=True, **markdown_kwargs)
            sections = _sections_payload(doc)
            tables = _tables_payload(doc)
            paragraph_count = len(list(doc.paragraphs))
            left_out = _left_out_content(doc, markdown)
            report = doc.conversion_report
        finally:
            doc.close()

        metadata: dict[str, Any] = {
            "section_count": len(sections),
            "paragraph_count": paragraph_count,
            "table_count": len(tables),
            "converter": self.name,
            "left_out": {kind: entry["count"] for kind, entry in left_out.items()},
        }
        warnings = _left_out_warnings(left_out)
        lossiness = _lossiness(left_out, markdown)
        if report is not None:
            metadata["hwp_conversion"] = {
                "unconverted": dict(report.unconverted),
                "dropped": dict(report.dropped),
            }
            if report.unconverted:
                summary = ", ".join(
                    f"{kind} {count}곳" for kind, count in sorted(report.unconverted.items())
                )
                warnings.append(f".hwp에서 문서 모델로 옮기지 못한 내용: {summary}")
                if lossiness == "low":
                    lossiness = "medium"

        return DocumentIngestResult(
            markdown=markdown,
            source_info=source_info,
            source_format="hwpx" if report is None else "hwp",
            engine="python-hwpx",
            engine_version=_python_hwpx_version(),
            metadata=metadata,
            sections=sections,
            tables=tables,
            warnings=warnings,
            lossiness=lossiness,
        )


#: 글을 담는 자리의 종류. 종류 이름은 ``metadata["left_out"]``의 키이자 계약이다.
#: 문단은 가장 가까운 담는 자리(머리말·꼬리말, 메모, 각주·미주, 글상자, 캡션, 표 칸)의 것으로
#: 센다. 표 칸 안 각주는 각주로, 글상자 안 표는 표로 한 번만 센다. 메모 필드(같은 메모가
#: 구역의 메모 목록에도 있다)와 숨은 설명의 문단은 따로 세지 않는다.
#: 글을 속성에 담는 조각(``run.content``) → (종류, 속성 이름).
_ATTRIBUTE_TEXT: dict[str, tuple[str, str]] = {
    "compose": ("composed_character", "composeText"),
    "checkBtn": ("form_caption", "caption"),
    "radioBtn": ("form_caption", "caption"),
    "btn": ("form_caption", "caption"),
    "textart": ("text_art", "text"),
}
_KIND_LABELS: dict[str, str] = {
    "header": "머리말",
    "footer": "꼬리말",
    "memo": "메모",
    "footnote": "각주",
    "endnote": "미주",
    "text_box": "글상자·도형 안 글",
    "equation": "수식",
    "ruby": "덧말",
    "composed_character": "글자 겹침",
    "form_caption": "양식 개체 캡션",
    "text_art": "글맵시",
    "master_page": "바탕쪽",
    "caption": "캡션",
    "table": "표",
}
#: Markdown이 글 사이에 끼우는 표시: 링크 주소, HTML 태그(문서 글의 ``<``는 ``&lt;``로 나간다).
_LINK_TARGET = re.compile(r"\]\([^)\s]*\)")
_HTML_TAG = re.compile(r"</?(?:span|mark|u|br|table|tr|td|th|caption|strong|em|del|s|a|img|sup)\b[^<>]*>")
_BACKSLASH_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
#: 비교에서 지우는 글자: 공백과 Markdown 서식·이스케이프 기호. 양쪽에서 같이 지운다.
_MARKDOWN_NOISE = re.compile(r"[\s\\*_~`|#>\[\]]+")


def _squash(text: str) -> str:
    """공백과 Markdown 서식 기호를 지운 비교용 글."""

    return _MARKDOWN_NOISE.sub("", text)


def _markdown_haystack(markdown: str) -> str:
    """Markdown을 글만 남겨 비교용으로: 링크 주소·태그를 빼고 이스케이프와 HTML 엔티티를 되돌린다."""

    text = _LINK_TARGET.sub("]", markdown)
    text = _HTML_TAG.sub("", text)
    text = _BACKSLASH_ESCAPE.sub(r"\1", text)
    return _squash(html.unescape(text))


def _own_segments(paragraph: Any) -> Iterator[str]:
    """문단 자신의 run에 든 글(``run.content``의 ``hp:t`` 글자)을, 글이 아닌 run 조각(컨트롤·수식·
    개체)에서 끊어 낸다.

    Markdown은 그 자리에 각주 표시·수식·링크를 끼우므로 한 덩어리로 찾으면 실린 글도
    빠진 것으로 보인다.
    """

    buffer: list[str] = []
    for run in paragraph.runs:
        for item in run.content:
            if item.container == "t":
                if item.kind in ("text", "unknown"):
                    # 내보내기는 한/글 하이픈(U+00AD)을 "-"로 쓴다.
                    buffer.append(item.text.replace("­", "-"))
            elif buffer:
                yield "".join(buffer)
                buffer = []
    if buffer:
        yield "".join(buffer)


def _paragraph_texts(paragraphs: Iterable[Any]) -> list[str]:
    return [segment for paragraph in paragraphs for segment in _own_segments(paragraph) if segment.strip()]


def _cell_paragraphs(table: Any) -> Iterator[Any]:
    for row in table.rows:
        for cell in row.cells:
            yield from cell.paragraphs


def _caption_of(obj: Any) -> Any:
    caption = getattr(obj, "caption", None)
    return caption if caption is not None and hasattr(caption, "paragraphs") else None


def _candidates(doc: HwpxDocument) -> Iterator[tuple[str, list[str]]]:
    """``(종류, 그 자리가 담은 글 조각들)``을 낸다(구역의 글, 바탕쪽 밖).

    머리말·꼬리말은 ``doc.page``, 각주·미주는 ``doc.notes``, 메모는 구역의 메모 목록, 표·글상자·캡션은
    ``doc.text.iter_objects()``, 수식·덧말·글자 겹침·양식 캡션·글맵시는 문단의 ``run.content``로 읽는다.
    """

    from ..markdown import equation_markdown

    for section in doc.sections:
        for story in doc.page.headers(section=section):
            yield "header", _paragraph_texts(story.paragraphs)
        for story in doc.page.footers(section=section):
            yield "footer", _paragraph_texts(story.paragraphs)
        group = section.memo_group
        for memo in group.memos if group is not None else ():
            yield "memo", _paragraph_texts(memo.paragraphs)
        for block in section.blocks:
            if hasattr(block, "rows"):  # 구역에 바로 놓인 표(문단 밖, 한/글이 아닌 프로그램이 쓴다)
                # 칸 문단을 hp:subList 없이 칸에 바로 두는 일이 많아 칸 글은 table_grid_text로 읽는다.
                yield "table", [text for row in table_grid_text(block) for text in row if text.strip()]
                caption = _caption_of(block)
                if caption is not None:
                    yield "caption", _paragraph_texts(caption.paragraphs)
    for note in doc.notes.footnotes:
        yield "footnote", _paragraph_texts(note.paragraphs)
    for note in doc.notes.endnotes:
        yield "endnote", _paragraph_texts(note.paragraphs)
    for place in doc.text.iter_objects():
        if place.section is None:
            continue  # 바탕쪽은 따로 센다
        obj = place.object
        if place.kind == "table":
            yield "table", _paragraph_texts(_cell_paragraphs(obj))
        elif place.kind == "shape":
            draw_text = obj.draw_text
            if draw_text is not None:
                yield "text_box", _paragraph_texts(draw_text.paragraphs)
        caption = _caption_of(obj)
        if caption is not None:
            yield "caption", _paragraph_texts(caption.paragraphs)
    for place in doc.text.iter_paragraphs():
        if place.section is None:
            continue
        for run in place.paragraph.runs:
            for item in run.content:
                if item.name in _ATTRIBUTE_TEXT:
                    kind, attribute = _ATTRIBUTE_TEXT[item.name]
                    yield kind, [item.attribute(attribute) or ""]
                elif item.kind == "equation":
                    # 수식은 LaTeX로 바뀌어 실린다. 실린 모양 그대로를 찾는다.
                    yield "equation", [equation_markdown(item.object.script)]
                elif item.kind == "ruby":
                    yield "ruby", [item.object.text or "", item.object.ruby_text or ""]


def _master_page_paragraphs(doc: HwpxDocument) -> list[list[Any]]:
    """바탕쪽마다 그 모든 문단(칸·글상자 안까지), 문서 차례로(``doc.text.iter_paragraphs()``의 바탕쪽 문단을
    바탕쪽의 첫 문단에서 나눈다)."""

    pages = list(doc.parts.master_pages)
    starts = {page.paragraphs[0]: number for number, page in enumerate(pages) if page.paragraphs}
    grouped: list[list[Any]] = [[] for _ in pages]
    current = None
    for place in doc.text.iter_paragraphs():
        if place.section is not None:
            continue
        current = starts.get(place.paragraph, current)
        if current is not None:
            grouped[current].append(place.paragraph)
    return grouped


def _deleted_marks(doc: HwpxDocument) -> int:
    """구역 글에 든 변경 추적의 지운 글 표시(``hp:deleteBegin``) 수."""

    return sum(
        1
        for place in doc.text.iter_paragraphs()
        if place.section is not None
        for run in place.paragraph.runs
        for item in run.content
        if item.kind == "delete_begin"
    )


def _left_out_content(doc: HwpxDocument, markdown: str) -> dict[str, dict[str, int]]:
    """Markdown에 글이 실리지 않은 요소를 종류별로 센다.

    미리 정한 목록이 아니라 결과와 대조해서 센다. 요소가 담은 글 조각이
    Markdown(이스케이프·공백 무시)에 없으면 그 요소를 빠진 것으로 본다. 그래서
    내보내기가 나중에 어떤 종류를 싣게 되면 이 보고에서도 저절로 빠진다.
    글이 같은 조각이 본문 다른 곳에 있으면 실린 것으로 보므로, 세는 값은
    하한이다.
    """

    haystack = _markdown_haystack(markdown)
    found: dict[str, dict[str, int]] = {}
    seen: set[tuple[str, tuple[str, ...]]] = set()
    cursor = 0

    def present(piece: str) -> bool:
        # 조각은 대개 문서 순서로 실려 있다. 앞서 찾은 자리부터 찾으면 큰 문서도 한 번 훑는다.
        nonlocal cursor
        index = haystack.find(piece, cursor)
        if index < 0:
            index = haystack.find(piece)
        if index < 0:
            return False
        cursor = index + len(piece)
        return True

    def record(kind: str, pieces: Iterable[str]) -> None:
        missing = [piece for piece in pieces if _squash(piece) and not present(_squash(piece))]
        if not missing:
            return
        # 머리말·꼬리말은 구역 설정과 본문 컨트롤에 같은 내용이 두 번 저장된다.
        key = (kind, tuple(missing))
        if kind in ("header", "footer") and key in seen:
            return
        seen.add(key)
        entry = found.setdefault(kind, {"count": 0, "chars": 0})
        entry["count"] += 1
        entry["chars"] += sum(len(_squash(piece)) for piece in missing)

    for kind, pieces in _candidates(doc):
        record(kind, pieces)
    if doc.parts.master_pages:
        for paragraphs in _master_page_paragraphs(doc):
            record("master_page", _paragraph_texts(paragraphs))

    deleted = _deleted_marks(doc)
    if deleted:
        found["tracked_deletion"] = {"count": deleted, "chars": 0}
    return found


def _left_out_warnings(left_out: dict[str, dict[str, int]]) -> list[str]:
    warnings = [
        f"Markdown에 없는 내용: {_KIND_LABELS[kind]} {entry['count']}곳({entry['chars']}자)"
        for kind, entry in left_out.items()
        if kind != "tracked_deletion"
    ]
    if "tracked_deletion" in left_out:
        warnings.append(
            f"변경 추적으로 지운 글 표시가 {left_out['tracked_deletion']['count']}곳 있습니다. "
            "지운 글이 살아 있는 글과 구분 없이 Markdown에 섞여 나올 수 있습니다."
        )
    return warnings


def _lossiness(left_out: dict[str, dict[str, int]], markdown: str) -> str:
    """``low``: 빠진 것이 없다. ``medium``: 빠진 것이 있다. ``high``: 빠진 글이
    Markdown에 실린 글보다 많다."""

    if not left_out:
        return "low"
    missing_chars = sum(entry["chars"] for entry in left_out.values())
    return "high" if missing_chars > len(_squash(markdown)) else "medium"


_OLE2_MAGIC = HwpxPackage.OLE2_MAGIC


def _starts_with_ole2(file_stream: BinaryIO) -> bool:
    """HWP 5.0(``.hwp``)이 쓰는 복합 파일로 시작하는가."""

    cur_pos = file_stream.tell()
    try:
        return file_stream.read(len(_OLE2_MAGIC)) == _OLE2_MAGIC
    finally:
        file_stream.seek(cur_pos)


def _looks_like_hwpx_package(file_stream: BinaryIO) -> bool:
    cur_pos = file_stream.tell()
    try:
        with ZipFile(file_stream) as archive:
            guard_zip_file(archive)
            names = set(archive.namelist())
            if "mimetype" in names:
                try:
                    mimetype = (
                        read_member(archive, "mimetype", limit=_MAX_MIMETYPE_BYTES)
                        .decode("utf-8", "replace")
                        .strip()
                    )
                    if "hwp" in mimetype.lower() or "hwpx" in mimetype.lower():
                        return True
                except Exception:
                    pass
            return any(name.startswith("Contents/section") and name.endswith(".xml") for name in names)
    except (BadZipFile, OSError, HwpxSecurityError):
        return False
    finally:
        file_stream.seek(cur_pos)


def _sections_payload(doc: HwpxDocument) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for index, section in enumerate(doc.sections):
        paragraphs = list(section.paragraphs)
        sections.append(
            {
                "index": index,
                "paragraph_count": len(paragraphs),
                "text_preview": "\n".join(
                    (paragraph.text or "").strip()
                    for paragraph in paragraphs[:5]
                    if (paragraph.text or "").strip()
                )[:500],
            }
        )
    return sections


def _tables_payload(doc: HwpxDocument) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for paragraph_index, paragraph in enumerate(doc.paragraphs):
        for table in paragraph.tables:
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            tables.append(
                {
                    "table_index": len(tables),
                    "paragraph_index": paragraph_index,
                    "rows": len(rows),
                    "cols": max((len(row) for row in rows), default=0),
                    "data": rows,
                }
            )
    return tables


def _python_hwpx_version() -> str:
    from importlib.metadata import PackageNotFoundError, version as package_version

    try:
        return package_version("python-hwpx")
    except PackageNotFoundError:
        return "0+unknown"
