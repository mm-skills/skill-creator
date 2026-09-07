# Harness: Antigravity (AGY / Gemini)

This file contains all Antigravity-specific mechanics for the skill-creator workflow.
Read this file at the start of any skill-creator session when running in Antigravity
(AGY). Apply these mechanics wherever the main SKILL.md says "see harness file".

---

## 1. Skill registration

In AGY, skills are registered as directories containing `SKILL.md` in the global
skills config path:

```
~/.gemini/config/skills/<skill-name>/SKILL.md
```

The `name` field in the YAML frontmatter and the directory name must match.
AGY's `available_skills` list is populated from these directories automatically.

For project-scoped skills, use:
```
<project-root>/.agents/skills/<skill-name>/SKILL.md
```

The `run_eval_agy.py` script simulates skill selection by calling the Gemini API
with a structured system prompt — no temporary file registration needed.

---

## 2. Subagent spawning

AGY supports parallel subagent execution via the `invoke_subagent` tool.

**With-skill run** — pass the skill path in the prompt:

```
Execute this task using the skill at <path-to-skill>:
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/with_skill/outputs/
- Outputs to save: <what the user cares about — e.g., "the .docx file", "the final CSV">

Read the skill's SKILL.md first, then follow its instructions to complete the task.
```

**Baseline run** (no skill):

```
Execute this task without any skill guidance:
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/without_skill/outputs/
- Outputs to save: <same as above>
```

Use `Workspace: "branch"` in `invoke_subagent` to give each subagent an isolated
workspace. Spawn all with-skill AND baseline runs in the same `invoke_subagent`
call — don't launch with-skill first and come back for baselines.

**AGY tool names** (use these in subagent prompts, not Claude tool names):
- File read: `view_file` (not `Read`)
- File write: `write_to_file` / `replace_file_content` (not `Write`/`Edit`)
- Shell commands: `run_command` (not `Bash`)
- Web search: `search_web`

---

## 3. Task notification capture

When a subagent completes, AGY delivers a completion message to your inbox
containing `total_tokens` and `duration_ms`. **Capture these immediately** —
they are not persisted anywhere else.

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

Process each message as it arrives rather than batching them.

---

## 4. Grading

Spawn a grader subagent that reads `agents/grader.md`, or grade inline.

For assertions that can be checked programmatically, use `run_command` to execute
a validation script rather than eyeballing it.

The `grading.json` expectations array must use `text`, `passed`, and `evidence`
fields — the eval viewer depends on these exact names.

---

## 5. Aggregation

Run the aggregation script using `run_command`:

```bash
python3 -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
```

Note: use `python3` not `python` on macOS. Run from the skill-creator directory.

---

## 6. Eval viewer

AGY has no browser/display. Always use `--static` to generate a standalone HTML file:

```bash
python3 <skill-creator-path>/eval-viewer/generate_review.py \
  <workspace>/iteration-N \
  --skill-name "my-skill" \
  --benchmark <workspace>/iteration-N/benchmark.json \
  --static <workspace>/iteration-N/review.html
```

For iteration 2+, also pass `--previous-workspace <workspace>/iteration-<N-1>`.

After generating, write the HTML as a `UserFacing: true` artifact so it appears
inline for the user, OR give them the absolute file path to open in their browser.

Feedback is downloaded as `feedback.json` when the user clicks "Submit All Reviews".
Copy `feedback.json` into the workspace directory before the next iteration.

**Always generate the eval viewer BEFORE evaluating inputs yourself.** Get outputs
in front of the human first.

Tell the user: "I've generated the results viewer at `<path>`. Open it in your
browser — the 'Outputs' tab lets you review each test case and leave feedback,
'Benchmark' shows the quantitative stats. Come back when you're done."

---

## 7. Description optimization

The AGY description optimizer uses the Gemini API instead of `claude -p`.
Run from the skill-creator directory using `run_command`:

```bash
python3 -m scripts.run_loop_agy \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --model <gemini-model-id> \
  --max-iterations 5 \
  --verbose
```

**Finding your model ID**: Check the AGY system prompt for the current model name
(e.g. `gemini-2.5-pro-preview-06-05`, `gemini-2.0-flash`). Use this so the
triggering test matches what the user actually experiences.

**Auth**: The scripts use Application Default Credentials (ADC) automatically —
`gcloud auth application-default login` should already be configured in AGY sessions.
No `GOOGLE_API_KEY` needed.

The loop behaviour is identical to the Claude version: 60/40 train/test split,
3 runs per query, up to 5 improvement iterations, `best_description` selected by
test score.

---

## 8. Packaging and presenting

AGY does not have a `present_files` tool. After running `package_skill.py`:

```bash
python3 -m scripts.package_skill <path/to/skill-folder>
```

Write the resulting `.skill` file as a `UserFacing: true` artifact using
`write_to_file`, or tell the user the absolute path to the file.

---

## 9. Task tracking

In AGY planning mode, use the `task.md` artifact to track steps (equivalent to
Claude Code's `TodoList` tool). Create or update `task.md` with `[ ]` / `[/]` / `[x]`
checkboxes as you progress through the workflow.

---

## 10. AGY-specific notes

- AGY always has subagents — no single-agent fallback mode needed.
- AGY sessions are persistent and stateful — you can refer back to earlier steps.
- Use `run_command` for all shell operations, not inline code execution.
- Use `view_file` to read files (supports line ranges, content offsets for large files).
- Use `write_to_file` for new files and `replace_file_content` for targeted edits.
- Use `search_web` or `read_url_content` for research tasks.
- The `generate_report.py` and `aggregate_benchmark.py` scripts are harness-neutral
  and work as-is with `python3`.
