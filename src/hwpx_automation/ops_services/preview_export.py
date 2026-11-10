# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import json
import logging
import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from ..configuration import absolute_executable, env_value, find_executable
from ..hwp_converter import HwpConversionError, convert_hwp_to_hwpx
from ..upstream import (
    export_document,
)

from .context import DocumentContext

logger = logging.getLogger("hwpx_automation.hwpx_ops")

try:  # python-hwpx >= layout preview feature
    from hwpx.tools.layout_preview import (
        render_layout_preview as render_hwpx_layout_preview,
    )
except Exception as exc:  # pragma: no cover - depends on installed python-hwpx
    render_hwpx_layout_preview = None
    _LAYOUT_PREVIEW_IMPORT_ERROR: Exception | None = exc
else:
    _LAYOUT_PREVIEW_IMPORT_ERROR = None

try:  # python-hwpx >= document viewer feature ([preview] extra for MathML)
    from hwpx.tools.document_viewer import (
        render_document_viewer as render_hwpx_document_viewer,
    )
except Exception as exc:  # pragma: no cover - depends on installed python-hwpx
    render_hwpx_document_viewer = None
    _DOCUMENT_VIEWER_IMPORT_ERROR: Exception | None = exc
else:
    _DOCUMENT_VIEWER_IMPORT_ERROR = None

try:  # optional MathML converter (python-hwpx[preview])
    from hwpx.equation import latex2mathml_available as _latex2mathml_available
except Exception:  # pragma: no cover - depends on installed python-hwpx
    _latex2mathml_available = None

_PREVIEW_SCHEMA_VERSION = "hwpx.render-preview.v1"
_VISUAL_REVIEW_SCHEMA_VERSION = "hwpx.visual-review.v1"
# Cap for inline-embedded preview PNGs (per page). Oversized pages keep their
# on-disk path but skip the base64 payload so a response can't balloon.
_DEFAULT_MAX_PREVIEW_IMAGE_BYTES = 6 * 1024 * 1024
# Cap for the inline viewer HTML copy. The viewer is always written to disk, so
# an oversized document degrades to "path only" instead of bloating the response.
_DEFAULT_MAX_VIEWER_HTML_BYTES = 2 * 1024 * 1024
_CSS_PX_PER_MM = 96 / 25.4
_CHROME_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def _preview_slug(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.stem).strip("-")
    return stem or "document"


def _chrome_executable() -> str | None:
    # Only absolute locations are eligible: the working directory is usually
    # the document workspace and must never supply the browser binary.
    env_path = absolute_executable(env_value("CHROME_PATH"))
    if env_path:
        return env_path
    for candidate in _CHROME_CANDIDATES:
        if candidate.startswith("/"):
            resolved = absolute_executable(candidate)
        else:
            resolved = find_executable(candidate)
        if resolved:
            return resolved
    return None


def _page_viewport(page: Dict[str, Any]) -> tuple[int, int]:
    width = max(320, math.ceil(float(page.get("widthMm", 210.0)) * _CSS_PX_PER_MM))
    height = max(320, math.ceil(float(page.get("heightMm", 297.0)) * _CSS_PX_PER_MM))
    return width, height


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# The core equation renderer stamps every equation span with a ``data-eq-mode``
# marker (``mathml`` on success, ``latex``/``script`` on the fail-closed
# fallbacks). Counting those markers gives an honest fidelity summary without a
# new core API.
_EQ_MODE_KEYS: dict[str, str] = {
    "mathml": "mathml",
    "latex": "latexFallback",
    "script": "scriptFallback",
}


def _count_equation_modes(html: str) -> dict[str, int]:
    """Summarize equation render fidelity by counting ``data-eq-mode`` markers."""

    return {
        key: html.count(f'data-eq-mode="{mode}"') for mode, key in _EQ_MODE_KEYS.items()
    }


def _equation_tier(counts: Mapping[str, int]) -> str:
    """Honest worst-case equation tier for the fidelity label."""

    if sum(counts.values()) == 0:
        return "none"
    if counts.get("scriptFallback"):
        return "script-fallback"
    if counts.get("latexFallback"):
        return "latex-fallback"
    return "mathml"


def _lean_disk_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Copy *manifest* for on-disk persistence without the inline payloads.

    The manifest.json never carries the base64 page PNGs or the inline viewer
    HTML — those live in the response (and, for the viewer, in ``viewer.html``).
    """
    disk_manifest = dict(manifest)
    disk_manifest["screenshots"] = [
        {key: value for key, value in shot.items() if key != "imageBase64"}
        for shot in manifest.get("screenshots", [])
    ]
    viewer_block = manifest.get("viewer")
    if isinstance(viewer_block, dict):
        disk_manifest["viewer"] = {
            key: value for key, value in viewer_block.items() if key != "html"
        }
    return disk_manifest


class PreviewExportService:
    def __init__(self, context: DocumentContext) -> None:
        self._context = context

    def export_text(self, path: str) -> Dict[str, Any]:
        """Export document content as plain text."""
        document, _ = self._context._open_document(path)
        return {"content": export_document(document, "text"), "format": "text"}

    def export_html(self, path: str) -> Dict[str, Any]:
        """Export document content as HTML."""
        document, _ = self._context._open_document(path)
        return {"content": export_document(document, "html"), "format": "html"}

    def export_markdown(self, path: str) -> Dict[str, Any]:
        """Export document content as Markdown."""
        document, _ = self._context._open_document(path)
        return {"content": export_document(document, "markdown"), "format": "markdown"}

    def _preview_output_dir(self, source_path: Path, output_dir: Optional[str]) -> Path:
        if output_dir:
            resolved = self._context.storage.resolve_path(output_dir, must_exist=False)
        else:
            resolved = source_path.parent / f"{_preview_slug(source_path)}-preview"
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _embed_screenshot_image(
        self,
        item: dict[str, Any],
        png_path: Path,
        *,
        embed_images: bool,
        max_image_bytes: int | None,
    ) -> None:
        """Attach a base64 PNG payload to a screenshot item, bounded by a byte cap.

        Keeps the on-disk artifact regardless; only the inline payload is gated so
        an oversized page degrades to "path only" instead of bloating the response.
        """
        if not embed_images:
            return
        try:
            raw = png_path.read_bytes()
        except OSError as exc:  # pragma: no cover - filesystem edge
            item["imageOmitted"] = f"read_error: {exc}"
            return
        item["bytes"] = len(raw)
        if max_image_bytes is not None and len(raw) > max_image_bytes:
            item["imageOmitted"] = "exceeds_max_image_bytes"
            return
        item["imageBase64"] = base64.b64encode(raw).decode("ascii")
        item["imageMime"] = "image/png"

    def _capture_preview_pages(
        self,
        *,
        page_html_paths: Sequence[Path],
        pages: Sequence[Dict[str, Any]],
        output_dir: Path,
        max_pages: int | None,
        embed_images: bool = False,
        max_image_bytes: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        capture_count = len(page_html_paths)
        if max_pages is not None:
            capture_count = min(capture_count, max(0, max_pages))

        try:
            from playwright.sync_api import sync_playwright  # pyright: ignore[reportMissingImports] - optional dependency, guarded
        except Exception as playwright_exc:
            playwright_error = str(playwright_exc)
        else:  # pragma: no cover - local CI normally uses Chrome CLI fallback
            screenshots: list[dict[str, Any]] = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for index, html_path in enumerate(page_html_paths[:capture_count]):
                        page_info = pages[index]
                        width, height = _page_viewport(page_info)
                        output_path = output_dir / f"page-{index + 1:03d}.png"
                        browser_page = browser.new_page(
                            viewport={"width": width, "height": height},
                            device_scale_factor=1,
                        )
                        browser_page.goto(html_path.as_uri(), wait_until="load")
                        browser_page.screenshot(path=str(output_path), full_page=True)
                        browser_page.close()
                        item = {
                            "pageIndex": index,
                            "path": self._context._relative_path(output_path),
                            "backend": "playwright-chromium",
                            "widthPx": width,
                            "heightPx": height,
                        }
                        self._embed_screenshot_image(
                            item,
                            output_path,
                            embed_images=embed_images,
                            max_image_bytes=max_image_bytes,
                        )
                        screenshots.append(item)
                finally:
                    browser.close()
            return screenshots, {
                "requested": True,
                "available": True,
                "backend": "playwright-chromium",
                "message": f"Captured {len(screenshots)} preview screenshot(s).",
            }

        chrome = _chrome_executable()
        if chrome is None:
            return [], {
                "requested": True,
                "available": False,
                "backend": None,
                "message": (
                    "No screenshot backend available. Install playwright browsers "
                    "or set HWPX_AUTOMATION_CHROME_PATH (legacy HWPX_MCP_CHROME_PATH) "
                    "to a Chrome executable. "
                    f"Playwright import error: {playwright_error}"
                ),
            }

        screenshots = []
        failures: list[str] = []
        for index, html_path in enumerate(page_html_paths[:capture_count]):
            page_info = pages[index]
            width, height = _page_viewport(page_info)
            output_path = output_dir / f"page-{index + 1:03d}.png"
            command = [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                f"--window-size={width},{height}",
                f"--screenshot={output_path}",
                html_path.as_uri(),
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=60,
                )
            except Exception as exc:  # pragma: no cover - environment specific
                failures.append(f"page {index + 1}: {exc}")
                continue
            if completed.returncode != 0 or not output_path.exists():
                detail = (
                    completed.stderr or completed.stdout or "unknown error"
                ).strip()
                failures.append(f"page {index + 1}: {detail}")
                continue
            item = {
                "pageIndex": index,
                "path": self._context._relative_path(output_path),
                "backend": "chrome-headless-cli",
                "widthPx": width,
                "heightPx": height,
            }
            self._embed_screenshot_image(
                item,
                output_path,
                embed_images=embed_images,
                max_image_bytes=max_image_bytes,
            )
            screenshots.append(item)

        message = f"Captured {len(screenshots)} preview screenshot(s) with Chrome CLI."
        if failures:
            message += " Failures: " + " | ".join(failures[:3])
        return screenshots, {
            "requested": True,
            "available": bool(screenshots),
            "backend": "chrome-headless-cli",
            "executable": chrome,
            "message": message,
        }

    def _build_viewer_block(
        self,
        source_path: Path,
        mode: str,
        output_path: Path,
        *,
        max_viewer_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Render the self-contained scrollable document viewer for the manifest.

        The viewer HTML is always written to ``viewer.html`` inside the resolved
        (workspace-guarded) output directory; the inline ``html`` copy is dropped
        when it exceeds *max_viewer_bytes* (default
        ``_DEFAULT_MAX_VIEWER_HTML_BYTES``) so a response cannot balloon.
        """
        if render_hwpx_document_viewer is None:
            raise self._context._new_error(
                "RENDER_PREVIEW_VIEWER_UNAVAILABLE",
                "Installed python-hwpx does not expose hwpx.tools.document_viewer.",
                details={"importError": str(_DOCUMENT_VIEWER_IMPORT_ERROR)},
                hint="Install python-hwpx[preview] and restart the MCP server.",
            )
        cap = (
            max_viewer_bytes
            if max_viewer_bytes is not None
            else _DEFAULT_MAX_VIEWER_HTML_BYTES
        )
        viewer = render_hwpx_document_viewer(
            source_path, title=source_path.name, mode=mode
        )
        html = viewer.html
        byte_size = len(html.encode("utf-8"))
        viewer_path = output_path / "viewer.html"
        viewer_path.write_text(html, encoding="utf-8")

        equation_rendering = _count_equation_modes(html)
        library_available = bool(_latex2mathml_available and _latex2mathml_available())
        block: Dict[str, Any] = {
            "viewerPath": self._context._relative_path(viewer_path),
            "byteSize": byte_size,
            "pageCount": viewer.page_count,
            "warnings": list(viewer.preview.warnings),
            "fidelityTier": (
                "text-approx-pagination; "
                f"equations={_equation_tier(equation_rendering)}"
            ),
            "equationLibrary": "latex2mathml" if library_available else "absent",
            "equationRendering": equation_rendering,
        }
        if byte_size > cap:
            block["htmlOmitted"] = "exceeds_max_viewer_bytes"
        else:
            block["html"] = html
        return block

    def render_preview(
        self,
        path: str,
        output_dir: Optional[str] = None,
        mode: str = "pages",
        screenshot: str = "auto",
        max_pages: Optional[int] = None,
        embed_images: bool = False,
        max_image_bytes: Optional[int] = None,
        viewer: bool = False,
        max_viewer_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate layout-aware HTML and optional PNG preview artifacts.

        When *embed_images* is true, each captured screenshot item also carries
        an ``imageBase64``/``imageMime`` payload (bounded by *max_image_bytes*,
        defaulting to ``_DEFAULT_MAX_PREVIEW_IMAGE_BYTES``) so a caller can return
        the page as an inline image content block.

        When *viewer* is true, a self-contained scrollable document viewer
        (equations rendered as native MathML when ``python-hwpx[preview]`` is
        installed) is added to the manifest under ``viewer``. The viewer is
        orthogonal to rasterization; pair it with ``screenshot="off"`` for the
        lightweight text path.
        """
        if embed_images and max_image_bytes is None:
            max_image_bytes = _DEFAULT_MAX_PREVIEW_IMAGE_BYTES
        if render_hwpx_layout_preview is None:
            raise self._context._new_error(
                "RENDER_PREVIEW_UNAVAILABLE",
                "Installed python-hwpx does not expose hwpx.tools.layout_preview.",
                details={"importError": str(_LAYOUT_PREVIEW_IMPORT_ERROR)},
                hint="Install the matching python-hwpx checkout/release and restart the MCP server.",
            )
        if mode not in {"pages", "long"}:
            raise self._context._new_error(
                "RENDER_PREVIEW_INVALID_MODE",
                "mode must be 'pages' or 'long'",
                details={"mode": mode},
            )
        if screenshot not in {"auto", "require", "off"}:
            raise self._context._new_error(
                "RENDER_PREVIEW_INVALID_SCREENSHOT_MODE",
                "screenshot must be 'auto', 'require', or 'off'",
                details={"screenshot": screenshot},
            )

        source_path = self._context._resolve_path(path)
        output_path = self._preview_output_dir(source_path, output_dir)
        preview = render_hwpx_layout_preview(
            source_path, mode=mode, title=source_path.name
        )
        preview_dict = preview.as_dict()

        html_path = output_path / "preview.html"
        manifest_path = output_path / "manifest.json"
        evidence_path = output_path / "visual-review.json"
        html_path.write_text(preview.html, encoding="utf-8")

        page_html_paths: list[Path] = []
        page_documents = preview.page_html_documents(title=source_path.name)
        for index, page_html in enumerate(page_documents):
            page_html_path = output_path / f"page-{index + 1:03d}.html"
            page_html_path.write_text(page_html, encoding="utf-8")
            page_html_paths.append(page_html_path)

        pages = []
        for index, page in enumerate(preview_dict["pages"]):
            item = dict(page)
            if index < len(page_html_paths):
                item["htmlPath"] = self._context._relative_path(page_html_paths[index])
            pages.append(item)

        if screenshot == "off":
            screenshots: list[dict[str, Any]] = []
            screenshot_engine = {
                "requested": False,
                "available": False,
                "backend": None,
                "message": "Screenshot generation was disabled by request.",
            }
            status = "html_only"
        else:
            screenshots, screenshot_engine = self._capture_preview_pages(
                page_html_paths=page_html_paths,
                pages=pages,
                output_dir=output_path,
                max_pages=max_pages,
                embed_images=embed_images,
                max_image_bytes=max_image_bytes,
            )
            requested_count = len(page_html_paths)
            if max_pages is not None:
                requested_count = min(requested_count, max(0, max_pages))
            if screenshots and len(screenshots) == requested_count:
                status = "ok"
            elif screenshots:
                status = "partial"
            else:
                status = "blocked"

        screenshot_by_page = {item["pageIndex"]: item for item in screenshots}
        for page in pages:
            screenshot_item = screenshot_by_page.get(page["index"])
            if screenshot_item is not None:
                page["screenshotPath"] = screenshot_item["path"]

        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        suggestion = None
        if status in {"blocked", "partial"}:
            suggestion = (
                "Open preview.html manually or install a headless browser backend "
                "(Playwright browsers or Chrome via HWPX_AUTOMATION_CHROME_PATH; "
                "legacy HWPX_MCP_CHROME_PATH is also accepted) and rerun render_preview."
            )

        visual_review = {
            "schemaVersion": _VISUAL_REVIEW_SCHEMA_VERSION,
            "sourcePath": self._context._relative_path(source_path),
            "current": {
                "status": "observed_pass" if status == "ok" else "blocked",
                "method": screenshot_engine.get("backend") or "html-preview",
                "screenshot_path": screenshots[0]["path"] if screenshots else None,
                "notes": (
                    "Layout preview screenshots generated. Final Hancom viewer acceptance is still required."
                    if status == "ok"
                    else screenshot_engine["message"]
                ),
            },
            "summary": {
                "resolved_visual_review_required": "observed_pass"
                if status == "ok"
                else "blocked",
                "layout_preview_status": status,
            },
        }
        _write_json(evidence_path, visual_review)

        manifest = {
            "schemaVersion": _PREVIEW_SCHEMA_VERSION,
            "status": status,
            "generatedAt": generated_at,
            "sourcePath": self._context._relative_path(source_path),
            "outputDir": self._context._relative_path(output_path),
            "htmlPath": self._context._relative_path(html_path),
            "manifestPath": self._context._relative_path(manifest_path),
            "visualReviewPath": self._context._relative_path(evidence_path),
            "mode": mode,
            "pageCount": len(pages),
            "pages": pages,
            "screenshots": screenshots,
            "screenshotEngine": screenshot_engine,
            "warnings": list(preview.warnings),
            "suggestion": suggestion,
        }
        if viewer:
            manifest["viewer"] = self._build_viewer_block(
                source_path, mode, output_path, max_viewer_bytes=max_viewer_bytes
            )
        # Keep the on-disk manifest lean — never persist inline base64/HTML payloads.
        _write_json(manifest_path, _lean_disk_manifest(manifest))
        return manifest

    def convert_hwp_to_hwpx(
        self, source: str, output: Optional[str] = None
    ) -> Dict[str, Any]:
        resolved_source = self._context._resolve_path(source)
        if resolved_source.suffix.lower() != ".hwp":
            raise self._context._new_error(
                "SOURCE_FILE_TYPE_INVALID", "source는 .hwp 파일이어야 합니다"
            )

        if output:
            resolved_output = self._context._resolve_output_path(output)
        else:
            resolved_output = resolved_source.with_suffix(".hwpx")

        try:
            result = convert_hwp_to_hwpx(str(resolved_source), str(resolved_output))
        except HwpConversionError as exc:
            raise self._context._new_error(
                "HWP_CONVERSION_FAILED", f"HWP 변환 실패: {exc}"
            ) from exc

        return {
            "success": result.success,
            "outputPath": result.output_path,
            "paragraphsConverted": result.paragraphs_converted,
            "tablesConverted": result.tables_converted,
            "skippedElements": result.skipped_elements,
            "warnings": result.warnings,
            "verification": result.verification,
            "openSafety": result.open_safety,
        }
