# SPDX-License-Identifier: Apache-2.0
"""``render-pdf``: the isolated Hancom render entry point.

A caller that pins its own python-hwpx cannot install this package's
``[oracle]`` extra next to it without moving core, so it runs the render in a
separate environment (``uvx --from ...``) and reads the result from stdout.
These tests lock that contract with fake backends; no Hancom is started.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest

from hwpx_automation.office.agent import cli as hwpx_cli
from hwpx_automation.office.rendering import mac_session, oracle

pymupdf = pytest.importorskip("pymupdf")

ROOT = Path(__file__).resolve().parents[1]
A4_POINTS = (595, 842)


def _write_pdf(path: str, pages: int) -> None:
    document = pymupdf.open()
    for number in range(pages):
        page = document.new_page(width=A4_POINTS[0], height=A4_POINTS[1])
        page.insert_text((72, 72), f"page {number + 1}")
    document.save(path)
    document.close()


class _FakeMac(oracle.MacHancomOracle):
    pages = 2
    reachable = True
    result: str | None = "pdf"
    calls: ClassVar[list[tuple[str, str | None]]] = []
    init_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).init_kwargs = kwargs
        super().__init__(**kwargs)

    def available(self) -> bool:
        return self.reachable

    def render_pdf(self, hwpx_path: str, out_pdf: str | None = None) -> str | None:
        type(self).calls.append((hwpx_path, out_pdf))
        if self.result is None or out_pdf is None:
            return None
        _write_pdf(out_pdf, self.pages)
        return out_pdf


class _FakeWindows(oracle.WindowsComOracle):
    init_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).init_kwargs = kwargs
        super().__init__(**kwargs)

    def available(self) -> bool:
        return True

    def render_pdf(self, hwpx_path: str, out_pdf: str | None = None) -> str | None:
        assert out_pdf is not None
        _write_pdf(out_pdf, 1)
        return out_pdf


@pytest.fixture(autouse=True)
def _oracle_reachable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Lift the suite-wide structural-only switch; never reach real Hancom."""

    monkeypatch.delenv("HWPX_ORACLE_STRUCTURAL_ONLY", raising=False)
    monkeypatch.delenv("HWPX_ORACLE_BUDGET_SECONDS", raising=False)
    monkeypatch.setattr(_FakeMac, "pages", 2)
    monkeypatch.setattr(_FakeMac, "reachable", True)
    monkeypatch.setattr(_FakeMac, "result", "pdf")
    monkeypatch.setattr(_FakeMac, "calls", [])
    monkeypatch.setattr(_FakeMac, "init_kwargs", {})
    monkeypatch.setattr(_FakeWindows, "init_kwargs", {})

    def _resolve(**kwargs: Any) -> oracle.RenderBackend:
        return _FakeMac(**kwargs)

    def _no_real_hancom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the real Hancom transport was reached")

    monkeypatch.setattr(oracle, "resolve_oracle", _resolve)
    # The fakes override available/render_pdf; anything reaching the real
    # discovery or GUI transport underneath them fails the test.
    for name in ("_app_path", "_automation_reachable", "_run_render_script"):
        monkeypatch.setattr(oracle.MacHancomOracle, name, _no_real_hancom)
    monkeypatch.setattr(oracle.WindowsComOracle, "render_many", _no_real_hancom)
    # Never contend with a real render on this desktop for the shared lock.
    monkeypatch.setattr(mac_session, "_gui_lock_path", lambda: tmp_path / "gui.lock")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "in.hwpx"
    path.write_bytes(b"PK\x03\x04 not inspected by render-pdf")
    return path


def _run(args: list[str], *, via: str = "module") -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    if via == "hwpx":
        code = hwpx_cli.main(["render-pdf", *args], stdout=stdout, stderr=stderr)
    else:
        from hwpx_automation.office.rendering import cli as render_cli

        code = render_cli.main(["render-pdf", *args], stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _last_json(stdout: str) -> dict[str, Any]:
    lines = stdout.splitlines()
    assert lines, "stdout is empty"
    payload = json.loads(lines[-1])
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize("via", ["module", "hwpx"])
def test_success_reports_pdf_pages_pngs_and_backend(
    tmp_path: Path, source: Path, via: str
) -> None:
    out = tmp_path / "nested" / "out.pdf"
    prefix = tmp_path / "pngs" / "page"

    code, stdout, _ = _run(
        [str(source), str(out), "--png", str(prefix), "--json"], via=via
    )

    assert code == 0
    pngs = [str(tmp_path / "pngs" / f"page-{i:03d}.png") for i in (1, 2)]
    assert _last_json(stdout) == {
        "ok": True,
        "pdf": str(out),
        "pages": 2,
        "pngs": pngs,
        "backend": "mac",
    }
    assert out.is_file()
    assert all(Path(png).is_file() for png in pngs)
    assert _FakeMac.calls == [(str(source), str(out))]


def test_json_line_is_ascii_even_for_korean_paths(tmp_path: Path, source: Path) -> None:
    out = tmp_path / "결과" / "시험지.pdf"

    code, stdout, _ = _run([str(source), str(out), "--json"])

    assert code == 0
    assert stdout.isascii()
    assert _last_json(stdout)["pdf"] == str(out)


def test_png_dpi_defaults_to_110_and_follows_dpi(tmp_path: Path, source: Path) -> None:
    from PIL import Image

    out = tmp_path / "out.pdf"
    _run([str(source), str(out), "--png", str(tmp_path / "a"), "--json"])
    _run([str(source), str(out), "--png", str(tmp_path / "b"), "--dpi", "72", "--json"])

    with Image.open(tmp_path / "a-001.png") as image:
        assert abs(image.width - A4_POINTS[0] * 110 / 72) <= 1
    with Image.open(tmp_path / "b-001.png") as image:
        assert image.width == A4_POINTS[0]


def test_relative_paths_are_reported_absolute(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    code, stdout, _ = _run(["in.hwpx", "out.pdf", "--png", "p", "--json"])

    assert code == 0
    payload = _last_json(stdout)
    assert payload["pdf"] == str(tmp_path / "out.pdf")
    assert payload["pngs"][0] == str(tmp_path / "p-001.png")
    assert _FakeMac.calls == [(str(source), str(tmp_path / "out.pdf"))]


def test_without_png_prefix_no_images_are_written(tmp_path: Path, source: Path) -> None:
    code, stdout, _ = _run([str(source), str(tmp_path / "out.pdf"), "--json"])

    assert code == 0
    assert _last_json(stdout)["pngs"] == []
    assert not list(tmp_path.rglob("*.png"))


def test_no_reachable_hancom_exits_3(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oracle, "resolve_oracle", lambda **_: oracle.NullOracle())

    code, stdout, _ = _run([str(source), str(tmp_path / "out.pdf"), "--json"])

    assert code == 3
    payload = _last_json(stdout)
    assert payload["ok"] is False
    assert payload["error"] == "hancom-unavailable"
    assert payload["backend"] is None
    assert payload["message"]
    assert not (tmp_path / "out.pdf").exists()


def test_structural_only_exits_3_without_probing(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HWPX_ORACLE_STRUCTURAL_ONLY", "1")

    def _must_not_probe(**_: Any) -> oracle.RenderBackend:
        raise AssertionError("structural-only mode must not probe for Hancom")

    monkeypatch.setattr(oracle, "resolve_oracle", _must_not_probe)

    code, stdout, _ = _run([str(source), str(tmp_path / "out.pdf"), "--json"])

    assert code == 3
    payload = _last_json(stdout)
    assert payload["error"] == "hancom-unavailable"
    assert "HWPX_ORACLE_STRUCTURAL_ONLY" in payload["message"]


def test_explicit_mac_backend_unavailable_exits_3(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oracle, "MacHancomOracle", _FakeMac)
    monkeypatch.setattr(_FakeMac, "reachable", False)

    def _must_not_resolve(**_: Any) -> oracle.RenderBackend:
        raise AssertionError("--backend mac must not fall back to auto discovery")

    monkeypatch.setattr(oracle, "resolve_oracle", _must_not_resolve)

    code, stdout, _ = _run(
        [str(source), str(tmp_path / "out.pdf"), "--backend", "mac", "--json"]
    )

    assert code == 3
    payload = _last_json(stdout)
    assert payload["error"] == "hancom-unavailable"
    assert payload["backend"] == "mac"
    assert _FakeMac.calls == []


def test_explicit_windows_backend_renders(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oracle, "WindowsComOracle", _FakeWindows)

    code, stdout, _ = _run(
        [str(source), str(tmp_path / "out.pdf"), "--backend", "windows", "--json"]
    )

    assert code == 0
    payload = _last_json(stdout)
    assert payload["backend"] == "windows"
    assert payload["pages"] == 1


def test_render_returning_none_exits_1(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_FakeMac, "result", None)

    code, stdout, _ = _run([str(source), str(tmp_path / "out.pdf"), "--json"])

    assert code == 1
    payload = _last_json(stdout)
    assert payload == {
        "ok": False,
        "error": "render-failed",
        "message": payload["message"],
        "backend": "mac",
    }


def test_render_raising_exits_1(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(self: Any, hwpx_path: str, out_pdf: str | None = None) -> str | None:
        raise RuntimeError("osascript died")

    monkeypatch.setattr(_FakeMac, "render_pdf", _explode)

    code, stdout, _ = _run([str(source), str(tmp_path / "out.pdf"), "--json"])

    assert code == 1
    payload = _last_json(stdout)
    assert payload["error"] == "render-failed"
    assert "osascript died" in payload["message"]


def test_unreadable_pdf_exits_1(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _garbage(self: Any, hwpx_path: str, out_pdf: str | None = None) -> str | None:
        assert out_pdf is not None
        Path(out_pdf).write_bytes(b"not a pdf")
        return out_pdf

    monkeypatch.setattr(_FakeMac, "render_pdf", _garbage)

    code, stdout, _ = _run([str(source), str(tmp_path / "out.pdf"), "--json"])

    assert code == 1
    assert _last_json(stdout)["error"] == "render-failed"


@pytest.mark.skipif(sys.platform == "win32", reason="the desktop lock is POSIX flock")
def test_unexpected_errors_still_end_with_the_json_line(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _broken() -> Path:
        raise PermissionError("lock directory is read-only")

    monkeypatch.setattr(mac_session, "_gui_lock_path", _broken)

    code, stdout, _ = _run([str(source), str(tmp_path / "o.pdf"), "--json"])

    assert code == 1
    payload = _last_json(stdout)
    assert payload["error"] == "internal-error"
    assert "read-only" in payload["message"]


def test_missing_input_exits_2_before_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _must_not_resolve(**_: Any) -> oracle.RenderBackend:
        raise AssertionError("a missing input must fail before Hancom discovery")

    monkeypatch.setattr(oracle, "resolve_oracle", _must_not_resolve)

    code, stdout, _ = _run(
        [str(tmp_path / "absent.hwpx"), str(tmp_path / "out.pdf"), "--json"]
    )

    assert code == 2
    payload = _last_json(stdout)
    assert payload["error"] == "input-missing"
    assert payload["backend"] is None


def test_missing_imaging_stack_exits_2_before_rendering(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pymupdf", None)

    code, stdout, _ = _run([str(source), str(tmp_path / "out.pdf"), "--json"])

    assert code == 2
    payload = _last_json(stdout)
    assert payload["error"] == "imaging-missing"
    assert "[oracle]" in payload["message"]
    assert _FakeMac.calls == []


def test_usage_error_with_json_is_still_one_json_line(tmp_path: Path) -> None:
    code, stdout, _ = _run(["only-one-positional", "--json"])

    assert code == 2
    assert _last_json(stdout)["error"] == "usage"


@pytest.mark.parametrize("flag", ["--timeout", "--dpi"])
def test_non_positive_numbers_are_usage_errors(
    tmp_path: Path, source: Path, flag: str
) -> None:
    code, stdout, _ = _run([str(source), str(tmp_path / "o.pdf"), flag, "0", "--json"])

    assert code == 2
    assert _last_json(stdout)["error"] == "usage"


def test_usage_error_without_json_goes_to_stderr() -> None:
    code, stdout, stderr = _run(["only-one-positional"])

    assert code == 2
    assert stdout == ""
    assert "usage:" in stderr


def test_timeout_bounds_every_backend_subprocess(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def _resolve(**kwargs: Any) -> oracle.RenderBackend:
        seen.update(kwargs)
        return _FakeMac(**kwargs)

    monkeypatch.setattr(oracle, "resolve_oracle", _resolve)
    _run([str(source), str(tmp_path / "o.pdf"), "--timeout", "7", "--json"])
    assert seen["timeout"] == 7.0
    assert seen["budget_seconds"] == 7.0

    monkeypatch.setattr(oracle, "MacHancomOracle", _FakeMac)
    _run([str(source), str(tmp_path / "o.pdf"), "--backend", "mac", "--timeout", "9"])
    assert _FakeMac.init_kwargs["timeout"] == 9.0
    assert _FakeMac.init_kwargs["budget_seconds"] == 9.0


def test_explicit_backend_honours_the_environment_budget(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HWPX_ORACLE_BUDGET_SECONDS", "42")
    monkeypatch.setattr(oracle, "MacHancomOracle", _FakeMac)

    _run([str(source), str(tmp_path / "o.pdf"), "--backend", "mac"])

    assert _FakeMac.init_kwargs["budget_seconds"] == 42.0


@pytest.mark.skipif(sys.platform == "win32", reason="the desktop lock is POSIX flock")
def test_mac_render_holds_the_shared_desktop_lock(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fcntl

    original = _FakeMac.render_pdf
    held: list[bool] = []

    def _probe(self: Any, hwpx_path: str, out_pdf: str | None = None) -> str | None:
        with (tmp_path / "gui.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held.append(True)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
                held.append(False)
        return original(self, hwpx_path, out_pdf)

    monkeypatch.setattr(_FakeMac, "render_pdf", _probe)

    code, _, _ = _run([str(source), str(tmp_path / "o.pdf"), "--json"])

    assert code == 0
    assert held == [True]


@pytest.mark.skipif(sys.platform == "win32", reason="the desktop lock is POSIX flock")
def test_busy_desktop_is_waited_for_then_reported(tmp_path: Path, source: Path) -> None:
    import fcntl

    with (tmp_path / "gui.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        code, stdout, _ = _run(
            [str(source), str(tmp_path / "o.pdf"), "--timeout", "0.3", "--json"]
        )

    assert code == 1
    payload = _last_json(stdout)
    assert payload["error"] == "hancom-busy"
    assert payload["backend"] == "mac"
    assert _FakeMac.calls == []


def test_json_is_the_last_stdout_line_even_when_the_backend_prints(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _FakeMac.render_pdf

    def _noisy(self: Any, hwpx_path: str, out_pdf: str | None = None) -> str | None:
        print("backend chatter")
        print('{"ok": false}')
        return original(self, hwpx_path, out_pdf)

    monkeypatch.setattr(_FakeMac, "render_pdf", _noisy)

    code, stdout, stderr = _run([str(source), str(tmp_path / "o.pdf"), "--json"])

    assert code == 0
    assert _last_json(stdout)["ok"] is True
    assert len(stdout.splitlines()) == 1
    assert "backend chatter" in stderr


def test_human_output_names_the_artifacts(tmp_path: Path, source: Path) -> None:
    out = tmp_path / "o.pdf"

    code, stdout, _ = _run([str(source), str(out), "--png", str(tmp_path / "p")])

    assert code == 0
    assert str(out) in stdout
    assert str(tmp_path / "p-002.png") in stdout
    assert "mac" in stdout


def test_human_failure_goes_to_stderr(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oracle, "resolve_oracle", lambda **_: oracle.NullOracle())

    code, stdout, stderr = _run([str(source), str(tmp_path / "o.pdf")])

    assert code == 3
    assert stdout == ""
    assert "hancom-unavailable" in stderr


def test_hwpx_and_module_forms_behave_identically(
    tmp_path: Path, source: Path
) -> None:
    args = [str(source), str(tmp_path / "o.pdf"), "--png", str(tmp_path / "p"), "--json"]

    assert _run(args, via="hwpx") == _run(args, via="module")


def _python(code: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")]),
        "HWPX_ORACLE_STRUCTURAL_ONLY": "1",
    }
    return subprocess.run(
        [sys.executable, *(["-c", code] if code else []), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def test_python_dash_m_entry_point(tmp_path: Path, source: Path) -> None:
    completed = _python(
        "",
        "-m",
        "hwpx_automation.office.rendering",
        "render-pdf",
        str(source),
        str(tmp_path / "o.pdf"),
        "--json",
    )

    assert completed.returncode == 3, completed.stderr
    assert _last_json(completed.stdout)["error"] == "hancom-unavailable"

    helped = _python("", "-m", "hwpx_automation.office.rendering", "render-pdf", "--help")
    assert helped.returncode == 0, helped.stderr
    assert "--png" in helped.stdout


def test_importing_the_package_and_hwpx_console_stays_lazy() -> None:
    completed = _python(
        "import json, sys\n"
        "import hwpx_automation.office.rendering\n"
        "import hwpx_automation.office.agent.cli\n"
        "print(json.dumps(sorted(name for name in sys.modules if name in {\n"
        "    'hwpx_automation.office.rendering.oracle',\n"
        "    'hwpx_automation.office.rendering.cli',\n"
        "    'pymupdf',\n"
        "})))\n"
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.splitlines()[-1]) == []
