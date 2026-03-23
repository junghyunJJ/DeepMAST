"""Re-run only the blinded judge panel for existing V3 trials."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from benchmark_core import (
    CASES_DIR,
    HUMAN_AUDIT_TEMPLATE_FIELDS,
    STAGE2_INTERPRETATION_V3_BENCHMARK,
    VARIANT_A,
    VARIANT_B,
    aggregate_panel_verdict,
    build_human_audit_template_rows,
    create_llm,
    default_results_paths,
    load_cases,
    render_research_markdown_summary,
    research_results_paths,
    run_single_research_judge,
    save_csv,
    save_json,
    save_jsonl,
    select_human_audit_cases,
    select_v3_judge_keys,
    summarize_human_audit_results,
    summarize_judgments,
    summarize_research_panel,
    summarize_trials,
)

DEFAULT_JUDGE_MODELS = "ollama:qwen3.5:35b,ollama:gpt-oss:20b,ollama:qwen3:30b"


def _parse_judge_models(raw: str) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for token in [part.strip() for part in raw.split(",") if part.strip()]:
        provider, _, model_name = token.partition(":")
        configs.append(
            {
                "label": token,
                "provider": provider,
                "model_kwargs": {"model": model_name, "temperature": 0},
            }
        )
    return configs


def _load_trials(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", required=True, help="Existing V3 trials.jsonl path")
    parser.add_argument("--stem", required=True, help="Output stem for rejudge artifacts")
    parser.add_argument("--judge-models", default=DEFAULT_JUDGE_MODELS)
    return parser.parse_args()


async def _run_rejudge(args: argparse.Namespace) -> dict[str, Any]:
    trials = _load_trials(Path(args.trials))
    summary = summarize_trials(trials)
    cases = load_cases(CASES_DIR / "stage2_interpretation_v3_cases.json")
    cases = [case for case in cases if case["benchmark_type"] == STAGE2_INTERPRETATION_V3_BENCHMARK]
    case_map = {case["case_id"]: case for case in cases}

    trial_pairs: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = {}
    for trial in trials:
        key = (trial["case_id"], int(trial.get("repeat_index", 0)), trial["model"])
        trial_pairs.setdefault(key, {})[trial["variant"]] = trial

    judge_cfgs = _parse_judge_models(args.judge_models)
    judge_panel = [
        (cfg["label"], create_llm(provider=cfg["provider"], **cfg["model_kwargs"]))
        for cfg in judge_cfgs
    ]

    selected_keys = select_v3_judge_keys(trial_pairs)
    research_judges: list[dict[str, Any]] = []
    judgments: list[dict[str, Any]] = []
    for (case_id, repeat_index, model_label), pair in trial_pairs.items():
        if (case_id, repeat_index, model_label) not in selected_keys:
            continue
        if VARIANT_A not in pair or VARIANT_B not in pair:
            continue
        judge_rows_for_pair: list[dict[str, Any]] = []
        for judge_label, judge_llm in judge_panel:
            judge_row = await run_single_research_judge(
                judge_llm=judge_llm,
                judge_label=judge_label,
                case=case_map[case_id],
                repeat_index=repeat_index,
                trial_a=pair[VARIANT_A],
                trial_b=pair[VARIANT_B],
            )
            judge_row["model"] = model_label
            research_judges.append(judge_row)
            judge_rows_for_pair.append(judge_row)
        judgments.append(
            aggregate_panel_verdict(
                case_id=case_id,
                repeat_index=repeat_index,
                model_label=model_label,
                judge_rows=judge_rows_for_pair,
            )
        )

    judgment_summary = summarize_judgments(judgments)
    research_panel_summary = summarize_research_panel(judgments, research_judges)
    audit_queue = select_human_audit_cases(
        panel_verdicts=judgments,
        trial_pairs=trial_pairs,
        case_map=case_map,
    )
    human_audit_summary = summarize_human_audit_results(
        panel_verdicts=judgments,
        audit_queue=audit_queue,
        completed_rows=[],
    )

    return {
        "trials": trials,
        "summary": summary,
        "judgments": judgments,
        "judgment_summary": judgment_summary,
        "research_judges": research_judges,
        "research_panel_summary": research_panel_summary,
        "human_audit_queue": audit_queue,
        "human_audit_summary": human_audit_summary,
    }


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = asyncio.run(_run_rejudge(args))

    paths = default_results_paths(args.stem)
    research_paths = research_results_paths(args.stem)
    if result["judgments"]:
        save_jsonl(paths["judgments_jsonl"], result["judgments"])
    save_jsonl(research_paths["research_judges_jsonl"], result["research_judges"])
    save_json(research_paths["research_panel_summary_json"], result["research_panel_summary"] or {})
    save_jsonl(research_paths["human_audit_queue_jsonl"], result["human_audit_queue"])
    save_csv(
        research_paths["human_audit_template_csv"],
        HUMAN_AUDIT_TEMPLATE_FIELDS,
        build_human_audit_template_rows(result["human_audit_queue"]),
    )
    save_json(research_paths["human_audit_summary_json"], result["human_audit_summary"])
    research_markdown = render_research_markdown_summary(
        benchmark_title="DrugTarget Skill Exposure Benchmark V3 — Rejudge",
        summary=result["summary"],
        panel_summary=result["research_panel_summary"],
        human_audit_summary=result["human_audit_summary"],
    )
    Path(research_paths["research_results_md"]).write_text(research_markdown, encoding="utf-8")

    print(research_paths["research_judges_jsonl"])
    print(research_paths["research_panel_summary_json"])
    print(research_paths["research_results_md"])


if __name__ == "__main__":
    main()
