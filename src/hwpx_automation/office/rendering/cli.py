# SPDX-License-Identifier: Apache-2.0
"""``render-pdf``: render one ``.hwpx`` through Hancom from any environment.

A caller that pins its own python-hwpx cannot install ``[oracle]`` beside it
without moving core, so it runs this command in an environment of its own and
reads the result back::

    uvx --from "python-hwpx-automation[oracle]==<version>" \\
        hwpx render-pdf in.hwpx out.pdf --png out/page --json

The same command is ``python -m hwpx_automation.office.rendering render-pdf``.
With ``--json`` the last stdout line is one JSON object, success or failure;
anything a backend prints goes to stderr. Exit codes: 0 rendered, 1 Hancom
was reached but the render failed, 2 usage or input error, 3 no Hancom
reachable (including ``HWPX_ORACLE_STRUCTURAL_ONLY``).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import signal
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from typing import Any, TextIO

EXIT_OK = 0
EXIT_RENDER_FAILED = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3

DEFAULT_PNG_DPI = 110
_MAX_PNG_DPI = 1200
_LOCK_POLL_SECONDS = 0.25
_BACKENDS = ("auto", "mac", "windows")


class _Failure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        exit_code: int,
        backend: str | None = None,
        *,
        human: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.backend = backend
        self.human = human or f"render-pdf: [{code}] {message}\n"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        text = f"{self.prog}: error: {message}"
        raise _Failure("usage", text, EXIT_USAGE, human=f"{self.format_usage()}{text}\n")


def _positive(kind: type[float | int], limit: float | None = None) -> Any:
    def parse(text: str) -> float | int:
        try:
            value = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
        if not math.isfinite(value) or value <= 0 or (limit is not None and value > limit):
            bound = f" and at most {limit:g}" if limit is not None else ""
            raise argparse.ArgumentTypeError(f"must be positive{bound}: {text!r}")
        return value

    return parse


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = _Parser(
        prog=prog or "python -m hwpx_automation.office.rendering",
        description="Render HWPX through a reachable Hancom (한글).",
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    render = commands.add_parser(
        "render-pdf",
        help="render one .hwpx to PDF (and optional page PNGs) through Hancom",
        description=(
            "Render IN through Hancom to OUT. With --json the last stdout line is "
            "one JSON object. Exit codes: 0 rendered, 1 render failed, 2 usage or "
            "input error, 3 no Hancom reachable."
        ),
    )
    render.add_argument("input", metavar="IN", help="source .hwpx")
    render.add_argument("output", metavar="OUT", help="PDF to write (parent directories created)")
    render.add_argument(
        "--png",
        metavar="PREFIX",
        help="also rasterize each page to PREFIX-001.png, PREFIX-002.png, ...",
    )
    render.add_argument(
        "--dpi",
        type=_positive(int, _MAX_PNG_DPI),
        default=DEFAULT_PNG_DPI,
        help=f"PNG resolution (default: {DEFAULT_PNG_DPI})",
    )
    render.add_argument(
        "--backend",
        choices=_BACKENDS,
        default="auto",
        help="auto picks the first reachable Hancom (Windows COM, then macOS)",
    )
    render.add_argument(
        "--timeout",
        type=_positive(float),
        metavar="SECONDS",
        help="upper bound for every Hancom subprocess of this render",
    )
    render.add_argument("--json", action="store_true", help="print one JSON result line")
    return parser


def _backend_name(backend: Any, oracle: Any) -> str | None:
    if isinstance(backend, oracle.MacHancomOracle):
        return "mac"
    if isinstance(backend, oracle.WindowsComOracle):
        return "windows"
    return None


def _resolve_backend(args: argparse.Namespace) -> tuple[Any, str | None]:
    from . import oracle

    if oracle.structural_only():
        raise _Failure(
            "hancom-unavailable",
            "HWPX_ORACLE_STRUCTURAL_ONLY is set; rendering is disabled.",
            EXIT_UNAVAILABLE,
            None if args.backend == "auto" else args.backend,
        )
    options: dict[str, Any] = {}
    if args.timeout is not None:
        options = {"timeout": args.timeout, "budget_seconds": args.timeout}
    if args.backend == "auto":
        backend = oracle.resolve_oracle(**options)
        name = _backend_name(backend, oracle)
    else:
        options.setdefault("budget_seconds", oracle.env_budget_seconds())
        factory = oracle.MacHancomOracle if args.backend == "mac" else oracle.WindowsComOracle
        backend, name = factory(**options), args.backend
    if name is None or not backend.available():
        where = (
            "no Hancom reachable"
            if args.backend == "auto"
            else f"the {args.backend} backend is not reachable"
        )
        raise _Failure(
            "hancom-unavailable",
            f"{where}: needs Hancom Office HWP on macOS with Automation and "
            "Accessibility permission, or Hancom with COM on Windows.",
            EXIT_UNAVAILABLE,
            name if args.backend == "auto" else args.backend,
        )
    return backend, name


def _pymupdf() -> Any:
    try:
        import pymupdf
    except ImportError:
        raise _Failure(
            "imaging-missing",
            "pymupdf is not installed; install python-hwpx-automation[oracle].",
            EXIT_USAGE,
        ) from None
    return pymupdf


def _rasterize(document: Any, prefix: str, dpi: int, backend: str | None) -> list[str]:
    base = os.path.abspath(prefix)
    pngs: list[str] = []
    try:
        os.makedirs(os.path.dirname(base), exist_ok=True)
        for number, page in enumerate(document, start=1):
            png = f"{base}-{number:03d}.png"
            page.get_pixmap(dpi=dpi).save(png)
            pngs.append(png)
    except OSError as exc:
        raise _Failure(
            "output-unwritable", f"cannot write page images: {exc}", EXIT_USAGE, backend
        ) from None
    except Exception as exc:  # noqa: BLE001 - pymupdf raises its own error types
        raise _Failure(
            "render-failed",
            f"cannot rasterize the rendered PDF: {exc}",
            EXIT_RENDER_FAILED,
            backend,
        ) from None
    return pngs


@contextlib.contextmanager
def _shared_desktop(backend: str | None, wait_seconds: float) -> Iterator[None]:
    """Hold the lock the render worker holds for the one shared Mac desktop.

    Two GUI renders at once drive the same menus and save panel, so a render
    from here must not start while the worker's is running, or the reverse.
    """

    if backend != "mac" or sys.platform == "win32":
        yield
        return
    import fcntl

    from .mac_session import _gui_lock_path

    deadline = time.monotonic() + wait_seconds
    with _gui_lock_path().open("a") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _Failure(
                        "hancom-busy",
                        f"another render held the Hancom desktop for {wait_seconds:g}s.",
                        EXIT_RENDER_FAILED,
                        backend,
                    ) from None
                time.sleep(_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _render_on_desktop(
    backend: Any, name: str | None, source: str, target: str, timeout: float | None
) -> str | None:
    started = time.monotonic()
    with _shared_desktop(name, timeout if timeout is not None else backend.timeout):
        if timeout is not None:
            # Time spent waiting for the desktop comes out of the same budget.
            backend.budget_seconds = max(0.0, timeout - (time.monotonic() - started))
        try:
            rendered: str | None = backend.render_pdf(source, target)
        except _Terminated:
            raise
        except Exception as exc:  # noqa: BLE001 - a backend failure is a result, not a traceback
            raise _Failure(
                "render-failed",
                f"Hancom render raised {type(exc).__name__}: {exc}",
                EXIT_RENDER_FAILED,
                name,
            ) from None
    return rendered


def _inspect_input(source: str) -> None:
    """Refuse a file that is not an HWPX package before Hancom sees it.

    Hancom answers a damaged file with a modal this command cannot dismiss, and
    that modal blocks every later render on the shared desktop. The render
    worker checks its input the same way.
    """

    from hwpx_automation.workflow.render_queue import inspect_hwpx
    from hwpx_automation.workflow.render_security import RenderSecurityViolation

    try:
        with open(source, "rb") as handle:
            inspect_hwpx(handle.read(), filename=os.path.basename(source), principal_id="render-pdf")
    except RenderSecurityViolation as exc:
        raise _Failure("input-invalid", f"not an HWPX package: {source} ({exc})", EXIT_USAGE) from None
    except OSError as exc:
        raise _Failure("input-invalid", f"cannot read {source}: {exc}", EXIT_USAGE) from None


class _Terminated(Exception):
    """SIGTERM, turned into an exception so the render unwinds instead of dying mid-way."""


@contextlib.contextmanager
def _terminate_as_exception() -> Iterator[None]:
    """While rendering, make SIGTERM raise so every cleanup runs.

    ``subprocess.run`` kills its child when an exception passes through it, the
    backend closes the document it opened, the staging folder is removed and the
    desktop lock is released. A plain SIGTERM would skip all of that and leave
    osascript driving Hancom's menus for the next render.
    """

    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _raise(signum: int, frame: Any) -> None:
        raise _Terminated("render-pdf was terminated (SIGTERM)")

    previous = signal.signal(signal.SIGTERM, _raise)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _render(args: argparse.Namespace) -> dict[str, Any]:
    source = os.path.abspath(args.input)
    target = os.path.abspath(args.output)
    if not os.path.isfile(source):
        raise _Failure("input-missing", f"input file not found: {source}", EXIT_USAGE)
    _inspect_input(source)
    fitz = _pymupdf()
    backend, name = _resolve_backend(args)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
    except OSError as exc:
        raise _Failure(
            "output-unwritable", f"cannot create {os.path.dirname(target)}: {exc}", EXIT_USAGE, name
        ) from None

    rendered = _render_on_desktop(backend, name, source, target, args.timeout)
    refusal = getattr(backend, "last_refusal", None)
    if rendered is None and refusal is not None:
        raise _Failure(
            "hancom-refused",
            f"Hancom refused to open the document: {refusal}",
            EXIT_RENDER_FAILED,
            name,
        )
    if rendered is None or not os.path.isfile(target):
        raise _Failure("render-failed", "Hancom did not produce a PDF.", EXIT_RENDER_FAILED, name)

    try:
        document = fitz.open(target)
        pages = document.page_count
    except Exception as exc:  # noqa: BLE001 - pymupdf raises its own error types
        raise _Failure(
            "render-failed", f"the rendered PDF is unreadable: {exc}", EXIT_RENDER_FAILED, name
        ) from None
    with document:
        if pages < 1:
            raise _Failure(
                "render-failed", "the rendered PDF has no pages.", EXIT_RENDER_FAILED, name
            )
        pngs = _rasterize(document, args.png, args.dpi, name) if args.png else []
    return {"ok": True, "pdf": target, "pages": pages, "pngs": pngs, "backend": name}


def _emit(payload: dict[str, Any], as_json: bool, stdout: TextIO) -> None:
    if as_json:
        # ASCII escapes keep the line parseable whatever the console encoding.
        stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
        return
    stdout.write(f"rendered {payload['pages']} page(s) with {payload['backend']}\n")
    stdout.write(f"pdf: {payload['pdf']}\n")
    stdout.writelines(f"png: {png}\n" for png in payload["pngs"])


def main(
    argv: Sequence[str] | None = None,
    *,
    prog: str | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run ``render-pdf``; returns the process exit code."""

    out = stdout or sys.stdout
    err = stderr or sys.stderr
    arguments = list(argv) if argv is not None else sys.argv[1:]
    as_json = "--json" in arguments
    try:
        # --help goes to the caller's stdout; everything a backend says goes
        # to stderr so stdout carries only our result.
        with contextlib.redirect_stdout(out):
            args = build_parser(prog).parse_args(arguments)
        with contextlib.redirect_stdout(err):
            try:
                with _terminate_as_exception():
                    payload = _render(args)
            except _Failure:
                raise
            except _Terminated as exc:
                raise _Failure("terminated", str(exc), EXIT_RENDER_FAILED) from None
            except Exception as exc:  # noqa: BLE001 - the result line is owed even here
                raise _Failure(
                    "internal-error", f"{type(exc).__name__}: {exc}", EXIT_RENDER_FAILED
                ) from None
        code = EXIT_OK
    except _Failure as failure:
        if not as_json:
            err.write(failure.human)
            return failure.exit_code
        payload = {
            "ok": False,
            "error": failure.code,
            "message": failure.message,
            "backend": failure.backend,
        }
        code = failure.exit_code
    except SystemExit as exc:  # --help
        return int(exc.code or 0)
    _emit(payload, as_json, out)
    return code
