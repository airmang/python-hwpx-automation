#!/usr/bin/env python3
"""Gate: run the Claude bundle's no-MCP path the way a claude.ai chat sandbox would.

The sandbox has a Python with lxml/pydantic/cryptography but no python-hwpx, no
reachable package index, no MCP server, and a read-only skill directory.  The
simulation copies the built Claude bundle, runs the start block of
``skills/hwpx/chat-engine.md`` (which imports the vendored engine from
``skills/hwpx/engine``) and then every W1~W5 case of the ChatGPT simulation
against Hancom-saved documents we did not author (python-hwpx
``tests/fixtures``).  It also checks discovery without ``SKILL_DIR``, a
lxml-only sandbox (automation unavailable, W1 still works) and a sandbox
without lxml (clear refusal, no traceback).

Usage::

    python3 scripts/claude_chat_sim.py --fixtures ../python-hwpx/tests/fixtures [--python python3.12] [--evidence out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import chatgpt_sandbox_sim as chatgpt  # noqa: E402  (shared cases and block helpers)

BUNDLE = ROOT / "plugins" / "claude" / "hwpx-plugin"
ALLOWED_IMPORTS = chatgpt.ALLOWED_IMPORTS | {"glob"}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def venv(python: str, path: Path, packages: list[str]) -> Path:
    run([python, "-m", "venv", str(path)], check=True)
    py = path / "bin" / "python"
    if packages:
        run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", *packages], check=True)
    return py


def check_imports(label: str, code: str) -> list[str]:
    saved = chatgpt.ALLOWED_IMPORTS
    chatgpt.ALLOWED_IMPORTS = ALLOWED_IMPORTS
    try:
        return chatgpt.check_imports(label, code)
    finally:
        chatgpt.ALLOWED_IMPORTS = saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", required=True, type=Path, help="python-hwpx tests/fixtures directory")
    parser.add_argument("--python", default="python3.12")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="hwpx-claude-chat-sim-"))
    evidence: dict = {"bundle": str(BUNDLE.relative_to(ROOT)), "python": args.python, "cases": [], "problems": []}
    try:
        py = venv(args.python, work / "venv", chatgpt.PREINSTALLED)
        evidence["sandboxPython"] = run([str(py), "-c", "import sys; print(sys.version.split()[0])"]).stdout.strip()

        # A plugin copy under a fake home, as a host would cache it; read-only like a mounted skill.
        home = work / "home"
        plugin = home / ".claude" / "plugins" / "cache" / "hwpx" / "hwpx-plugin" / "0"
        shutil.copytree(BUNDLE, plugin, ignore=shutil.ignore_patterns("__pycache__"))
        skill = plugin / "skills" / "hwpx"
        chatgpt.read_only(plugin)
        env = {**os.environ, "HOME": str(home), "PIP_INDEX_URL": chatgpt.BLOCKED_INDEX, "PIP_TIMEOUT": "3",
               "PIP_RETRIES": "0", "PYTHONNOUSERSITE": "1"}
        for key in ("PYTHONPATH", "VIRTUAL_ENV", "HWPX_AUTOMATION_WORKSPACE_ROOTS"):
            env.pop(key, None)

        guide = (skill / "chat-engine.md").read_text(encoding="utf-8")
        start = chatgpt.python_blocks(guide)[0]
        workflows = chatgpt.workflow_blocks(guide)
        evidence["blocks"] = sorted(workflows)
        if sorted(workflows) != ["W1", "W2", "W3", "W4", "W5"]:
            evidence["problems"].append(f"chat-engine.md workflow blocks {sorted(workflows)}")
        for label, code in [("chat-engine.md start", start), *workflows.items()]:
            evidence["problems"].extend(check_imports(label, code))
        with_dir = start.replace("SKILL_DIR = None", f"SKILL_DIR = {json.dumps(str(skill))}", 1)

        data = work / "mnt-user-data"
        for case_id, block, fixture, overrides, expected, reason in chatgpt.CASES:
            case_dir = data / case_id
            case_dir.mkdir(parents=True)
            params = dict(overrides)
            if fixture:
                src = case_dir / Path(fixture).name
                shutil.copyfile(args.fixtures / fixture, src)
                params["src"] = str(src)
            out_name = "output.hwp" if fixture and fixture.endswith(".hwp") else "output.hwpx"
            params["out"] = str(case_dir / out_name)
            code = with_dir + "\n" + chatgpt.inject_overrides(workflows[block], params)
            proc = run([str(py), "-c", code], cwd=case_dir, env=env, timeout=300)
            output_exists = (case_dir / out_name).exists()
            leftovers = [p.name for p in case_dir.glob("*.checking.*")]
            writes = block != "W1"
            if expected == "ok":
                passed = proc.returncode == 0 and output_exists == writes
            else:
                passed = (proc.returncode != 0 and not output_exists and "Traceback" not in proc.stderr
                          and reason in proc.stderr)
            passed = passed and not leftovers and "준비 완료" in proc.stdout
            evidence["cases"].append({"case": case_id, "block": block, "fixture": fixture, "expected": expected,
                                      "passed": passed, "returncode": proc.returncode,
                                      "stdoutTail": proc.stdout[-600:], "stderrTail": proc.stderr[-600:]})
            print(f"[{'PASS' if passed else 'FAIL'}] {case_id}")

        # Discovery: no SKILL_DIR, the engine must be found under the host's plugin cache.
        case_dir = data / "discover"
        case_dir.mkdir()
        proc = run([str(py), "-c", start + "\nprint('ENGINE_AT', ENGINE)"], cwd=case_dir, env=env, timeout=300)
        discovered = proc.returncode == 0 and f"ENGINE_AT {skill / 'engine'}" in proc.stdout
        evidence["discovery"] = {"passed": discovered, "stdoutTail": proc.stdout[-400:], "stderrTail": proc.stderr[-400:]}
        print(f"[{'PASS' if discovered else 'FAIL'}] discovery without SKILL_DIR")

        # A different python-hwpx already installed in the sandbox must not shadow the vendored engine.
        shadow_py = venv(args.python, work / "venv-shadow", [*chatgpt.PREINSTALLED, "python-hwpx==6.5.0"])
        proc = run([str(shadow_py), "-c", with_dir + "\nprint('LOADED', hwpx.__version__, hwpx.__file__)"],
                   cwd=case_dir, env=env, timeout=300)
        vendored = json.loads((skill / "engine" / "VENDOR.json").read_text(encoding="utf-8"))
        core_version = next(w["version"] for w in vendored["wheels"] if w["distribution"] == "python-hwpx")
        unshadowed = proc.returncode == 0 and f"LOADED {core_version} {skill / 'engine'}" in proc.stdout
        evidence["preinstalledOtherVersion"] = {"passed": unshadowed, "stdoutTail": proc.stdout[-400:],
                                                "stderrTail": proc.stderr[-400:]}
        print(f"[{'PASS' if unshadowed else 'FAIL'}] an installed python-hwpx 6.5.0 does not shadow the engine")

        # lxml-only sandbox: core works, automation reported unavailable.
        core_py = venv(args.python, work / "venv-lxml", ["lxml"])
        case_dir = data / "lxml-only-W1"
        case_dir.mkdir()
        src = case_dir / Path(chatgpt.DISASTER).name
        shutil.copyfile(args.fixtures / chatgpt.DISASTER, src)
        proc = run([str(core_py), "-c", with_dir + "\n" + chatgpt.inject_overrides(workflows["W1"], {"src": str(src)})],
                   cwd=case_dir, env=env, timeout=300)
        lxml_only = proc.returncode == 0 and "새 문서 만들기(W5) 불가" in proc.stdout
        evidence["lxmlOnly"] = {"passed": lxml_only, "stdoutTail": proc.stdout[-400:], "stderrTail": proc.stderr[-400:]}
        print(f"[{'PASS' if lxml_only else 'FAIL'}] lxml-only sandbox: W1 works, W5 reported unavailable")

        # No lxml at all: a clear refusal, never a traceback or an install attempt.
        bare_py = venv(args.python, work / "venv-bare", [])
        proc = run([str(bare_py), "-c", with_dir], cwd=case_dir, env=env, timeout=300)
        bare = proc.returncode != 0 and "lxml" in proc.stderr and "Traceback" not in proc.stderr
        evidence["noLxml"] = {"passed": bare, "stderrTail": proc.stderr[-400:]}
        print(f"[{'PASS' if bare else 'FAIL'}] sandbox without lxml refuses clearly")

        for name, ok in (("discovery", discovered), ("shadowing", unshadowed), ("lxml-only", lxml_only), ("no-lxml", bare)):
            if not ok:
                evidence["problems"].append(f"{name} check failed")
        written = [p for p in skill.rglob("*") if p.name == "__pycache__"]
        if written:
            evidence["problems"].append(f"the run wrote into the skill directory: {written[:3]}")
    finally:
        failed = [c["case"] for c in evidence["cases"] if not c["passed"]]
        evidence["ok"] = not failed and not evidence["problems"] and len(evidence["cases"]) == len(chatgpt.CASES)
        if args.evidence:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for problem in evidence["problems"]:
            print(f"[PROBLEM] {problem}")
        print(f"{'OK' if evidence['ok'] else 'FAILED'}: {len(evidence['cases']) - len(failed)}/{len(chatgpt.CASES)} cases")
        if args.keep:
            print(f"sandbox kept at {work}")
        else:
            for path in [work, *work.rglob("*")]:
                try:
                    path.chmod(path.stat().st_mode | stat.S_IWUSR)
                except OSError:
                    pass
            shutil.rmtree(work, ignore_errors=True)
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
