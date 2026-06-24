from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = PROJECT_ROOT / "benchmarks" / "skills"


def test_public_skills_bundle_layout() -> None:
    expected = {
        ".gitignore",
        "README.md",
        "scripts/benchmark_skill_harness.py",
        "scripts/compare_expanded.py",
        "scripts/reproduce_offline.sh",
        "scripts/reproduce_live.sh",
        "results/skill_load_harness_benchmark_122b.md",
        "results/compare_expanded_qwen3_5_122b.json",
        "results/compare_expanded_qwen3_5_122b_stats.json",
        "results/compare_expanded_qwen3_5_122b_trials.jsonl",
        "figures/fig3.svg",
        "figures/fig_skill_harness_comparison.png",
        "figures/fig_skill_harness_comparison.svg",
        "figures/full_fig_skill_harness_comparison.png",
        "figures/full_fig_skill_harness_comparison.svg",
        "metadata/source_paths.md",
        "metadata/manifest.json",
    }

    missing = [rel for rel in sorted(expected) if not (BUNDLE / rel).exists()]

    assert missing == []


def test_public_skills_bundle_excludes_old_and_temp_artifacts() -> None:
    forbidden_names = {".DS_Store", ".Rhistory", "__pycache__", "old"}
    found = [
        path.relative_to(BUNDLE).as_posix()
        for path in BUNDLE.rglob("*")
        if path.name in forbidden_names
    ]

    assert found == []


def test_public_skills_scripts_are_repo_relative() -> None:
    scripts = [
        BUNDLE / "scripts" / "benchmark_skill_harness.py",
        BUNDLE / "scripts" / "compare_expanded.py",
        BUNDLE / "scripts" / "reproduce_offline.sh",
        BUNDLE / "scripts" / "reproduce_live.sh",
    ]

    for script in scripts:
        text = script.read_text(encoding="utf-8")
        assert "/Users/jungj2" not in text
        assert "docs/benchmarks/skills" not in text


def test_reference_skills_results_are_not_gitignored() -> None:
    result_paths = [
        "results/skill_load_harness_benchmark_122b.md",
        "results/compare_expanded_qwen3_5_122b.json",
        "results/compare_expanded_qwen3_5_122b_trials.jsonl",
    ]

    for rel_path in result_paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(BUNDLE / rel_path)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        assert result.returncode == 1, rel_path


def test_skills_offline_reproduction_validates_reference_artifacts() -> None:
    result = subprocess.run(
        ["bash", str(BUNDLE / "scripts" / "reproduce_offline.sh")],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "[offline] validated qwen3.5:122b reference artifacts" in result.stdout
    assert "F1_A=0.817" in result.stdout
    assert "F1_B=0.939" in result.stdout


def test_skills_live_reproduction_default_is_preview_only() -> None:
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
    assert "SCALING_MODEL=qwen3.5:122b" in result.stdout
