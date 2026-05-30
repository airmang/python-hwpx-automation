# MCP 품질 파이프라인 예제

목표: 좋은 품질 샘플을 매번 요구하지 않고, 양식 HWPX와 아이디어만으로 완성도 있는 결과 문서를 만든다.

## 흐름

1. 사용자의 아이디어를 짧은 브리프 또는 content spec으로 정리한다.
2. MCP 도구 `analyze_quality_generation`으로 양식 구조와 내장 품질 프로필 기반 생성 계획을 확인한다.
3. MCP 도구 `apply_quality_generation`으로 출력 HWPX를 생성한다.
4. 반환된 `quality.gaps`, `revision_history`, `validation`을 확인한다.
5. 부족한 부분이 있으면 브리프를 보강하거나 파이프라인의 revision 권고를 반영해 다시 생성한다.

## 입력 예시

```json
{
  "form_filename": "inputs/form-template.hwpx",
  "idea_brief": "초등학생 AI 기초 소양과 교원 AI 수업 설계 역량을 강화하는 2026년 AI 중점학교 운영계획서를 작성한다.",
  "destination_filename": "outputs/ai-school-plan.hwpx"
}
```

## 성공 기준

- 목표 품질 샘플 파일 없이도 일반 생성이 시작된다.
- 생성된 `.hwpx`가 다시 열리고 package/document validation을 통과한다.
- MCP 응답에 품질 점검 결과와 revision 이력이 남는다.
- 복잡한 레이아웃, 이미지 기반 양식, 바이너리 `.hwp` 처리는 v1 범위 밖으로 둔다.
