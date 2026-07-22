# HWPX Deterministic Direct-Call Replay

Use this harness when a plugin change needs a cheap, repeatable regression signal before
manual HWPX viewer review. It executes the `toolCalls` already selected in each task; it does
**not** give `instruction` to an agent and does not measure tool selection, routing, recovery,
or unnecessary calls. Never cite its score as live-agent evidence.

```bash
python3 scripts/task_eval_harness.py \
  --tasks examples/eval_tasks/tasks.json \
  --profile examples/eval_tasks/profiles/current-0.8.0.json \
  --profile examples/eval_tasks/profiles/current-0.1.6.json \
  --profile examples/eval_tasks/profiles/baseline-0.1.5.json \
  --output examples/out/deterministic_task_replay_report.json \
  --markdown examples/out/deterministic_task_replay_report.md \
  --work-dir examples/out/task_eval_work
```

The task file schema is `hwpx.task-replay.v1`.

- `id`: stable task id, grouped by `family`.
- `instruction`: the natural-language request represented as metadata. The harness does not
  use it to choose a tool.
- `startDocument`: seed document kind plus optional paragraphs/tables.
- `requiredTools`: MCP tools the task expects the plugin to expose.
- `requiredGuidance`: optional skill guidance tags a profile must claim.
- `toolCalls`: replayable MCP-style call sequence with `{document}`,
  `{workDir}`, and `{outputDir}` placeholders.
- `oracles`: automatic checks such as text presence, table shape/cells,
  generated files, and `open_safety`.

Profiles model plugin versions. The current profile resolves the exact default names from
`references/tool-contract.generated.json`; historical profiles may list names explicitly,
mark `brokenTools`, or omit `guidanceTags`. The report classifies failed tasks as:

- `tool_absent`: a required tool is missing from the profile.
- `tool_misbehavior`: a tool is marked broken, raises, or fails an oracle.
- `skill_guidance_gap`: the skill bundle body or the profile lacks required
  task guidance.

Guidance scoring verifies the **authored skill bundle body**, not just profile tags:
every tool a task replays must literally appear in `SKILL.md` plus authored
`references/*.md` (`tool-contract.generated.md` is excluded; `--skill-root` overrides the bundle location), and each
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
