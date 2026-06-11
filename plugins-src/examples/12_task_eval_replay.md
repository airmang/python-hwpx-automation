# HWPX Task Evaluation Replay

Use this harness when a plugin change needs a cheap, repeatable quality signal
before manual HWPX viewer review.

```bash
python3 scripts/task_eval_harness.py \
  --tasks examples/eval_tasks/tasks.json \
  --profile examples/eval_tasks/profiles/current-0.1.6.json \
  --profile examples/eval_tasks/profiles/baseline-0.1.5.json \
  --output examples/out/task_eval_report.json \
  --markdown examples/out/task_eval_report.md \
  --work-dir examples/out/task_eval_work
```

The task file schema is `hwpx.task-replay.v1`.

- `id`: stable task id, grouped by `family`.
- `instruction`: the natural-language user request being represented.
- `startDocument`: seed document kind plus optional paragraphs/tables.
- `requiredTools`: MCP tools the task expects the plugin to expose.
- `requiredGuidance`: optional skill guidance tags a profile must claim.
- `toolCalls`: replayable MCP-style call sequence with `{document}`,
  `{workDir}`, and `{outputDir}` placeholders.
- `oracles`: automatic checks such as text presence, table shape/cells,
  generated files, and `open_safety`.

Profiles model plugin versions. The current profile can expose `"*"`, while an
older profile may list only known tools, mark `brokenTools`, or omit
`guidanceTags`. The report classifies failed tasks as:

- `tool_absent`: a required tool is missing from the profile.
- `tool_misbehavior`: a tool is marked broken, raises, or fails an oracle.
- `skill_guidance_gap`: the profile lacks required task guidance.

To add a case, copy an existing task in `examples/eval_tasks/tasks.json`, keep
the id stable and descriptive, add at least one oracle that would fail on a
wrong result, then run the harness and the pytest suite. Prefer small documents:
the goal is regression triage, not visual approval.
