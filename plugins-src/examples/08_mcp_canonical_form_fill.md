# MCP Canonical Form-Fill Workflow

사용자가 기존 HWPX 양식(누름틀·라벨 표 셀·경로 셀·표 밖 본문이 섞여 있어도)을
채워달라고 할 때의 canonical 경로다: `analyze_form_fill` → `apply_form_fill` →
(요구 시) `verify_form_fill`. 전체 규칙은
`references/workflows-forms.md`가 정본이다.

## 1. Analyze Without Mutating

`analyze_form_fill(plan=...)`을 먼저 호출한다. 이 호출은 파일을 변경하지 않는다.
plan은 strict `hwpx.mixed-form-plan/v1`이며 모든 target을 discriminated
operation 하나의 목록으로 모은다.

```json
{
  "plan": {
    "schemaVersion": "hwpx.mixed-form-plan/v1",
    "source": "inputs/template.hwpx",
    "output": "outputs/ai-room-operating-plan.hwpx",
    "expectedRevision": "sha256:<get_document_map이 보고한 revision>",
    "idempotencyKey": null,
    "dryRun": true,
    "overwrite": true,
    "quality": "transparent",
    "verificationRequirements": [
      "package", "reopen", "openSafety", "semanticDiff", "bytePreservation"
    ],
    "operations": [
      {
        "operationId": "native-school",
        "target": {"kind": "nativeField", "name": "학교명"},
        "value": "광교고등학교"
      },
      {
        "operationId": "label-department",
        "target": {
          "kind": "labelCell",
          "sectionPath": "/section[1]",
          "tableAnchor": "담당 부서",
          "cellAnchor": {"label": "담당 부서", "direction": "right"}
        },
        "value": "교육연구부"
      },
      {
        "operationId": "body-purpose",
        "target": {
          "kind": "bodyAnchor",
          "sectionPath": "/section[1]",
          "anchor": "추진 배경을 입력하세요.",
          "expectedCount": 1
        },
        "value": "AI 융합형 교육실 구축으로 학생 맞춤형 탐구 수업을 확대한다."
      }
    ]
  }
}
```

계속 진행하는 조건:

- 반환된 plan의 source/output과 expected revision이 의도와 일치
- `nativeField` / `canonicalPath` / `labelCell` / `bodyAnchor` 별 operation이
  전부 해석됨 — unresolved/ambiguous target 0
- 모호한 target이 있으면 임의로 첫 후보를 고르지 말고 한 묶음으로 사용자에게 확인

## 2. Dry-Run, Then Commit In One Transaction

위처럼 `plan.dryRun=true`로 `apply_form_fill(plan=...)`을 호출해 semantic diff를
검토하고, commit은 같은 operations를 `plan.dryRun=false` + 새 `idempotencyKey` +
최신 revision으로 재분석해 **한 번, 한 트랜잭션**으로 적용한다. 같은 작업을
`apply_table_ops`/`apply_body_ops` 별도 commit으로 쪼개 원자성을 깨지 않는다.

수락 조건:

- rollback/idempotency 영수증과 package reopen 확인
- byte-preservation 범위와 `openSafety.ok == true`
- 한 operation이라도 실패하면 destination 전체가 적용 전 상태로 rollback

## 3. Verify When Required

검증이 요구된 계약에서는 `verify_form_fill` 결과를 commit과 같은 revision에
연결한다. `visual_review_required == true`이면 최종 제출 전 실제 열린 문서 또는
사람의 시각 검토가 남아 있음을 보고한다. 이 워크플로는 픽셀 단위 레이아웃
동일성을 주장하지 않는다.

## 호환 부록 — legacy template-formfit

기존 `hwpx.template-formfit.baseline.v1` baseline 자동화는
`analyze_template_formfit` / `apply_template_formfit` 호환 표면으로 계속
동작한다(**DEPRECATED — 5.0 경계 확정**, 동작 유지·제거는 다음 major). 새 작업에는
사용하지 않는다. 회귀 자산: `examples/08_template_formfit.py`
(quickcheck `--template-formfit`).
