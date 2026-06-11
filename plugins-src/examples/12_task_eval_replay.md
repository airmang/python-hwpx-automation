# HWPX Task Evaluation Replay

Use this harness when a plugin change needs a cheap, repeatable quality signal
before manual HWPX viewer review.

```bash
python3 scripts/task_eval_harness.py \
  --tasks examples/eval_tasks/tasks.json \
  --profile examples/eval_tasks/profiles/current-0.1.8.json \
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
- `skill_guidance_gap`: the skill bundle body or the profile lacks required
  task guidance.

Guidance scoring verifies the **skill bundle body**, not just profile tags:
every tool a task replays must literally appear in `SKILL.md` +
`references/*.md` (`--skill-root` overrides the bundle location), and each
`requiredGuidance` tag maps to keyword groups (`GUIDANCE_BODY_KEYWORDS` in
`scripts/task_eval_harness.py`) that must also appear in the body. A profile
tag without body evidence fails with `skill_guidance_gap` plus
`missingBundleTools`/`missingGuidanceEvidence` details. Oracles can also check
replayed call payloads with
`{"type": "call_result_has", "callIndex": N, "key": "..."}`.

To add a case, copy an existing task in `examples/eval_tasks/tasks.json`, keep
the id stable and descriptive, add at least one oracle that would fail on a
wrong result, then run the harness and the pytest suite. Prefer small documents:
the goal is regression triage, not visual approval.
