# MCP Operating Plan Workflow

Use this when an MCP client is connected to `hwpx-mcp-server` from the operating-plan stack.

## 1. Validate Without Writing

```json
{
  "tool": "validate_document_plan",
  "arguments": {
    "document_plan": {
      "schemaVersion": "hwpx.document_plan.v1",
      "title": "2026 AI 중점학교 운영계획서",
      "metadata": {
        "organization": "샘플고등학교",
        "author": "AI교육기획팀",
        "date": "2026-05-14",
        "document_type": "operating_plan"
      },
      "blocks": [
        {"type": "heading", "level": 1, "text": "Ⅰ. 신청 목적"},
        {"type": "paragraph", "text": "학교의 AI·디지털 기반 수업 역량을 강화하기 위한 운영 방향을 제시한다."}
      ],
      "qualityGates": {
        "validatePackage": true,
        "validateDocument": true,
        "reopen": true,
        "minTableCount": 2,
        "visualReviewRequired": true
      }
    }
  }
}
```

If `ok=false`, fix `issues[].path` and `repairHints[]`. Do not create a file.

## 2. Analyze Without Writing

```json
{
  "tool": "analyze_document_plan",
  "arguments": {
    "document_plan": "<same plan>",
    "destination_filename": "outputs/operating-plan.hwpx",
    "quality_profile": "operating_plan"
  }
}
```

Expected fields:

```json
{
  "mutated": false,
  "can_create": true,
  "handoff_status": "ready",
  "quality_preview": {
    "profiles": {
      "operating_plan": {
        "pass": true,
        "score": 5.0,
        "gaps": [],
        "repair_hints": []
      }
    }
  }
}
```

If `handoff_status` is `needs_revision`, revise the plan before creating.

## 3. Create Explicitly

```json
{
  "tool": "create_document_from_plan",
  "arguments": {
    "filename": "outputs/operating-plan.hwpx",
    "document_plan": "<validated plan>",
    "quality_profile": "operating_plan"
  }
}
```

Required handoff evidence:

- `created == true`
- `handoff_status == "ready"`
- `quality.validation.reopened == true`
- `quality.validation.validate_package.ok == true`
- `quality.validation.validate_document.ok == true`
- `quality.profiles.operating_plan.pass == true`

## 4. Read Back Generated Content

Use:

```json
{"tool": "get_document_text", "arguments": {"filename": "outputs/operating-plan.hwpx"}}
```

and table checks such as:

```json
{"tool": "get_table_text", "arguments": {"filename": "outputs/operating-plan.hwpx", "table_index": 1}}
```

## Limitations

`visual_review_required=true` means package/schema/profile checks passed, but final submission still needs rendered or human visual review for form fit.
