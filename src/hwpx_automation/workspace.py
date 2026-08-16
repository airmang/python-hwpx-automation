# SPDX-License-Identifier: Apache-2.0
"""Canonical fail-closed workspace-root resolution for local MCP paths."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets
import stat
import sys
import tempfile
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path, PurePath, PureWindowsPath
from typing import Iterable
from urllib.parse import unquote, urlsplit

from .configuration import canonical_env_name, legacy_env_name


WORKSPACE_ROOTS_ENV = canonical_env_name("WORKSPACE_ROOTS")
LEGACY_WORKSPACE_ROOTS_ENV = legacy_env_name("WORKSPACE_ROOTS")
LEGACY_SANDBOX_ROOT_ENV = legacy_env_name("SANDBOX_ROOT")


class WorkspaceConfigurationError(RuntimeError):
    """The host did not provide a usable, bounded workspace root."""

    code = "WORKSPACE_ROOT_INVALID"


class WorkspacePathError(PermissionError):
    """A requested path escaped or violated the configured workspace policy."""

    def __init__(self, message: str, *, code: str, reason: str) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason

    def safe_details(self) -> dict[str, str]:
        return {"reason": self.reason}


@dataclass(frozen=True, slots=True)
class WorkspaceOutputGuard:
    """Identity-bound capability for one authorized output parent."""

    path: Path
    root: Path
    root_device: int
    root_inode: int
    parent_device: int
    parent_inode: int
    target_existed: bool
    target_device: int | None
    target_inode: int | None
    target_digest: str | None
    target_mode: int | None
    owned_parent_directories: tuple[tuple[Path, int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceMissingParentGuard:
    """Identity-bound precondition for an output whose parent is absent."""

    path: Path
    root: Path
    root_device: int
    root_inode: int
    anchor: Path
    anchor_device: int
    anchor_inode: int
    missing_parts: tuple[str, ...]


def _digest_descriptor(descriptor: int, *, copy_to: int | None = None) -> str:
    """Hash one descriptor, optionally copying it to another descriptor."""

    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    if copy_to is not None:
        os.lseek(copy_to, 0, os.SEEK_SET)
        os.ftruncate(copy_to, 0)
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        if copy_to is not None:
            view = memoryview(chunk)
            while view:
                written = os.write(copy_to, view)
                view = view[written:]
    if copy_to is not None:
        os.fsync(copy_to)
    return digest.hexdigest()


def _snapshot_target(
    path: Path,
) -> tuple[bool, int | None, int | None, str | None, int | None]:
    """Capture the exact regular file currently occupying an output name."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return False, None, None, None, None
    except OSError as exc:
        raise WorkspacePathError(
            "output target could not be captured safely",
            code="WORKSPACE_PATH_INVALID",
            reason="output_target_unavailable",
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise WorkspacePathError(
                "output target is not a regular file",
                code="WORKSPACE_PATH_INVALID",
                reason="output_target_not_regular",
            )
        digest = _digest_descriptor(descriptor)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise WorkspacePathError(
                "output target changed while it was captured",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        return (
            True,
            after.st_dev,
            after.st_ino,
            digest,
            stat.S_IMODE(after.st_mode),
        )
    finally:
        os.close(descriptor)


def _exchange_entries(parent_fd: int, first: str, second: str) -> None:
    """Atomically exchange two descriptor-relative names on macOS/Linux."""

    libc = ctypes.CDLL(None, use_errno=True)
    first_raw = os.fsencode(first)
    second_raw = os.fsencode(second)
    if sys.platform == "darwin":
        function = getattr(libc, "renameatx_np", None)
        if function is None:  # pragma: no cover - supported macOS invariant
            raise WorkspaceConfigurationError(
                "macOS renameatx_np is required for atomic output CAS"
            )
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        # RENAME_SWAP | RENAME_NOFOLLOW_ANY
        result = function(parent_fd, first_raw, parent_fd, second_raw, 0x12)
    elif sys.platform.startswith("linux"):
        function = getattr(libc, "renameat2", None)
        if function is None:  # pragma: no cover - old libc/runtime
            raise WorkspaceConfigurationError(
                "Linux renameat2 is required for atomic output CAS"
            )
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        # RENAME_EXCHANGE
        result = function(parent_fd, first_raw, parent_fd, second_raw, 0x2)
    else:
        raise WorkspaceConfigurationError(
            "atomic output replacement requires macOS renameatx_np or Linux renameat2"
        )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


@lru_cache(maxsize=1)
def _descriptor_cas_supported() -> bool:
    """Return whether this host exposes the atomic exchange primitive we use."""

    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        return False
    libc = ctypes.CDLL(None)
    if sys.platform == "darwin":
        return getattr(libc, "renameatx_np", None) is not None
    if sys.platform.startswith("linux"):
        return getattr(libc, "renameat2", None) is not None
    return False


def _relative_file_snapshot(
    parent_fd: int,
    name: str,
) -> tuple[int, int, str, int]:
    """Return identity, digest, and mode for a no-follow regular file."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise WorkspacePathError(
                "authorized output target is no longer a regular file",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        digest = _digest_descriptor(descriptor)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise WorkspacePathError(
                "authorized output target changed while it was read",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        return (
            after.st_dev,
            after.st_ino,
            digest,
            stat.S_IMODE(after.st_mode),
        )
    finally:
        os.close(descriptor)


def _split_roots(raw: str) -> list[str]:
    value = raw.strip()
    if not value:
        raise WorkspaceConfigurationError(
            f"{WORKSPACE_ROOTS_ENV} is set but contains no workspace roots"
        )
    if value.startswith("["):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkspaceConfigurationError(
                f"{WORKSPACE_ROOTS_ENV} must be a JSON string array or {os.pathsep!r}-separated paths"
            ) from exc
        if not isinstance(decoded, list) or not all(
            isinstance(item, str) and item.strip() for item in decoded
        ):
            raise WorkspaceConfigurationError(
                f"{WORKSPACE_ROOTS_ENV} JSON value must be a non-empty string array"
            )
        return [item.strip() for item in decoded]
    return [item.strip() for item in value.split(os.pathsep) if item.strip()]


def _normalize_roots(values: Iterable[str | os.PathLike[str]]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in values:
        raw = Path(value).expanduser()
        try:
            root = raw.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise WorkspaceConfigurationError(
                "an authorized workspace root does not exist or cannot be resolved"
            ) from exc
        if not root.is_dir():
            raise WorkspaceConfigurationError("an authorized workspace root is not a directory")
        if root == Path(root.anchor):
            raise WorkspaceConfigurationError(
                "a filesystem root cannot be authorized as an HWPX workspace"
            )
        if root not in roots:
            roots.append(root)
    if not roots:
        raise WorkspaceConfigurationError("at least one authorized workspace root is required")
    return tuple(roots)


def _normalize_path_input(
    value: str | os.PathLike[str], *, windows: bool | None = None
) -> str:
    """Normalize common local-path forms before workspace authorization.

    Ordinary filesystem path names are preserved byte-for-byte: only explicit
    transport decoration (surrounding quotes and ``file:`` URIs) is unwrapped.
    A path such as ``" report.hwpx "`` with meaningful surrounding whitespace is
    therefore never silently redirected to a different, unspaced file.
    """

    text = os.fspath(value)

    # Unwrap surrounding quotes only. Whitespace outside the quote wrapper is
    # transport decoration, while the quoted payload itself is preserved.
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        text = stripped[1:-1]

    # Only treat the input as a URI when it actually carries the ``file`` scheme.
    # Running URI parsing over ordinary paths is what previously mangled valid
    # names, so unscheme'd input flows through untouched.
    if text[:5].lower() == "file:":
        try:
            parsed = urlsplit(text)
        except ValueError as exc:
            # A malformed authority (e.g. ``file://[invalid]/x``) makes urlsplit
            # raise; map it onto the typed workspace error contract instead of
            # leaking an untyped parser exception, without echoing the input.
            raise WorkspacePathError(
                "workspace path is not a valid file URI",
                code="WORKSPACE_PATH_INVALID",
                reason="malformed_file_uri",
            ) from exc
        path = unquote(parsed.path)
        authority = parsed.netloc
        # An empty or ``localhost`` authority denotes the local host: resolve to
        # the plain path. A non-local authority names a remote host, which is
        # not an addressable local workspace path, so reject it explicitly
        # rather than silently localizing or mangling it into a UNC reference.
        if authority and authority.lower() != "localhost":
            raise WorkspacePathError(
                "workspace path names a non-local file URI authority",
                code="WORKSPACE_PATH_INVALID",
                reason="non_local_file_uri_authority",
            )
        text = path

    use_windows = os.name == "nt" if windows is None else windows
    if use_windows:
        if len(text) >= 3 and text[0] == "/" and text[1].isalpha() and text[2] == ":":
            text = text[1:]
        text = text.replace("/", "\\")
    return text


def _windows_system_root() -> PureWindowsPath | None:
    """Return the Windows system directory to fence off, or ``None`` elsewhere."""

    if os.name != "nt":
        return None
    return PureWindowsPath(os.environ.get("SystemRoot", r"C:\Windows"))


def _is_degenerate_cwd(
    workspace: PurePath,
    *,
    system_root: PureWindowsPath | None,
) -> bool:
    """Return whether a cwd fallback root is an unusable degenerate location.

    A degenerate root is the filesystem root itself (a path that is its own
    parent), or — when *system_root* is provided — the Windows system directory
    or a descendant of it. GUI MCP clients launch servers from such directories
    (``/`` on macOS, ``C:\\Windows\\System32`` on Windows), which must never
    become an implicit workspace root. Passing *system_root* explicitly keeps
    the Windows rule testable on POSIX via ``PureWindowsPath``.
    """

    if workspace == workspace.parent:
        return True
    if system_root is not None:
        candidate_parts = tuple(part.lower() for part in PureWindowsPath(workspace).parts)
        system_parts = tuple(part.lower() for part in system_root.parts)
        if system_parts and candidate_parts[: len(system_parts)] == system_parts:
            return True
    return False


@dataclass(frozen=True, slots=True)
class WorkspaceResolver:
    """Resolve relative and absolute paths inside one or more authorized roots."""

    roots: tuple[Path, ...]
    source: str

    @classmethod
    def from_environment(cls, *, cwd: Path | None = None) -> "WorkspaceResolver":
        explicit = os.environ.get(WORKSPACE_ROOTS_ENV)
        if explicit is not None:
            return cls(_normalize_roots(_split_roots(explicit)), WORKSPACE_ROOTS_ENV)

        legacy_roots = os.environ.get(LEGACY_WORKSPACE_ROOTS_ENV)
        if legacy_roots is not None:
            return cls(
                _normalize_roots(_split_roots(legacy_roots)),
                LEGACY_WORKSPACE_ROOTS_ENV,
            )

        legacy = os.environ.get(LEGACY_SANDBOX_ROOT_ENV)
        if legacy is not None:
            if not legacy.strip():
                raise WorkspaceConfigurationError(
                    f"{LEGACY_SANDBOX_ROOT_ENV} is set but empty"
                )
            return cls(_normalize_roots([legacy]), LEGACY_SANDBOX_ROOT_ENV)

        process_workspace = cwd or Path.cwd()
        if _is_degenerate_cwd(process_workspace, system_root=_windows_system_root()):
            raise WorkspaceConfigurationError(
                f"the process working directory {os.fspath(process_workspace)!r} is not a "
                f"usable HWPX workspace root; set {WORKSPACE_ROOTS_ENV} to one or more "
                "existing document directories "
                f'(for example {WORKSPACE_ROOTS_ENV}="~/Documents" on macOS/Linux '
                f'or {WORKSPACE_ROOTS_ENV}="C:\\hwpx" on Windows)'
            )
        return cls(_normalize_roots([process_workspace]), "process-cwd")

    @classmethod
    def from_roots(
        cls,
        roots: Iterable[str | os.PathLike[str]],
        *,
        source: str = "explicit",
    ) -> "WorkspaceResolver":
        return cls(_normalize_roots(roots), source)

    @property
    def primary_root(self) -> Path:
        return self.roots[0]

    def _candidate(self, value: str | os.PathLike[str]) -> Path:
        text = _normalize_path_input(value)
        if not text or not text.strip() or "\0" in text:
            raise WorkspacePathError(
                "workspace path must be a non-empty filesystem path",
                code="WORKSPACE_PATH_INVALID",
                reason="empty_or_invalid_path",
            )
        portable_path = text.replace("\\", "/").casefold().rstrip("/")
        if portable_path == "/mnt/user-data" or portable_path.startswith(
            "/mnt/user-data/"
        ):
            raise WorkspacePathError(
                "client-uploaded files are not accessible to the local MCP server",
                code="CLIENT_UPLOAD_PATH_UNAVAILABLE",
                reason="client_upload_path",
            )
        candidate = Path(text).expanduser()
        return candidate if candidate.is_absolute() else self.primary_root / candidate

    def _authorized_root(self, resolved: Path) -> Path | None:
        for root in self.roots:
            if resolved == root or root in resolved.parents:
                return root
        return None

    def resolve(
        self,
        value: str | os.PathLike[str],
        *,
        must_exist: bool = True,
    ) -> Path:
        candidate = self._candidate(value)
        try:
            resolved = candidate.resolve(strict=must_exist)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise WorkspacePathError(
                "workspace path could not be resolved safely",
                code="WORKSPACE_PATH_INVALID",
                reason="resolution_failed",
            ) from exc

        if self._authorized_root(resolved) is None:
            raise WorkspacePathError(
                "path is outside the authorized HWPX workspace roots",
                code="WORKSPACE_OUTSIDE_ROOT",
                reason="outside_authorized_roots",
            )
        return resolved

    def resolve_output(
        self,
        value: str | os.PathLike[str],
        *,
        create_parents: bool = True,
    ) -> Path:
        resolved = self.resolve(value, must_exist=False)
        if resolved.exists() and resolved.is_dir():
            raise WorkspacePathError(
                "output path identifies a directory, not a document",
                code="WORKSPACE_PATH_INVALID",
                reason="output_is_directory",
            )
        if create_parents:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            parent = resolved.parent.resolve(strict=True)
            if self._authorized_root(parent) is None:
                raise WorkspacePathError(
                    "output parent escaped the authorized HWPX workspace roots",
                    code="WORKSPACE_SYMLINK_ESCAPE",
                    reason="output_parent_escape",
                )
            resolved = parent / resolved.name
        return resolved

    def capture_output(
        self,
        value: str | os.PathLike[str],
        *,
        create_parents: bool = True,
    ) -> WorkspaceOutputGuard:
        """Bind an output to its current root and parent directory identities."""

        resolved = self.resolve_output(value, create_parents=create_parents)
        try:
            parent = resolved.parent.resolve(strict=True)
            root = self._authorized_root(parent)
            if root is None:
                raise WorkspacePathError(
                    "output parent escaped the authorized HWPX workspace roots",
                    code="WORKSPACE_SYMLINK_ESCAPE",
                    reason="output_parent_escape",
                )
            parent_stat = os.stat(parent, follow_symlinks=False)
            root_stat = os.stat(root, follow_symlinks=False)
            if _descriptor_cas_supported():
                relative_parent = parent.relative_to(root)
                directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                root_fd = os.open(root, directory_flags)
                opened: list[int] = [root_fd]
                parent_fd = root_fd
                try:
                    observed_root = os.fstat(root_fd)
                    if (observed_root.st_dev, observed_root.st_ino) != (
                        root_stat.st_dev,
                        root_stat.st_ino,
                    ):
                        raise WorkspacePathError(
                            "workspace root changed while binding output",
                            code="WORKSPACE_PATH_CHANGED",
                            reason="workspace_root_changed",
                        )
                    for component in relative_parent.parts:
                        next_fd = os.open(
                            component,
                            directory_flags,
                            dir_fd=parent_fd,
                        )
                        opened.append(next_fd)
                        parent_fd = next_fd
                    observed_parent = os.fstat(parent_fd)
                    if (observed_parent.st_dev, observed_parent.st_ino) != (
                        parent_stat.st_dev,
                        parent_stat.st_ino,
                    ):
                        raise WorkspacePathError(
                            "output parent changed while binding output",
                            code="WORKSPACE_PATH_CHANGED",
                            reason="output_parent_changed",
                        )
                    try:
                        (
                            target_device,
                            target_inode,
                            target_digest,
                            target_mode,
                        ) = _relative_file_snapshot(parent_fd, resolved.name)
                        target_existed = True
                    except FileNotFoundError:
                        target_existed = False
                        target_device = None
                        target_inode = None
                        target_digest = None
                        target_mode = None
                finally:
                    for descriptor in reversed(opened):
                        os.close(descriptor)
            else:
                (
                    target_existed,
                    target_device,
                    target_inode,
                    target_digest,
                    target_mode,
                ) = _snapshot_target(parent / resolved.name)
        except WorkspacePathError:
            raise
        except OSError as exc:
            raise WorkspacePathError(
                "output parent could not be bound safely",
                code="WORKSPACE_PATH_INVALID",
                reason="output_parent_unavailable",
            ) from exc
        if not stat.S_ISDIR(parent_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise WorkspacePathError(
                "output parent is not a stable directory",
                code="WORKSPACE_PATH_INVALID",
                reason="output_parent_not_directory",
            )
        return WorkspaceOutputGuard(
            path=parent / resolved.name,
            root=root,
            root_device=root_stat.st_dev,
            root_inode=root_stat.st_ino,
            parent_device=parent_stat.st_dev,
            parent_inode=parent_stat.st_ino,
            target_existed=target_existed,
            target_device=target_device,
            target_inode=target_inode,
            target_digest=target_digest,
            target_mode=target_mode,
        )

    def capture_output_precondition(
        self,
        value: str | os.PathLike[str],
    ) -> WorkspaceOutputGuard | WorkspaceMissingParentGuard:
        """Bind an output without creating any missing parent directories."""

        try:
            return self.capture_output(value, create_parents=False)
        except WorkspacePathError as exc:
            if exc.reason != "output_parent_unavailable":
                raise

        path = self.resolve(value, must_exist=False)
        ancestor = path.parent
        missing_reversed: list[str] = []
        while True:
            try:
                anchor_stat = os.stat(ancestor, follow_symlinks=False)
            except FileNotFoundError:
                if ancestor == ancestor.parent:  # pragma: no cover - bounded root
                    raise WorkspacePathError(
                        "output parent could not be bound safely",
                        code="WORKSPACE_PATH_INVALID",
                        reason="output_parent_unavailable",
                    ) from None
                missing_reversed.append(ancestor.name)
                ancestor = ancestor.parent
                continue
            break
        if not stat.S_ISDIR(anchor_stat.st_mode):
            raise WorkspacePathError(
                "output parent anchor is not a directory",
                code="WORKSPACE_PATH_INVALID",
                reason="output_parent_not_directory",
            )
        root = self._authorized_root(ancestor)
        if root is None:
            raise WorkspacePathError(
                "output parent escaped the authorized HWPX workspace roots",
                code="WORKSPACE_SYMLINK_ESCAPE",
                reason="output_parent_escape",
            )
        root_stat = os.stat(root, follow_symlinks=False)
        missing_parts = tuple(reversed(missing_reversed))
        if not missing_parts:
            raise WorkspacePathError(
                "output parent could not be bound safely",
                code="WORKSPACE_PATH_INVALID",
                reason="output_parent_unavailable",
            )
        return WorkspaceMissingParentGuard(
            path=path,
            root=root,
            root_device=root_stat.st_dev,
            root_inode=root_stat.st_ino,
            anchor=ancestor,
            anchor_device=anchor_stat.st_dev,
            anchor_inode=anchor_stat.st_ino,
            missing_parts=missing_parts,
        )

    def materialize_output_guard(
        self,
        precondition: WorkspaceOutputGuard | WorkspaceMissingParentGuard,
    ) -> WorkspaceOutputGuard:
        """Create only a previously bound missing parent chain and return its guard."""

        if isinstance(precondition, WorkspaceOutputGuard):
            return precondition

        created: list[tuple[Path, int, int]] = []
        try:
            current = self.resolve(precondition.path, must_exist=False)
            root_stat = os.stat(precondition.root, follow_symlinks=False)
            anchor_stat = os.stat(precondition.anchor, follow_symlinks=False)
            if (
                current != precondition.path
                or self._authorized_root(precondition.anchor) != precondition.root
                or (root_stat.st_dev, root_stat.st_ino)
                != (precondition.root_device, precondition.root_inode)
                or (anchor_stat.st_dev, anchor_stat.st_ino)
                != (precondition.anchor_device, precondition.anchor_inode)
                or not stat.S_ISDIR(root_stat.st_mode)
                or not stat.S_ISDIR(anchor_stat.st_mode)
            ):
                raise WorkspacePathError(
                    "authorized output parent changed before creation",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_parent_changed",
                )
            parent = precondition.anchor
            for component in precondition.missing_parts:
                child = parent / component
                try:
                    os.mkdir(child, 0o700)
                except FileExistsError as exc:
                    raise WorkspacePathError(
                        "authorized output parent appeared before creation",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_parent_changed",
                    ) from exc
                child_stat = os.stat(child, follow_symlinks=False)
                if not stat.S_ISDIR(child_stat.st_mode):
                    raise WorkspacePathError(
                        "created output parent is not a directory",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_parent_changed",
                    )
                created.append((child, child_stat.st_dev, child_stat.st_ino))
                parent = child
            guard = self.capture_output(precondition.path, create_parents=False)
            expected_parent = created[-1]
            if (
                guard.path != precondition.path
                or guard.root != precondition.root
                or (guard.root_device, guard.root_inode)
                != (precondition.root_device, precondition.root_inode)
                or (guard.parent_device, guard.parent_inode)
                != (expected_parent[1], expected_parent[2])
                or guard.target_existed
            ):
                raise WorkspacePathError(
                    "authorized output changed while creating its parent",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_parent_changed",
                )
            return replace(
                guard,
                owned_parent_directories=tuple(created),
            )
        except BaseException:
            self.cleanup_owned_parent_directories(created)
            raise

    @staticmethod
    def cleanup_owned_parent_directories(
        guard_or_directories: (
            WorkspaceOutputGuard | Iterable[tuple[Path, int, int]]
        ),
    ) -> bool:
        """Remove only exact, empty directories created for one publication."""

        directories = (
            guard_or_directories.owned_parent_directories
            if isinstance(guard_or_directories, WorkspaceOutputGuard)
            else tuple(guard_or_directories)
        )
        preserved = True
        for path, device, inode in reversed(directories):
            try:
                observed = os.stat(path, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (
                not stat.S_ISDIR(observed.st_mode)
                or (observed.st_dev, observed.st_ino) != (device, inode)
            ):
                preserved = False
                continue
            try:
                os.rmdir(path)
            except OSError:
                preserved = False
        return preserved

    def _assert_output_guard(self, guard: WorkspaceOutputGuard) -> None:
        """Fail closed when an output root/parent changed after authorization."""

        try:
            current = self.resolve(guard.path, must_exist=False)
            parent = current.parent.resolve(strict=True)
            root_stat = os.stat(guard.root, follow_symlinks=False)
            parent_stat = os.stat(parent, follow_symlinks=False)
        except WorkspacePathError:
            raise
        except OSError as exc:
            raise WorkspacePathError(
                "authorized output path changed before publication",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_parent_changed",
            ) from exc
        if (
            current != guard.path
            or self._authorized_root(parent) != guard.root
            or (root_stat.st_dev, root_stat.st_ino)
            != (guard.root_device, guard.root_inode)
            or (parent_stat.st_dev, parent_stat.st_ino)
            != (guard.parent_device, guard.parent_inode)
            or not stat.S_ISDIR(root_stat.st_mode)
            or not stat.S_ISDIR(parent_stat.st_mode)
        ):
            raise WorkspacePathError(
                "authorized output path changed before publication",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_parent_changed",
            )

    def read_guarded_bytes(self, guard: WorkspaceOutputGuard) -> bytes:
        """Read the exact regular file captured by *guard* without path chasing."""

        self._assert_output_guard(guard)
        if not guard.target_existed:
            raise FileNotFoundError(guard.path)
        if not _descriptor_cas_supported():
            data = guard.path.read_bytes()
            (
                existed,
                device,
                inode,
                digest,
                mode,
            ) = _snapshot_target(guard.path)
            if (
                not existed
                or device != guard.target_device
                or inode != guard.target_inode
                or digest != guard.target_digest
                or mode != guard.target_mode
                or hashlib.sha256(data).hexdigest() != digest
            ):
                raise WorkspacePathError(
                    "authorized file changed while it was read",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                )
            self._assert_output_guard(guard)
            return data

        relative_parent = guard.path.parent.relative_to(guard.root)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root_fd = os.open(guard.root, directory_flags)
        opened: list[int] = [root_fd]
        parent_fd = root_fd
        descriptor: int | None = None
        try:
            root_stat = os.fstat(root_fd)
            if (root_stat.st_dev, root_stat.st_ino) != (
                guard.root_device,
                guard.root_inode,
            ):
                raise WorkspacePathError(
                    "authorized workspace root changed before read",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="workspace_root_changed",
                )
            for component in relative_parent.parts:
                next_fd = os.open(component, directory_flags, dir_fd=parent_fd)
                opened.append(next_fd)
                parent_fd = next_fd
            parent_stat = os.fstat(parent_fd)
            if (parent_stat.st_dev, parent_stat.st_ino) != (
                guard.parent_device,
                guard.parent_inode,
            ):
                raise WorkspacePathError(
                    "authorized output parent changed before read",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_parent_changed",
                )
            self._assert_target_guard(guard, parent_fd)
            descriptor = os.open(
                guard.path.name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_fd,
            )
            before = os.fstat(descriptor)
            chunks: list[bytes] = []
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                digest.update(chunk)
            after = os.fstat(descriptor)
            if (
                (before.st_dev, before.st_ino)
                != (guard.target_device, guard.target_inode)
                or (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                )
                != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                )
                or digest.hexdigest() != guard.target_digest
                or stat.S_IMODE(after.st_mode) != guard.target_mode
            ):
                raise WorkspacePathError(
                    "authorized file changed while it was read",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                )
            self._assert_output_guard(guard)
            return b"".join(chunks)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            for opened_descriptor in reversed(opened):
                os.close(opened_descriptor)

    @staticmethod
    def _assert_target_guard(
        guard: WorkspaceOutputGuard,
        parent_fd: int,
        *,
        name: str | None = None,
    ) -> None:
        """Compare a descriptor-relative target with the captured file bytes."""

        target_name = name or guard.path.name
        try:
            device, inode, digest, mode = _relative_file_snapshot(
                parent_fd,
                target_name,
            )
        except FileNotFoundError:
            if guard.target_existed:
                raise WorkspacePathError(
                    "authorized output target disappeared before publication",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                ) from None
            return
        except OSError as exc:
            raise WorkspacePathError(
                "authorized output target changed before publication",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            ) from exc
        if (
            not guard.target_existed
            or device != guard.target_device
            or inode != guard.target_inode
            or digest != guard.target_digest
            or mode != guard.target_mode
        ):
            raise WorkspacePathError(
                "authorized output target changed before publication",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )

    def atomic_publish_bytes(
        self,
        guard: WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> WorkspaceOutputGuard:
        """Publish bytes and return the exact identity-bound candidate claim."""

        self._assert_output_guard(guard)
        if not _descriptor_cas_supported():
            # Portable fallback retains both identity checks. POSIX hosts use
            # the stronger root-anchored descriptor path below.
            original_data = (
                self.read_guarded_bytes(guard) if guard.target_existed else None
            )
            temporary = guard.path.parent / (
                f".{guard.path.name}.{secrets.token_hex(8)}.tmp"
            )
            candidate_identity: tuple[int, int, str, int] | None = None
            published = False

            def cleanup_owned_temporary(path: Path) -> None:
                try:
                    path.unlink(missing_ok=True)
                except PermissionError:
                    try:
                        os.chmod(path, stat.S_IWRITE)
                    except FileNotFoundError:
                        return
                    path.unlink(missing_ok=True)

            def restore_owned_fallback_candidate() -> None:
                """Best-effort rollback only while our exact candidate is live."""

                if candidate_identity is None:
                    return
                try:
                    observed = _snapshot_target(guard.path)
                except (OSError, WorkspacePathError):
                    return
                if not observed[0] or observed[1:] != candidate_identity:
                    return
                if not guard.target_existed:
                    try:
                        guard.path.unlink()
                    except PermissionError:
                        # Windows cannot unlink a read-only verification
                        # snapshot until its read-only bit is cleared.
                        os.chmod(guard.path, stat.S_IWRITE)
                        writable = _snapshot_target(guard.path)
                        if (
                            not writable[0]
                            or writable[1:4] != candidate_identity[:3]
                        ):
                            return
                        guard.path.unlink()
                    return
                if original_data is None:  # pragma: no cover - guard invariant
                    return
                restore = guard.path.parent / (
                    f".{guard.path.name}.{secrets.token_hex(8)}.restore"
                )
                try:
                    with restore.open("xb") as stream:
                        stream.write(original_data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(
                        restore,
                        guard.target_mode
                        if guard.target_mode is not None
                        else 0o600,
                    )
                    # Recheck ownership immediately before the portable replace.
                    current = _snapshot_target(guard.path)
                    if not current[0] or current[1:] != candidate_identity:
                        return
                    os.replace(restore, guard.path)
                finally:
                    cleanup_owned_temporary(restore)

            try:
                with temporary.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                desired_mode = (
                    mode
                    if mode is not None
                    else guard.target_mode
                    if guard.target_existed
                    else 0o600
                )
                os.chmod(temporary, desired_mode)
                (
                    candidate_existed,
                    candidate_device,
                    candidate_inode,
                    candidate_digest,
                    candidate_mode,
                ) = _snapshot_target(temporary)
                if (
                    not candidate_existed
                    or candidate_device is None
                    or candidate_inode is None
                    or candidate_digest != hashlib.sha256(data).hexdigest()
                    or candidate_mode is None
                ):
                    raise WorkspacePathError(
                        "output candidate changed before publication",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_candidate_changed",
                    )
                # Use the platform-observed mode. Windows normalizes chmod to
                # its read-only bit instead of preserving arbitrary POSIX bits.
                candidate_identity = (
                    candidate_device,
                    candidate_inode,
                    candidate_digest,
                    candidate_mode,
                )
                self._assert_output_guard(guard)
                (
                    target_existed,
                    target_device,
                    target_inode,
                    target_digest,
                    target_mode,
                ) = _snapshot_target(guard.path)
                if (
                    target_existed != guard.target_existed
                    or target_device != guard.target_device
                    or target_inode != guard.target_inode
                    or target_digest != guard.target_digest
                    or target_mode != guard.target_mode
                ):
                    raise WorkspacePathError(
                        "authorized output target changed before publication",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_target_changed",
                    )
                os.replace(temporary, guard.path)
                published = True
            finally:
                cleanup_owned_temporary(temporary)
            try:
                self._assert_output_guard(guard)
                observed = _snapshot_target(guard.path)
                if (
                    candidate_identity is None
                    or not observed[0]
                    or observed[1:] != candidate_identity
                ):
                    raise WorkspacePathError(
                        "published output differs from the verified candidate",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_target_changed",
                    )
            except BaseException:
                if published:
                    restore_owned_fallback_candidate()
                raise
            try:
                claim = self.capture_output(guard.path, create_parents=False)
                if (
                    candidate_identity is None
                    or claim.path != guard.path
                    or claim.root != guard.root
                    or (claim.root_device, claim.root_inode)
                    != (guard.root_device, guard.root_inode)
                    or (claim.parent_device, claim.parent_inode)
                    != (guard.parent_device, guard.parent_inode)
                    or not claim.target_existed
                    or (
                        claim.target_device,
                        claim.target_inode,
                        claim.target_digest,
                        claim.target_mode,
                    )
                    != candidate_identity
                ):
                    raise WorkspacePathError(
                        "published output changed before ownership was claimed",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_target_changed",
                    )
                return replace(
                    claim,
                    owned_parent_directories=guard.owned_parent_directories,
                )
            except BaseException:
                if published:
                    restore_owned_fallback_candidate()
                raise

        relative_parent = guard.path.parent.relative_to(guard.root)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root_fd = os.open(guard.root, directory_flags)
        opened: list[int] = [root_fd]
        temporary_name = f".{guard.path.name}.{secrets.token_hex(8)}.tmp"
        parent_fd = root_fd
        temp_created = False
        snapshot_file = None
        try:
            root_stat = os.fstat(root_fd)
            if (root_stat.st_dev, root_stat.st_ino) != (
                guard.root_device,
                guard.root_inode,
            ):
                raise WorkspacePathError(
                    "authorized workspace root changed before publication",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="workspace_root_changed",
                )
            for component in relative_parent.parts:
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=parent_fd,
                )
                opened.append(next_fd)
                parent_fd = next_fd
            parent_stat = os.fstat(parent_fd)
            if (parent_stat.st_dev, parent_stat.st_ino) != (
                guard.parent_device,
                guard.parent_inode,
            ):
                raise WorkspacePathError(
                    "authorized output parent changed before publication",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_parent_changed",
                )
            self._assert_target_guard(guard, parent_fd)
            if guard.target_existed:
                snapshot_file = tempfile.TemporaryFile()
                source_fd = os.open(
                    guard.path.name,
                    os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                    dir_fd=parent_fd,
                )
                try:
                    before = os.fstat(source_fd)
                    snapshot_digest = _digest_descriptor(
                        source_fd,
                        copy_to=snapshot_file.fileno(),
                    )
                    after = os.fstat(source_fd)
                finally:
                    os.close(source_fd)
                if (
                    not stat.S_ISREG(after.st_mode)
                    or (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                    )
                    != (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                    )
                    or snapshot_digest != guard.target_digest
                    or stat.S_IMODE(after.st_mode) != guard.target_mode
                ):
                    raise WorkspacePathError(
                        "authorized output target changed while snapshotting",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_target_changed",
                    )
            temp_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            temp_created = True
            try:
                desired_mode = (
                    mode
                    if mode is not None
                    else guard.target_mode
                    if guard.target_existed
                    else 0o600
                )
                os.fchmod(temp_fd, desired_mode)
                view = memoryview(data)
                while view:
                    written = os.write(temp_fd, view)
                    view = view[written:]
                os.fsync(temp_fd)
            finally:
                os.close(temp_fd)
            candidate_device, candidate_inode, candidate_digest, candidate_mode = (
                _relative_file_snapshot(parent_fd, temporary_name)
            )
            if (
                candidate_digest != hashlib.sha256(data).hexdigest()
                or candidate_mode != desired_mode
            ):
                raise WorkspacePathError(
                    "output candidate changed before publication",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_candidate_changed",
                )

            def candidate_matches(name: str) -> bool:
                try:
                    observed = _relative_file_snapshot(parent_fd, name)
                except (OSError, WorkspacePathError):
                    return False
                return observed == (
                    candidate_device,
                    candidate_inode,
                    candidate_digest,
                    candidate_mode,
                )

            def restore_original_if_candidate() -> bool:
                if snapshot_file is None or not candidate_matches(guard.path.name):
                    return False
                restore_name = (
                    f".{guard.path.name}.{secrets.token_hex(8)}.restore"
                )
                restore_created = False
                restore_fd = os.open(
                    restore_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                restore_created = True
                try:
                    os.fchmod(
                        restore_fd,
                        guard.target_mode
                        if guard.target_mode is not None
                        else 0o600,
                    )
                    os.lseek(snapshot_file.fileno(), 0, os.SEEK_SET)
                    while True:
                        chunk = os.read(snapshot_file.fileno(), 1024 * 1024)
                        if not chunk:
                            break
                        view = memoryview(chunk)
                        while view:
                            written = os.write(restore_fd, view)
                            view = view[written:]
                    os.fsync(restore_fd)
                finally:
                    os.close(restore_fd)
                try:
                    _exchange_entries(parent_fd, restore_name, guard.path.name)
                    if not candidate_matches(restore_name):
                        _exchange_entries(
                            parent_fd,
                            restore_name,
                            guard.path.name,
                        )
                        return False
                    os.unlink(restore_name, dir_fd=parent_fd)
                    restore_created = False
                    os.fsync(parent_fd)
                    return True
                finally:
                    if restore_created:
                        try:
                            os.unlink(restore_name, dir_fd=parent_fd)
                        except OSError:
                            pass

            self._assert_output_guard(guard)
            self._assert_target_guard(guard, parent_fd)
            published = False
            try:
                if guard.target_existed:
                    try:
                        _exchange_entries(parent_fd, temporary_name, guard.path.name)
                    except OSError as exc:
                        raise WorkspacePathError(
                            "authorized output target changed before publication",
                            code="WORKSPACE_PATH_CHANGED",
                            reason="output_target_changed",
                        ) from exc
                    published = True
                    try:
                        self._assert_target_guard(
                            guard,
                            parent_fd,
                            name=temporary_name,
                        )
                    except BaseException:
                        # The displaced entry is not the state we captured.
                        # Exchange it back so an external writer is preserved.
                        _exchange_entries(
                            parent_fd,
                            temporary_name,
                            guard.path.name,
                        )
                        published = False
                        raise
                    if not candidate_matches(guard.path.name):
                        raise WorkspacePathError(
                            "published output differs from the verified candidate",
                            code="WORKSPACE_PATH_CHANGED",
                            reason="output_target_changed",
                        )
                    self._assert_output_guard(guard)
                    os.unlink(temporary_name, dir_fd=parent_fd)
                    temp_created = False
                else:
                    try:
                        os.link(
                            temporary_name,
                            guard.path.name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError as exc:
                        raise WorkspacePathError(
                            "authorized output target appeared before publication",
                            code="WORKSPACE_PATH_CHANGED",
                            reason="output_target_changed",
                        ) from exc
                    published = True
                    if not candidate_matches(guard.path.name):
                        raise WorkspacePathError(
                            "published output differs from the verified candidate",
                            code="WORKSPACE_PATH_CHANGED",
                            reason="output_target_changed",
                        )
                    self._assert_output_guard(guard)
                    os.unlink(temporary_name, dir_fd=parent_fd)
                    temp_created = False
                os.fsync(parent_fd)
                if not candidate_matches(guard.path.name):
                    raise WorkspacePathError(
                        "published output changed before completion",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_target_changed",
                    )
                self._assert_output_guard(guard)
            except BaseException:
                if published and guard.target_existed:
                    restore_original_if_candidate()
                elif published:
                    if candidate_matches(guard.path.name):
                        os.unlink(guard.path.name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                raise
        finally:
            if temp_created:
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except OSError:
                    pass
            if snapshot_file is not None:
                snapshot_file.close()
            for descriptor in reversed(opened):
                os.close(descriptor)
        return WorkspaceOutputGuard(
            path=guard.path,
            root=guard.root,
            root_device=guard.root_device,
            root_inode=guard.root_inode,
            parent_device=guard.parent_device,
            parent_inode=guard.parent_inode,
            target_existed=True,
            target_device=candidate_device,
            target_inode=candidate_inode,
            target_digest=candidate_digest,
            target_mode=candidate_mode,
            owned_parent_directories=guard.owned_parent_directories,
        )

    def atomic_write_bytes(
        self,
        guard: WorkspaceOutputGuard,
        data: bytes,
        *,
        mode: int | None = None,
    ) -> Path:
        """Publish bytes through a guarded writer and return the output path."""

        return self.atomic_publish_bytes(guard, data, mode=mode).path

    def remove_output(self, guard: WorkspaceOutputGuard) -> None:
        """Remove only the exact regular file captured by *guard*."""

        self._assert_output_guard(guard)
        if not guard.target_existed:
            return
        if not _descriptor_cas_supported():
            (
                existed,
                device,
                inode,
                digest,
                mode,
            ) = _snapshot_target(guard.path)
            if (
                not existed
                or device != guard.target_device
                or inode != guard.target_inode
                or digest != guard.target_digest
                or mode != guard.target_mode
            ):
                raise WorkspacePathError(
                    "authorized output target changed before removal",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                )
            try:
                guard.path.unlink()
            except PermissionError:
                os.chmod(guard.path, stat.S_IWRITE)
                writable = _snapshot_target(guard.path)
                if (
                    not writable[0]
                    or writable[1] != guard.target_device
                    or writable[2] != guard.target_inode
                    or writable[3] != guard.target_digest
                ):
                    raise WorkspacePathError(
                        "authorized output target changed before removal",
                        code="WORKSPACE_PATH_CHANGED",
                        reason="output_target_changed",
                    )
                guard.path.unlink()
            self._assert_output_guard(guard)
            return

        relative_parent = guard.path.parent.relative_to(guard.root)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root_fd = os.open(guard.root, directory_flags)
        opened: list[int] = [root_fd]
        parent_fd = root_fd
        sentinel_name = f".{guard.path.name}.{secrets.token_hex(8)}.remove"
        sentinel_created = False
        exchanged = False
        sentinel_at_target = False
        try:
            root_stat = os.fstat(root_fd)
            if (root_stat.st_dev, root_stat.st_ino) != (
                guard.root_device,
                guard.root_inode,
            ):
                raise WorkspacePathError(
                    "authorized workspace root changed before removal",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="workspace_root_changed",
                )
            for component in relative_parent.parts:
                next_fd = os.open(component, directory_flags, dir_fd=parent_fd)
                opened.append(next_fd)
                parent_fd = next_fd
            parent_stat = os.fstat(parent_fd)
            if (parent_stat.st_dev, parent_stat.st_ino) != (
                guard.parent_device,
                guard.parent_inode,
            ):
                raise WorkspacePathError(
                    "authorized output parent changed before removal",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_parent_changed",
                )
            self._assert_target_guard(guard, parent_fd)
            os.mkdir(sentinel_name, mode=0o700, dir_fd=parent_fd)
            sentinel_created = True
            sentinel_stat = os.stat(
                sentinel_name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            sentinel_identity = (sentinel_stat.st_dev, sentinel_stat.st_ino)
            _exchange_entries(parent_fd, sentinel_name, guard.path.name)
            exchanged = True
            sentinel_at_target = True
            try:
                self._assert_target_guard(guard, parent_fd, name=sentinel_name)
            except BaseException:
                _exchange_entries(parent_fd, sentinel_name, guard.path.name)
                exchanged = False
                sentinel_at_target = False
                raise
            current_sentinel = os.stat(
                guard.path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(current_sentinel.st_mode)
                or (current_sentinel.st_dev, current_sentinel.st_ino)
                != sentinel_identity
            ):
                raise WorkspacePathError(
                    "authorized output target changed during removal",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                )
            try:
                os.rmdir(guard.path.name, dir_fd=parent_fd)
            except OSError as exc:
                raise WorkspacePathError(
                    "authorized output target changed during removal",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                ) from exc
            sentinel_at_target = False
            os.fsync(parent_fd)
            try:
                os.stat(
                    guard.path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise WorkspacePathError(
                    "authorized output target changed during removal",
                    code="WORKSPACE_PATH_CHANGED",
                    reason="output_target_changed",
                )
            self._assert_output_guard(guard)
            self._assert_target_guard(guard, parent_fd, name=sentinel_name)
            os.unlink(sentinel_name, dir_fd=parent_fd)
            sentinel_created = False
            exchanged = False
        except BaseException:
            if exchanged and sentinel_at_target:
                target_is_sentinel = False
                try:
                    current_sentinel = os.stat(
                        guard.path.name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    target_is_sentinel = bool(
                        stat.S_ISDIR(current_sentinel.st_mode)
                        and (current_sentinel.st_dev, current_sentinel.st_ino)
                        == sentinel_identity
                    )
                    if target_is_sentinel:
                        _exchange_entries(
                            parent_fd,
                            sentinel_name,
                            guard.path.name,
                        )
                        exchanged = False
                        sentinel_at_target = False
                except (FileNotFoundError, OSError, WorkspacePathError):
                    pass
                if exchanged and not target_is_sentinel:
                    try:
                        self._assert_target_guard(
                            guard,
                            parent_fd,
                            name=sentinel_name,
                        )
                        os.unlink(sentinel_name, dir_fd=parent_fd)
                        sentinel_created = False
                        exchanged = False
                        sentinel_at_target = False
                    except (FileNotFoundError, OSError, WorkspacePathError):
                        pass
            elif exchanged:
                try:
                    self._assert_target_guard(
                        guard,
                        parent_fd,
                        name=sentinel_name,
                    )
                    try:
                        os.link(
                            sentinel_name,
                            guard.path.name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        # Preserve the external winner but remove only our exact,
                        # randomly named displaced candidate.
                        pass
                    os.unlink(sentinel_name, dir_fd=parent_fd)
                    sentinel_created = False
                    exchanged = False
                except (FileNotFoundError, OSError, WorkspacePathError):
                    pass
            raise
        finally:
            if sentinel_created and not exchanged:
                try:
                    os.rmdir(sentinel_name, dir_fd=parent_fd)
                except OSError:
                    pass
            for descriptor in reversed(opened):
                os.close(descriptor)

    def display_path(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        if resolved == self.primary_root or self.primary_root in resolved.parents:
            return str(resolved.relative_to(self.primary_root))
        return str(resolved)

    def describe(self) -> dict[str, object]:
        return {
            "source": self.source,
            "roots": [str(root) for root in self.roots],
            "rootCount": len(self.roots),
            "relativePathRoot": str(self.primary_root),
            "failClosed": True,
        }
