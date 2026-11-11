from __future__ import annotations

import builtins
import importlib.util
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as _ET

import pytest

# Keep legacy global alias used by existing tests.
builtins.ET = _ET

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _matching_core_repo() -> Path:
    name = _REPO_ROOT.name
    for prefix in ("python-hwpx-automation", "hwpx-mcp-server"):
        if prefix in name:
            return _REPO_ROOT.parent / name.replace(prefix, "python-hwpx", 1)
    return _REPO_ROOT.parent / f".no-matching-core-for-{name}"


_MATCHING_CORE_REPO = _matching_core_repo()


def _resolve_python_hwpx_paths() -> tuple[Path, Path | None]:
    """Resolve core from an explicit pin, matching worktree, or installed package.

    Never fall back to the owner's unpinned ``../python-hwpx`` checkout: that can
    silently test a different revision and may be outside the active worktree's
    filesystem boundary.
    """

    explicit = os.environ.get("PYTHON_HWPX_REPO")
    if explicit:
        repo = Path(explicit).expanduser().resolve()
        return repo, repo / "src"
    if _MATCHING_CORE_REPO.is_dir():
        return _MATCHING_CORE_REPO, _MATCHING_CORE_REPO / "src"

    spec = importlib.util.find_spec("hwpx")
    if spec is None or spec.origin is None:
        raise RuntimeError(
            "python-hwpx is not installed; set PYTHON_HWPX_REPO to an explicit checkout"
        )
    package_dir = Path(spec.origin).resolve().parent
    if package_dir.parent.name == "src":
        return package_dir.parent.parent, package_dir.parent
    return package_dir.parent, None


_LOCAL_PYTHON_HWPX_REPO, _LOCAL_PYTHON_HWPX_SRC = _resolve_python_hwpx_paths()

if _LOCAL_PYTHON_HWPX_SRC is not None and _LOCAL_PYTHON_HWPX_SRC.exists():
    local_hwpx_src = str(_LOCAL_PYTHON_HWPX_SRC)
    if local_hwpx_src not in sys.path:
        sys.path.insert(0, local_hwpx_src)


@pytest.fixture(autouse=True)
def _clear_path_sandbox_for_inprocess_tests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Give each test explicit repository and temporary workspace roots.

    The automation CLI resolves `HWPX_AUTOMATION_WORKSPACE_ROOTS` first, then
    the supported 6.x `HWPX_MCP_WORKSPACE_ROOTS`/`HWPX_MCP_SANDBOX_ROOT`
    fallbacks, and finally a non-degenerate cwd.

    But unit tests often operate on pytest tmp directories and may call helpers
    directly in-process. If the environment variable is already set in the
    parent shell, those tests would fail.

    Product code never opens the whole filesystem. Tests authorize their public
    fixtures and their one pytest temporary directory; individual security tests
    may replace this value with a narrower root.

    The default suite is also structurally isolated from live GUI automation.
    Real Hancom tests opt in explicitly with ``HWPX_MAC_ORACLE_SMOKE`` (macOS)
    or ``HWPX_WINDOWS_ORACLE_SMOKE`` (Windows; that smoke lifts the switch for
    itself only); without that signal, any incidental renderer resolution must
    degrade without launching ``osascript`` or Hancom COM.
    """

    monkeypatch.delenv("HWPX_MCP_SANDBOX_ROOT", raising=False)
    monkeypatch.delenv("HWPX_MCP_WORKSPACE_ROOTS", raising=False)
    if not os.environ.get("HWPX_MAC_ORACLE_SMOKE"):
        monkeypatch.setenv("HWPX_ORACLE_STRUCTURAL_ONLY", "1")
    monkeypatch.setenv(
        "HWPX_AUTOMATION_WORKSPACE_ROOTS",
        json.dumps([str(_REPO_ROOT), str(tmp_path), str(_LOCAL_PYTHON_HWPX_REPO)]),
    )
    from hwpx_automation import server as server_module
    from hwpx_automation.hwpx_ops import HwpxOps
    from hwpx_automation.storage import LocalDocumentStorage, clear_open_safety_memo
    from hwpx_automation.workspace import WorkspaceResolver

    # Passing open-safety verdicts are remembered per content (EFF-15). Tests
    # replace validators and engine internals freely, so each test starts with
    # an empty memo instead of inheriting another test's verdict.
    clear_open_safety_memo()
    server_module._replace_ops(
        HwpxOps(
            storage=LocalDocumentStorage(
                workspace_resolver=WorkspaceResolver.from_environment(),
                auto_backup=False,
            )
        )
    )


EMBEDDED_ERROR_RE = re.compile(
    r"traceback \(most recent call last\)|\bexception\b|error executing tool",
    re.IGNORECASE,
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _repo_root() -> Path:
    return _REPO_ROOT


def _pythonpath_with_local_sources(existing: str = "") -> str:
    paths = [str(_repo_root() / "src")]
    if _LOCAL_PYTHON_HWPX_SRC is not None and _LOCAL_PYTHON_HWPX_SRC.exists():
        paths.append(str(_LOCAL_PYTHON_HWPX_SRC))
    if existing:
        paths.append(existing)
    return os.pathsep.join(paths)


def _default_server_cmd() -> str:
    cmd = os.getenv("SERVER_CMD") or os.getenv("MCP_SERVER_CMD")
    if cmd:
        return cmd
    return f"{sys.executable} -m hwpx_automation.server"


def _split_server_cmd(command: str) -> list[str]:
    # Windows shell parsing is different, so keep POSIX parsing there disabled.
    return shlex.split(command, posix=os.name != "nt")


def _find_default_sample_fixture() -> Path | None:
    explicit = os.getenv("MCP_SAMPLE_FIXTURE")
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.exists():
            return candidate.resolve()
    fallback = _repo_root() / "tests" / "sample.hwpx"
    if fallback.exists():
        return fallback.resolve()
    return None


@dataclass(frozen=True)
class MCPTestConfig:
    server_cmd: str
    server_cwd: Path
    request_timeout: float
    shutdown_timeout: float
    debug_tail_lines: int
    strict_error_mode: bool
    require_error_data: bool
    send_initialized_notification: bool
    expect_path_sandbox: bool
    sample_fixture: Path | None


@dataclass(frozen=True)
class ToolCallContext:
    target_path: Path
    secondary_path: Path
    seed_text: str
    find_text: str
    replace_text: str


class MCPHarnessError(RuntimeError):
    """Raised when the subprocess transport fails unexpectedly."""


class MCPTimeoutError(TimeoutError):
    """Raised when response wait time exceeds the configured timeout."""


class StdioMCPClient:
    """Small JSON-RPC-over-stdio client for MCP contract/e2e tests."""

    # Tool name hints used by tests.
    CREATE_HINTS = (
        "create_document",
        "create",
        "new",
        "init",
    )
    ADD_HINTS = (
        "add_paragraph",
        "insert_paragraph",
        "append",
        "insert",
        "paragraph",
    )
    REPLACE_HINTS = (
        "search_and_replace",
        "batch_replace",
        "replace",
        "edit",
        "modify",
    )
    READ_HINTS = (
        "get_document_text",
        "read_text",
        "get_paragraph",
        "get_document_info",
        "open_info",
        "read",
    )

    def __init__(
        self,
        *,
        config: MCPTestConfig,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.cwd = (cwd or config.server_cwd).resolve()
        self.extra_env = extra_env or {}
        self._proc: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._closed = False
        self._id_counter = itertools.count(1)
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._responses: dict[Any, dict[str, Any]] = {}
        self.notifications: deque[dict[str, Any]] = deque(maxlen=500)
        self._stdout_tail: deque[str] = deque(maxlen=config.debug_tail_lines)
        self._stderr_tail: deque[str] = deque(maxlen=config.debug_tail_lines)

    @staticmethod
    def default_initialize_params() -> dict[str, Any]:
        protocol_version = os.getenv("MCP_PROTOCOL_VERSION", "2025-11-25")
        return {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "pytest-mcp-harness", "version": "0.1.0"},
        }

    @staticmethod
    def _validate_request_payload(payload: dict[str, Any]) -> None:
        assert payload.get("jsonrpc") == "2.0", f"invalid request jsonrpc: {payload}"
        assert "id" in payload, f"missing request id: {payload}"
        assert isinstance(payload.get("method"), str) and payload["method"], (
            f"invalid request method: {payload}"
        )
        assert "params" in payload and isinstance(payload["params"], dict), (
            f"invalid request params: {payload}"
        )

    @staticmethod
    def assert_error_object(error_obj: Any, *, require_data: bool) -> None:
        assert isinstance(error_obj, dict), (
            f"error must be an object, got {type(error_obj)!r}"
        )
        assert isinstance(error_obj.get("code"), int), (
            f"error.code must be int: {error_obj}"
        )
        assert isinstance(error_obj.get("message"), str) and error_obj["message"], (
            f"error.message must be non-empty string: {error_obj}"
        )
        if require_data:
            assert "data" in error_obj, (
                f"error.data missing in strict mode: {error_obj}"
            )

    @staticmethod
    def _assert_response_envelope(message: Any, *, expected_id: Any) -> None:
        assert isinstance(message, dict), f"response must be object: {message!r}"
        assert message.get("jsonrpc") == "2.0", (
            f"response jsonrpc must be 2.0: {message}"
        )
        assert message.get("id") == expected_id, (
            f"response id mismatch: expected={expected_id!r}, got={message.get('id')!r}, payload={message}"
        )
        has_result = "result" in message
        has_error = "error" in message
        assert has_result ^ has_error, (
            f"response must have exactly one of result/error: {message}"
        )

    @staticmethod
    def _iter_text_fragments(tool_result: dict[str, Any]) -> Iterable[str]:
        content = tool_result.get("content")
        if not isinstance(content, list):
            return []
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return chunks

    @staticmethod
    def parse_tool_result_payload(
        tool_result: dict[str, Any],
    ) -> dict[str, Any] | list[Any] | None:
        if not isinstance(tool_result, dict):
            return None
        structured = tool_result.get("structuredContent")
        if isinstance(structured, (dict, list)):
            return structured
        for text in StdioMCPClient._iter_text_fragments(tool_result):
            stripped = text.strip()
            if not stripped:
                continue
            if stripped[0] not in {"{", "["}:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, (dict, list)):
                return parsed
        return None

    @staticmethod
    def _schema_types(prop_schema: dict[str, Any]) -> list[str]:
        types: list[str] = []
        declared_type = prop_schema.get("type")
        if isinstance(declared_type, str):
            types.append(declared_type)
        elif isinstance(declared_type, list):
            types.extend(item for item in declared_type if isinstance(item, str))
        for option in prop_schema.get("anyOf", []):
            if isinstance(option, dict):
                opt_type = option.get("type")
                if isinstance(opt_type, str):
                    types.append(opt_type)
        return types

    @classmethod
    def _value_for_property(
        cls, prop_name: str, prop_schema: dict[str, Any], ctx: ToolCallContext
    ) -> Any:
        key = prop_name.lower()

        if "source" in key and ("file" in key or "path" in key):
            return str(ctx.target_path)
        if "destination" in key and ("file" in key or "path" in key):
            return str(ctx.secondary_path)
        if any(
            token in key for token in ("filename", "file", "path", "uri", "document")
        ):
            return str(ctx.target_path)
        if key == "replacements":
            return [{"find": ctx.find_text, "replace": ctx.replace_text}]
        if "find" in key or "query" in key or "search" in key:
            return ctx.find_text
        if "replace" in key:
            return ctx.replace_text
        if "text" in key or "content" in key or "instruction" in key:
            return ctx.seed_text
        if "paragraph_index" in key:
            return 0
        if key in {"start_index", "offset", "start_pos"}:
            return 0
        if key in {"end_index", "end_pos"}:
            return 1
        if key in {"rows", "cols"}:
            return 2
        if key in {"row", "col", "column", "table_index"}:
            return 0
        if "level" in key:
            return 1
        if prop_schema.get("enum"):
            return prop_schema["enum"][0]
        if "default" in prop_schema and prop_schema["default"] is not None:
            return prop_schema["default"]

        schema_types = cls._schema_types(prop_schema)
        if "integer" in schema_types:
            minimum = prop_schema.get("minimum")
            if isinstance(minimum, int):
                return minimum
            return 0
        if "number" in schema_types:
            minimum = prop_schema.get("minimum")
            if isinstance(minimum, (int, float)):
                return float(minimum)
            return 1.0
        if "boolean" in schema_types:
            return False
        if "array" in schema_types:
            return []
        if "object" in schema_types:
            return {}

        return "mcp-test"

    @classmethod
    def build_tool_arguments(
        cls, tool: dict[str, Any], ctx: ToolCallContext
    ) -> dict[str, Any]:
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            return {}

        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}

        required = schema.get("required")
        if not isinstance(required, list):
            required = []

        args: dict[str, Any] = {}
        for prop_name in required:
            if not isinstance(prop_name, str):
                continue
            prop_schema = properties.get(prop_name)
            if not isinstance(prop_schema, dict):
                prop_schema = {}
            args[prop_name] = cls._value_for_property(prop_name, prop_schema, ctx)
        return args

    @staticmethod
    def select_tool(
        tools: list[dict[str, Any]],
        include_keywords: Iterable[str],
        *,
        exclude_keywords: Iterable[str] = (),
    ) -> dict[str, Any] | None:
        include = [kw.lower() for kw in include_keywords]
        exclude = [kw.lower() for kw in exclude_keywords]
        scored: list[tuple[int, int, dict[str, Any]]] = []

        for idx, tool in enumerate(tools):
            name = str(tool.get("name", ""))
            if not name:
                continue
            lowered = name.lower()
            if any(kw in lowered for kw in exclude):
                continue
            score = 0
            for rank, kw in enumerate(include):
                if kw in lowered:
                    score += 100 - rank
            if score > 0:
                scored.append((score, -idx, tool))

        if not scored:
            return None
        scored.sort(reverse=True)
        return scored[0][2]

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.extra_env)
        workspace_keys = {
            "HWPX_AUTOMATION_WORKSPACE_ROOTS",
            "HWPX_MCP_WORKSPACE_ROOTS",
            "HWPX_MCP_SANDBOX_ROOT",
        }
        if not workspace_keys.intersection(self.extra_env):
            env["HWPX_AUTOMATION_WORKSPACE_ROOTS"] = json.dumps([str(self.cwd)])
            env.pop("HWPX_MCP_WORKSPACE_ROOTS", None)
            env.pop("HWPX_MCP_SANDBOX_ROOT", None)
        elif "HWPX_AUTOMATION_WORKSPACE_ROOTS" not in self.extra_env:
            # A test explicitly exercising a 6.x fallback must not inherit the
            # canonical value from the parent pytest process.
            env.pop("HWPX_AUTOMATION_WORKSPACE_ROOTS", None)
        env["PYTHONPATH"] = _pythonpath_with_local_sources(env.get("PYTHONPATH", ""))
        return env

    def start(self) -> None:
        if self._proc is not None:
            return

        argv = _split_server_cmd(self.config.server_cmd)
        self._proc = subprocess.Popen(
            argv,
            cwd=str(self.cwd),
            env=self._build_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._stdout_thread = threading.Thread(
            target=self._stdout_reader_loop, daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_reader_loop, daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _stdout_reader_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            self._stdout_tail.append(line)
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                with self._cv:
                    self.notifications.append(
                        {
                            "kind": "malformed_stdout_json",
                            "line": line,
                        }
                    )
                    self._cv.notify_all()
                continue
            with self._cv:
                if (
                    isinstance(message, dict)
                    and "id" in message
                    and ("result" in message or "error" in message)
                ):
                    self._responses[message["id"]] = message
                else:
                    self.notifications.append(
                        message if isinstance(message, dict) else {"raw": message}
                    )
                self._cv.notify_all()

    def _stderr_reader_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for raw_line in proc.stderr:
            self._stderr_tail.append(raw_line.rstrip("\n"))

    def _write_json_line(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise MCPHarnessError("cannot write request: MCP subprocess is not running")
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if "\n" in line or "\r" in line:
            raise AssertionError(
                f"embedded newline is forbidden in JSON-RPC payload: {line!r}"
            )
        try:
            proc.stdin.write(f"{line}\n")
            proc.stdin.flush()
        except BrokenPipeError as exc:
            raise MCPHarnessError(
                f"broken pipe while writing request\n{self.debug_report()}"
            ) from exc

    def build_request_payload(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._id_counter),
            "method": method,
            "params": params,
        }
        self._validate_request_payload(payload)
        return payload

    def send_payload(self, payload: dict[str, Any]) -> Any:
        self._validate_request_payload(payload)
        self._write_json_line(payload)
        return payload["id"]

    def wait_for_response(
        self, request_id: Any, *, timeout: float | None = None
    ) -> dict[str, Any]:
        proc = self._proc
        if proc is None:
            raise MCPHarnessError(
                "cannot wait for response: MCP subprocess is not running"
            )

        timeout_sec = timeout if timeout is not None else self.config.request_timeout
        deadline = time.monotonic() + timeout_sec

        with self._cv:
            while request_id not in self._responses:
                if proc.poll() is not None:
                    raise MCPHarnessError(
                        f"MCP subprocess exited before response for id={request_id!r} (rc={proc.returncode})\n"
                        f"{self.debug_report()}"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPTimeoutError(
                        f"timeout waiting {timeout_sec:.2f}s for response id={request_id!r}\n{self.debug_report()}"
                    )
                self._cv.wait(timeout=remaining)
            return self._responses.pop(request_id)

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        payload = self.build_request_payload(method, params or {})
        request_id = self.send_payload(payload)
        response = self.wait_for_response(request_id, timeout=timeout)
        self._assert_response_envelope(response, expected_id=request_id)
        return response

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if "\n" in line or "\r" in line:
            raise AssertionError(
                f"embedded newline is forbidden in JSON-RPC payload: {line!r}"
            )
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise MCPHarnessError(
                "cannot write notification: MCP subprocess is not running"
            )
        try:
            proc.stdin.write(f"{line}\n")
            proc.stdin.flush()
        except BrokenPipeError as exc:
            raise MCPHarnessError(
                f"broken pipe while writing notification\n{self.debug_report()}"
            ) from exc

    def initialize(self) -> dict[str, Any]:
        response = self.request("initialize", self.default_initialize_params())
        if "error" in response:
            self.assert_error_object(
                response["error"], require_data=self.config.require_error_data
            )
            pytest.fail(
                f"initialize returned JSON-RPC error: {response['error']}\n{self.debug_report()}"
            )
        result = response["result"]
        assert isinstance(result, dict), f"initialize result must be object: {result!r}"
        assert "protocolVersion" in result, (
            f"missing protocolVersion in initialize result: {result}"
        )
        assert "capabilities" in result, (
            f"missing capabilities in initialize result: {result}"
        )
        assert "serverInfo" in result, (
            f"missing serverInfo in initialize result: {result}"
        )
        if self.config.send_initialized_notification:
            self.notify("notifications/initialized", {})
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        response = self.request("tools/list", {})
        if "error" in response:
            self.assert_error_object(
                response["error"], require_data=self.config.require_error_data
            )
            pytest.fail(
                f"tools/list returned JSON-RPC error: {response['error']}\n{self.debug_report()}"
            )
        result = response["result"]
        assert isinstance(result, dict), f"tools/list result must be object: {result!r}"
        tools = result.get("tools")
        assert isinstance(tools, list), (
            f"tools/list result.tools must be a list: {result}"
        )
        normalized: list[dict[str, Any]] = []
        for tool in tools:
            if isinstance(tool, dict):
                normalized.append(tool)
        return normalized

    def call_tool_raw(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )

    def _assert_no_embedded_error(self, tool_name: str, result: dict[str, Any]) -> None:
        if not self.config.strict_error_mode:
            return
        if bool(result.get("isError")):
            raise AssertionError(
                f"tools/call({tool_name}) returned result.isError=true. "
                "Strict mode requires JSON-RPC error object for failures."
            )
        for text in self._iter_text_fragments(result):
            if EMBEDDED_ERROR_RE.search(text):
                raise AssertionError(
                    f"tools/call({tool_name}) returned success result containing exception-like text: {text!r}"
                )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self.call_tool_raw(name, arguments)
        if "error" in response:
            self.assert_error_object(
                response["error"], require_data=self.config.require_error_data
            )
            pytest.fail(
                f"tools/call({name}) returned JSON-RPC error: {response['error']}\n{self.debug_report()}"
            )
        result = response["result"]
        assert isinstance(result, dict), (
            f"tools/call({name}) result must be object: {result!r}"
        )
        self._assert_no_embedded_error(name, result)
        return result

    def assert_tool_error(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self.call_tool_raw(name, arguments)
        if "error" in response:
            self.assert_error_object(
                response["error"], require_data=self.config.require_error_data
            )
            return response["error"]

        result = response.get("result")
        assert isinstance(result, dict), (
            f"unexpected tools/call({name}) envelope: {response}"
        )
        if self.config.strict_error_mode:
            raise AssertionError(
                "tools/call failure did not return JSON-RPC error object in strict mode: "
                f"name={name}, result={result}"
            )
        assert bool(result.get("isError")) is True, (
            "lenient mode expects tools/call errors to set result.isError=true "
            f"when JSON-RPC error is absent: {result}"
        )
        return result

    def debug_report(self) -> str:
        proc = self._proc
        return_code = None if proc is None else proc.poll()
        stdout_tail = "\n".join(self._stdout_tail) or "<empty>"
        stderr_tail = "\n".join(self._stderr_tail) or "<empty>"
        notifications = (
            "\n".join(
                json.dumps(item, ensure_ascii=False)
                for item in list(self.notifications)[-20:]
            )
            or "<none>"
        )
        return (
            f"[mcp-debug] cwd={self.cwd}\n"
            f"[mcp-debug] returncode={return_code}\n"
            f"[mcp-debug] recent stdout lines:\n{stdout_tail}\n"
            f"[mcp-debug] recent stderr lines:\n{stderr_tail}\n"
            f"[mcp-debug] recent notifications:\n{notifications}"
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc is None:
            return

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=self.config.shutdown_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=self.config.shutdown_timeout)

        if self._stdout_thread is not None:
            self._stdout_thread.join(timeout=1.0)
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=1.0)

        for handle in (proc.stdin, proc.stdout, proc.stderr):
            if handle is not None:
                handle.close()

    def __enter__(self) -> "StdioMCPClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


@pytest.fixture(scope="session")
def mcp_test_config() -> MCPTestConfig:
    server_cwd_raw = os.getenv("MCP_SERVER_CWD")
    if server_cwd_raw:
        server_cwd = Path(server_cwd_raw).expanduser().resolve()
    else:
        server_cwd = _repo_root()

    return MCPTestConfig(
        server_cmd=_default_server_cmd(),
        server_cwd=server_cwd,
        request_timeout=_env_float("MCP_REQUEST_TIMEOUT_SEC", 8.0),
        shutdown_timeout=_env_float("MCP_SHUTDOWN_TIMEOUT_SEC", 3.0),
        debug_tail_lines=_env_int("MCP_DEBUG_TAIL_LINES", 80),
        strict_error_mode=_env_bool("MCP_STRICT_ERROR_MODE", True),
        require_error_data=_env_bool("MCP_REQUIRE_ERROR_DATA", True),
        send_initialized_notification=_env_bool("MCP_SEND_INITIALIZED", True),
        expect_path_sandbox=_env_bool("MCP_EXPECT_PATH_SANDBOX", True),
        sample_fixture=_find_default_sample_fixture(),
    )


@pytest.fixture(scope="session")
def sample_hwpx_fixture_path(mcp_test_config: MCPTestConfig) -> Path | None:
    return mcp_test_config.sample_fixture


@pytest.fixture()
def mcp_server_factory(mcp_test_config: MCPTestConfig):
    clients: list[StdioMCPClient] = []

    def _factory(
        *,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
        auto_initialize: bool = True,
    ) -> StdioMCPClient:
        client = StdioMCPClient(config=mcp_test_config, cwd=cwd, extra_env=extra_env)
        client.start()
        if auto_initialize:
            client.initialize()
        clients.append(client)
        return client

    yield _factory

    for client in reversed(clients):
        client.close()


@pytest.fixture()
def mcp_client(mcp_server_factory) -> StdioMCPClient:
    return mcp_server_factory()
