"""Run the main DrugTarget skill-ablation benchmark (Stage 2 synthesis only)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from benchmark_core import (
    CASES_DIR,
    MAIN_STAGE2_BENCHMARK,
    default_results_paths,
    HUMAN_AUDIT_TEMPLATE_FIELDS,
    render_research_markdown_summary,
    render_markdown_summary,
    research_results_paths,
    run_benchmark,
    save_csv,
    save_json,
    save_jsonl,
)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    result = asyncio.run(
        run_benchmark(
            benchmark_type=MAIN_STAGE2_BENCHMARK,
            cases_path=CASES_DIR / "stage2_synthesis_cases.json",
            include_judge=True,
        )
    )

    paths = default_results_paths("stage2_synthesis")
    research_paths = research_results_paths("stage2_synthesis")
    save_jsonl(paths["trials_jsonl"], result["trials"])
    save_json(paths["summary_json"], result["summary"])
    if result["judgments"]:
        save_jsonl(paths["judgments_jsonl"], result["judgments"])
    save_jsonl(research_paths["research_judges_jsonl"], result["research_judges"])
    save_json(
        research_paths["research_panel_summary_json"],
        result["research_panel_summary"] or {},
    )
    save_jsonl(research_paths["human_audit_queue_jsonl"], result["human_audit_queue"])
    save_csv(
        research_paths["human_audit_template_csv"],
        HUMAN_AUDIT_TEMPLATE_FIELDS,
        result["human_audit_template_rows"],
    )
    save_json(
        research_paths["human_audit_summary_json"],
        result["human_audit_summary"],
    )

    markdown = render_markdown_summary(
        benchmark_title="DrugTarget Skill Exposure Benchmark — Stage 2 Synthesis",
        summary=result["summary"],
        judgment_summary=result["judgment_summary"],
    )
    Path(paths["results_md"]).write_text(markdown, encoding="utf-8")
    research_markdown = render_research_markdown_summary(
        benchmark_title="DrugTarget Skill Exposure Benchmark — Stage 2 Synthesis",
        summary=result["summary"],
        panel_summary=result["research_panel_summary"],
        human_audit_summary=result["human_audit_summary"],
    )
    Path(research_paths["research_results_md"]).write_text(research_markdown, encoding="utf-8")

    print(f"Saved trials to: {paths['trials_jsonl']}")
    print(f"Saved summary to: {paths['summary_json']}")
    if result["judgments"]:
        print(f"Saved judgments to: {paths['judgments_jsonl']}")
    print(f"Saved markdown report to: {paths['results_md']}")
    print(f"Saved research judge rows to: {research_paths['research_judges_jsonl']}")
    print(f"Saved research panel summary to: {research_paths['research_panel_summary_json']}")
    print(f"Saved human audit queue to: {research_paths['human_audit_queue_jsonl']}")
    print(f"Saved human audit template to: {research_paths['human_audit_template_csv']}")
    print(f"Saved human audit summary to: {research_paths['human_audit_summary_json']}")
    print(f"Saved research markdown report to: {research_paths['research_results_md']}")


if __name__ == "__main__":
    main()
