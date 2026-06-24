from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = PROJECT_ROOT / "benchmarks" / "dth"


def test_public_dth_bundle_layout() -> None:
    expected = {
        ".gitignore",
        "README.md",
        "scripts/figure_dth_benchmark_results.R",
        "scripts/judge_dth_yes_no_blind.py",
        "scripts/reproduce_offline.sh",
        "scripts/reproduce_live.sh",
        "inputs/conditions.json",
        "results/cumulative_valid_only_summary_for_20each_target.json",
        "results/cumulative_valid_only_summary_for_20each_target.md",
        "results/dth_yes_no_qwen397b_cloud_methods_results.md",
        "results/judge/dth_yes_no_glm52_cloud_blind_summary.json",
        "results/judge/dth_yes_no_gpt54_blind_summary.json",
        "results/judge/dth_yes_no_sonnet46_blind_summary.json",
        "results/raw_runs/DTH_no/trials.jsonl",
        "results/raw_runs/DTH_yes/trials.jsonl",
        "figures/Fig3A_DTH_EvidenceCoverage.svg",
        "figures/Fig3B_DTH_BlindJudgeRigor.svg",
        "metadata/source_paths.md",
        "metadata/manifest.json",
    }

    missing = [rel for rel in sorted(expected) if not (BUNDLE / rel).exists()]

    assert missing == []


def test_public_dth_bundle_excludes_local_temp_artifacts() -> None:
    forbidden_names = {".DS_Store", ".Rhistory", "__pycache__", "Rplots.pdf"}
    found = [
        path.relative_to(BUNDLE).as_posix()
        for path in BUNDLE.rglob("*")
        if path.name in forbidden_names
    ]

    assert found == []


def test_reference_dth_results_are_not_gitignored() -> None:
    result_paths = [
        "results/cumulative_valid_only_summary_for_20each_target.json",
        "results/judge/dth_yes_no_gpt54_blind_summary.json",
        "results/raw_runs/DTH_no/trials.jsonl",
    ]

    for rel_path in result_paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(BUNDLE / rel_path)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        assert result.returncode == 1, rel_path


def test_dth_offline_reproduction_validates_reference_artifacts() -> None:
    result = subprocess.run(
        ["bash", str(BUNDLE / "scripts" / "reproduce_offline.sh")],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "SKIP_R": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "[offline] artifact validation ok" in result.stdout
    assert "[offline] SKIP_R=1; skipped figure regeneration" in result.stdout


def test_dth_live_reproduction_default_is_preview_only() -> None:
    result = subprocess.run(
        ["bash", str(BUNDLE / "scripts" / "reproduce_live.sh")],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "[live] dry run" in result.stdout
    assert "--run" in result.stdout
    assert "qwen3.5:397b-cloud / ollama / 11434" in result.stdout
