# MCP Template Form-Fit Workflow

Use this when the user provides or references an approved operating-plan HWPX
template and the goal is to preserve that form while filling generated content.

## 1. Analyze Without Mutating

Call `analyze_template_formfit` first. Use the P6 baseline JSON when working
with the approved AI 융합형 교육실 template.

```json
{
  "source_filename": "inputs/template.hwpx",
  "baseline": "baselines/template-formfit-baseline.json",
  "content": {
    "school": {"name": "광교고등학교"},
    "sections": {
      "background_purpose": [
        "AI 융합형 교육실 구축으로 학생 맞춤형 탐구 수업을 확대한다.",
        "교원 공동 설계와 지역 연계를 통해 지속 가능한 운영 체계를 만든다."
      ],
      "timeline": {
        "rows": [
          {"월": "3월", "추진 내용": "운영 협의체 구성"},
          {"월": "4월", "추진 내용": "공간 설계 및 기자재 선정"}
        ]
      }
    }
  },
  "destination_filename": "outputs/ai-room-operating-plan.hwpx"
}
```

Continue only when:

- `mutated == false`
- `source.unchanged_after_analysis == true`
- `unresolved_count == 0`
- required anchors resolve once
- `destination.path` is different from `source.path`

## 2. Apply To A Copy

```json
{
  "analysis": "<analysis payload from analyze_template_formfit>",
  "confirm": true
}
```

Accept handoff only when:

- `handoff_status == "ready"`
- `source.preserved == true`
- `validation.validate_package.ok == true`
- `validation.validate_document.ok == true`
- `residual_markers.blocking == []`

If `visual_review_required == true`, report that final submission still needs
opened-document or human visual review. This workflow does not claim pixel-level
layout parity.
