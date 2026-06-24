from __future__ import annotations

import subprocess
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = PROJECT_ROOT / "benchmarks" / "cci_skill_ablation"


def test_public_bundle_has_lr_retrieval_style_layout() -> None:
    expected = {
        "README.md",
        ".gitignore",
        "inputs/cci_full_cases.json",
        "inputs/pilot_cci_cases.json",
        "scripts/benchmark_cci_core.py",
        "scripts/run_cci_skill_ablation.py",
        "scripts/reproduce_offline.sh",
        "scripts/reproduce_live.sh",
        "scripts/export_figure_data.py",
        "scripts/figure_table3_results.R",
        "scripts/s_figure_table3_results.R",
        "results/full_cci_v2_D_guide_trials.jsonl",
        "results/full_cci_v2_D_guide_summary.json",
        "results/full_cci_v2_D_guide_results.md",
        "results/figure_tables/fabrication_counts.csv",
        "results/figure_tables/main_condition_scores.csv",
        "results/figure_tables/supplementary_condition_scores.csv",
        "figures/SkillAblation.png",
        "figures/SkillAblation.svg",
        "figures/s_SkillAblation.png",
        "metadata/source_paths.md",
        "metadata/manifest.json",
    }

    missing = [rel for rel in sorted(expected) if not (BUNDLE / rel).exists()]

    assert missing == []


def test_public_bundle_excludes_local_temp_artifacts() -> None:
    forbidden_names = {".DS_Store", ".Rhistory", "__pycache__"}
    found = [
        path.relative_to(BUNDLE).as_posix()
        for path in BUNDLE.rglob("*")
        if path.name in forbidden_names
    ]

    assert found == []


def test_reference_results_are_not_gitignored() -> None:
    result_paths = [
        "results/full_cci_v2_D_guide_trials.jsonl",
        "results/full_cci_v2_D_guide_summary.json",
        "results/figure_tables/main_condition_scores.csv",
    ]

    for rel_path in result_paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(BUNDLE / rel_path)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        assert result.returncode == 1, rel_path


def test_public_scripts_are_repo_relative() -> None:
    scripts = [
        BUNDLE / "scripts" / "reproduce_offline.sh",
        BUNDLE / "scripts" / "reproduce_live.sh",
        BUNDLE / "scripts" / "figure_table3_results.R",
        BUNDLE / "scripts" / "s_figure_table3_results.R",
    ]

    for script in scripts:
        text = script.read_text(encoding="utf-8")
        assert "/Users/jungj2" not in text
        assert "docs/benchmarks/cci_skill_ablation" not in text


def test_offline_reproduction_regenerates_summary_without_r() -> None:
    result = subprocess.run(
        [
            "bash",
            str(BUNDLE / "scripts" / "reproduce_offline.sh"),
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "SKIP_R": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "[offline] regenerating summary" in result.stdout
    assert (BUNDLE / "results" / "figure_tables" / "main_condition_scores.csv").exists()


def test_live_reproduction_default_is_preview_only() -> None:
    result = subprocess.run(
        [
            "bash",
            str(BUNDLE / "scripts" / "reproduce_live.sh"),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "[live] dry run" in result.stdout
    assert "--run" in result.stdout
    assert "OPENAI_API_KEY" in result.stdout
