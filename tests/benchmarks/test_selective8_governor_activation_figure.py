from __future__ import annotations

import subprocess
from pathlib import Path


def test_selective8_governor_activation_r_script_generates_svg(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (
        repo_root
        / "docs/benchmarks/hypothesis_generation_consistency/figures/"
        "selective8_governor_activation_fig3.R"
    )
    results_dir = (
        repo_root
        / "docs/benchmarks/hypothesis_generation_consistency/results/"
        "selective8_governor_production_20260611_142352"
    )
    output_svg = tmp_path / "selective8_governor_activation_fig3.svg"

    subprocess.run(
        [
            "Rscript",
            str(script),
            "--results-dir",
            str(results_dir),
            "--output",
            str(output_svg),
        ],
        check=True,
        cwd=repo_root,
    )

    svg_text = output_svg.read_text(encoding="utf-8")
    assert output_svg.exists()
    assert "Selective8 governor activation fidelity" in svg_text
    assert "Governor" in svg_text
    assert "Activation trace checkpoint benchmark" in svg_text
