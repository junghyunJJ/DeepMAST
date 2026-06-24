from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = PROJECT_ROOT / "benchmarks" / "sgcp_accuracy_recall"


def test_public_sgcp_bundle_layout() -> None:
    expected = {
        ".gitignore",
        "README.md",
        "scripts/plot_sgcp_main_figure.R",
        "scripts/reproduce_offline.sh",
        "scripts/reproduce_live.sh",
        "scripts/validate_reference_artifacts.py",
        "results/sgcp_accuracy_recall_summary.csv",
        "results/sgcp_accuracy_recall_tests.csv",
        "results/multihop_full_summary_35b_7000_20260604T003510Z_rw3.json",
        "results/multihop_full_summary_122b_6000_20260605T004513Z_rw3.json",
        "results/raw/multihop_full_qwen35_35b_port7000_wiki_off_rw3.jsonl",
        "results/raw/multihop_full_qwen35_35b_port7000_wiki_doc_routing_rw3.jsonl",
        "results/raw/multihop_full_qwen35_122b_port6000_wiki_off_rw3.jsonl",
        "results/raw/multihop_full_qwen35_122b_port6000_wiki_doc_routing_rw3.jsonl",
        "figures/sgcp_accuracy_recall_main.png",
        "figures/sgcp_accuracy_recall_main.svg",
        "metadata/source_paths.md",
        "metadata/manifest.json",
    }

    missing = [rel for rel in sorted(expected) if not (BUNDLE / rel).exists()]

    assert missing == []


def test_public_sgcp_bundle_excludes_local_temp_artifacts() -> None:
    forbidden_names = {
        ".DS_Store",
        ".Rhistory",
        "__pycache__",
        ".container_dir",
        ".pid",
        ".run_id",
    }
    forbidden_fragments = {
        ".badrows-backup",
        ".stale-badrows-backup",
        "/logs/",
    }
    found = []
    for path in BUNDLE.rglob("*"):
        rel = path.relative_to(BUNDLE).as_posix()
        if path.name in forbidden_names or any(fragment in rel for fragment in forbidden_fragments):
            found.append(rel)

    assert found == []


def test_public_sgcp_scripts_are_repo_relative() -> None:
    scripts = [
        BUNDLE / "scripts" / "plot_sgcp_main_figure.R",
        BUNDLE / "scripts" / "reproduce_offline.sh",
        BUNDLE / "scripts" / "reproduce_live.sh",
        BUNDLE / "scripts" / "validate_reference_artifacts.py",
    ]

    for script in scripts:
        text = script.read_text(encoding="utf-8")
        assert "/Users/jungj2" not in text
        assert "docs/writing/figures" not in text
        assert "mcp/llmwiki_rag/benchmarking" not in text


def test_reference_sgcp_results_are_not_gitignored() -> None:
    result_paths = [
        "results/sgcp_accuracy_recall_summary.csv",
        "results/sgcp_accuracy_recall_tests.csv",
        "results/raw/multihop_full_qwen35_35b_port7000_wiki_off_rw3.jsonl",
        "figures/sgcp_accuracy_recall_main.svg",
    ]

    for rel_path in result_paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(BUNDLE / rel_path)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        assert result.returncode == 1, rel_path


def test_sgcp_offline_reproduction_validates_reference_artifacts() -> None:
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
    assert "[offline] validated SGCP reference artifacts" in result.stdout
    assert "35B accuracy_delta=+8.6pp" in result.stdout
    assert "122B recall_delta=+6.6pp" in result.stdout


def test_sgcp_live_reproduction_default_is_preview_only() -> None:
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
