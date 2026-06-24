from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = PROJECT_ROOT / "benchmarks" / "lr_retrieval_relevance"


def test_public_lr_retrieval_bundle_layout() -> None:
    expected = {
        ".gitignore",
        "README.md",
        "inputs/cci_full_cases.json",
        "scripts/export_coverage_figure_data.py",
        "scripts/coverage_figure.R",
        "scripts/reproduce_offline.sh",
        "scripts/reproduce_live.sh",
        "results/converted_runner_rows.jsonl",
        "results/gene_coverage_labels_122b.jsonl",
        "results/entity_coverage_labels_122b.jsonl",
        "results/retrieval_summary.csv",
        "results/retrieval_summary.json",
        "results/coverage_tables/coverage_percase.csv",
        "results/coverage_tables/coverage_group_summary.csv",
        "results/coverage_tables/coverage_sig.csv",
        "figures/fig_retrieval_coverage.svg",
        "figures/fig_retrieval_coverage.png",
        "metadata/source_paths.md",
        "metadata/manifest.json",
    }

    missing = [rel for rel in sorted(expected) if not (BUNDLE / rel).exists()]

    assert missing == []


def test_public_lr_retrieval_bundle_excludes_local_temp_artifacts() -> None:
    forbidden_names = {".DS_Store", ".Rhistory", "__pycache__", "Rplots.pdf"}
    found = [
        path.relative_to(BUNDLE).as_posix()
        for path in BUNDLE.rglob("*")
        if path.name in forbidden_names
    ]

    assert found == []


def test_reference_lr_retrieval_results_are_not_gitignored() -> None:
    result_paths = [
        "results/converted_runner_rows.jsonl",
        "results/retrieval_summary.csv",
        "results/coverage_tables/coverage_group_summary.csv",
        "results/manuscript/figures/fig_retrieval_coverage.svg",
    ]

    for rel_path in result_paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(BUNDLE / rel_path)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        assert result.returncode == 1, rel_path


def test_lr_retrieval_offline_reproduction_regenerates_tables_without_r() -> None:
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
    assert "[offline] regenerating coverage tables" in result.stdout
    assert "[offline] SKIP_R=1; skipped figure regeneration" in result.stdout
    assert (BUNDLE / "results/coverage_tables/coverage_group_summary.csv").exists()


def test_lr_retrieval_live_reproduction_default_is_preview_only() -> None:
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
    assert "qwen3.5:35b" in result.stdout
    assert "qwen3.5:122b" in result.stdout
