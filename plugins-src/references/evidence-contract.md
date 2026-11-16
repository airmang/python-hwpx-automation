# 증거 계약 (openSafety · visual-review v1 · hard gates · 제출 증거)

모든 워크플로가 공유하는 단일 증거 계약. 다른 문서는 이 파일을 포인터로만 참조한다.

## 1. openSafety (editor-open safety)

- 정의: `hwpx.tools.package_validator.validate_editor_open_safety(path)`가 검증하는
  "한컴 편집기에서 안전하게 열리는가" 판정. MCP 쓰기 도구는 저장 전 임시 파일에서 이
  검증을 수행하고, 통과한 경우에만 대상 파일을 교체한다.
- 쓰기 도구가 `openSafety`를 반환하면 `openSafety.ok == true`(또는
  `verification.openSafety.ok == true`, `validation.openSafety.ok == true`)를 확인한다.
  해당 필드가 없는 도구는 생성 계약에 선언된 verification receipt와 재열기/전용 검증
  도구를 사용하며, 존재하지 않는 공통 필드를 추정하지 않는다.
- `openSafety.ok == false`인 파일은 **handoff하지 않는다**. `validation.*.issues[]`와
  `recovery.repair_hints[]`를 따라 재저장/재생성한 뒤 다시 검사한다.
- ZIP 자체가 안 열리거나 `mimetype` 첫 엔트리/CRC 손상이 의심되면 편집 전에
  `repair_hwpx`(또는 `hwpx-repair`)로 복구 복사본을 만들고 `crcOk`,
  `validatePackage.ok`, `openSafety.ok`, `reordered`, `recovered`를 evidence로 남긴다.
- local 스크립트(`scripts/zip_replace_all.py`, `scripts/fix_namespaces.py`)도 open-safety
  검증 통과 시에만 대상을 교체한다. 이 가드를 우회하는 경로를 만들지 않는다.

## 2. visual-review v1 (열린 문서 검토 증거)

`visual_review_required=true`는 구조 검증은 통과했지만 렌더러/사람의 시각 검수는 하지
않았다는 뜻이다. 이때 파일 단위 검증만으로 "최종 제출 가능"을 주장하지 않는다.

ComputerUse 또는 사람이 HWPX viewer로 문서를 연 뒤 `scripts/visual_review.py`로
`hwpx.visual-review.v1` evidence를 남긴다.

최종 제출 가능 주장 요건 (전부 충족해야 함):

- `schemaVersion == "hwpx.visual-review.v1"`
- `current.status == "observed_pass"` (허용 상태는 `observed_pass`, `needs_review`, `blocked`뿐)
- `current.screenshot_path`가 존재 — `--observation`만으로는 부족하다
- `summary.ready_for_submission_claim == true`

상태 의미:

- `needs_review`: 재생성 또는 레이아웃 보완 필요.
- `blocked`: viewer가 없어 열린 문서 검토가 남음. CI/컨테이너에서는 blocked fallback을
  기록하고 "제출 준비 완료"가 아니라 "viewer 검토 대기"로 handoff한다.

```bash
# viewer가 없는 환경의 blocked fallback
python3 scripts/visual_review.py out/plan.hwpx --evidence out/visual_review.json \
  --viewer none --status blocked \
  --notes "No HWPX viewer is available in this environment." \
  --layout-risk "Rendered page breaks and table fit require opened-document review."

# 열린 문서를 확인한 경우 (screenshot 필수)
python3 scripts/visual_review.py out/plan.hwpx --evidence out/visual_review_pass.json \
  --viewer auto --method computer-use --status observed_pass \
  --screenshot out/visual_review_page1.png \
  --notes "Opened in local HWPX viewer. Tables fit and no clipped placeholders."
```

추가 규칙:

- `--viewer`는 `auto`, `none`, `command:open` 등 viewer 실행 방식이고, ComputerUse는
  `--method computer-use`로 기록하는 관찰 방법이다.
- `iterations[]`는 같은 target checksum에 같은 evidence 파일을 다시 쓸 때만 누적된다.
  재생성된 HWPX는 새 evidence 파일을 쓰고 `--regenerated-from`으로 이전 evidence를
  연결한다 (추적성만 제공, iterations 병합 아님).
- `blocked`/`needs_review`를 새 관찰 없이 `observed_pass`로 격상하지 않는다.
- MCP `render_preview`의 `visualReviewPath`는 빠른 렌더 프리뷰 evidence다. 이것만으로는
  최종 제출 가능 주장을 할 수 없고, 위의 열린 문서 검토 요건이 여전히 필요하다.
- 정부보고서 전용 관찰 항목은
  [`government-report-visual-review.md`](government-report-visual-review.md)를 본다.

Evidence schema 전문과 필드 설명은 `examples/09_visual_review_loop.md`,
`examples/11_computeruse_visual_review.md`를 본다. 공통 handoff 경로는
`current.timestamp`, `current.tool_path`, `current.screenshot_path`,
`summary.ready_for_submission_claim`이며, viewer unavailable/disabled/failure fallback에는
`current.fallback_reason`이 추가된다.

## 3. BuilderSaveReport hard gates

`hwpx.builder`의 `document.save_to_path(path)`가 반환하는 `BuilderSaveReport`:

- `hard_gates["package_validation"] == "pass"` — package validator 통과 (필수)
- `hard_gates["document_errors"] == "pass"` — document validator error 없음 (필수)
- `hard_gates["reopen"] == "pass"` — `HwpxDocument.open(path)` 재오픈 성공 (필수)
- `hard_gates["editor_open_safety"] == "pass"` — editor-open safety 통과 (필수)
- `hard_gates["schema_lint"] == "warning"` — schema warning 가시화. **hard fail 아님**.
  hard error가 아니면 `document_errors`는 pass다.
- `visual_review_required == True`이면 §2의 열린 문서 검토 evidence까지 남긴다.
  (`header_footer`, `page_number`, `table`, `image`, `page_break` 같은 layout-sensitive
  기능 사용 시 기본적으로 true가 된다.)

## 4. 운영계획서 제출 증거 체크리스트

운영 계획서(또는 form-fit destination)를 "제출 준비 완료"로 handoff하기 전 전부 확인:

- `plan_validation.ok == true`
- `quality.validation.reopened == true`
- `quality.validation.validate_package.ok == true`
- `quality.validation.validate_document.ok == true`
- `verification.openSafety.ok == true`
- file-only `inspect_operating_plan_quality(path).report_version == "operating-plan-quality-v1"`
- file-only `inspect_operating_plan_quality(path).status == "ready"`
- `quality.visual_review_required == true`이면 §2의 visual-review evidence
  (`observed_pass` + screenshot + `ready_for_submission_claim == true`)
- form-fit 경로 추가 조건: `handoff_status == "ready"`, `source.preserved == true`,
  `residual_markers.blocking == []`

하나라도 미충족이면 "제출 준비 완료"가 아니라 미충족 항목을 명시한 상태로 handoff한다.
