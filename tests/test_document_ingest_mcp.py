from __future__ import annotations

from pathlib import Path

import pytest

from hwpx_automation import ingest_adapters
import hwpx_automation.server as server


def _sample_hwpx(tmp_path: Path) -> Path:
    target = tmp_path / "document_ingest_sample.hwpx"
    server.create_document(str(target))
    server.add_heading(str(target), "Project Report", level=1)
    server.add_paragraph(str(target), "Overview paragraph.")
    server.add_table(str(target), 2, 2, [["Name", "Value"], ["A", "1"]])
    return target


def test_document_to_markdown_from_local_hwpx(tmp_path: Path) -> None:
    target = _sample_hwpx(tmp_path)

    result = server.document_to_markdown(str(target))

    assert result["ok"] is True
    assert "Project Report" in result["markdown"]
    assert "| Name | Value |" in result["markdown"]
    assert result["meta"]["source_format"] == "hwpx"
    assert result["meta"]["engine"] == "python-hwpx"
    assert result["meta"]["table_count"] == 1
    assert result["attempts"][0]["converter"] == "HwpxMarkdownConverter"
    assert result["attempts"][0]["accepted"] is True


def test_document_to_markdown_chunks_paragraph_strategy(tmp_path: Path) -> None:
    target = _sample_hwpx(tmp_path)

    result = server.document_to_markdown(
        str(target),
        output="chunks",
        chunk_strategy="paragraph",
        max_chars_per_chunk=32,
    )

    assert result["ok"] is True
    assert result["chunks"]
    assert result["meta"]["chunk_strategy"] == "paragraph"
    assert result["meta"]["max_chars_per_chunk"] == 32


def test_document_extract_json_from_local_hwpx(tmp_path: Path) -> None:
    target = _sample_hwpx(tmp_path)

    result = server.document_extract_json(str(target))

    assert result["ok"] is True
    assert "Project Report" in result["doc"]["markdown"]
    assert result["doc"]["tables"][0]["data"][1] == ["A", "1"]
    assert result["meta"]["source_format"] == "hwpx"


def test_document_to_markdown_uses_markitdown_adapter_for_non_hwpx(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _FakeMarkItDown:
        def convert(self, path: str):
            assert path.endswith("sample.txt")
            return type("FakeResult", (), {"text_content": "# Converted\n\nPlain text body."})()

    monkeypatch.setattr(ingest_adapters, "_load_markitdown_class", lambda: _FakeMarkItDown)
    target = tmp_path / "sample.txt"
    target.write_text("plain text", encoding="utf-8")

    result = server.document_to_markdown(str(target))

    assert result["ok"] is True
    assert result["markdown"] == "# Converted\n\nPlain text body."
    assert result["meta"]["source_format"] == "txt"
    assert result["meta"]["engine"] == "markitdown"
    assert result["warnings"] == [
        "Converted by optional MarkItDown adapter; layout fidelity is not claimed.",
    ]
    assert result["attempts"][0]["converter"] == "HwpxMarkdownConverter"
    assert result["attempts"][0]["accepted"] is False
    assert result["attempts"][1]["converter"] == "MarkItDownAdapter"
    assert result["attempts"][1]["accepted"] is True


def test_document_to_markdown_reports_missing_markitdown_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _missing_markitdown():
        raise ingest_adapters.MissingMarkItDownDependency("install hwpx-mcp-server[ingest]")

    monkeypatch.setattr(ingest_adapters, "_load_markitdown_class", _missing_markitdown)
    target = tmp_path / "sample.txt"
    target.write_text("plain text", encoding="utf-8")

    result = server.document_to_markdown(str(target))

    assert result["ok"] is False
    assert result["error"] == "MissingMarkItDownDependency"
    assert "hwpx-mcp-server[ingest]" in result["message"]
    assert result["attempts"][0]["converter"] == "HwpxMarkdownConverter"
    assert result["attempts"][0]["accepted"] is False
    assert result["attempts"][1]["converter"] == "MarkItDownAdapter"
    assert result["attempts"][1]["accepted"] is True
    assert result["attempts"][1]["error_type"] == "MissingMarkItDownDependency"


@pytest.mark.parametrize("name", ["broken.hwp", "broken.hwpx"])
def test_an_hwp_python_hwpx_cannot_open_fails_instead_of_reaching_markitdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
) -> None:
    """A .hwp/.hwpx that python-hwpx cannot open (HWP 3.x, password, damaged)
    used to fall through to MarkItDown, which returned the file's bytes as
    Markdown with ok=True. It must fail with python-hwpx's own reason."""

    class _MarkItDownMustNotRun:
        def convert(self, path: str):
            raise AssertionError(f"MarkItDown was asked to convert {path}")

    monkeypatch.setattr(ingest_adapters, "_load_markitdown_class", lambda: _MarkItDownMustNotRun)
    target = tmp_path / name
    target.write_bytes(b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05" + b"\x00" * 64)

    result = server.document_to_markdown(str(target))

    assert result["ok"] is False
    assert "markdown" not in result
    assert result["error"] == "UnsupportedDocumentFormat"
    assert result["message"].startswith("HwpxMarkdownConverter could not convert the document: ")
    first = result["attempts"][0]
    assert first["converter"] == "HwpxMarkdownConverter"
    assert first["accepted"] is True
    assert first["error_type"]
    assert first["message"] and first["message"] in result["message"]
    assert result["attempts"][1] == {
        **result["attempts"][1],
        "converter": "MarkItDownAdapter",
        "accepted": False,
    }


def test_markitdown_adapter_refuses_hwp_sources_by_extension_and_mimetype() -> None:
    import io

    from hwpx_automation.ingest import DocumentSourceInfo, MarkItDownAdapter

    adapter = MarkItDownAdapter()
    stream = io.BytesIO(b"x")
    assert adapter.accepts(stream, DocumentSourceInfo(extension=".hwp")) is False
    assert adapter.accepts(stream, DocumentSourceInfo(extension=".HWPX")) is False
    assert adapter.accepts(stream, DocumentSourceInfo(mimetype="application/hwp+zip")) is False
    assert adapter.accepts(stream, DocumentSourceInfo(extension=".docx")) is True
    assert adapter.accepts(stream, DocumentSourceInfo()) is True


@pytest.mark.parametrize("fails", [False, True])
def test_markitdown_adapter_removes_its_temporary_copy_of_a_stream(
    monkeypatch: pytest.MonkeyPatch,
    fails: bool,
) -> None:
    """A stream with no local path is copied to a temporary file for MarkItDown;
    the copy is removed when the conversion ends, also when it fails."""

    import io

    from hwpx_automation.ingest import DocumentSourceInfo, MarkItDownAdapter

    seen: list[Path] = []

    class _FakeMarkItDown:
        def convert(self, path: str):
            seen.append(Path(path))
            assert Path(path).read_bytes() == b"plain text"
            if fails:
                raise ValueError("cannot read this")
            return type("FakeResult", (), {"text_content": "plain text"})()

    monkeypatch.setattr(ingest_adapters, "_load_markitdown_class", lambda: _FakeMarkItDown)
    stream = io.BytesIO(b"plain text")
    info = DocumentSourceInfo(extension=".txt")

    if fails:
        with pytest.raises(ValueError, match="cannot read this"):
            MarkItDownAdapter().convert(stream, info)
    else:
        result = MarkItDownAdapter().convert(stream, info)
        assert result.markdown == "plain text"

    assert len(seen) == 1 and seen[0].suffix == ".txt"
    assert not seen[0].exists()
    assert stream.tell() == 0
