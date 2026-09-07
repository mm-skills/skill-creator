# Harness: Claude Code / Claude.ai / Cowork

This file contains all Claude-specific mechanics for the skill-creator workflow.
Read this file at the start of any skill-creator session when running in Claude Code,
Claude.ai, or Cowork. Apply these mechanics wherever the main SKILL.md says
"see harness file".

---

## 1. Skill registration

Skills are registered as command files in `.claude/commands/`:

```
<project-root>/.claude/commands/<skill-name>.md
```

The file uses YAML frontmatter with a `description` field. Claude's `available_skills`
list is populated from these files. The `run_eval.py` script creates and cleans up
these files automatically for each test query.

---

## 2. Subagent spawning

Claude Code supports parallel subagent execution. Use this prompt template for
with-skill runs:

```
Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/with_skill/outputs/
- Outputs to save: <what the user cares about — e.g., "the .docx file", "the final CSV">
```

For baseline runs (no skill):
```
Execute this task:
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/without_skill/outputs/
- Outputs to save: <same as above>
```

For improvement baseline (old skill version):
- Snapshot the skill first: `cp -r <skill-path> <workspace>/skill-snapshot/`
- Point the baseline subagent at the snapshot path

Spawn all with-skill AND baseline runs in the same turn — don't do with-skill first
then come back for baselines. Launch everything at once.

---

## 3. Task notification capture

When a subagent task completes, the completion notification contains `total_tokens`
and `duration_ms`. **Capture these immediately** — they are not persisted anywhere
else and cannot be recovered after the fact.

Save to `timing.json` in the run directory:

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3,
  "executor_start": "2026-01-15T10:30:00Z",
  "executor_end": "2026-01-15T10:32:45Z",
  "executor_duration_seconds": 165.0
}
```

Process each notification as it arrives rather than trying to batch them.

---

## 4. Grading

Spawn a grader subagent (or grade inline) that reads `agents/grader.md`.

For assertions that can be checked programmatically, write and run a script rather
than eyeballing it — scripts are faster, more reliable, and can be reused.

The `grading.json` expectations array must use the fields `text`, `passed`, and
`evidence` (not `name`/`met`/`details`) — the eval viewer depends on these exact names.

---

## 5. Aggregation

Run the aggregation script from the skill-creator directory:

```bash
python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
```

This produces `benchmark.json` and `benchmark.md`. Put each `with_skill` version
before its baseline counterpart.

---

## 6. Eval viewer

Launch the viewer after aggregation:

```bash
nohup python <skill-creator-path>/eval-viewer/generate_review.py \
  <workspace>/iteration-N \
  --skill-name "my-skill" \
  --benchmark <workspace>/iteration-N/benchmark.json \
  > /dev/null 2>&1 &
VIEWER_PID=$!
```

For iteration 2+, also pass `--previous-workspace <workspace>/iteration-<N-1>`.

**Cowork / headless environments**: Use `--static <output_path>` to write a
standalone HTML file instead of starting a server. The user can open it in their
browser. Feedback will be downloaded as `feedback.json` when they click
"Submit All Reviews". Copy `feedback.json` into the workspace directory for the
next iteration to pick up.

Kill the viewer when done:

```bash
kill $VIEWER_PID 2>/dev/null
```

**Important (especially in Cowork)**: ALWAYS generate the eval viewer BEFORE
evaluating inputs yourself and making skill revisions. Get outputs in front of
the human first.

Tell the user: "I've opened the results in your browser. There are two tabs —
'Outputs' lets you click through each test case and leave feedback, 'Benchmark'
shows the quantitative comparison. When you're done, come back here and let me know."

---

## 7. Description optimization

The description optimizer requires the `claude` CLI (`claude -p`). Run it from
the skill-creator directory:

```bash
python -m scripts.run_loop \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --model <model-id-powering-this-session> \
  --max-iterations 5 \
  --verbose
```

Use the model ID from your system prompt (the one powering the current session)
so the triggering test matches what the user actually experiences.

The loop automatically splits the eval set 60/40 train/test, runs each query
3x for reliability, proposes improvements on failures, and returns
`best_description` selected by test score to avoid overfitting.

While it runs, periodically tail output to give the user iteration updates.

**Claude.ai**: Skip description optimization — `claude -p` is not available.
**Cowork**: This works fine — `claude -p` via subprocess is supported.

---

## 8. Packaging and presenting

Check whether you have access to the `present_files` tool before packaging:

```bash
python -m scripts.package_skill <path/to/skill-folder>
```

If `present_files` is available, use it to deliver the `.skill` file to the user.
If not, tell the user the path to the `.skill` file so they can download it.

---

## 9. Task tracking

Use Claude Code's built-in `TodoList` tool to track steps during the workflow.

---

## 10. Claude.ai adaptations

Claude.ai doesn't have subagents. Adapt as follows:

- **Running test cases**: Read the skill's SKILL.md, then follow its instructions
  to accomplish the test prompt yourself. Do them one at a time. Skip baseline runs.
- **Reviewing results**: No browser. Present results directly in the conversation.
  For file outputs (.docx, .xlsx, etc.), save to the filesystem and tell the user
  the path so they can download and inspect. Ask for feedback inline.
- **Benchmarking**: Skip quantitative benchmarking — baseline comparisons aren't
  meaningful without subagents. Focus on qualitative user feedback.
- **Description optimization**: Skip — requires `claude -p` CLI.
- **Blind comparison**: Skip — requires subagents.
- **Packaging**: `package_skill.py` works — user can download the `.skill` file.
- **Updating an existing skill**: Preserve the original `name`. Copy to a writable
  location (e.g. `/tmp/skill-name/`) before editing if the install path is read-only.

---

## 11. Cowork adaptations

Cowork has subagents and Python but no browser/display:

- Main workflow (parallel spawning, baselines, grading) works normally.
- If severe timeout issues arise, run test prompts in series rather than parallel.
- **Eval viewer**: Always use `--static <output_path>`. Proffer a link to the HTML
  file so the user can open it in their browser.
- **Feedback**: The viewer's "Submit All Reviews" button downloads `feedback.json`.
  You may need to request file access first.
- **Description optimization**: Works — `claude -p` via subprocess is supported.
  Save until the skill is in good shape and the user agrees.
- **Updating an existing skill**: Follow the Claude.ai update guidance above.
