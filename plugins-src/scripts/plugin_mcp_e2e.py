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

try:
    import anyio
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ModuleNotFoundError:
    if os.environ.get("HWPX_E2E_BOOTSTRAPPED") == "1":
        raise
    env = dict(os.environ, HWPX_E2E_BOOTSTRAPPED="1")
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


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_TOOLS = {
    "start_workflow",
    "get_workflow",
    "continue_workflow",
    "approve_workflow_decision",
    "cancel_workflow",
    "resume_workflow",
}
RENDER_TOOLS = {"render_submit", "render_status", "render_cancel", "render_health"}


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


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    required = set(contract["skillRequiredTools"])
    with (
        tempfile.TemporaryDirectory(prefix="hwpx-plugin-e2e-") as tmp,
        tempfile.TemporaryDirectory(prefix="hwpx-plugin-e2e-denied-") as denied_tmp,
    ):
        sandbox = Path(tmp)
        denied_root = Path(denied_tmp)
        env = dict(os.environ)
        if args.mcp_config:
            config_payload = json.loads(args.mcp_config.read_text(encoding="utf-8"))
            servers = config_payload.get("mcpServers") or {}
            server_config = servers.get(args.mcp_server_name)
            if not isinstance(server_config, dict):
                raise RuntimeError(
                    f"MCP server {args.mcp_server_name!r} is absent from {args.mcp_config}"
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
                "HWPX_MCP_WORKSPACE_ROOTS": json.dumps([str(sandbox)]),
                "HWPX_SKILL_VERSION": args.skill_version,
                "HWPX_MCP_ADVANCED": "1" if args.advanced else "0",
                "HWPX_WORKFLOW_STORE": str(sandbox / "workflow.sqlite3"),
                "LOG_LEVEL": "ERROR",
            }
        )
        if args.mcp_repo:
            env["HWPX_MCP_SERVER_REPO"] = str(args.mcp_repo.resolve())
        if args.core_repo:
            env["PYTHON_HWPX_REPO"] = str(args.core_repo.resolve())
        if args.server_package:
            env["HWPX_MCP_SERVER_PACKAGE"] = args.server_package
            env["HWPX_MCP_DISABLE_LOCAL_EDITABLE"] = "1"
        if args.core_package:
            env["HWPX_PYTHON_HWPX_PACKAGE"] = args.core_package
        if args.expected_server_version:
            env["HWPX_MCP_SERVER_VERSION"] = args.expected_server_version
        if args.expected_core_version:
            env["HWPX_PYTHON_HWPX_VERSION"] = args.expected_core_version
        if args.server_runtime:
            env["HWPX_MCP_RUNTIME_ROOT"] = str(args.server_runtime)

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
                if health.get("toolSurface", {}).get("status") != "ok":
                    raise RuntimeError(f"plugin health is not ok: {health}")
                workspace = health.get("workspace") or {}
                observed_roots = [
                    Path(value).resolve() for value in workspace.get("roots", [])
                ]
                if workspace.get(
                    "source"
                ) != "HWPX_MCP_WORKSPACE_ROOTS" or observed_roots != [
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
                    payload = render_receipt.get("receipt") or {}
                    if (
                        payload.get("status") != "unavailable"
                        or payload.get("render_checked") is not False
                    ):
                        raise RuntimeError(
                            f"unconfigured render must be honestly unavailable: {render_receipt}"
                        )
                return {
                    "ok": True,
                    "toolCount": len(names),
                    "contractHash": contract["contractHash"],
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
                    "realRenderRequired": args.require_real_render,
                    "versions": health.get("capability", {}).get("versions"),
                    "workspace": workspace,
                    "outsideWorkspaceDenial": workspace_denials["outside"],
                    "workspaceDenials": workspace_denials,
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
    parser.add_argument("--mcp-server-name", default="hwpx-mcp-server")
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "references" / "tool-contract.generated.json",
    )
    parser.add_argument("--mcp-repo", type=Path)
    parser.add_argument("--core-repo", type=Path)
    parser.add_argument("--server-package")
    parser.add_argument("--core-package")
    parser.add_argument("--expected-server-version", default="3.0.0")
    parser.add_argument("--expected-core-version", default="3.0.0")
    parser.add_argument(
        "--server-runtime", "--server-venv", dest="server_runtime", type=Path
    )
    parser.add_argument("--skill-version", default="0.2.0")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-real-render", action="store_true")
    parser.add_argument("--advanced", action="store_true")
    args = parser.parse_args()
    if args.launcher is None and args.mcp_config is None:
        args.launcher = (
            ROOT / "plugins" / "codex" / "hwpx-plugin" / "scripts" / "hwpx-mcp-server"
        )
    if args.launcher is not None and not args.launcher.is_file():
        parser.error(f"launcher not found: {args.launcher}")
    if args.mcp_config is not None and not args.mcp_config.is_file():
        parser.error(f"MCP config not found: {args.mcp_config}")
    report = anyio.run(_run, args)
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
