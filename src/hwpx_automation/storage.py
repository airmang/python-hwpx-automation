# SPDX-License-Identifier: Apache-2.0
"""Storage backends for HWPX document operations."""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple, cast
from urllib import error, parse, request

try:  # python-hwpx >= 2.10.3
    from hwpx.tools.package_validator import validate_package
except Exception as exc:  # pragma: no cover - depends on installed python-hwpx
    validate_package = None
    _PACKAGE_VALIDATOR_IMPORT_ERROR: Exception | None = exc
else:
    _PACKAGE_VALIDATOR_IMPORT_ERROR = None

try:  # python-hwpx >= 2.10.3
    from hwpx.tools.package_validator import is_editor_open_blocking_issue
except Exception as exc:  # pragma: no cover - depends on installed python-hwpx
    is_editor_open_blocking_issue = None
    _OPEN_SAFETY_CLASSIFIER_IMPORT_ERROR: Exception | None = exc
else:
    _OPEN_SAFETY_CLASSIFIER_IMPORT_ERROR = None

from . import quality as quality_contract
from .errors import HwpDocumentError
from .upstream import (
    HwpxDocument,
    hwp5_conversion_report,
    hwp5_document_bytes,
    hwpx_view_bytes,
    is_hwp5_source,
    is_hwp5_target,
    native_hwp5_supported,
    open_document,
    validate_document_path,
)
from .workspace import (
    LEGACY_SANDBOX_ROOT_ENV,
    LEGACY_WORKSPACE_ROOTS_ENV,
    WORKSPACE_ROOTS_ENV,
    WorkspaceConfigurationError,
    WorkspaceMissingParentGuard,
    WorkspaceOutputGuard,
    WorkspaceResolver,
)
from .network_policy import NetworkPolicy, build_policy_opener

_REQUIRED_HWPX_FILES = [
    "mimetype",
    "Contents/content.hpf",
    "Contents/header.xml",
    "Contents/section0.xml",
]
_SECTION_XML_RE = re.compile(r"^Contents/section\d+\.xml$")
_PLACEHOLDER_PATTERNS = [
    re.compile(r"\[[^\[\]\n]{1,100}\]"),
    re.compile(r"\[\[[^\[\]\n]{1,100}\]\]"),
    re.compile(r"\{\{[^{}\n]{1,100}\}\}"),
    re.compile(r"__[^_\n]{1,100}__"),
]
_UNESCAPED_AMP_RE = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)")
_NESTED_OPENING_TAG_RE = re.compile(r"<hp:t\b[^>]*>[^<]*(<(?!/?hp:)[^>]+>)")
_EMPTY_HP_T_RE = re.compile(r"<hp:t\b[^>]*>\s*</hp:t>")

HwpxVerificationSource = Path | bytes


class DocumentStorage(Protocol):
    """Protocol describing storage backends used by :class:`HwpxOps`."""

    base_directory: Path

    def resolve_path(self, path: str, *, must_exist: bool = True) -> Path:
        """Return the backend-specific absolute path for *path*."""

    def resolve_output_path(self, path: str) -> Path:
        """Return a path suitable for writing output."""

    def relative_path(self, path: Path) -> str:
        """Return a user-friendly relative representation of *path*."""

    def ensure_backup(self, path: Path) -> Optional[Path]:
        """Create a backup of *path* if it exists, returning the backup path."""

    def maybe_backup(self, path: Path) -> None:
        """Create a backup of *path* when backend policy requires it."""

    def open_document(self, path: str) -> Tuple[HwpxDocument, Path]:
        """Open the document located at *path* and return it with the resolved path."""

    def save_document(
        self, document: HwpxDocument, target: Path, *, quality: Any = None
    ) -> Dict[str, Any]:
        """Persist *document* to *target* using backend specific rules."""


class LocalDocumentStorage:
    """Filesystem based :class:`DocumentStorage` implementation."""

    def __init__(
        self,
        *,
        base_directory: Path | None = None,
        auto_backup: bool = False,
        logger: logging.Logger | None = None,
        workspace_resolver: WorkspaceResolver | None = None,
    ) -> None:
        if workspace_resolver is not None and base_directory is not None:
            raise ValueError("base_directory and workspace_resolver are mutually exclusive")
        self._deferred_workspace_error: WorkspaceConfigurationError | None = None
        if workspace_resolver is not None:
            self._workspace: WorkspaceResolver | None = workspace_resolver
        elif base_directory is not None:
            self._workspace = WorkspaceResolver.from_roots([base_directory])
        else:
            # Implicit cwd fallback. When neither HWPX_AUTOMATION_WORKSPACE_ROOTS
            # nor its supported HWPX_MCP_WORKSPACE_ROOTS fallback nor the
            # legacy root is configured and the cwd is degenerate (e.g. a GUI MCP
            # client launched from C:\Windows\System32 or /), defer the actionable
            # error to first use so import and startup do not crash and
            # mcp_server_health can still report the misconfiguration.
            try:
                self._workspace = WorkspaceResolver.from_environment()
            except WorkspaceConfigurationError as exc:
                if (
                    os.environ.get(WORKSPACE_ROOTS_ENV) is not None
                    or os.environ.get(LEGACY_WORKSPACE_ROOTS_ENV) is not None
                    or os.environ.get(LEGACY_SANDBOX_ROOT_ENV) is not None
                ):
                    raise
                self._workspace = None
                self._deferred_workspace_error = exc
        self.base_directory = (
            self._workspace.primary_root
            if self._workspace is not None
            else Path(os.devnull)
        )
        self._auto_backup = auto_backup
        self._logger = logger or logging.getLogger(__name__)

    @property
    def workspace(self) -> WorkspaceResolver:
        if self._workspace is None:
            # A degenerate/unconfigured cwd fallback deferred this error so the
            # server could boot; surface it now as a clean WORKSPACE_ROOT_INVALID.
            raise cast(WorkspaceConfigurationError, self._deferred_workspace_error)
        return self._workspace

    def resolve_path(self, path: str, *, must_exist: bool = True) -> Path:
        return self.workspace.resolve(path, must_exist=must_exist)

    def resolve_output_path(self, path: str) -> Path:
        return self.workspace.resolve_output(path)

    def capture_output_guard(
        self,
        path: str | os.PathLike[str],
        *,
        create_parents: bool = True,
    ) -> WorkspaceOutputGuard:
        return self.workspace.capture_output(path, create_parents=create_parents)

    def capture_output_precondition(
        self,
        path: str | os.PathLike[str],
    ) -> WorkspaceOutputGuard | WorkspaceMissingParentGuard:
        return self.workspace.capture_output_precondition(path)

    def materialize_output_guard(
        self,
        precondition: WorkspaceOutputGuard | WorkspaceMissingParentGuard,
    ) -> WorkspaceOutputGuard:
        return self.workspace.materialize_output_guard(precondition)

    def cleanup_owned_parent_directories(
        self,
        guard: WorkspaceOutputGuard,
    ) -> bool:
        return self.workspace.cleanup_owned_parent_directories(guard)

    def atomic_write_bytes(
        self,
        guard: WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> Path:
        return self.workspace.atomic_write_bytes(guard, data, mode=mode)

    def atomic_publish_bytes(
        self,
        guard: WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> WorkspaceOutputGuard:
        """Publish and return the exact candidate identity for transaction ownership."""

        return self.workspace.atomic_publish_bytes(guard, data, mode=mode)

    def read_guarded_bytes(self, guard: WorkspaceOutputGuard) -> bytes:
        """Read the exact preimage represented by an output guard."""

        return self.workspace.read_guarded_bytes(guard)

    def remove_guarded_output(self, guard: WorkspaceOutputGuard) -> None:
        """Remove only the exact candidate represented by an output guard."""

        self.workspace.remove_output(guard)

    def relative_path(self, path: Path) -> str:
        return self.workspace.display_path(path)

    def ensure_backup(self, path: Path) -> Optional[Path]:
        if not path.exists():
            return None
        if path.suffix.lower() == ".hwpx":
            require_hwpx_editor_open_safe(path, role="backup source")
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        return backup

    def maybe_backup(self, path: Path) -> None:
        if not self._auto_backup:
            return
        backup = self.ensure_backup(path)
        if backup is not None:
            self._logger.info(
                "created backup",
                extra={"path": str(path), "backup": str(backup)},
            )

    def open_document(self, path: str) -> Tuple[HwpxDocument, Path]:
        resolved = self.resolve_path(path)
        document = open_local_document(resolved, role="local HWPX open")
        return document, resolved

    def save_document(
        self, document: HwpxDocument, target: Path, *, quality: Any = None
    ) -> Dict[str, Any]:
        # General document saves use the SavePipeline gate. Byte-preserving
        # form writers have their own guarded open-safety publication path.
        quality_contract.assert_write_capability()
        if is_hwp5_target(target):
            require_native_hwp5()
        guard = self.capture_output_guard(target)
        self.maybe_backup(target)
        pre_save_snapshot = build_hwpx_presave_snapshot(target)
        # Validate in an isolated temp, then publish through the identity-bound
        # workspace guard. Candidate creation never follows the output parent.
        # The gate always checks HWPX parts, so an .hwp target is staged as HWPX.
        tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=_staging_suffix(target))
        tmp_path = Path(tmp_path_str)
        try:
            os.close(tmp_fd)
            report = quality_contract.save_through_pipeline(
                document, tmp_path, quality=quality
            )
            verification_report = build_hwpx_verification_report(tmp_path, pre_save_snapshot)
            if not verification_report["openSafety"]["ok"]:
                raise RuntimeError(
                    "saved HWPX failed open-safety verification: "
                    + verification_report["openSafety"]["summary"]
                )
            data = _published_bytes(document, target, tmp_path, verification_report)
            self.atomic_write_bytes(guard, data)
            verification_report["filePath"] = str(target)
            verification_report["visualComplete"] = quality_contract.visual_complete_block(report)
            return verification_report
        finally:
            tmp_path.unlink(missing_ok=True)


class RemoteDocumentClient(Protocol):
    """Protocol describing the minimal HTTP client interface required."""

    def download(self, path: str) -> bytes:
        """Return the binary payload for *path* from the remote service."""

    def upload(self, path: str, data: bytes) -> None:
        """Persist *data* to *path* on the remote service."""


def _report_allows_editor_open(report: Mapping[str, Any]) -> bool:
    package = report.get("validatePackage", {})
    reopen = report.get("reopen", {})
    return bool(
        isinstance(package, Mapping)
        and isinstance(reopen, Mapping)
        and package.get("ok")
        and reopen.get("ok")
    )


def require_hwpx_editor_open_safe(
    source: HwpxVerificationSource,
    *,
    role: str,
) -> Dict[str, Any]:
    """Fail only on conditions expected to stop an editor from opening HWPX."""

    open_safety = build_hwpx_open_safety_report(source)
    if not _report_allows_editor_open(open_safety):
        raise RuntimeError(
            f"{role} failed open-safety verification: "
            + open_safety["summary"]
        )
    return open_safety


def require_native_hwp5() -> None:
    """Refuse ``.hwp`` work clearly when the installed core cannot read or write it."""

    if not native_hwp5_supported():
        raise HwpDocumentError(
            "설치된 python-hwpx는 HWP 5.0(.hwp) 문서를 열거나 저장하지 못합니다.",
            code="READ_ONLY_HWP_DOCUMENT",
        )


def open_local_document(path: Path, *, role: str) -> HwpxDocument:
    """Open a local HWPX or HWP 5.0 document for editing.

    An HWPX package must pass the editor open-safety check first. An ``.hwp``
    file is converted by python-hwpx, which refuses damaged, encrypted and
    DRM files itself (``Hwp5Error``).
    """

    if is_hwp5_source(path):
        require_native_hwp5()
        return open_document(path)
    require_hwpx_editor_open_safe(path, role=role)
    return open_document(path)


def require_hwpx_package(
    source: Path | str, *, output: Path | str | None = None
) -> None:
    """Refuse an ``.hwp`` source or output for editors that patch HWPX package bytes."""

    if is_hwp5_source(source) or (output is not None and is_hwp5_target(output)):
        raise HwpDocumentError(
            "이 도구는 HWPX 패키지의 바이트를 직접 고치므로 HWP 5.0(.hwp) 문서를 입력이나 출력으로 쓸 수 없습니다.",
            code="HWPX_PACKAGE_REQUIRED",
        )


def _staging_suffix(target: Path) -> str:
    return ".hwpx" if is_hwp5_target(target) else (target.suffix or ".hwpx")


def _published_bytes(
    document: HwpxDocument,
    target: Path,
    staged: Path,
    verification_report: Dict[str, Any],
) -> bytes:
    """The bytes to publish at *target*: the verified HWPX, or HWP 5.0 for ``.hwp``.

    The HWP 5.0 bytes are reopened before anything is written, and the report
    records what an ``.hwp`` source could not carry into the document model.
    """

    conversion = hwp5_conversion_report(document)
    if conversion is not None and (conversion["unconverted"] or conversion["dropped"]):
        verification_report["hwpConversion"] = conversion
        verification_report["warnings"].append(
            "content the .hwp source could not carry into the document model is not in the saved file"
        )
    if not is_hwp5_target(target):
        return staged.read_bytes()
    data = hwp5_document_bytes(document)
    reopened = open_document(data)
    reopened.close()
    verification_report["format"] = "hwp"
    verification_report["fileSizeBytes"] = len(data)
    return data


@dataclass(slots=True)
class _RestDocumentClient:
    """Default HTTP client used by :class:`HttpDocumentStorage`."""

    base_url: str
    timeout: float | None
    headers: Mapping[str, str]
    allow_private_network: bool | None = None
    _network_policy: NetworkPolicy = field(init=False, repr=False)
    _opener: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("HTTP storage requires a base URL")
        self._network_policy = (
            NetworkPolicy.from_environment()
            if self.allow_private_network is None
            else NetworkPolicy(allow_private_network=self.allow_private_network)
        )
        self._opener = build_policy_opener(self._network_policy)

    def download(self, path: str) -> bytes:
        url = self._build_url(path)
        req = request.Request(url, method="GET")
        for key, value in self.headers.items():
            req.add_header(key, value)
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                return response.read()
        except error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(path) from exc
            raise RuntimeError(f"HTTP download failed: {exc}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"HTTP download failed: {exc}") from exc

    def upload(self, path: str, data: bytes) -> None:
        url = self._build_url(path)
        req = request.Request(url, data=data, method="PUT")
        for key, value in self.headers.items():
            req.add_header(key, value)
        req.add_header("Content-Type", "application/octet-stream")
        try:
            with self._opener.open(req, timeout=self.timeout):
                return None
        except error.HTTPError as exc:
            raise RuntimeError(f"HTTP upload failed: {exc}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"HTTP upload failed: {exc}") from exc

    def _build_url(self, path: str) -> str:
        query = parse.urlencode({"path": path})
        url = f"{self.base_url.rstrip('/')}/documents?{query}"
        return self._network_policy.validate_url(url)


class HttpDocumentStorage:
    """HTTP based :class:`DocumentStorage` implementation with local caching."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        client: RemoteDocumentClient | None = None,
        logger: logging.Logger | None = None,
        allow_private_network: bool | None = None,
    ) -> None:
        if client is None and not base_url:
            raise ValueError("HTTP storage requires either a base URL or a client")

        self.base_directory = Path("/")
        self._logger = logger or logging.getLogger(__name__)
        self._headers = dict(headers or {})
        self._client = client or _RestDocumentClient(
            base_url=base_url or "",
            timeout=timeout,
            headers=self._headers,
            allow_private_network=allow_private_network,
        )
        self._cache_dir = Path(tempfile.mkdtemp(prefix="hwpx_http_cache_"))
        self._cache: Dict[str, Path] = {}

    def resolve_path(self, path: str, *, must_exist: bool = True) -> Path:
        # HTTP storage treats the provided path as an opaque identifier.
        return Path(path)

    def resolve_output_path(self, path: str) -> Path:
        return self.resolve_path(path, must_exist=False)

    def relative_path(self, path: Path) -> str:
        return str(path)

    def ensure_backup(self, path: Path) -> Optional[Path]:
        # Backups are left to the remote service.
        return None

    def maybe_backup(self, path: Path) -> None:
        # No-op; backups must be handled remotely if supported.
        return None

    def open_document(self, path: str) -> Tuple[HwpxDocument, Path]:
        try:
            payload = self._client.download(path)
        except FileNotFoundError:
            raise
        except Exception as exc:  # pragma: no cover - handled in tests for fake clients
            raise RuntimeError(f"HTTP storage open failed: {exc}") from exc

        local_path = self._cache_path(path)
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            suffix=local_path.suffix or ".hwpx",
            dir=str(local_path.parent),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(tmp_fd, "wb") as tmp_fh:
                tmp_fh.write(payload)
            if is_hwp5_source(tmp_path):
                require_native_hwp5()
            else:
                require_hwpx_editor_open_safe(tmp_path, role="HTTP storage open")
            os.replace(tmp_path, local_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        self._cache[path] = local_path

        document = open_document(local_path)
        return document, Path(path)

    def save_document(
        self, document: HwpxDocument, target: Path, *, quality: Any = None
    ) -> Dict[str, Any]:
        quality_contract.assert_write_capability()
        if is_hwp5_target(target):
            require_native_hwp5()
        remote_key = str(target)
        cache_path = self._cache.get(remote_key)
        if cache_path is None:
            cache_path = self._cache_path(remote_key)
            self._cache[remote_key] = cache_path

        pre_save_snapshot = build_hwpx_presave_snapshot(cache_path if cache_path.exists() else None)
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            suffix=_staging_suffix(cache_path),
            dir=str(cache_path.parent),
        )
        tmp_path = Path(tmp_path_str)

        try:
            os.close(tmp_fd)
            report = quality_contract.save_through_pipeline(document, tmp_path, quality=quality)
            verification_report = build_hwpx_verification_report(tmp_path, pre_save_snapshot)
            if not verification_report["openSafety"]["ok"]:
                raise RuntimeError(
                    "saved HWPX failed open-safety verification: "
                    + verification_report["openSafety"]["summary"]
                )
            verification_report["visualComplete"] = quality_contract.visual_complete_block(report)
            payload = _published_bytes(document, target, tmp_path, verification_report)
            if is_hwp5_target(target):
                tmp_path.write_bytes(payload)
        except quality_contract.QualityGateError:
            tmp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:  # pragma: no cover - unexpected save error
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"HTTP storage save failed: {exc}") from exc

        try:
            self._client.upload(remote_key, payload)
        except Exception as exc:  # pragma: no cover - handled in tests for fake clients
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"HTTP storage save failed: {exc}") from exc
        os.replace(tmp_path, cache_path)
        return verification_report

    def _cache_path(self, path: str) -> Path:
        suffix = Path(path).suffix or ".hwpx"
        safe_name = parse.quote_plus(path)
        filename = safe_name if safe_name.endswith(suffix) else f"{safe_name}{suffix}"
        return self._cache_dir / filename


def build_hwpx_presave_snapshot(
    source: HwpxVerificationSource | None,
) -> Dict[str, Any] | None:
    if source is None or (isinstance(source, Path) and not source.exists()):
        return None
    return _collect_hwpx_snapshot(source)


def _hwpx_view(source: HwpxVerificationSource) -> HwpxVerificationSource:
    """*source* itself, or for an ``.hwp`` the HWPX package of its document model.

    HWPX verification reads package parts, so an HWP 5.0 file is checked
    through the model python-hwpx opens it to.
    """

    if is_hwp5_source(source):
        require_native_hwp5()
        return hwpx_view_bytes(source)
    return source


def _issue_messages(report: Any, attr_name: str = "issues") -> List[str]:
    return [str(issue) for issue in getattr(report, attr_name, ())]


def _open_safety_dependency_error() -> str | None:
    if validate_package is None:
        detail = (
            str(_PACKAGE_VALIDATOR_IMPORT_ERROR)
            if _PACKAGE_VALIDATOR_IMPORT_ERROR is not None
            else "hwpx.tools.package_validator.validate_package is unavailable"
        )
        return f"python-hwpx>=2.10.3 is required for HWPX open-safety validation: {detail}"
    if is_editor_open_blocking_issue is None:
        detail = (
            str(_OPEN_SAFETY_CLASSIFIER_IMPORT_ERROR)
            if _OPEN_SAFETY_CLASSIFIER_IMPORT_ERROR is not None
            else "hwpx.tools.package_validator.is_editor_open_blocking_issue is unavailable"
        )
        return f"python-hwpx>=2.10.3 is required for HWPX open-safety validation: {detail}"
    return None


def build_hwpx_open_safety_report(
    source: HwpxVerificationSource,
) -> Dict[str, Any]:
    package_payload: Dict[str, Any]
    document_payload: Dict[str, Any]
    reopen_payload: Dict[str, Any]

    source = _hwpx_view(source)
    dependency_error = _open_safety_dependency_error()
    if dependency_error is not None:
        package_payload = {
            "ok": False,
            "validatorOk": False,
            "errors": [dependency_error],
            "warnings": [],
            "validatorErrors": [dependency_error],
        }
    else:
        try:
            assert validate_package is not None
            assert is_editor_open_blocking_issue is not None
            package_report = validate_package(source)
            package_errors = _issue_messages(package_report, "errors")
            blocking_issues = [
                issue for issue in package_report.errors if is_editor_open_blocking_issue(issue)
            ]
            advisory_issues = [
                issue for issue in package_report.errors if not is_editor_open_blocking_issue(issue)
            ]
            blocking_package_errors = [str(issue) for issue in blocking_issues]
            compatibility_warnings = [str(issue) for issue in advisory_issues]
            package_payload = {
                "ok": not blocking_package_errors,
                "validatorOk": bool(package_report.ok),
                "errors": blocking_package_errors,
                "warnings": [*_issue_messages(package_report, "warnings"), *compatibility_warnings],
                "validatorErrors": package_errors,
            }
        except Exception as exc:  # noqa: BLE001
            package_payload = {
                "ok": False,
                "validatorOk": False,
                "errors": [str(exc)],
                "warnings": [],
                "validatorErrors": [str(exc)],
            }

    try:
        document_report = validate_document_path(source)
        document_payload = {
            "ok": bool(document_report.ok),
            "errors": _issue_messages(document_report, "errors"),
            "warnings": _issue_messages(document_report, "warnings"),
        }
    except Exception as exc:  # noqa: BLE001
        document_payload = {
            "ok": False,
            "errors": [str(exc)],
            "warnings": [],
        }

    try:
        reopened = open_document(source)
        close = getattr(reopened, "close", None)
        if callable(close):
            close()
        reopen_payload = {"ok": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        reopen_payload = {"ok": False, "error": str(exc)}

    ok = bool(package_payload["ok"] and document_payload["ok"] and reopen_payload["ok"])
    failures: List[str] = []
    if not package_payload["ok"]:
        failures.append("package validation failed")
    if not document_payload["ok"]:
        failures.append("document validation failed")
    if not reopen_payload["ok"]:
        failures.append("reopen failed")

    return {
        "ok": ok,
        "summary": "open-safety verification passed" if ok else "; ".join(failures),
        "validatePackage": package_payload,
        "validateDocument": document_payload,
        "reopen": reopen_payload,
    }


def build_hwpx_verification_report(
    source: HwpxVerificationSource,
    pre_save_snapshot: Dict[str, Any] | None = None,
    *,
    file_path: Path | None = None,
) -> Dict[str, Any]:
    view = _hwpx_view(source)
    snapshot = _collect_hwpx_snapshot(view)
    open_safety = build_hwpx_open_safety_report(view)
    displayed_path = file_path or (source if isinstance(source, Path) else None)
    file_size = len(source) if isinstance(source, bytes) else source.stat().st_size
    totals = snapshot["totals"]
    missing_files = snapshot["missing_files"]
    warnings: List[str] = []
    if missing_files:
        warnings.append(f"missing required files: {', '.join(missing_files)}")
    if totals["placeholders"]:
        warnings.append("placeholder-like tokens remain in saved document")
    if totals["suspiciousPatterns"]:
        warnings.append("suspicious XML/text patterns detected in saved document")

    diff_summary = {
        "xmlLength": 0,
        "hpTabs": 0,
        "paragraphs": 0,
        "tables": 0,
    }
    if pre_save_snapshot is not None:
        before = pre_save_snapshot["totals"]
        diff_summary = {
            "xmlLength": totals["xmlLength"] - before["xmlLength"],
            "hpTabs": totals["hpTabs"] - before["hpTabs"],
            "paragraphs": totals["paragraphs"] - before["paragraphs"],
            "tables": totals["tables"] - before["tables"],
        }

    ok = (
        open_safety["ok"]
        and not missing_files
        and not totals["placeholders"]
        and not totals["suspiciousPatterns"]
    )
    summary = "verification passed"
    if not ok:
        summary = "; ".join(warnings) if warnings else "verification failed"

    return {
        "ok": ok,
        "summary": summary,
        "filePath": str(displayed_path) if displayed_path is not None else "<memory>",
        "fileSizeBytes": file_size,
        "requiredFilesChecked": list(_REQUIRED_HWPX_FILES),
        "missingFiles": missing_files,
        "openSafety": open_safety,
        "sectionReports": snapshot["section_reports"],
        "totals": {
            "sections": totals["sections"],
            "xmlLength": totals["xmlLength"],
            "hpTabs": totals["hpTabs"],
            "paragraphs": totals["paragraphs"],
            "tables": totals["tables"],
            "placeholders": totals["placeholders"],
            "suspiciousPatterns": totals["suspiciousPatterns"],
        },
        "diffSummary": diff_summary,
        "warnings": warnings,
    }


def _collect_hwpx_snapshot(source: HwpxVerificationSource) -> Dict[str, Any]:
    missing_files: List[str] = []
    section_reports: List[Dict[str, Any]] = []
    totals = {
        "sections": 0,
        "xmlLength": 0,
        "hpTabs": 0,
        "paragraphs": 0,
        "tables": 0,
        "placeholders": 0,
        "suspiciousPatterns": 0,
    }

    source = _hwpx_view(source)
    archive_source = BytesIO(source) if isinstance(source, bytes) else source
    with zipfile.ZipFile(archive_source) as archive:
        names = set(archive.namelist())
        for required in _REQUIRED_HWPX_FILES:
            if required not in names:
                missing_files.append(required)

        section_names = sorted(name for name in names if _SECTION_XML_RE.match(name))
        totals["sections"] = len(section_names)
        for section_name in section_names:
            xml_text = archive.read(section_name).decode("utf-8", errors="replace")
            section_index = int(section_name.removeprefix("Contents/section").removesuffix(".xml"))
            placeholder_examples: List[str] = []
            placeholder_count = 0
            for pattern in _PLACEHOLDER_PATTERNS:
                for match in pattern.findall(xml_text):
                    placeholder_count += 1
                    if match not in placeholder_examples and len(placeholder_examples) < 5:
                        placeholder_examples.append(match)

            suspicious_patterns: List[str] = []
            if _UNESCAPED_AMP_RE.search(xml_text):
                suspicious_patterns.append("unescaped_ampersand")
            if _EMPTY_HP_T_RE.search(xml_text):
                suspicious_patterns.append("empty_hp_t")
            if _NESTED_OPENING_TAG_RE.search(xml_text):
                suspicious_patterns.append("nested_opening_tag_in_text")
            if ">>" in xml_text or "<<" in xml_text:
                suspicious_patterns.append("double_angle_marker")

            paragraph_count = xml_text.count("<hp:p")
            table_count = xml_text.count("<hp:tbl")
            hp_tab_count = xml_text.count("<hp:tab")
            xml_length = len(xml_text)

            totals["xmlLength"] += xml_length
            totals["hpTabs"] += hp_tab_count
            totals["paragraphs"] += paragraph_count
            totals["tables"] += table_count
            totals["placeholders"] += placeholder_count
            totals["suspiciousPatterns"] += len(suspicious_patterns)

            section_reports.append(
                {
                    "section": section_index,
                    "xmlDeclaration": xml_text.startswith("<?xml"),
                    "truncatedXml": bool(re.search(r"<[^>]*$", xml_text)),
                    "brokenTagPattern": bool(re.search(r"<[^>]*<", xml_text)),
                    "xmlLength": xml_length,
                    "hpTabs": hp_tab_count,
                    "paragraphs": paragraph_count,
                    "tables": table_count,
                    "placeholderCount": placeholder_count,
                    "placeholderExamples": placeholder_examples,
                    "suspiciousPatternCount": len(suspicious_patterns),
                    "suspiciousPatterns": suspicious_patterns,
                }
            )

    return {
        "missing_files": missing_files,
        "section_reports": section_reports,
        "totals": totals,
    }
