# MCP 품질 생성 예제 (canonical document-plan 경로)

목표: 좋은 품질 샘플을 매번 요구하지 않고, 양식 HWPX 구조와 아이디어만으로 완성도 있는
결과 문서를 만든다.

> 5.0 경계 참고: `analyze_quality_generation`/`apply_quality_generation` 전환 stub은
> 제거됐다. 이 예제는 canonical `create_document_from_plan` + `inspect_document_quality`
> 흐름으로 같은 목표를 달성한다. 대체표는 `references/migration-mcp-5.0.md`.

## 흐름

1. 완성 대상 양식의 구조가 필요하면 `document_to_markdown(form_filename)` 또는
   `get_document_map(form_filename)`으로 섹션·표·필수 항목을 확인한다.
2. 사용자의 아이디어를 `hwpx.document_plan.v1`로 정규화하고 파악한 구조를 반영한다.
3. `validate_document_plan(document_plan)` — `ok=false`이면 `issues[]`/`repairHints[]`를
   반영해 plan을 고친다.
4. `create_document_from_plan(destination_filename, document_plan, quality_profile=...)`으로
   출력 HWPX를 생성한다. proposal 성격이면 `create_proposal_document`를 대신 쓴다.
5. `inspect_document_quality(destination_filename, rubric=...)`로 결과를 점검한다.
6. `quality.gaps`/rubric 점수가 부족하면 document_plan을 보강해 다시 생성한다.

## 입력 예시

```json
{
  "destination_filename": "outputs/ai-school-plan.hwpx",
  "document_plan": {
    "schemaVersion": "hwpx.document_plan.v1",
    "metadata": {"title": "2026년 AI 중점학교 운영계획서"},
    "blocks": [
      {"type": "heading", "level": 1, "text": "2026년 AI 중점학교 운영계획서"},
      {"type": "paragraph", "text": "초등학생 AI 기초 소양과 교원 AI 수업 설계 역량을 강화한다."}
    ]
  },
  "quality_profile": "korean_ai_school_application_v1"
}
```

## 성공 기준

- 목표 품질 샘플 파일 없이도 `create_document_from_plan` 생성이 시작된다.
- 생성된 `.hwpx`가 다시 열리고 package/document validation을 통과한다.
- `inspect_document_quality` 응답에 rubric 점검 결과가 남는다.
- 복잡한 레이아웃, 이미지 기반 양식, 바이너리 `.hwp` 처리는 범위 밖으로 둔다.
