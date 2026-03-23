"""Run a temperature sweep for the V3 DrugTarget interpretation benchmark."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
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
    load_human_audit_results,
    load_judge_model_configs,
    render_markdown_summary,
    render_research_markdown_summary,
    research_results_paths,
    run_single_research_judge,
    run_single_trial,
    save_csv,
    save_json,
    save_jsonl,
    select_human_audit_cases,
    summarize_human_audit_results,
    summarize_judgments,
    summarize_research_panel,
    summarize_trials,
)

DEFAULT_STEM_PREFIX = "stage2_interpretation_v3_qwen35_122b"


def _parse_temperature_list(raw: str) -> list[float]:
    values: list[float] = []
    for token in [part.strip() for part in raw.split(",") if part.strip()]:
        values.append(float(token))
    if not values:
        raise ValueError("At least one temperature is required")
    return values


def _temperature_token(temp: float) -> str:
    value = int(round(temp * 10))
    return f"t{value:02d}"


def _build_stem(prefix: str, temp: float, repeats: int) -> str:
    return f"{prefix}_{_temperature_token(temp)}_r{repeats}"


def _parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    raise ValueError(f"Invalid boolean flag: {raw}")


def _generator_model_config(*, model: str, temperature: float, repeats: int) -> dict[str, Any]:
    return {
        "label": f"ollama:{model}@temp={temperature:.1f}",
        "provider": "ollama",
        "model_kwargs": {"model": model, "temperature": temperature},
        "repeats": repeats,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3.5:122b")
    parser.add_argument("--temperatures", default="0.0,0.2,0.3,0.4")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--include-judge", default="false", choices=["true", "false"])
    parser.add_argument("--stem-prefix", default=DEFAULT_STEM_PREFIX)
    return parser.parse_args()


async def _run_single_temperature(
    *,
    model: str,
    temperature: float,
    repeats: int,
    include_judge: bool,
    stem_prefix: str,
) -> dict[str, Any]:
    cases = load_cases(CASES_DIR / "stage2_interpretation_v3_cases.json")
    cases = [case for case in cases if case["benchmark_type"] == STAGE2_INTERPRETATION_V3_BENCHMARK]
    case_map = {case["case_id"]: case for case in cases}

    model_cfg = _generator_model_config(model=model, temperature=temperature, repeats=repeats)
    llm = create_llm(provider=model_cfg["provider"], **model_cfg["model_kwargs"])

    trials: list[dict[str, Any]] = []
    for repeat_index in range(repeats):
        for case in cases:
            for variant in (VARIANT_A, VARIANT_B):
                trial = await run_single_trial(llm=llm, case=case, variant=variant)
                trial["model"] = model_cfg["label"]
                trial["repeat_index"] = repeat_index
                trials.append(trial)

    summary = summarize_trials(trials)
    judgments: list[dict[str, Any]] = []
    research_judges: list[dict[str, Any]] = []
    research_panel_summary = None
    judgment_summary = None
    audit_queue: list[dict[str, Any]] = []
    human_audit_summary = {
        "queued_count": 0,
        "completed_count": 0,
        "pending_count": 0,
        "agreement_rate": None,
        VARIANT_A: 0,
        VARIANT_B: 0,
        "tie": 0,
        "sign_test_pvalue": None,
        "completed_packets": [],
    }

    if include_judge:
        judge_cfgs = load_judge_model_configs(model_cfg)
        judge_panel = [
            (judge_cfg["label"], create_llm(provider=judge_cfg["provider"], **judge_cfg["model_kwargs"]))
            for judge_cfg in judge_cfgs
        ]
        trial_pairs: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = {}
        for trial in trials:
            key = (trial["case_id"], int(trial.get("repeat_index", 0)), trial["model"])
            trial_pairs.setdefault(key, {})[trial["variant"]] = trial

        for (case_id, repeat_index, model_label), pair in trial_pairs.items():
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

        trial_pairs = {}
        for trial in trials:
            key = (trial["case_id"], int(trial.get("repeat_index", 0)), trial["model"])
            trial_pairs.setdefault(key, {})[trial["variant"]] = trial
        audit_queue = select_human_audit_cases(
            panel_verdicts=judgments,
            trial_pairs=trial_pairs,
            case_map=case_map,
        )
        human_results_path = os.getenv("DRUGTARGET_BENCHMARK_HUMAN_AUDIT_RESULTS", "").strip()
        completed_human_audits = load_human_audit_results(human_results_path) if human_results_path else []
        human_audit_summary = summarize_human_audit_results(
            panel_verdicts=judgments,
            audit_queue=audit_queue,
            completed_rows=completed_human_audits,
        )

    stem = _build_stem(stem_prefix, temperature, repeats)
    paths = default_results_paths(stem)
    save_jsonl(paths["trials_jsonl"], trials)
    save_json(paths["summary_json"], summary)
    markdown = render_markdown_summary(
        benchmark_title=f"DrugTarget Skill Exposure Benchmark V3 — Sweep {temperature:.1f}",
        summary=summary,
        judgment_summary=judgment_summary,
    )
    Path(paths["results_md"]).write_text(markdown, encoding="utf-8")

    if include_judge:
        research_paths = research_results_paths(stem)
        if judgments:
            save_jsonl(paths["judgments_jsonl"], judgments)
        save_jsonl(research_paths["research_judges_jsonl"], research_judges)
        save_json(research_paths["research_panel_summary_json"], research_panel_summary or {})
        save_jsonl(research_paths["human_audit_queue_jsonl"], audit_queue)
        save_csv(
            research_paths["human_audit_template_csv"],
            HUMAN_AUDIT_TEMPLATE_FIELDS,
            build_human_audit_template_rows(audit_queue),
        )
        save_json(research_paths["human_audit_summary_json"], human_audit_summary)
        research_markdown = render_research_markdown_summary(
            benchmark_title=f"DrugTarget Skill Exposure Benchmark V3 — Sweep {temperature:.1f}",
            summary=summary,
            panel_summary=research_panel_summary,
            human_audit_summary=human_audit_summary,
        )
        Path(research_paths["research_results_md"]).write_text(research_markdown, encoding="utf-8")

    return {"temperature": temperature, "stem": stem, "summary": summary}


async def _run_all(args: argparse.Namespace) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    temperatures = _parse_temperature_list(args.temperatures)
    include_judge = _parse_bool(args.include_judge)
    for temperature in temperatures:
        logging.info("Running V3 sweep temperature %.1f", temperature)
        result = await _run_single_temperature(
            model=args.model,
            temperature=temperature,
            repeats=args.repeats,
            include_judge=include_judge,
            stem_prefix=args.stem_prefix,
        )
        results.append(result)
    return results


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    results = asyncio.run(_run_all(args))
    for item in results:
        print(item["stem"])
        print(item["summary"])


if __name__ == "__main__":
    main()
