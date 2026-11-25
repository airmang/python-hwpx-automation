"""Integration style tests for the HTTP document storage backend."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, List
import zipfile
from xml.etree import ElementTree as ET

import pytest

from hwpx.document import HwpxDocument

from hwpx_automation.storage import HttpDocumentStorage, RemoteDocumentClient

_HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"


class FakeClient(RemoteDocumentClient):
    """Minimal fake HTTP client used to emulate remote responses."""

    def __init__(
        self,
        payloads: Dict[str, bytes],
        *,
        download_error: Exception | None = None,
        upload_error: Exception | None = None,
    ) -> None:
        self._payloads = dict(payloads)
        self._download_error = download_error
        self._upload_error = upload_error
        self.download_calls: List[str] = []
        self.upload_calls: List[tuple[str, bytes]] = []
        self.uploaded_payloads: Dict[str, bytes] = {}

    def download(self, path: str) -> bytes:
        self.download_calls.append(path)
        if self._download_error is not None:
            raise self._download_error
        try:
            return self._payloads[path]
        except KeyError as exc:  # pragma: no cover - defensive
            raise FileNotFoundError(path) from exc

    def upload(self, path: str, data: bytes) -> None:
        if self._upload_error is not None:
            raise self._upload_error
        self.upload_calls.append((path, data))
        self.uploaded_payloads[path] = data


@pytest.fixture()
def sample_payload() -> bytes:
    sample_path = Path(__file__).with_name("sample.hwpx")
    return sample_path.read_bytes()


def _payload_with_stale_lineseg(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload), "r") as source:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "Contents/section0.xml":
                    root = ET.fromstring(data)
                    paragraph = None
                    for candidate in root.findall(f".//{{{_HP_NS}}}p"):
                        text_nodes = candidate.findall(f".//{{{_HP_NS}}}t")
                        has_visible_text = any((node.text or "") for node in text_nodes)
                        if has_visible_text and all(
                            child.tag.rsplit("}", 1)[-1].lower() == "run"
                            for child in candidate
                        ):
                            paragraph = candidate
                            break
                    assert paragraph is not None
                    lineseg_array = ET.SubElement(paragraph, f"{{{_HP_NS}}}linesegarray")
                    ET.SubElement(lineseg_array, f"{{{_HP_NS}}}lineseg", {"textpos": "999"})
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                target.writestr(info, data)
    return buffer.getvalue()


def test_http_storage_downloads_and_caches_document(sample_payload: bytes) -> None:
    client = FakeClient({"docs/sample.hwpx": sample_payload})
    storage = HttpDocumentStorage(base_url="https://example.com", client=client)

    document, resolved = storage.open_document("docs/sample.hwpx")

    assert isinstance(document, HwpxDocument)
    assert resolved == Path("docs/sample.hwpx")
    assert client.download_calls == ["docs/sample.hwpx"]

    cached_path = storage._cache["docs/sample.hwpx"]
    assert cached_path.exists()
    assert cached_path.read_bytes() == sample_payload


def test_http_storage_open_rejects_unsafe_download_without_caching(sample_payload: bytes) -> None:
    client = FakeClient({"remote.hwpx": _payload_with_stale_lineseg(sample_payload)})
    storage = HttpDocumentStorage(base_url="https://example.com", client=client)

    with pytest.raises(RuntimeError, match="open-safety"):
        storage.open_document("remote.hwpx")

    assert "remote.hwpx" not in storage._cache
    assert list(storage._cache_dir.iterdir()) == []


def test_http_storage_save_uploads_changes(sample_payload: bytes) -> None:
    client = FakeClient({"remote.hwpx": sample_payload})
    storage = HttpDocumentStorage(base_url="https://example.com", client=client)

    document, resolved = storage.open_document("remote.hwpx")
    cached_path = storage._cache["remote.hwpx"]

    storage.save_document(document, resolved)

    assert client.upload_calls
    upload_path, upload_bytes = client.upload_calls[-1]
    assert upload_path == "remote.hwpx"
    assert upload_bytes == cached_path.read_bytes()
    assert client.uploaded_payloads["remote.hwpx"] == cached_path.read_bytes()


def test_http_storage_open_propagates_not_found() -> None:
    client = FakeClient({}, download_error=FileNotFoundError("missing"))
    storage = HttpDocumentStorage(base_url="https://example.com", client=client)

    with pytest.raises(FileNotFoundError):
        storage.open_document("missing.hwpx")


def test_http_storage_save_reports_upload_errors(sample_payload: bytes) -> None:
    client = FakeClient({"remote.hwpx": sample_payload}, upload_error=RuntimeError("boom"))
    storage = HttpDocumentStorage(base_url="https://example.com", client=client)
    document, resolved = storage.open_document("remote.hwpx")

    with pytest.raises(RuntimeError) as excinfo:
        storage.save_document(document, resolved)

    assert "HTTP storage save failed" in str(excinfo.value)


def test_http_storage_upload_failure_preserves_cache(sample_payload: bytes) -> None:
    client = FakeClient({"remote.hwpx": sample_payload}, upload_error=RuntimeError("boom"))
    storage = HttpDocumentStorage(base_url="https://example.com", client=client)
    document, resolved = storage.open_document("remote.hwpx")
    cached_path = storage._cache["remote.hwpx"]
    cached_before = cached_path.read_bytes()
    document.add_paragraph("local change that must not replace cache on upload failure")

    with pytest.raises(RuntimeError, match="HTTP storage save failed"):
        storage.save_document(document, resolved)

    assert cached_path.read_bytes() == cached_before
    assert list(cached_path.parent.glob(f"*{cached_path.suffix}")) == [cached_path]


def test_http_storage_does_not_write_an_opened_hwp_back_as_hwp(tmp_path: Path) -> None:
    import warnings

    from hwpx_automation.errors import HwpDocumentError
    from hwpx_automation.upstream import native_hwp5_supported

    if not native_hwp5_supported():
        pytest.skip("python-hwpx < 6.6.0 cannot open .hwp")
    source = tmp_path / "made.hwp"
    made = HwpxDocument.new()
    made.add_paragraph("ALPHA synthetic line")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # .hwp writing is experimental in core
        made.save(str(source))
    client = FakeClient({"remote.hwp": source.read_bytes()})
    storage = HttpDocumentStorage(base_url="https://example.com", client=client)
    document, resolved = storage.open_document("remote.hwp")

    with pytest.raises(HwpDocumentError) as refused:
        storage.save_document(document, resolved)

    assert refused.value.code == "HWP_SOURCE_OVERWRITE"
    assert client.upload_calls == []
