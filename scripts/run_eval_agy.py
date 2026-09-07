#!/usr/bin/env python3
"""Run trigger evaluation for a skill description against Gemini/AGY.

Drop-in equivalent of run_eval.py for the Antigravity harness.
Uses the Gemini API (google-generativeai SDK) instead of claude -p.

Auth priority:
  1. GOOGLE_API_KEY environment variable
  2. Application Default Credentials (ADC) via gcloud auth application-default login
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.utils import parse_skill_md


# System prompt template that simulates AGY's skill-selection mechanism.
# The model is instructed to emit a detectable trigger phrase if it decides
# to invoke the skill — mirroring how Claude Code emits a Skill/Read tool call.
_SYSTEM_PROMPT_TEMPLATE = """\
You are an AI assistant with access to the following specialized skills.
When a user's request would meaningfully benefit from using a skill, start
your response with the exact phrase:
  READING SKILL: {skill_name}

Available skills:
- {skill_name}: {skill_description}

Only read the skill if it is genuinely relevant and needed for the request.
For simple questions you can answer directly from your knowledge, do not
read a skill.
"""


def _configure_genai(api_key: str | None = None) -> None:
    """Configure the google-generativeai SDK with auth.

    Falls back to Application Default Credentials if no API key is set.
    Calling configure() with api_key=None is a no-op, so ADC is used
    automatically when the SDK makes its first API call.
    """
    try:
        import google.generativeai as genai
        if api_key:
            genai.configure(api_key=api_key)
        # If no key: SDK uses ADC automatically (gcloud auth application-default)
    except ImportError:
        print(
            "Error: google-generativeai not installed.\n"
            "Install with: pip install google-generativeai",
            file=sys.stderr,
        )
        sys.exit(1)


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    model: str,
    api_key: str | None = None,
) -> bool:
    """Run a single query against Gemini and return whether the skill was triggered.

    Triggering is detected by checking whether the model's response starts with
    (or prominently contains within the first 300 characters) the trigger phrase
    "READING SKILL: <skill_name>".
    """
    import google.generativeai as genai

    _configure_genai(api_key)

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        skill_name=skill_name,
        skill_description=skill_description,
    )

    gemini_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_prompt,
    )

    response = gemini_model.generate_content(query)
    text = response.text.strip()

    trigger_phrase = f"READING SKILL: {skill_name}"
    # Check start or near-start of response (within first 300 chars)
    return trigger_phrase in text[:300]


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    runs_per_query: int,
    trigger_threshold: float,
    model: str,
    api_key: str | None = None,
    verbose: bool = False,
) -> dict:
    """Run the full eval set against Gemini and return results.

    Output schema is identical to run_eval.py so run_loop_agy.py can
    consume it without any changes.
    """
    results = []

    # Use ThreadPoolExecutor (not ProcessPoolExecutor) — API calls are I/O bound
    # and don't need separate processes.
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_to_info: dict = {}
        for item in eval_set:
            for run_idx in range(runs_per_query):
                future = executor.submit(
                    run_single_query,
                    item["query"],
                    skill_name,
                    description,
                    model,
                    api_key,
                )
                future_to_info[future] = (item, run_idx)

        query_triggers: dict[str, list[bool]] = {}
        query_items: dict[str, dict] = {}

        for future in as_completed(future_to_info):
            item, _ = future_to_info[future]
            query = item["query"]
            query_items[query] = item
            if query not in query_triggers:
                query_triggers[query] = []
            try:
                triggered = future.result()
                query_triggers[query].append(triggered)
                if verbose:
                    status = "TRIGGERED" if triggered else "no-trigger"
                    print(f"  [{status}] {query[:70]}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: query failed: {e}", file=sys.stderr)
                query_triggers[query].append(False)

    for query, triggers in query_triggers.items():
        item = query_items[query]
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        did_pass = (
            trigger_rate >= trigger_threshold
            if should_trigger
            else trigger_rate < trigger_threshold
        )
        results.append(
            {
                "query": query,
                "should_trigger": should_trigger,
                "trigger_rate": trigger_rate,
                "triggers": sum(triggers),
                "runs": len(triggers),
                "pass": did_pass,
            }
        )

    passed = sum(1 for r in results if r["pass"])
    total = len(results)

    return {
        "skill_name": skill_name,
        "description": description,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run trigger evaluation for a skill description (Antigravity/Gemini)"
    )
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument(
        "--description", default=None, help="Override description to test"
    )
    parser.add_argument(
        "--num-workers", type=int, default=10, help="Number of parallel workers"
    )
    parser.add_argument(
        "--runs-per-query",
        type=int,
        default=3,
        help="Number of runs per query for reliability",
    )
    parser.add_argument(
        "--trigger-threshold",
        type=float,
        default=0.5,
        help="Trigger rate threshold to count as triggered",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.0-flash",
        help="Gemini model name (default: gemini-2.0-flash)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Google API key (default: use ADC / GOOGLE_API_KEY env var)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print progress to stderr"
    )
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, original_description, _ = parse_skill_md(skill_path)
    description = args.description or original_description

    # Allow GOOGLE_API_KEY env var as fallback
    import os
    api_key = args.api_key or os.environ.get("GOOGLE_API_KEY")

    if args.verbose:
        print(f"Skill: {name}", file=sys.stderr)
        print(f"Model: {args.model}", file=sys.stderr)
        print(f"Evaluating description: {description[:100]}...", file=sys.stderr)
        print(f"Eval set: {len(eval_set)} queries × {args.runs_per_query} runs", file=sys.stderr)

    output = run_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        num_workers=args.num_workers,
        runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold,
        model=args.model,
        api_key=api_key,
        verbose=args.verbose,
    )

    if args.verbose:
        summary = output["summary"]
        print(
            f"Results: {summary['passed']}/{summary['total']} passed",
            file=sys.stderr,
        )
        for r in output["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            rate_str = f"{r['triggers']}/{r['runs']}"
            print(
                f"  [{status}] rate={rate_str} expected={r['should_trigger']}: "
                f"{r['query'][:70]}",
                file=sys.stderr,
            )

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
