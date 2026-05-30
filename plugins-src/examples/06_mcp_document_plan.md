# MCP document-plan workflow

Use this when an MCP client has `hwpx-mcp-server` connected and the user asks
for a new HWPX document, report, form draft, meeting record, or operating plan.

## Flow

1. Normalize the request into `hwpx.document_plan.v1`.
2. Call `validate_document_plan` first. This does not write a file.
3. Call `create_document_from_plan` with the target filename.
4. Check `quality.validation.reopened`, `validate_package.ok`,
   `validate_document.ok`, and `visual_review_required`.
5. If quality gates fail, revise the plan and regenerate.

## Recovery loop

If `validate_document_plan` returns `ok=false`, do not call
`create_document_from_plan` yet. Read the structured fields, repair the JSON
plan, then rerun validation:

```json
{
  "ok": false,
  "can_create": false,
  "issues": [
    {
      "code": "invalid_table_row",
      "path": "blocks[3].rows[0]",
      "message": "blocks[3].rows[0] must be a mapping",
      "severity": "error",
      "suggestion": "Use a row object whose keys match the table columns."
    }
  ],
  "repairHints": [
    {
      "path": "blocks[3].rows[0]",
      "code": "invalid_table_row",
      "action": "fix",
      "message": "Use a row object whose keys match the table columns."
    }
  ],
  "next_action": "repair document_plan using repairHints, then rerun validate_document_plan"
}
```

For table issues, align `columns[].key` with every row object. Missing row keys
become blank generated cells, but extra keys are ignored. For style warnings,
use `body`, `title`, `subtitle`, `heading`, `bullet`, `table_header`,
`table_cell`, or omit `style`.

## Example tool payload

```json
{
  "filename": "outputs/ai-education-plan.hwpx",
  "document_plan": {
    "schemaVersion": "hwpx.document_plan.v1",
    "title": "2026 AI Education Operating Plan",
    "metadata": {
      "organization": "Sample School",
      "date": "2026-05-09"
    },
    "blocks": [
      {"type": "heading", "level": 1, "text": "Executive Summary"},
      {"type": "paragraph", "text": "The plan connects lessons, teacher training, and outcome review."},
      {"type": "bullets", "items": ["Run grade-band AI lessons.", "Review outcomes each term."]},
      {
        "type": "table",
        "caption": "Budget Plan",
        "columns": [
          {"key": "item", "label": "Item", "widthWeight": 2},
          {"key": "amount", "label": "Amount", "widthWeight": 1}
        ],
        "rows": [
          {"item": "AI devices", "amount": "5,000,000 KRW"}
        ]
      }
    ],
    "qualityGates": {
      "validatePackage": true,
      "validateDocument": true,
      "reopen": true,
      "visualReviewRequired": true
    }
  }
}
```

`visual_review_required=true` means the generated HWPX passed structural checks
but was not visually rendered or pixel-reviewed.
