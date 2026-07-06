#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""One-command release: hwpx-mcp-server (PyPI) + hwpx-plugin (marketplace pin bump).

엔진(hwpx-mcp-server) 릴리스와 플러그인(마켓 핀·버전) 갱신을 한 번에 수행한다.
2-레포 수동 릴리스의 마찰과 "핀 스큐"(마켓 핀이 엔진 릴리스보다 뒤처짐)를 없앤다.

흐름
  1. hwpx-mcp-server: pyproject/CHANGELOG bump → commit → tag vX → push
     (레포의 `.github/workflows/release.yml` 이 태그 트리거로 PyPI 게시)
  2. PyPI 에 X 전파될 때까지 대기
  3. 마켓(이 레포): origin/main 으로 reset(★stale 가드) → 런처 핀 + 플러그인 버전 bump →
     build_hwpx_plugins.py 재생성 → validate → CHANGELOG → commit → push

사용
  # 계획만 출력(안전 기본값 = dry-run):
  HWPX_MCP_SERVER_REPO=~/Code/projects/hwpx/hwpx-mcp-server \
    python3 scripts/release_stack.py --engine 2.17.0 --plugin 0.1.22
  # 실제 실행(되돌릴 수 없는 PyPI 게시 포함):
  ... --engine 2.17.0 --plugin 0.1.22 --yes
  # 엔진은 이미 게시됨 → 마켓 핀/버전만:
  ... --engine 2.16.0 --plugin 0.1.22 --skip-engine --yes
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

MKT_REPO = Path(__file__).resolve().parents[1]  # 이 스크립트를 담은 마켓 레포
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def log(msg: str) -> None:
    print(f"\n\033[1;36m▶ {msg}\033[0m")


def die(msg: str) -> None:
    print(f"\033[1;31m✗ {msg}\033[0m", file=sys.stderr)
    sys.exit(1)


def git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True)
    if check and r.returncode != 0:
        die(f"git {' '.join(args)} 실패 ({repo}):\n{r.stderr.strip()}")
    return r.stdout.strip()


def require_clean_main(repo: Path, name: str) -> None:
    if not (repo / "pyproject.toml").exists() and not (repo / "packaging").exists():
        die(f"{name} 레포로 보이지 않음: {repo}")
    if git(repo, "branch", "--show-current") != "main":
        die(f"{name} 이 main 브랜치가 아님 (release 는 main 에서만).")
    if git(repo, "status", "--porcelain"):
        die(f"{name} 워킹트리가 더럽다 — 커밋/스태시 후 다시.")


def bump_version_line(path: Path, new: str) -> None:
    txt = path.read_text(encoding="utf-8")
    txt2 = re.sub(r'(?m)^version = "\d+\.\d+\.\d+"', f'version = "{new}"', txt, count=1)
    if txt == txt2:
        die(f"version 라인을 못 찾음: {path}")
    path.write_text(txt2, encoding="utf-8")


def finalize_changelog(path: Path, version: str, today: str, extra_body: str = "") -> None:
    """keep-a-changelog: '## [Unreleased]' 아래에 '## [version] - today' 섹션을 만든다."""
    txt = path.read_text(encoding="utf-8")
    if "## [Unreleased]" not in txt:
        die(f"CHANGELOG 에 '## [Unreleased]' 없음: {path}")
    section = f"## [Unreleased]\n\n## [{version}] - {today}\n{extra_body}".rstrip() + "\n"
    path.write_text(txt.replace("## [Unreleased]", section, 1), encoding="utf-8")


def sub_in_files(paths, pattern: str, repl: str) -> int:
    total = 0
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        txt2, n = re.subn(pattern, repl, txt)
        if n:
            p.write_text(txt2, encoding="utf-8")
            total += n
    return total


def wait_for_pypi(version: str, tries: int = 40, interval: int = 15) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "v"
        subprocess.run(["uv", "venv", "-q", str(venv)], check=True)
        py = venv / "bin" / "python"
        for i in range(1, tries + 1):
            r = subprocess.run(
                ["uv", "pip", "install", "-q", "--python", str(py),
                 f"hwpx-mcp-server=={version}"],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                log(f"→ PyPI 에 {version} 설치 가능 확인 (시도 {i})")
                return
            print(f"  [{i}/{tries}] PyPI 전파 대기…", flush=True)
            subprocess.run(["sleep", str(interval)])
    die(f"PyPI 에 {version} 이 안 올라옴 — release.yml CI 로그를 확인하세요.")


def main() -> None:
    ap = argparse.ArgumentParser(description="hwpx 스택 원-샷 릴리스 (엔진 PyPI + 플러그인 핀)")
    ap.add_argument("--engine", required=True, help="hwpx-mcp-server 새 버전 (예: 2.17.0)")
    ap.add_argument("--plugin", required=True, help="hwpx-plugin 새 버전 (예: 0.1.22)")
    ap.add_argument("--mcp-repo", default=os.environ.get("HWPX_MCP_SERVER_REPO"),
                    help="hwpx-mcp-server 체크아웃 경로 (또는 HWPX_MCP_SERVER_REPO 환경변수)")
    ap.add_argument("--skip-engine", action="store_true",
                    help="엔진은 이미 PyPI 게시됨 → 마켓 핀/버전만 갱신")
    ap.add_argument("--yes", action="store_true",
                    help="실제 실행(되돌릴 수 없는 PyPI 게시 포함). 없으면 계획만 출력(dry-run).")
    args = ap.parse_args()

    if not SEMVER.match(args.engine):
        die(f"--engine 은 x.y.z 형식: {args.engine}")
    if not SEMVER.match(args.plugin):
        die(f"--plugin 은 x.y.z 형식: {args.plugin}")

    today = date.today().isoformat()

    # ---- 마켓 레포 사전점검 ----
    require_clean_main(MKT_REPO, "marketplace")
    cur_pin = re.search(r"hwpx-mcp-server==(\d+\.\d+\.\d+)",
                        (MKT_REPO / "packaging/templates/hwpx-mcp-server").read_text()).group(1)

    mcp_repo = None
    if not args.skip_engine:
        if not args.mcp_repo:
            die("엔진 릴리스에는 --mcp-repo 또는 HWPX_MCP_SERVER_REPO 필요 (--skip-engine 이면 생략 가능).")
        mcp_repo = Path(args.mcp_repo).expanduser().resolve()
        require_clean_main(mcp_repo, "hwpx-mcp-server")
        cur_engine = re.search(r'(?m)^version = "(\d+\.\d+\.\d+)"',
                               (mcp_repo / "pyproject.toml").read_text()).group(1)
        if git(mcp_repo, "tag", "-l", f"v{args.engine}"):
            die(f"태그 v{args.engine} 가 이미 있음 — 재릴리스 금지(--skip-engine 을 쓰세요).")

    # ---- 계획 출력 ----
    log("릴리스 계획")
    if args.skip_engine:
        print(f"  엔진   : (건너뜀 — 이미 게시된 hwpx-mcp-server=={args.engine} 가정)")
    else:
        print(f"  엔진   : hwpx-mcp-server {cur_engine} → {args.engine}  (커밋·태그 v{args.engine}·push → CI PyPI 게시)")
    print(f"  플러그인: hwpx-plugin (핀 {cur_pin} → {args.engine}, 버전 → {args.plugin}, 4호스트 재빌드·push)")
    if not args.yes:
        print("\n\033[1;33m(dry-run) --yes 없이는 아무것도 실행/게시하지 않습니다.\033[0m")
        return

    # ---- 1) 엔진 릴리스 ----
    if not args.skip_engine:
        log(f"[1/3] hwpx-mcp-server {args.engine} 릴리스 컷")
        git(mcp_repo, "fetch", "-q", "origin", "main")
        git(mcp_repo, "rebase", "-q", "origin/main")
        bump_version_line(mcp_repo / "pyproject.toml", args.engine)
        finalize_changelog(mcp_repo / "CHANGELOG.md", args.engine, today)
        git(mcp_repo, "add", "pyproject.toml", "CHANGELOG.md")
        git(mcp_repo, "commit", "-q", "-m", f"chore: release hwpx-mcp-server {args.engine}")
        git(mcp_repo, "tag", "-a", f"v{args.engine}", "-m", f"hwpx-mcp-server {args.engine}")
        git(mcp_repo, "push", "-q", "origin", "main")
        git(mcp_repo, "push", "-q", "origin", f"v{args.engine}")
        print("  → 태그 push 완료. release.yml 이 PyPI 에 게시 중…")
        # ---- 2) PyPI 대기 ----
        log(f"[2/3] PyPI 전파 대기 (hwpx-mcp-server=={args.engine})")
        wait_for_pypi(args.engine)
    else:
        wait_for_pypi(args.engine)  # skip-engine 이어도 존재 확인은 한다

    # ---- 3) 마켓 핀/버전 bump + 재빌드 + push ----
    log(f"[3/3] hwpx-plugin {args.plugin} — 핀 hwpx-mcp-server=={args.engine}")
    git(MKT_REPO, "fetch", "-q", "origin", "main")
    git(MKT_REPO, "reset", "--hard", "-q", "origin/main")  # ★ stale 가드
    tdir = MKT_REPO / "packaging" / "templates"
    n_pin = sub_in_files(
        list(tdir.glob("*")) + [MKT_REPO / "scripts" / "validate_hwpx_plugin.py"],
        r"hwpx-mcp-server==\d+\.\d+\.\d+", f"hwpx-mcp-server=={args.engine}")
    n_ver = sub_in_files(
        list(tdir.glob("*.plugin.json")) + [tdir / "codex.marketplace.json"],
        r'"version": "\d+\.\d+\.\d+"', f'"version": "{args.plugin}"')
    n_ver += sub_in_files([MKT_REPO / "packaging" / "hosts.json"],
                          r"version: \d+\.\d+\.\d+", f"version: {args.plugin}")
    print(f"  핀 치환 {n_pin}곳, 버전 치환 {n_ver}곳")
    if n_pin == 0 or n_ver == 0:
        die("핀/버전 치환 0곳 — 템플릿 구조가 바뀌었는지 확인.")
    subprocess.run([sys.executable, str(MKT_REPO / "scripts/build_hwpx_plugins.py")], check=True)
    subprocess.run([sys.executable, str(MKT_REPO / "scripts/validate_hwpx_plugin.py")], check=True)
    finalize_changelog(
        MKT_REPO / "CHANGELOG.md", args.plugin, today,
        extra_body=f"### Changed\n- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server=={args.engine}`으로 갱신.\n")
    git(MKT_REPO, "add", "-A")
    git(MKT_REPO, "commit", "-q", "-m",
        f"chore(release): hwpx-plugin {args.plugin} — pin hwpx-mcp-server {args.engine}")
    git(MKT_REPO, "push", "-q", "origin", "main")

    log(f"✅ 완료 — 엔진 {args.engine} PyPI 게시 + 플러그인 {args.plugin} 마켓 push")
    print("   사용자는 다음 플러그인 업데이트(자동 업데이트 켜져 있으면 자동) + 재시작 시 반영됩니다.")


if __name__ == "__main__":
    main()
