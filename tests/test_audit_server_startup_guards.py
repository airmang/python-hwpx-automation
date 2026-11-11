# SPDX-License-Identifier: Apache-2.0
"""Startup refuses unknown profiles and unauthenticated non-loopback HTTP."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

import hwpx_automation.server as server

ROOT = Path(__file__).resolve().parents[1]
_GUARD_ENV = (
    "HWPX_AUTOMATION_PROFILE",
    "HWPX_MCP_PROFILE",
    "HWPX_AUTOMATION_TRANSPORT",
    "HWPX_MCP_TRANSPORT",
    "HWPX_AUTOMATION_HOST",
    "HWPX_MCP_HOST",
    "HWPX_AUTOMATION_HTTP_TOKEN",
    "HWPX_AUTOMATION_ALLOW_UNAUTHENTICATED_HTTP",
)


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Capture what main() would serve instead of serving it."""

    import uvicorn

    for name in _GUARD_ENV:
        monkeypatch.delenv(name, raising=False)
    captured: dict[str, object] = {}
    sentinel = object()
    captured["sentinel"] = sentinel
    monkeypatch.setattr(server.mcp, "streamable_http_app", lambda: sentinel)
    monkeypatch.setattr(
        server.mcp, "run", lambda *, transport: captured.update(stdio=transport)
    )
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda app, *, host, port, log_level: captured.update(app=app, host=host),
    )
    return captured


def test_unknown_profile_from_environment_is_rejected(launched, monkeypatch) -> None:
    monkeypatch.setenv("HWPX_AUTOMATION_PROFILE", "playmcp")

    with pytest.raises(SystemExit):
        server.main([])

    assert "stdio" not in launched and "app" not in launched


def test_unknown_transport_from_environment_is_rejected(launched, monkeypatch) -> None:
    monkeypatch.setenv("HWPX_AUTOMATION_TRANSPORT", "sse-everywhere")

    with pytest.raises(SystemExit):
        server.main([])

    assert "stdio" not in launched and "app" not in launched


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.0.10", "example.internal", ""])
def test_http_refuses_non_loopback_bind_without_auth(launched, host: str) -> None:
    with pytest.raises(SystemExit):
        server.main(["--transport", "streamable-http", "--host", host])

    assert "app" not in launched


def test_http_host_from_environment_is_guarded_too(launched, monkeypatch) -> None:
    monkeypatch.setenv("HWPX_AUTOMATION_TRANSPORT", "streamable-http")
    monkeypatch.setenv("HWPX_AUTOMATION_HOST", "0.0.0.0")

    with pytest.raises(SystemExit):
        server.main([])

    assert "app" not in launched


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_http_loopback_needs_no_auth(launched, host: str) -> None:
    server.main(["--transport", "http", "--host", host])

    assert launched["app"] is launched["sentinel"]
    assert launched["host"] == host


def test_http_non_loopback_is_allowed_with_explicit_opt_in(launched) -> None:
    server.main(
        ["--transport", "http", "--host", "0.0.0.0", "--allow-unauthenticated-http"]
    )

    assert launched["app"] is launched["sentinel"]


def test_short_token_is_rejected(launched, monkeypatch) -> None:
    monkeypatch.setenv("HWPX_AUTOMATION_HTTP_TOKEN", "short")

    with pytest.raises(SystemExit):
        server.main(["--transport", "http", "--host", "0.0.0.0"])


def test_token_wraps_the_app_and_checks_every_request(launched, monkeypatch) -> None:
    token = "t" * 40
    monkeypatch.setenv("HWPX_AUTOMATION_HTTP_TOKEN", token)
    reached: list[str] = []

    async def inner(scope, receive, send):  # noqa: ANN001
        reached.append(scope["type"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(server.mcp, "streamable_http_app", lambda: inner)
    server.main(["--transport", "http", "--host", "0.0.0.0"])
    app = launched["app"]
    assert app is not inner

    def call(headers: list[tuple[bytes, bytes]]) -> int:
        sent: list[dict] = []

        async def send(message):  # noqa: ANN001
            sent.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        asyncio.run(app({"type": "http", "headers": headers}, receive, send))
        return int(sent[0]["status"])

    assert call([]) == 401
    assert call([(b"authorization", b"Bearer wrong" + b"x" * 40)]) == 401
    assert call([(b"authorization", token.encode())]) == 401
    assert reached == []
    assert call([(b"authorization", b"Bearer " + token.encode())]) == 200
    assert reached == ["http"]


def test_dockerfile_uses_a_real_profile_and_a_loopback_default() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    profile = re.search(r"HWPX_AUTOMATION_PROFILE=(\S+)", dockerfile)
    host = re.search(r"HWPX_AUTOMATION_HOST=(\S+)", dockerfile)
    assert profile is not None and profile.group(1) in {"full", "minimal"}
    assert host is not None and host.group(1) == "127.0.0.1"
    command = dockerfile[dockerfile.index("CMD ") :]
    assert "0.0.0.0" not in command
    assert "--allow-unauthenticated-http" not in dockerfile
