"""Regenerate the committed guardrail figure from its source-data CSV."""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.plot_sni_guardrail_publication import make_figure

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with (ROOT / "results/figure_source_data.csv").open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    counts = {arm: Counter() for arm in ("on", "off")}
    for row in rows:
        if row["panel"] == "A":
            counts[row["condition_or_run"]][row["measurement"]] = int(float(row["value"]))
    b = {row["measurement"]: float(row["value"]) for row in rows if row["panel"] == "B"}
    example = {"run": "25–BA", **b}
    blocks = [
        {"run": row["condition_or_run"], "codes": row["measurement"], "hard_errors": int(float(row["value"]))}
        for row in rows
        if row["panel"] == "C"
    ]
    assert {arm: sum(values.values()) for arm, values in counts.items()} == {"on": 20, "off": 20}
    assert round(example["reference"], 4) == example["after"] != example["before"]
    make_figure(counts, example, blocks, ROOT / "figures")
    svg = ROOT / "figures/guardrail_effects.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")


if __name__ == "__main__":
    main()
