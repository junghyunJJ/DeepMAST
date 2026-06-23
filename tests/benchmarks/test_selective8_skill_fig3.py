from __future__ import annotations

import subprocess
from pathlib import Path


def test_selective8_skill_fig3_writes_dataset_and_model_separate_svgs(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (
        repo_root
        / "docs/benchmarks/hypothesis_generation_consistency/figures/"
        "selective8_governor_vs_middleware_skill_fig3.R"
    )

    subprocess.run(
        [
            "Rscript",
            str(script),
            "--output-dir",
            str(tmp_path),
            "--bootstrap-n",
            "200",
        ],
        check=True,
        cwd=repo_root,
    )

    outputs = {
        "lung_35b": ("Lung/IPF", "Breast cancer", "35B", "122B"),
        "lung_122b": ("Lung/IPF", "Breast cancer", "122B", "35B"),
        "breast_35b": ("Breast cancer", "Lung/IPF", "35B", "122B"),
        "breast_122b": ("Breast cancer", "Lung/IPF", "122B", "35B"),
    }

    for suffix, (dataset, other_dataset, model, other_model) in outputs.items():
        svg = tmp_path / f"selective8_governor_vs_middleware_skill_fig3_{suffix}.svg"
        assert svg.exists()
        svg_text = svg.read_text(encoding="utf-8")

        assert dataset in svg_text
        assert other_dataset not in svg_text
        assert model in svg_text
        assert other_model not in svg_text
        assert "Mode" in svg_text
        assert "Governor" in svg_text
        assert "Activator" in svg_text
        assert "Middleware only" in svg_text
        assert "Condition" in svg_text
        assert "Group" in svg_text
        assert "Skill Reading Expected" in svg_text
        assert "No Skill Reading Expected" in svg_text
        assert "Activation" not in svg_text
        assert "Drug-target" not in svg_text
        assert ">Rate</text>" not in svg_text
        for skill_label in [
            "Open Targets",
            "ChEMBL",
            "Census",
            "STRING",
            "GWAS",
            "Literature",
            "HTML report",
        ]:
            assert skill_label in svg_text
        if suffix == "breast_122b":
            assert "10/10" in svg_text

    script_text = script.read_text(encoding="utf-8")
    assert "geom_errorbar" in script_text
    assert "bootstrap_condition_metrics" in script_text
    assert "pheatmap" in script_text
    assert "No Skill Reading Expected" in script_text
