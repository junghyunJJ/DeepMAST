"""Export the completed guardrail comparison as a publication figure and tables."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = REPO / "res/deep_interpreter/bc/sni_repair_ablation/guardrail_posthoc_recovered_20260908T055100Z"
COLORS = {"passed": "#007A6B", "errors": "#B64B35", "blocked": "#BEC7D1"}
LABELS = {"passed": "Passed predefined checks", "errors": "Produced with detected errors", "blocked": "Output blocked"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def category(row: dict) -> str:
    if row["primary_outcome"] == "passed":
        assert row["report_complete"] and row["hard_error_count"] == 0
        return "passed"
    if row["report_complete"] and (row["hard_error_count"] or 0) > 0:
        return "errors"
    if row["corrected_generation_classification"] == "guardrail_blocked":
        assert not row["report_complete"]
        return "blocked"
    raise ValueError(f"Unresolved or unclassified row: {row['pair_id']} {row['sequence']} {row['arm']}")


def correction_example(rows: list[dict]) -> dict:
    row = next(r for r in rows if (r["pair_id"], r["sequence"], r["arm"]) == ("25", "BA", "on"))
    directory = Path(row["data_dir"])
    example = {"run": "25–BA", "directory": str(directory)}
    for phase in ("before", "after"):
        path = directory / phase / "part2_final.md"
        matches = re.findall(r"\*\*LAMA5[-–]ITGB4\*\*[^\n]*?combined score\s+([0-9.]+)", path.read_text(encoding="utf-8"))
        assert matches and len(set(matches)) == 1, path
        example[phase] = float(matches[0])
        example[f"{phase}_source"] = str(path)
    source = directory / "sig_liana.csv"
    with source.open(encoding="utf-8") as stream:
        values = [float(r["combinedscore"]) for r in csv.DictReader(stream) if r["ligand"] == "LAMA5" and r["receptor"] == "ITGB4"]
    assert len(values) == 1
    example["reference"] = values[0]
    example["reference_source"] = str(source)
    assert example["after"] == round(example["reference"], 4)
    assert example["before"] != example["after"]
    return example


def blocking_examples(rows: list[dict]) -> list[dict]:
    blocks = []
    for row in rows:
        if row["arm"] != "on" or category(row) != "blocked":
            continue
        directory = Path(row["data_dir"])
        validation = directory / "report_validation_final.json"
        errors = [i for i in read_json(validation)["issues"] if i["severity"] == "error"]
        assert errors
        assert not (directory / "synthesis.md").exists()
        assert not (directory / "CCI_Analysis_Report.html").exists()
        blocks.append({"run": f"{row['pair_id']}–{row['sequence']}", "hard_errors": len(errors),
                       "codes": ";".join(sorted({i['code'] for i in errors})), "source": str(validation)})
    return blocks


def panel_label(ax, letter: str, title: str) -> None:
    ax.text(-0.22, 1.13, letter, transform=ax.transAxes, fontsize=13, weight="bold", va="bottom")
    ax.set_title(title, loc="left", fontsize=10.5, weight="bold", pad=17)


def make_figure(counts: dict, example: dict, blocks: list[dict], output: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                         "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
                         "axes.linewidth": 0.7, "savefig.facecolor": "white"})
    fig = plt.figure(figsize=(180 / 25.4, 140 / 25.4))
    grid = fig.add_gridspec(2, 2, height_ratios=[1, 1.15], hspace=0.67, wspace=0.31,
                           left=0.14, right=0.98, bottom=0.07, top=0.83)
    a = fig.add_subplot(grid[0, :])
    for y, arm in enumerate(("on", "off")):
        left = 0
        for key in ("passed", "errors", "blocked"):
            n = counts[arm][key]
            if n:
                a.barh(y, n, left=left, height=0.48, color=COLORS[key], edgecolor="white", linewidth=1)
                a.text(left+n/2, y, f"{n} ({n/20:.0%})", ha="center", va="center", fontsize=8.5,
                       color="#1F2933" if key == "blocked" else "white", weight="bold")
            left += n
    a.set_yticks([0, 1], ["Guardrail ON", "Guardrail OFF"])
    a.invert_yaxis()
    a.set_xlim(0, 20)
    a.set_xticks([0, 5, 10, 15, 20])
    a.set_xlabel("Runs (n = 20 per condition)")
    a.spines[["top", "right", "left"]].set_visible(False)
    a.tick_params(axis="y", length=0, pad=7)
    a.tick_params(axis="x", labelsize=8)
    a.legend(handles=[Patch(facecolor=COLORS[k], label=LABELS[k]) for k in COLORS],
             loc="upper left", bbox_to_anchor=(0.13, 0.925), bbox_transform=fig.transFigure, frameon=False, ncol=3,
             fontsize=7.5, handlelength=1.2, columnspacing=1.2)
    fig.text(0.055, 0.965, "A", fontsize=13, weight="bold", va="top")
    fig.text(0.14, 0.963, "Final report outcomes", fontsize=10.5, weight="bold", va="top")

    b = fig.add_subplot(grid[1, 0])
    b.set_axis_off()
    panel_label(b, "B", "Numerical correction")
    b.text(0.5, 1.0, "LAMA5–ITGB4 combined score", ha="center", va="top", fontsize=8.5)
    for x, phase, title, color in [(0.02, "before", "Before repair", COLORS["errors"]),
                                   (0.59, "after", "After repair", COLORS["passed"])]:
        b.add_patch(FancyBboxPatch((x, 0.51), 0.39, 0.27, boxstyle="round,pad=0.012,rounding_size=0.025",
                                  facecolor="#F5F7F9", edgecolor="#D5DCE2", linewidth=0.7))
        b.text(x+0.195, 0.835, title, ha="center", fontsize=8)
        b.text(x+0.195, 0.645, f"{example[phase]:.4f}", ha="center", va="center", fontsize=15, weight="bold", color=color)
    b.annotate("", xy=(0.57, 0.645), xytext=(0.43, 0.645), arrowprops={"arrowstyle": "->", "lw": 1, "color": "#56616E"})
    b.text(0.5, 0.34, f"Source data: {example['reference']:.4f}", ha="center", fontsize=9, weight="bold")
    b.text(0.5, 0.20, f"Illustrative ON run: {example['run']}", ha="center", fontsize=8, color="#52616B")

    c = fig.add_subplot(grid[1, 1])
    c.set_axis_off()
    panel_label(c, "C", "Observed output blocking")
    short_labels = {"factor_pathway_direction_mismatch": "Pathway–factor\ndirection mismatch",
                    "inline_citation_overclaimed": "Inline citation\noverclaim"}
    cells = [[row["run"], short_labels.get(row["codes"], row["codes"])+f" ({row['hard_errors']})", "Blocked"] for row in blocks]
    table = c.table(cellText=cells, colLabels=["ON run", "Residual error", "Output"],
                    colWidths=[0.19, 0.58, 0.23], bbox=[0, 0.38, 1, 0.54], cellLoc="left", colLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(7.4)
    for (r, _), cell in table.get_celld().items():
        cell.set_edgecolor("#D5DCE2")
        cell.set_linewidth(0.5)
        if r == 0:
            cell.set_facecolor("#F5F7F9")
            cell.set_text_props(weight="bold")
    c.text(0.5, 0.25, f"{len(blocks)}/20 ON runs blocked ({len(blocks)/20:.0%})", ha="center", fontsize=9, weight="bold")
    c.text(0.5, 0.10, "Final report was not produced", ha="center", fontsize=7.8, color="#52616B")
    for extension in ("pdf", "svg", "png"):
        fig.savefig(output / f"guardrail_effects.{extension}", dpi=300)
    plt.close(fig)


def export(results: Path, output: Path) -> None:
    comparison = read_json(results / "comparison.json")
    rows = comparison["rows"]
    assert len(rows) == 40
    assert all(comparison["summary"][arm]["unknown"] == 0 for arm in ("on", "off"))
    counts = {arm: Counter(category(row) for row in rows if row["arm"] == arm) for arm in ("on", "off")}
    for arm in counts:
        assert sum(counts[arm].values()) == 20
        assert counts[arm]["passed"] == comparison["summary"][arm]["passed"]
        assert counts[arm]["errors"] == comparison["summary"][arm]["invalid_output"]["count"]
        assert counts[arm]["blocked"] == comparison["summary"][arm]["blocked"]
    example = correction_example(rows)
    blocks = blocking_examples(rows)
    assert len(blocks) == counts["on"]["blocked"]
    output.mkdir(parents=True, exist_ok=True)
    make_figure(counts, example, blocks, output)

    table_rows = [{"Outcome": LABELS[key], "Guardrail ON": f"{counts['on'][key]}/20 ({counts['on'][key]/20:.0%})",
                   "Guardrail OFF": f"{counts['off'][key]}/20 ({counts['off'][key]/20:.0%})"} for key in COLORS]
    write_csv(output / "table_1_guardrail_outcomes.csv", table_rows, ["Outcome", "Guardrail ON", "Guardrail OFF"])
    footnote = ("Values are n/20 (%). Categories are mutually exclusive and exhaustive. A passing report was complete and had zero hard errors under the predefined validation policy. "
                "The error category requires at least one confirmed hard error; remaining semantic checks could be omitted once failure was established. "
                "These are repeated executions on one breast cancer dataset, not independent biological samples. ON runs are historical controls. "
                "Errors include reporting-scope violations and should not all be described as hallucinations.")
    lines = ["# Table 1. Final report outcomes with and without report-level guardrails", "", "| Outcome | Guardrail ON | Guardrail OFF |", "|---|---:|---:|"]
    lines += [f"| {r['Outcome']} | {r['Guardrail ON']} | {r['Guardrail OFF']} |" for r in table_rows]
    lines += ["", footnote, ""]
    (output / "table_1_guardrail_outcomes.md").write_text("\n".join(lines), encoding="utf-8")
    latex = ["\\begin{tabular}{lrr}", "\\hline", "Outcome & Guardrail ON & Guardrail OFF \\\\", "\\hline"]
    latex += [(f"{r['Outcome']} & {r['Guardrail ON']} & {r['Guardrail OFF']} \\\\").replace("%", "\\%") for r in table_rows]
    latex += ["\\hline", "\\end{tabular}", "% " + footnote, ""]
    (output / "table_1_guardrail_outcomes.tex").write_text("\n".join(latex), encoding="utf-8")

    per_run = [{"arm": r["arm"], "pair_id": r["pair_id"], "sequence": r["sequence"], "category": category(r),
                "report_complete": r["report_complete"], "hard_errors_observed": r["hard_error_count"],
                "evaluation_complete": r["evaluation_complete"], "generation_seconds": r["generation_seconds"],
                "source_directory": r["data_dir"]} for r in rows]
    write_csv(output / "table_s1_per_run.csv", per_run, list(per_run[0]))
    plot_data = [{"panel": "A", "condition_or_run": arm, "measurement": key, "value": counts[arm][key], "unit": "runs", "source": str(results / "comparison.json")} for arm in counts for key in COLORS]
    plot_data += [{"panel": "B", "condition_or_run": example["run"], "measurement": phase, "value": example[phase], "unit": "combined score", "source": example[f"{phase}_source"]} for phase in ("before", "after", "reference")]
    plot_data += [{"panel": "C", "condition_or_run": r["run"], "measurement": r["codes"], "value": r["hard_errors"], "unit": "reported residual hard errors", "source": r["source"]} for r in blocks]
    write_csv(output / "figure_source_data.csv", plot_data, list(plot_data[0]))
    caption = (
        "# Figure X. Outcomes and documented functions of report-level guardrails\n\n"
        "**(A)** Final outcomes of 20 Guardrail ON and 20 Guardrail OFF executions using Qwen3.5-122B with SNI enabled on the same breast cancer dataset. "
        "Categories are mutually exclusive: complete reports passing the predefined validation checks, complete reports with at least one detected hard error, and runs blocked by the report guardrail. "
        "Counts and percentages use all 20 executions per condition. The ON/OFF contrast summarizes the combined pipeline outcome and does not isolate the causal contribution of correction or blocking. "
        f"**(B)** Illustrative numerical correction in ON run {example['run']}: the reported LAMA5–ITGB4 combined score changed from {example['before']:.4f} to {example['after']:.4f}, matching the source-data value rounded to four decimal places. "
        "This is a single documented repair, not an aggregate correction-rate estimate. "
        "**(C)** The two observed ON output blocks. Each run terminated with one reported residual hard error in Part 3; neither synthesis Markdown nor the final HTML report was produced. "
        "The analysis evaluates predefined reporting and consistency requirements rather than overall scientific accuracy. ON controls were generated earlier than OFF runs.\n\n"
        "## Files and reproduction\n\n"
        "PDF and SVG are vector exports; SVG retains editable text. PNG is 300 dpi. The figure is 180 × 140 mm. "
        "No significance tests or uncertainty intervals are implied. The numeric repair is illustrative.\n\n"
        "`figure_source_data.csv` provides plotted values and original source paths. `table_s1_per_run.csv` contains all 40 runs.\n\n"
        "Reproduce from the repository root:\n\n"
        "```bash\n.venv/bin/python scripts/plot_sni_guardrail_publication.py\n```\n"
    )
    (output / "figure_caption.md").write_text(caption, encoding="utf-8")
    sources = {str(results / "comparison.json"), example["before_source"], example["after_source"], example["reference_source"], *(r["source"] for r in blocks)}
    provenance = {"source_sha256": {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in sorted(sources)},
                  "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "counts": counts,
                  "figure_size_mm": [180, 140], "png_dpi": 300, "correction_example": example, "blocks": blocks}
    (output / "publication_manifest.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    export(args.results.resolve(), (args.output or args.results / "publication").resolve())
