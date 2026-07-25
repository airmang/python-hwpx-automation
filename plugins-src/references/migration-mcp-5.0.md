# 5.0 경계 마이그레이션 가이드

`hwpx-mcp-server` 5.0.0에서 5개 전환기 stub이 제거됐고, 3개 도구가 DEPRECATED로
강등됐다. 나머지 compatibility facade(2군) 3종은 분류가 바뀌지 않았다 — 계속 지원되며,
이 문서는 새 작업에서 어떤 경로를 먼저 선택할지만 정리한다. 서버 쪽 제거 계약과 계약
delta는 `hwpx-mcp-server` 레포의 `docs/deprecation-5.0.0.md`가 정본이다.

## 제거됨 (5종) — 호출하면 오류

| 제거된 도구 | 대체 | 비고 |
|---|---|---|
| `plan_edit` | `apply_document_commands` | dry-run으로 옛 plan/preview 의미를 얻는다. |
| `preview_edit` | `apply_document_commands` (`dry_run=True`) | 같은 receipt 구조 + rollback/idempotency 보장 추가. |
| `apply_edit` | `apply_document_commands` | 단건 편집도 command 1개짜리 원자 batch로 표현한다. |
| `analyze_quality_generation` | `create_document_from_plan` + `inspect_document_quality` | 별도 사전 분석 없이 plan schema + 품질 inspector로 대체한다. |
| `apply_quality_generation` | `create_document_from_plan`(+ proposal 프리셋은 `create_proposal_document`) | plan 기반 생성이 품질 정책을 직접 싣는다. |

## DEPRECATED (1군, 3종) — 계속 동작하지만 새 사용 금지

다음 major에서 제거 예정. 기존 자동화 호환으로만 유지한다.

- `fill_form_field` → canonical plan의 `nativeField` operation.
- `analyze_template_formfit` / `apply_template_formfit` → 구조적 채움은
  `apply_table_ops`(`fill_cells` 등), mixed-form 채움은
  `analyze_form_fill` → `apply_form_fill` → `verify_form_fill`.

## Compatibility facade (2군, 분류 불변) — 새 작업 권장 경로

계속 지원되고 제거 계획이 없다. 새 작업에서 우선 선택할 경로만 아래로 이주한다.

- `apply_edits` → 이종 편집은 `apply_document_commands`
  ([workflows-agent-document.md](workflows-agent-document.md)). 기존 operation-list
  호출자를 위한 상세는 [workflows-editing.md](workflows-editing.md)에 남아 있다.
- `fill_by_path` → 양식 밖 일반 좌표 편집은 `get_document_map` →
  `apply_document_commands`; 양식 mixed-form 채움은 canonical plan에 합친다.
- `create_comparison_table_document` → `doc_diff` → 신구대조표 document_plan →
  `create_document_from_plan` ([workflows-bulk-compare.md](workflows-bulk-compare.md)).

## 참고

- [`api.md`](api.md) — template-formfit 시그니처와 DEPRECATED 표시.
- [`workflows-forms.md`](workflows-forms.md) — compatibility facade 경계 표.
- [`workflows-creation.md`](workflows-creation.md) §7 — quality-profile 생성 canonical 경로.
