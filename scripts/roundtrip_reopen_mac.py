# SPDX-License-Identifier: Apache-2.0
"""왕복 산출물의 실한컴(Mac) 재개봉 판정 배치 — roundtrip_fidelity의 나머지 절반.

core ``scripts/roundtrip_fidelity.py``가 남긴 ``work/roundtrip-v1/`` 재직렬화
산출물 전건을 ``MacHancomOracle``(GUI 자동화, open → PDF 저장 → 닫기)로 개봉해
판정한다. **렌더 산출 = 개봉 성공**의 대리 판정이며, 판정 채널 자체의 유효성은
음성 대조로 증명한다: 실한컴이 손상으로 거부하는 입력(예: reader_robustness의
IRB pair)이 하나라도 "성공"하면 ``harnessValid: false``로 전체를 무효화한다
(fail-closed — 조용한 auto-repair를 성공으로 오독하지 않기 위함, openrate
FR-005 교훈).

운영 노트:

* GUI 단일 세션이라 직렬 실행. 실패 후에는 잔존 모달이 후속 런을 오염시킬 수
  있어 한컴을 종료(quit → killall 폴백)하고 이어간다.
* 영수증 JSON에는 벽시계·소요시간을 넣지 않는다(결정론 — 같은 입력·같은
  판정이면 재실행 diff가 0이어야 한다). 진행 로그는 stderr로만.
* 실행 전제: 로그인된 GUI 세션 + osascript 자동화 권한,
  ``HWPX_ORACLE_STRUCTURAL_ONLY`` 미설정.

    python scripts/roundtrip_reopen_mac.py \
        --roundtrip-dir ../python-hwpx/work/roundtrip-v1 \
        --negative ../python-hwpx/tests/fixtures/reader_robustness/irb_form_blank.hwpx \
        --negative ../python-hwpx/tests/fixtures/reader_robustness/irb_form_filled.hwpx \
        --out ../python-hwpx/work/roundtrip-v1-reopen/receipt.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import subprocess
import sys
import time
from pathlib import Path

from hwpx_automation.office.rendering.oracle import MacHancomOracle

SCHEMA_VERSION = "python-hwpx.roundtrip-reopen/v1"
_APP_NAME = "Hancom Office HWP"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hancom_build(app_path: str) -> str:
    try:
        with open(Path(app_path) / "Contents" / "Info.plist", "rb") as fh:
            info = plistlib.load(fh)
        short = info.get("CFBundleShortVersionString", "?")
        build = info.get("CFBundleVersion", "?")
        return f"{short} build {build}"
    except OSError:
        return "unknown"


def _recover_app() -> None:
    """실패 후 잔존 모달/문서로부터 복구 — 종료 시도 후 강제 종료 폴백."""
    subprocess.run(
        ["osascript", "-e", f'tell application "{_APP_NAME}" to quit'],
        capture_output=True, text=True, timeout=15, check=False,
    )
    time.sleep(2)
    subprocess.run(["killall", _APP_NAME], capture_output=True, check=False)
    time.sleep(3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roundtrip-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pdf-dir", type=Path, default=None,
                        help="렌더 PDF 보관 디렉터리 (기본: <out>의 디렉터리)")
    parser.add_argument("--negative", action="append", type=Path, default=[],
                        help="실한컴이 거부해야 하는 음성 대조 입력 (반복 지정)")
    parser.add_argument("--limit", type=int, default=None, help="스모크용 상한")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    manifest_path = args.roundtrip_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["included"]
    if args.limit is not None:
        entries = entries[: args.limit]

    if not args.negative:
        print("[중단] 음성 대조 없이는 판정 채널 유효성을 증명할 수 없다 — --negative 필수",
              file=sys.stderr)
        return 2

    oracle = MacHancomOracle(timeout=args.timeout)
    if not oracle.available():
        print("[중단] MacHancomOracle 사용 불가 (GUI 세션/권한/앱 확인)", file=sys.stderr)
        return 2
    build = _hancom_build(oracle._app_path() or "")
    pdf_dir = args.pdf_dir or args.out.parent
    pdf_dir.mkdir(parents=True, exist_ok=True)

    def judge(src: Path, out_pdf: Path) -> dict[str, object]:
        started = time.monotonic()
        pdf = oracle.render_pdf(str(src), str(out_pdf))
        elapsed = time.monotonic() - started
        reopened = pdf is not None
        print(f"  {'PASS' if reopened else 'FAIL'} ({elapsed:5.1f}s) {src.name}",
              file=sys.stderr, flush=True)
        if not reopened:
            _recover_app()
        return {"reopened": reopened,
                "pdfBytes": out_pdf.stat().st_size if reopened else 0}

    results: list[dict[str, object]] = []
    for index, entry in enumerate(entries, 1):
        rel = entry["file"]
        src = args.roundtrip_dir / rel
        print(f"[{index}/{len(entries)}] {rel}", file=sys.stderr, flush=True)
        out_pdf = pdf_dir / (rel.replace("/", "__") + ".pdf")
        verdict = judge(src, out_pdf)
        results.append({
            "file": rel,
            "resavedSha256": entry["resavedSha256"],
            "overallCategory": entry["overallCategory"],
            **verdict,
        })

    negatives: list[dict[str, object]] = []
    for src in args.negative:
        print(f"[음성 대조] {src.name}", file=sys.stderr, flush=True)
        out_pdf = pdf_dir / ("negative__" + src.name + ".pdf")
        verdict = judge(src, out_pdf)
        negatives.append({"file": src.name, "sha256": _sha256(src), **verdict})

    harness_valid = bool(negatives) and all(not n["reopened"] for n in negatives)
    reopened_count = sum(1 for r in results if r["reopened"])
    receipt = {
        "schemaVersion": SCHEMA_VERSION,
        "oracle": "MacHancomOracle",
        "hancomBuild": build,
        "roundtripManifestSummary": manifest["summary"],
        "harnessValid": harness_valid,
        "results": results,
        "negatives": negatives,
        "summary": {
            "total": len(results),
            "reopened": reopened_count,
            "failed": len(results) - reopened_count,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] {args.out} — reopened {reopened_count}/{len(results)}, "
          f"harnessValid={harness_valid}", file=sys.stderr)
    if not harness_valid:
        return 1
    return 0 if reopened_count == len(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
