#!/usr/bin/env python3
"""G2/G3 gate: run the built ``hwpx-web`` skill the way the ChatGPT sandbox does.

The simulation reproduces what the owner observed in ChatGPT web Chat
(2026-09-29): Python 3.12, lxml/pydantic/cryptography preinstalled, no
python-hwpx, a read-only skill directory, and no reachable package index.
It then executes every code block of ``references/web-workflows.md`` against
Hancom-saved documents we did not author (python-hwpx ``tests/fixtures``:
the third-party hwpxlib corpus and public-sector samples).

Usage::

    python3 scripts/chatgpt_sandbox_sim.py --zip dist/hwpx-web-1.0.0.zip \\
        --fixtures ../python-hwpx/tests/fixtures --evidence out.json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PREINSTALLED = ["lxml", "pydantic", "cryptography"]
BLOCKED_INDEX = "http://127.0.0.1:9/simple"
ALLOWED_IMPORTS = {"hwpx", "hwpx_automation", "importlib", "json", "os", "re", "site", "subprocess", "sys"}

# (case id, block id, input fixture or None, P overrides, expected outcome, reason substring for refusals)
DISASTER = "hwpxlib_corpus/error__20250808__2015년_12월_재난안전종합상황_분석_및_전망.hwpx"
PROJECT = "hwpxlib_corpus/error__20250523__프로젝트 계획서.hwpx"
CASES = [
    ("W1-read-disaster-report", "W1", DISASTER, {}, "ok", ""),
    ("W2-replace-everywhere", "W2", DISASTER, {"replacements": {"재난안전": "재난·안전"}}, "ok", ""),
    ("W2-refuse-missing-text", "W2", DISASTER, {"replacements": {"문서에없는문구": "x"}}, "refuse", "찾지 못한 문구"),
    ("W2-refuse-chained", "W2", DISASTER,
     {"replacements": {"2015년 12월": "임시", "임시": "2016년 1월"}}, "refuse", "순서에 따라"),
    ("W3-fill-empty-right-cell", "W3", "m3_gongmun_gold/mfds_admin_notice.hwpx", {"values": {"성명": "홍길동"}}, "ok", ""),
    ("W3-refuse-duplicate-label", "W3", "hwpxlib_corpus/error__20230728__test.hwpx",
     {"values": {"성명": "홍길동"}}, "refuse", "같은 라벨이"),
    ("W3-refuse-neighbour-label", "W3", "hwpxlib_corpus/error__20251107__test.hwpx",
     {"values": {"학교명": "광교고등학교"}}, "refuse", "빈 칸이 하나로"),
    ("W3-overwrite-with-direction", "W3", "hwpxlib_corpus/error__20251107__test.hwpx",
     {"values": {"학교명": "광교고등학교"}, "directions": {"학교명": "down"}}, "ok", ""),
    ("W3-refuse-clickhere-row", "W3", PROJECT,
     {"values": {"프로젝트 배경": "교실 수업에서 생성형 AI 활용이 늘고 있다."}}, "refuse", "누름틀이 있다"),
    ("W4-fill-clickhere", "W4", PROJECT,
     {"values": {"_AI_프로젝트계획서프로젝트배경": "교실 수업에서 생성형 AI 활용이 늘고 있다."}}, "ok", ""),
    ("W4-refuse-unknown-field", "W4", PROJECT, {"values": {"없는누름틀": "x"}}, "refuse", "없는 이름"),
    ("W5-create-from-plan", "W5", None, {}, "ok", ""),
    ("W5-refuse-bad-plan", "W5", None,
     {"plan": {"schema": "hwpx.document_plan.v1", "blocks": [{"type": "heading", "text": "제목"}]}}, "refuse", "문서 계획 오류"),
]


def python_blocks(markdown: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", markdown, flags=re.DOTALL)


def workflow_blocks(markdown: str) -> dict[str, str]:
    blocks = {}
    for code in python_blocks(markdown):
        match = re.match(r"# (W\d) ", code)
        if match:
            blocks[match.group(1)] = code
    return blocks


def check_imports(label: str, code: str) -> list[str]:
    """Code blocks may import only the public engine surface."""
    problems = []
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
            if node.module == "hwpx_automation" and any(a.name != "api" for a in node.names):
                problems.append(f"{label}: hwpx_automation imports other than api")
        else:
            continue
        for name in names:
            if name.split(".")[0] not in ALLOWED_IMPORTS or name.startswith("hwpx_automation."):
                problems.append(f"{label}: import {name} is outside the public surface")
    return problems


def inject_overrides(code: str, overrides: dict) -> str:
    """Insert ``P.update(...)`` right after the block's ``P = {...}`` assignment."""
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "P" for t in node.targets):
            lines = code.splitlines()
            update = f"P.update({json.dumps(overrides, ensure_ascii=False)})"
            return "\n".join(lines[: node.end_lineno] + [update] + lines[node.end_lineno :]) + "\n"
    raise SystemExit("workflow block has no P assignment")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def make_sandbox(python: str, work: Path) -> Path:
    venv = work / "venv"
    run([python, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", *PREINSTALLED], check=True)
    return py


def read_only(tree: Path) -> None:
    for path in [tree, *tree.rglob("*")]:
        mode = path.stat().st_mode
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path, help="python-hwpx tests/fixtures directory")
    parser.add_argument("--python", default="python3.12", help="interpreter matching the ChatGPT sandbox")
    parser.add_argument("--evidence", type=Path, help="write the JSON evidence record here")
    parser.add_argument("--keep", action="store_true", help="keep the temporary sandbox for inspection")
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="hwpx-web-sim-"))
    evidence: dict = {"zip": str(args.zip), "python": args.python, "cases": [], "problems": []}
    try:
        py = make_sandbox(args.python, work)
        evidence["sandboxPython"] = run([str(py), "-c", "import sys; print(sys.version.split()[0])"]).stdout.strip()

        skills = work / "skills"
        with zipfile.ZipFile(args.zip) as archive:
            tops = {name.split("/")[0] for name in archive.namelist()}
            if len(tops) != 1:
                raise SystemExit(f"ZIP must have one top-level folder, found {sorted(tops)}")
            archive.extractall(skills)
        skill = skills / tops.pop()
        read_only(skills)

        env = {**os.environ, "PIP_INDEX_URL": BLOCKED_INDEX, "PIP_TIMEOUT": "3", "PIP_RETRIES": "0"}
        boot = run([str(py), str(skill / "scripts" / "bootstrap.py")], env=env, timeout=600)
        status = json.loads(boot.stdout.strip().splitlines()[-1])
        evidence["bootstrap"] = status
        modes = (status.get("core", {}).get("mode"), status.get("automation", {}).get("mode"))
        if not status.get("ok") or modes != ("offline", "offline"):
            evidence["problems"].append(f"bootstrap did not install offline: {status}")
            raise SystemExit(1)
        again = json.loads(run([str(py), str(skill / "scripts" / "bootstrap.py")], env=env).stdout.strip().splitlines()[-1])
        if (again.get("core", {}).get("mode"), again.get("automation", {}).get("mode")) != ("already-installed", "already-installed"):
            evidence["problems"].append(f"second bootstrap run was not idempotent: {again}")

        skill_md = (skill / "SKILL.md").read_text(encoding="utf-8")
        prelude = python_blocks(skill_md)[0]
        workflows = workflow_blocks((skill / "references" / "web-workflows.md").read_text(encoding="utf-8"))
        evidence["blocks"] = sorted(workflows)
        for label, code in [("SKILL.md prelude", prelude), *workflows.items()]:
            evidence["problems"].extend(check_imports(label, code))

        data = work / "mnt-data"
        for case_id, block, fixture, overrides, expected, reason in CASES:
            case_dir = data / case_id
            case_dir.mkdir(parents=True)
            params = dict(overrides)
            if fixture:
                src = case_dir / Path(fixture).name
                shutil.copyfile(args.fixtures / fixture, src)
                params["src"] = str(src)
            params["out"] = str(case_dir / "output.hwpx")
            code = prelude + "\n" + inject_overrides(workflows[block], params)
            code = code.replace("SKILL_DIR = None", f"SKILL_DIR = {json.dumps(str(skill))}", 1)
            code = code.replace('"/mnt/data"', json.dumps(str(case_dir)))
            proc = run([str(py), "-c", code], cwd=case_dir, env=env, timeout=300)
            output_exists = (case_dir / "output.hwpx").exists()
            leftovers = [p.name for p in case_dir.glob("*.checking.hwpx")]
            writes = block != "W1"
            if expected == "ok":
                passed = proc.returncode == 0 and output_exists == writes
            else:
                passed = (proc.returncode != 0 and not output_exists and "Traceback" not in proc.stderr
                          and reason in proc.stderr)
            passed = passed and not leftovers
            record = {
                "case": case_id,
                "block": block,
                "fixture": fixture,
                "expected": expected,
                "passed": passed,
                "returncode": proc.returncode,
                "stdoutTail": proc.stdout[-800:],
                "stderrTail": proc.stderr[-800:],
            }
            evidence["cases"].append(record)
            print(f"[{'PASS' if passed else 'FAIL'}] {case_id}")

        # Core-only sandbox: lxml present, pydantic absent. The core must still install offline,
        # automation must be reported unavailable, and W1 must work.
        core_venv = work / "venv-core-only"
        run([args.python, "-m", "venv", str(core_venv)], check=True)
        core_py = core_venv / "bin" / "python"
        run([str(core_py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "lxml"], check=True)
        core_status = json.loads(run([str(core_py), str(skill / "scripts" / "bootstrap.py")], env=env, timeout=600).stdout.strip().splitlines()[-1])
        case_dir = data / "core-only-W1"
        case_dir.mkdir(parents=True)
        src = case_dir / Path(DISASTER).name
        shutil.copyfile(args.fixtures / DISASTER, src)
        code = prelude + "\n" + inject_overrides(workflows["W1"], {"src": str(src)})
        code = code.replace("SKILL_DIR = None", f"SKILL_DIR = {json.dumps(str(skill))}", 1).replace('"/mnt/data"', json.dumps(str(case_dir)))
        proc = run([str(core_py), "-c", code], cwd=case_dir, env=env, timeout=300)
        core_only_ok = (core_status.get("ok") is True and core_status.get("automation", {}).get("ok") is False
                        and proc.returncode == 0 and "새 문서 만들기(W5) 불가" in proc.stdout)
        evidence["coreOnly"] = {"passed": core_only_ok, "bootstrap": core_status, "stdoutTail": proc.stdout[-400:], "stderrTail": proc.stderr[-400:]}
        print(f"[{'PASS' if core_only_ok else 'FAIL'}] core-only sandbox (lxml only)")
        if not core_only_ok:
            evidence["problems"].append("core-only sandbox did not degrade gracefully")

        facade = (skill / "references" / "automation-python-api.md").read_text(encoding="utf-8")
        names = sorted(set(re.findall(r"`api\.([A-Za-z_]+)", facade)))
        probe = "from hwpx_automation import api; import json, sys; print(json.dumps([n for n in sys.argv[1:] if not hasattr(api, n)]))"
        missing = json.loads(run([str(py), "-c", probe, *names]).stdout)
        evidence["facadeNames"] = names
        if missing:
            evidence["problems"].append(f"facade reference names missing from hwpx_automation.api: {missing}")
    finally:
        failed = [c["case"] for c in evidence["cases"] if not c["passed"]]
        evidence["ok"] = not failed and not evidence["problems"] and len(evidence["cases"]) == len(CASES)
        if args.evidence:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for problem in evidence["problems"]:
            print(f"[PROBLEM] {problem}")
        print(f"{'OK' if evidence['ok'] else 'FAILED'}: {len(evidence['cases']) - len(failed)}/{len(CASES)} cases")
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
