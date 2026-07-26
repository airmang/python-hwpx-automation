# MCP government-report workflow

Use this when an MCP client has `python-hwpx-automation` connected. New host
configs use the local key `hwpx`; an existing 6.x config may still use
`hwpx-mcp-server`. Neither key is the FastMCP identity. Use this flow when the user asks
for a Korean government-style report, official briefing note, or 공문형 보고서.

## Flow

1. Use `parse_government_report_text` for pasted report text, or write a
   `hwpx.document_plan.v2` with `preset="government_report"`.
2. Use `compute_report_value` for report-safe numbers such as KRW Hangul,
   comma formatting, ratios, deltas, dates, and age.
3. Call `create_government_report_document`. It applies the government report
   style preset and quality profile automatically.
4. Check `created`, `handoff_status`, `plan_validation`, `quality.validation`,
   and `visual_review_required`.
5. If `created=false`, use `plan_validation.repairHints` before regenerating.

## Parser payload

```json
{
  "tool": "parse_government_report_text",
  "arguments": {
    "title": "2026년 AI 활용 교육 추진 현황 보고",
    "text": "Ⅰ. 추진 개요\n□ 주요 성과\n○ 교원 연수 128명 이수\n※ 세부 증빙은 별첨\n\n구분\t실적\t비고\n교원 연수\t128명\t기초·심화 과정 운영"
  }
}
```

The response contains `document_plan`, `plan_validation`, `can_create`, and
`next_tool`. When `can_create=true`, call `create_government_report_document`.

## Computed values

```jsonl
{"tool": "compute_report_value", "arguments": {"operation": "krw_hangul", "values": [8750000]}}
{"tool": "compute_report_value", "arguments": {"operation": "commas", "values": [12500000]}}
{"tool": "compute_report_value", "arguments": {"operation": "ratios", "values": [8750000, 12500000]}}
{"tool": "compute_report_value", "arguments": {"operation": "delta_percent", "values": [110, 100]}}
{"tool": "compute_report_value", "arguments": {"operation": "date", "values": ["2026. 6. 3."]}}
```

## Create payload

```json
{
  "tool": "create_government_report_document",
  "arguments": {
    "filename": "outputs/ai-government-report.hwpx",
    "document_plan": {
      "schemaVersion": "hwpx.document_plan.v2",
      "preset": "government_report",
      "title": "2026년 AI 활용 교육 추진 현황 보고",
      "metadata": {
        "title": "2026년 AI 활용 교육 추진 현황 보고",
        "author": "미래교육과",
        "organization": "샘플교육지원청"
      },
      "visualReviewRequired": true,
      "sections": [
        {
          "blocks": [
            {"type": "heading", "level": 1, "text": "Ⅰ. 추진 개요"},
            {"type": "paragraph", "text": "AI 활용 교육 사업의 추진 실적과 향후 조치 계획을 보고드림."},
            {"type": "bullets", "style": "square", "items": ["주요 성과: 교원 연수 및 학생 프로젝트 운영 확대"]},
            {"type": "bullets", "style": "circle", "items": ["교원 연수 128명 이수"]},
            {"type": "bullets", "style": "note", "items": ["세부 예산 집행 증빙은 별첨 자료로 관리"]},
            {
              "type": "table",
              "tableProfile": "government",
              "caption": "AI 활용 교육 추진 현황",
              "unit": "단위: 명, 팀",
              "header": ["구분", "실적", "비고"],
              "rows": [["교원 연수", "128", "기초·심화 과정 운영"]]
            }
          ]
        }
      ]
    }
  }
}
```

Expected success signals:

- `created == true`
- `style_preset == "government_report"`
- `quality_profile == "government_report"`
- `handoff_status == "ready"`
- `quality.validation.reopened == true`
- `quality.validation.validate_package.ok == true`
- `quality.validation.validate_document.ok == true`

If `created=false`, do not hand off the file. Repair the plan using
`plan_validation.repairHints`, then rerun the create tool.
