from __future__ import annotations

import subprocess
from pathlib import Path


def test_selective8_fig3_plot_reports_checkpoints_and_generates_svg(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (
        repo_root
        / "docs/benchmarks/hypothesis_generation_consistency/plot_selective8_fig3.R"
    )
    output_svg = tmp_path / "selective8_lung_breast_fig3.svg"

    completed = subprocess.run(
        [
            "Rscript",
            str(script),
            "--output",
            str(output_svg),
            "--png-output",
            "",
        ],
        check=True,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    svg_text = output_svg.read_text(encoding="utf-8")
    assert "check: arguments ok" in completed.stdout
    assert "check: records ok" in completed.stdout
    assert "check: output svg ok" in completed.stdout
    assert "DeepMAST selective8 hypothesis benchmark" in svg_text
