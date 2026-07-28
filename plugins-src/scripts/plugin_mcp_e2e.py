#!/usr/bin/env python3
"""Protocol-level E2E through the generated Codex plugin launcher."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MCP_CONFIG_KEY = "hwpx"
LEGACY_MCP_CONFIG_KEY = "hwpx-mcp-server"
_SOURCE_AFFECTING_ENV = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")
anyio: Any = None
ClientSession: Any = None
StdioServerParameters: Any = None
stdio_client: Any = None
WORKFLOW_TOOLS = {
    "start_workflow",
    "get_workflow",
    "continue_workflow",
    "approve_workflow_decision",
    "cancel_workflow",
    "resume_workflow",
}
RENDER_TOOLS = {"render_submit", "render_status", "render_cancel", "render_health"}


def _sanitized_environment(
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Drop ambient Python source selectors from installed/E2E execution."""

    env = dict(os.environ if base is None else base)
    for name in _SOURCE_AFFECTING_ENV:
        env.pop(name, None)
    return env


def _ensure_mcp_dependencies() -> None:
    global anyio, ClientSession, StdioServerParameters, stdio_client
    try:
        import anyio as anyio_module
        from mcp import ClientSession as client_session
        from mcp.client.stdio import StdioServerParameters as server_parameters
        from mcp.client.stdio import stdio_client as stdio_client_function
    except ModuleNotFoundError:
        if os.environ.get("HWPX_E2E_BOOTSTRAPPED") == "1":
            raise
        env = _sanitized_environment()
        env["HWPX_E2E_BOOTSTRAPPED"] = "1"
        raise SystemExit(
            subprocess.run(
                [
                    "uv",
                    "run",
                    "--no-project",
                    "--with",
                    "mcp>=1.2",
                    "--with",
                    "anyio>=4",
                    "python",
                    __file__,
                    *sys.argv[1:],
                ],
                env=env,
                check=False,
            ).returncode
        )
    anyio = anyio_module
    ClientSession = client_session
    StdioServerParameters = server_parameters
    stdio_client = stdio_client_function


def _select_mcp_server(
    config_payload: dict[str, Any],
    key: str,
    *,
    source: Path,
) -> dict[str, Any]:
    """Select exactly the requested host-local alias.

    The default is the new ``hwpx`` key. Passing ``hwpx-mcp-server`` remains an
    explicit 6.x compatibility override, never a silent fallback.
    """

    servers = config_payload.get("mcpServers") or {}
    server_config = servers.get(key) if isinstance(servers, dict) else None
    if not isinstance(server_config, dict):
        raise RuntimeError(f"MCP server {key!r} is absent from {source}")
    return server_config


def _structured(result: Any) -> dict[str, Any]:
    if bool(getattr(result, "isError", False)):
        raise RuntimeError(f"MCP tool returned isError: {result}")
    payload = getattr(result, "structuredContent", None)
    if isinstance(payload, dict):
        return payload
    for content in getattr(result, "content", ()):
        text = getattr(content, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _mcp_error_code(exc: BaseException) -> str | None:
    error = getattr(exc, "error", None)
    data = getattr(error, "data", None)
    if isinstance(data, dict):
        value = data.get("errorCode")
        return value if isinstance(value, str) else None
    return None


def _probe_installed_runtime(args: argparse.Namespace) -> dict[str, Any]:
    if args.server_runtime is None:
        return {"mode": "editable-or-direct", "originChecked": False}
    env_root = args.server_runtime / "envs"
    candidates = sorted(env_root.glob("*/bin/python")) if env_root.is_dir() else []
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one installed launcher runtime, found {candidates}"
        )
    code = r"""
import importlib.util
import json
from importlib.metadata import version
from pathlib import Path

import hwpx
import hwpx_automation

print(json.dumps({
    "versions": {
        "python-hwpx": version("python-hwpx"),
        "python-hwpx-automation": version("python-hwpx-automation"),
    },
    "origins": {
        "hwpx": str(Path(hwpx.__file__).resolve()),
        "hwpx_automation": str(Path(hwpx_automation.__file__).resolve()),
    },
    "capabilities": {
        "mcp": importlib.util.find_spec("mcp") is not None,
        "pymupdf": importlib.util.find_spec("fitz") is not None,
        "pillow": importlib.util.find_spec("PIL") is not None,
        "numpy": importlib.util.find_spec("numpy") is not None,
        "previewMath": importlib.util.find_spec("latex2mathml") is not None,
    },
}))
"""
    completed = subprocess.run(
        [str(candidates[0]), "-c", code],
        env=_sanitized_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    expected = {
        "python-hwpx": args.expected_core_version,
        "python-hwpx-automation": args.expected_server_version,
    }
    if payload.get("versions") != expected:
        raise RuntimeError(
            f"installed runtime version mismatch: {payload.get('versions')} != {expected}"
        )
    excluded = [
        path.resolve()
        for path in (args.core_repo, args.automation_repo)
        if path is not None
    ]
    for module, raw_origin in payload.get("origins", {}).items():
        origin = Path(raw_origin).resolve()
        if "site-packages" not in origin.as_posix():
            raise RuntimeError(f"{module} did not load from site-packages: {origin}")
        if any(origin == root or root in origin.parents for root in excluded):
            raise RuntimeError(f"{module} leaked from source checkout: {origin}")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict) or not all(capabilities.values()):
        raise RuntimeError(f"installed runtime extras are incomplete: {capabilities}")
    payload.update({"mode": "installed-wheel", "originChecked": True})
    return payload


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    active_contract_names = {
        tool["name"]
        for tool in contract["tools"]
        if args.advanced or tool["profile"] == "default"
    }
    # Skill-required is a cross-profile inventory. Startup health applies it
    # only to the selected profile, matching the server's own active-required
    # intersection (for example advanced-only ``score_form_fill``).
    required = set(contract["skillRequiredTools"]) & active_contract_names
    with (
        tempfile.TemporaryDirectory(prefix="hwpx-plugin-e2e-") as tmp,
        tempfile.TemporaryDirectory(prefix="hwpx-plugin-e2e-denied-") as denied_tmp,
    ):
        sandbox = Path(tmp)
        denied_root = Path(denied_tmp)
        env = _sanitized_environment()
        if args.mcp_config:
            config_payload = json.loads(args.mcp_config.read_text(encoding="utf-8"))
            server_config = _select_mcp_server(
                config_payload,
                args.mcp_server_name,
                source=args.mcp_config,
            )
            command = server_config.get("command")
            command_args = server_config.get("args") or []
            config_env = server_config.get("env") or {}
            if not isinstance(command, str) or not command:
                raise RuntimeError("installed MCP config has no executable command")
            if not isinstance(command_args, list) or not all(
                isinstance(value, str) for value in command_args
            ):
                raise RuntimeError("installed MCP config args must be strings")
            if not isinstance(config_env, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in config_env.items()
            ):
                raise RuntimeError("installed MCP config env must contain string pairs")
            substitutions = {
                "${CLAUDE_PLUGIN_ROOT}": str(args.mcp_config.resolve().parent),
            }

            def expand_plugin_root(value: str) -> str:
                for token, replacement in substitutions.items():
                    value = value.replace(token, replacement)
                return value

            command = expand_plugin_root(command)
            command_args = [expand_plugin_root(value) for value in command_args]
            config_env = {
                key: expand_plugin_root(value) for key, value in config_env.items()
            }
            env.update(config_env)
            launch_surface = str(args.mcp_config)
        else:
            command = str(args.launcher)
            command_args = []
            launch_surface = str(args.launcher)
        env.update(
            {
                "HWPX_AUTOMATION_WORKSPACE_ROOTS": json.dumps([str(sandbox)]),
                "HWPX_SKILL_VERSION": args.skill_version,
                "HWPX_AUTOMATION_ADVANCED": "1" if args.advanced else "0",
                "HWPX_AUTOMATION_WORKFLOW_STORE": str(
                    sandbox / "workflow.sqlite3"
                ),
                "LOG_LEVEL": "ERROR",
            }
        )
        if args.automation_repo:
            env["HWPX_AUTOMATION_REPO"] = str(args.automation_repo.resolve())
        if args.core_repo:
            env["PYTHON_HWPX_REPO"] = str(args.core_repo.resolve())
        if args.server_package:
            env["HWPX_AUTOMATION_PACKAGE"] = args.server_package
            env["HWPX_AUTOMATION_DISABLE_LOCAL_EDITABLE"] = "1"
        if args.core_package:
            env["HWPX_PYTHON_HWPX_PACKAGE"] = args.core_package
        if args.expected_server_version:
            env["HWPX_AUTOMATION_VERSION"] = args.expected_server_version
        if args.expected_core_version:
            env["HWPX_PYTHON_HWPX_VERSION"] = args.expected_core_version
        if args.server_runtime:
            env["HWPX_AUTOMATION_RUNTIME_ROOT"] = str(args.server_runtime)

        params = StdioServerParameters(
            command=command,
            args=command_args,
            env=env,
            cwd=sandbox,
        )
        async with stdio_client(params, errlog=sys.stderr) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                if names != active_contract_names:
                    missing_names = sorted(active_contract_names - names)
                    unexpected_names = sorted(names - active_contract_names)
                    raise RuntimeError(
                        "installed plugin contract mismatch: "
                        f"missing={missing_names}, unexpected={unexpected_names}"
                    )
                missing = sorted(required - names)
                if missing:
                    raise RuntimeError(
                        f"installed plugin missing skill-required tools: {missing}"
                    )
                count_key = "advancedToolCount" if args.advanced else "defaultToolCount"
                if len(names) != int(contract[count_key]):
                    raise RuntimeError(
                        f"installed plugin tool count {len(names)} != contract {contract[count_key]}"
                    )
                missing_workflow = sorted(WORKFLOW_TOOLS - names)
                if missing_workflow:
                    raise RuntimeError(
                        f"installed plugin missing workflow tools: {missing_workflow}"
                    )
                missing_render = sorted(RENDER_TOOLS - names)
                if missing_render:
                    raise RuntimeError(
                        f"installed plugin missing async render tools: {missing_render}"
                    )

                document = sandbox / "unfamiliar-form.hwpx"
                output = sandbox / "unfamiliar-form-filled.hwpx"
                timeout = timedelta(seconds=90)
                _structured(
                    await session.call_tool(
                        "create_document",
                        {"filename": str(document)},
                        read_timeout_seconds=timeout,
                    )
                )

                async def expect_workspace_denial(
                    requested: str,
                    created_path: Path,
                    *,
                    label: str,
                ) -> str:
                    try:
                        denied_result = await session.call_tool(
                            "create_document",
                            {"filename": requested},
                            read_timeout_seconds=timeout,
                        )
                    except Exception as exc:
                        denial_code = _mcp_error_code(exc)
                        if created_path.name in str(exc):
                            raise RuntimeError(
                                f"{label} denial leaked the requested filename"
                            ) from exc
                    else:
                        denial_code = (
                            "TOOL_EXECUTION_FAILED"
                            if bool(getattr(denied_result, "isError", False))
                            else None
                        )
                    if denial_code != "WORKSPACE_OUTSIDE_ROOT":
                        raise RuntimeError(
                            f"{label} write was not denied correctly: {denial_code}"
                        )
                    if created_path.exists():
                        raise RuntimeError(f"{label} write created a file")
                    return denial_code

                outside_path = denied_root / "outside-denied.hwpx"
                traversal_path = denied_root / "traversal-denied.hwpx"
                symlink_path = denied_root / "symlink-denied.hwpx"
                link = sandbox / "escape-link"
                link.symlink_to(denied_root, target_is_directory=True)
                workspace_denials = {
                    "outside": await expect_workspace_denial(
                        str(outside_path), outside_path, label="outside-workspace"
                    ),
                    "traversal": await expect_workspace_denial(
                        f"../{denied_root.name}/{traversal_path.name}",
                        traversal_path,
                        label="traversal",
                    ),
                    "symlink": await expect_workspace_denial(
                        f"{link.name}/{symlink_path.name}",
                        symlink_path,
                        label="symlink-escape",
                    ),
                }
                _structured(
                    await session.call_tool(
                        "add_table",
                        {
                            "filename": str(document),
                            "rows": 2,
                            "cols": 2,
                            "data": [["처음 보는 양식", ""], ["성명", "[작성]"]],
                        },
                        read_timeout_seconds=timeout,
                    )
                )
                raw_phone = "010-1234-5678"
                raw_email = "hong@example.com"
                _structured(
                    await session.call_tool(
                        "add_paragraph",
                        {
                            "filename": str(document),
                            "text": f"연락처 {raw_phone} / {raw_email}",
                        },
                        read_timeout_seconds=timeout,
                    )
                )
                pii_read = _structured(
                    await session.call_tool(
                        "get_document_text",
                        {"filename": str(document)},
                        read_timeout_seconds=timeout,
                    )
                )
                masked_text = str(pii_read.get("text", ""))
                if (
                    raw_phone in masked_text
                    or raw_email in masked_text
                    or "010-****-****" not in masked_text
                ):
                    raise RuntimeError(
                        f"default installed PII masking failed: {pii_read}"
                    )
                pii_masking = {
                    "ok": True,
                    "rawPhoneAbsent": raw_phone not in masked_text,
                    "rawEmailAbsent": raw_email not in masked_text,
                    "maskedPhonePresent": "010-****-****" in masked_text,
                }
                receipt = _structured(
                    await session.call_tool(
                        "start_workflow",
                        {
                            "family": "unknown_form_fill",
                            "idempotency_key": "plugin-e2e-unknown-form",
                            "source_path": str(document),
                            "output_path": str(output),
                            "parameters": {
                                "operationKind": "table",
                                "operations": [
                                    {
                                        "op": "fill_cell",
                                        "table_index": 0,
                                        "row": 1,
                                        "col": 1,
                                        "text": "홍길동",
                                    }
                                ],
                            },
                        },
                        read_timeout_seconds=timeout,
                    )
                )
                workflow_id = receipt.get("workflowId")
                if not isinstance(workflow_id, str):
                    raise RuntimeError(f"workflow did not start: {receipt}")
                states = [receipt.get("state")]
                for _ in range(12):
                    if receipt.get("state") == "decision":
                        receipt = _structured(
                            await session.call_tool(
                                "approve_workflow_decision",
                                {"workflow_id": workflow_id, "approved": True},
                                read_timeout_seconds=timeout,
                            )
                        )
                    elif receipt.get("terminal") is True:
                        break
                    else:
                        receipt = _structured(
                            await session.call_tool(
                                "continue_workflow",
                                {"workflow_id": workflow_id},
                                read_timeout_seconds=timeout,
                            )
                        )
                    states.append(receipt.get("state"))
                receipt = _structured(
                    await session.call_tool(
                        "get_workflow",
                        {"workflow_id": workflow_id},
                        read_timeout_seconds=timeout,
                    )
                )
                if receipt.get("state") not in {"completed", "needs_review"}:
                    raise RuntimeError(
                        f"workflow did not reach an honest terminal state: {receipt}"
                    )
                if (
                    receipt.get("state") == "needs_review"
                    and receipt.get("stopReason") != "VERIFICATION_EVIDENCE_REQUIRED"
                ):
                    raise RuntimeError(f"unexpected needs_review reason: {receipt}")
                if not output.is_file() or output.resolve() == document.resolve():
                    raise RuntimeError(
                        f"workflow did not create a distinct output copy: {receipt}"
                    )
                artifacts = receipt.get("artifacts") or []
                output_artifact = next(
                    (item for item in artifacts if item.get("role") == "output"), None
                )
                if not output_artifact or not output_artifact.get("contentHash"):
                    raise RuntimeError(
                        f"output artifact receipt is incomplete: {receipt}"
                    )
                open_safety = receipt.get("openSafety") or {}
                if (
                    receipt.get("state") == "completed"
                    and open_safety.get("ok") is not True
                ):
                    raise RuntimeError(
                        f"completed workflow lacks openSafety: {receipt}"
                    )
                if open_safety.get("renderChecked") is not False:
                    raise RuntimeError(
                        f"pre-render receipt must remain renderChecked=false: {receipt}"
                    )
                health = _structured(
                    await session.call_tool(
                        "mcp_server_health", {}, read_timeout_seconds=timeout
                    )
                )
                tool_surface = health.get("toolSurface", {})
                if tool_surface.get("status") != "ok":
                    raise RuntimeError(f"plugin health is not ok: {health}")
                runtime_contract_hash = tool_surface.get("contractHash")
                if runtime_contract_hash != contract["contractHash"]:
                    raise RuntimeError(
                        "installed runtime contract hash mismatch: "
                        f"{runtime_contract_hash} != {contract['contractHash']}"
                    )
                expected_versions = {
                    "version": args.expected_server_version,
                    "pythonHwpxVersion": args.expected_core_version,
                    "skillBundleVersion": args.skill_version,
                }
                observed_versions = {
                    key: health.get(key) for key in expected_versions
                }
                if observed_versions != expected_versions:
                    raise RuntimeError(
                        "installed health version mismatch: "
                        f"{observed_versions} != {expected_versions}"
                    )
                server_info = health.get("serverInfo") or {}
                if (
                    health.get("server") != "python-hwpx-automation"
                    or server_info.get("name") != "python-hwpx-automation"
                    or server_info.get("canonicalMcpConsole")
                    != "hwpx-automation-mcp"
                    or server_info.get("hostConfigKeyRole") != "host-local-alias"
                ):
                    raise RuntimeError(
                        f"installed product/MCP identity mismatch: {health}"
                    )
                workspace = health.get("workspace") or {}
                observed_roots = [
                    Path(value).resolve() for value in workspace.get("roots", [])
                ]
                if workspace.get(
                    "source"
                ) != "HWPX_AUTOMATION_WORKSPACE_ROOTS" or observed_roots != [
                    sandbox.resolve()
                ]:
                    raise RuntimeError(
                        f"installed workspace policy is not active: {workspace}"
                    )
                render_health = _structured(
                    await session.call_tool(
                        "render_health", {}, read_timeout_seconds=timeout
                    )
                )
                render_error_code: str | None = None
                try:
                    render_receipt = _structured(
                        await session.call_tool(
                            "render_submit",
                            {
                                "filename": str(output),
                                "idempotency_key": "plugin-e2e-render",
                            },
                            read_timeout_seconds=timeout,
                        )
                    )
                except Exception as exc:
                    render_error_code = _mcp_error_code(exc)
                    if (
                        args.require_real_render
                        or render_error_code != "TOOL_EXECUTION_FAILED"
                        or render_health.get("degradedReason") != "NOT_CONFIGURED"
                    ):
                        raise
                    # The strict protocol adapter promotes an ``ok: false``
                    # unconfigured-render receipt to a typed JSON-RPC error.
                    # Treat that as the honest no-backend outcome only when
                    # health independently confirms NOT_CONFIGURED.
                    render_receipt = {}
                if args.require_real_render:
                    receipt_payload = render_receipt.get("receipt") or {}
                    job_id = receipt_payload.get("job_id")
                    if not isinstance(job_id, str):
                        raise RuntimeError(
                            f"real render did not return a job id: {render_receipt}"
                        )
                    render_dir = sandbox / "real-hancom-render"
                    for _ in range(120):
                        render_receipt = _structured(
                            await session.call_tool(
                                "render_status",
                                {"job_id": job_id, "output_dir": str(render_dir)},
                                read_timeout_seconds=timeout,
                            )
                        )
                        status = (render_receipt.get("receipt") or {}).get("status")
                        if status not in {"queued", "running"}:
                            break
                        await anyio.sleep(1)
                    payload = render_receipt.get("receipt") or {}
                    if (
                        payload.get("status") != "succeeded"
                        or payload.get("render_checked") is not True
                    ):
                        raise RuntimeError(
                            f"installed real-Hancom render failed: {render_receipt}"
                        )
                    saved = render_receipt.get("savedArtifacts") or []
                    if not saved or not all(
                        Path(item["path"]).is_file() for item in saved
                    ):
                        raise RuntimeError(
                            f"installed render artifacts missing: {render_receipt}"
                        )
                else:
                    if render_error_code is None:
                        payload = render_receipt.get("receipt") or {}
                        if (
                            payload.get("status") != "unavailable"
                            or payload.get("render_checked") is not False
                        ):
                            raise RuntimeError(
                                "unconfigured render must be honestly unavailable: "
                                f"{render_receipt}"
                            )
                return {
                    "ok": True,
                    "toolCount": len(names),
                    "contractHash": runtime_contract_hash,
                    "requiredTools": sorted(required),
                    "workflowTools": sorted(WORKFLOW_TOOLS),
                    "renderTools": sorted(RENDER_TOOLS),
                    "workflowStates": states,
                    "workflowTerminalState": receipt.get("state"),
                    "workflowStopReason": receipt.get("stopReason"),
                    "outputCopy": str(output),
                    "openSafety": open_safety,
                    "renderHealth": render_health,
                    "renderReceipt": render_receipt,
                    "renderErrorCode": render_error_code,
                    "realRenderRequired": args.require_real_render,
                    "versions": observed_versions,
                    "serverInfo": server_info,
                    "identity": {
                        "fastMcpName": health.get("server"),
                        "canonicalMcpConsole": server_info.get(
                            "canonicalMcpConsole"
                        ),
                        "hostConfigKey": (
                            args.mcp_server_name if args.mcp_config else None
                        ),
                        "hostConfigKeyRole": server_info.get(
                            "hostConfigKeyRole"
                        ),
                    },
                    "workspace": workspace,
                    "outsideWorkspaceDenial": workspace_denials["outside"],
                    "workspaceDenials": workspace_denials,
                    "piiMasking": pii_masking,
                    "launchSurface": launch_surface,
                    "advanced": args.advanced,
                }


def main() -> int:
    parser = argparse.ArgumentParser()
    launch_group = parser.add_mutually_exclusive_group()
    launch_group.add_argument(
        "--launcher",
        type=Path,
    )
    launch_group.add_argument("--mcp-config", type=Path)
    parser.add_argument(
        "--mcp-server-name",
        default=DEFAULT_MCP_CONFIG_KEY,
        help=(
            "host-local config key (default: hwpx); pass hwpx-mcp-server only "
            "to exercise an existing 6.x config"
        ),
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "references" / "tool-contract.generated.json",
    )
    parser.add_argument(
        "--automation-repo",
        "--mcp-repo",
        dest="automation_repo",
        type=Path,
    )
    parser.add_argument("--core-repo", type=Path)
    parser.add_argument("--server-package")
    parser.add_argument("--core-package")
    parser.add_argument("--expected-server-version", default="6.0.3")
    parser.add_argument("--expected-core-version", default="5.0.1")
    parser.add_argument(
        "--server-runtime", "--server-venv", dest="server_runtime", type=Path
    )
    parser.add_argument("--skill-version", default="1.0.0")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-real-render", action="store_true")
    parser.add_argument("--advanced", action="store_true")
    args = parser.parse_args()
    if args.launcher is None and args.mcp_config is None:
        args.launcher = (
            ROOT
            / "plugins"
            / "codex"
            / "hwpx-plugin"
            / "scripts"
            / "hwpx-automation-mcp"
        )
    if args.launcher is not None and not args.launcher.is_file():
        parser.error(f"launcher not found: {args.launcher}")
    if args.mcp_config is not None and not args.mcp_config.is_file():
        parser.error(f"MCP config not found: {args.mcp_config}")
    _ensure_mcp_dependencies()
    report = anyio.run(_run, args)
    report["installedRuntime"] = _probe_installed_runtime(args)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
