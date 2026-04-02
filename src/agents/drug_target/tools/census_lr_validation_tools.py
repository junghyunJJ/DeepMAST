"""CLI wrapper tools for compare-census-gene-pair-by-cell-type skill."""

from __future__ import annotations

import csv
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.agents.drug_target.tools.census_batch_core import (
    _resolve_disease_name,
    batch_census_lr_pairs,
    write_census_csv,
    sanitize_for_json,
)

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _script_path() -> Path:
    return (
        _project_root()
        / "skills"
        / "compare-census-gene-pair-by-cell-type"
        / "scripts"
        / "compare_census_gene_pair_by_cell_type.py"
    )


def _sanitize_token(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_").lower() or "unknown"


def _build_compare_command(
    *,
    disease: str,
    gene_a: str,
    gene_b: str,
    target_cell_type: str,
    organism: str,
    census_version: str,
    min_cells: int,
    top_n: int,
    include_non_primary: bool,
    obs_extra_filter: str,
    output_csv: str,
) -> list[str]:
    cmd = [
        "python",
        str(_script_path()),
        "--disease",
        disease,
        "--gene-a",
        gene_a,
        "--gene-b",
        gene_b,
        "--target-cell-type",
        target_cell_type,
        "--organism",
        organism,
        "--census-version",
        census_version,
        "--min-cells",
        str(min_cells),
        "--top-n",
        str(top_n),
    ]
    if include_non_primary:
        cmd.append("--include-non-primary")
    if obs_extra_filter.strip():
        cmd.extend(["--obs-extra-filter", obs_extra_filter.strip()])
    if output_csv.strip():
        cmd.extend(["--output-csv", output_csv.strip()])
    return cmd


def _parse_percent(value: str) -> float:
    return float(value.strip().replace("%", "")) / 100.0


def _parse_float(value: str) -> float:
    cleaned = value.strip()
    if cleaned.startswith("<"):
        cleaned = cleaned[1:]
    return float(cleaned)


def _parse_target_vs_rest(stdout: str, gene_a: str, gene_b: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    pattern = re.compile(
        r"^\-\s(?P<metric>.+?):\s"
        r"target=(?P<target>[\d\.]+%)\s\|\s"
        r"rest=(?P<rest>[\d\.]+%)\s\|\s"
        r"diff=(?P<diff>[\d\.]+%)\s\|\s"
        r"RR=(?P<rr>[-+eE\d\.]+|inf)\s\|\s"
        r"z=(?P<z>[-+eE\d\.]+|nan)\s\|\s"
        r"p=(?P<p>[\<\-\+eE\d\.]+|nan)$"
    )
    for raw in stdout.splitlines():
        line = raw.strip()
        match = pattern.match(line)
        if not match:
            continue
        metric_name = match.group("metric")
        entry = {
            "target_pct": _parse_percent(match.group("target")),
            "rest_pct": _parse_percent(match.group("rest")),
            "diff": _parse_percent(match.group("diff")),
            "risk_ratio": _parse_float(match.group("rr")),
            "z": _parse_float(match.group("z")),
            "p_value": _parse_float(match.group("p")),
        }
        metrics[metric_name] = entry

    return {
        "gene_a": metrics.get(f"{gene_a}+"),
        "gene_b": metrics.get(f"{gene_b}+"),
        "coexpression": metrics.get(f"{gene_a}+ & {gene_b}+"),
    }


def _parse_available_celltypes(output: str) -> list[dict[str, Any]]:
    marker = "Examples of available cell types:"
    if marker not in output:
        return []
    part = output.split(marker, 1)[1]
    pairs = re.findall(r"([^,\(\)]+)\((\d+)\)", part)
    candidates: list[dict[str, Any]] = []
    for name, count in pairs:
        candidates.append({"name": name.strip(), "n_cells": int(count)})
    return candidates


def _resolve_interest_cell_type(
    requested: str,
    candidates: list[dict[str, Any]],
) -> tuple[str | None, str]:
    if not candidates:
        return None, "none"

    req = requested.strip().lower()
    exact = [c for c in candidates if c["name"].strip().lower() == req]
    if exact:
        best = max(exact, key=lambda x: x["n_cells"])
        return best["name"], "exact"

    partial = [
        c
        for c in candidates
        if req in c["name"].strip().lower() or c["name"].strip().lower() in req
    ]
    if partial:
        best = max(partial, key=lambda x: x["n_cells"])
        return best["name"], "fuzzy"

    return None, "none"


@tool
def run_compare_census_lr_pair(
    data_dir: str,
    disease: str,
    gene_a: str,
    gene_b: str,
    target_cell_type: str,
    organism: str = "homo_sapiens",
    census_version: str = "2025-11-08",
    min_cells: int = 50,
    top_n: int = 20,
    include_non_primary: bool = False,
    obs_extra_filter: str = "",
    output_csv: str = "",
    timeout_sec: int = 600,
) -> str:
    """Run compare_census_gene_pair_by_cell_type.py with fail-soft behavior."""
    result: dict[str, Any] = {
        "data_dir": str(Path(data_dir).expanduser().resolve()),
        "script_path": str(_script_path()),
        "disease": disease,
        "gene_a": gene_a,
        "gene_b": gene_b,
        "requested_cell_type": target_cell_type,
        "resolved_cell_type": target_cell_type,
        "resolution_mode": "exact",
        "census_version": census_version,
        "executed": False,
        "retried": False,
        "disease_resolved": None,
        "disease_resolution_mode": None,
        "target_vs_rest": {
            "gene_a": None,
            "gene_b": None,
            "coexpression": None,
        },
        "errors": [],
    }

    script = _script_path()
    if not script.exists():
        result["errors"].append(f"Script not found: {script}")
        return json.dumps(result, indent=2)

    csv_path = output_csv.strip()
    if not csv_path:
        evidence_dir = Path(result["data_dir"]) / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        # Use resolved_cell_type for CSV naming (updated after fuzzy resolution)
        csv_ct = result.get("resolved_cell_type", target_cell_type)
        csv_name = (
            f"census_{_sanitize_token(gene_a)}_{_sanitize_token(gene_b)}_"
            f"{_sanitize_token(csv_ct)}.csv"
        )
        csv_path = str(evidence_dir / csv_name)

    def _run(cell_type: str, run_disease: str | None = None):
        cmd = _build_compare_command(
            disease=run_disease or disease,
            gene_a=gene_a,
            gene_b=gene_b,
            target_cell_type=cell_type,
            organism=organism,
            census_version=census_version,
            min_cells=min_cells,
            top_n=top_n,
            include_non_primary=include_non_primary,
            obs_extra_filter=obs_extra_filter,
            output_csv=csv_path,
        )
        proc = subprocess.run(
            cmd,
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return cmd, proc

    try:
        cmd, proc = _run(target_cell_type)
        combined_output = f"{proc.stdout}\n{proc.stderr}"
        logger.debug("Census stdout: %s", proc.stdout[-2000:])
        logger.debug("Census stderr: %s", proc.stderr[-2000:])

        if proc.returncode != 0:
            # ① Disease resolution first — "No cells matched" often means
            #   the disease string doesn't exist in Census MONDO vocabulary.
            current_disease = disease
            disease_resolved, disease_mode = _resolve_disease_name(disease, organism)
            if disease_resolved and disease_resolved != disease:
                result["disease_resolved"] = disease_resolved
                result["disease_resolution_mode"] = disease_mode
                result["disease"] = disease_resolved
                current_disease = disease_resolved
                cmd, proc = _run(target_cell_type, current_disease)
                combined_output = f"{proc.stdout}\n{proc.stderr}"
                logger.debug("Census stdout: %s", proc.stdout[-2000:])
                logger.debug("Census stderr: %s", proc.stderr[-2000:])

            # ② Cell type resolution (existing logic) — if still failing
            if proc.returncode != 0:
                candidates = _parse_available_celltypes(combined_output)
                resolved, mode = _resolve_interest_cell_type(target_cell_type, candidates)
                if resolved and resolved != target_cell_type:
                    result["retried"] = True
                    result["resolved_cell_type"] = resolved
                    result["resolution_mode"] = mode
                    cmd, proc = _run(resolved, current_disease)
                    logger.debug("Census stdout: %s", proc.stdout[-2000:])
                    logger.debug("Census stderr: %s", proc.stderr[-2000:])

            if proc.returncode != 0:
                result["errors"].append(
                    "compare_census_gene_pair_by_cell_type.py failed: "
                    + (proc.stderr.strip() or proc.stdout.strip() or "unknown error")
                )
                return json.dumps(result, indent=2)

        result["executed"] = True
        result["target_vs_rest"] = _parse_target_vs_rest(proc.stdout, gene_a, gene_b)
        return json.dumps(result, indent=2)

    except subprocess.TimeoutExpired:
        result["errors"].append(
            f"compare_census_gene_pair_by_cell_type.py timed out after {timeout_sec}s"
        )
        return json.dumps(result, indent=2)
    except Exception as exc:
        result["errors"].append(f"Census comparison failed: {exc}")
        return json.dumps(result, indent=2)


@tool
def run_batch_census_lr_pairs(
    data_dir: str,
    disease: str,
    pairs_json: str,
    target_cell_type: str,
    organism: str = "homo_sapiens",
    census_version: str = "2025-11-08",
    max_cells: int = 1_000_000,
) -> str:
    """Batch Census L-R co-expression validation for multiple pairs at once.

    Opens Census ONCE, fetches all unique genes in a single query, then
    computes per-pair z-test statistics in-memory. ~14x faster than
    calling run_compare_census_lr_pair per pair.

    Args:
        data_dir: Path to the data directory (evidence/ subdirectory used for CSVs).
        disease: Disease label for Census obs filter.
        pairs_json: JSON array of [gene_a, gene_b] pairs,
            e.g. '[["CXCL12","CXCR4"],["FGF2","FGFR1"]]'
        target_cell_type: Cell type for target-vs-rest comparison.
        organism: Census organism key.
        census_version: Pinned Census release.
        max_cells: Hard cap on cell count to prevent OOM.

    Returns:
        JSON object with batch_size, success_count, and per-pair results
        matching run_compare_census_lr_pair schema.
    """
    result: dict = {
        "batch_size": 0,
        "success_count": 0,
        "results": [],
        "errors": [],
    }

    # Robust pairs_json parsing (handles Qwen/Ollama double-serialized JSON)
    pairs_raw = pairs_json
    if isinstance(pairs_raw, str):
        try:
            pairs_raw = json.loads(pairs_raw)
        except (json.JSONDecodeError, TypeError):
            pass
        # Handle double-serialized
        if isinstance(pairs_raw, str):
            try:
                pairs_raw = json.loads(pairs_raw)
            except (json.JSONDecodeError, TypeError):
                result["errors"].append(f"Could not parse pairs_json: {pairs_json[:200]}")
                return json.dumps(sanitize_for_json(result), indent=2)

    if not isinstance(pairs_raw, list):
        result["errors"].append(f"pairs_json must be a JSON array, got {type(pairs_raw).__name__}")
        return json.dumps(sanitize_for_json(result), indent=2)

    pairs = [(p[0], p[1]) for p in pairs_raw if isinstance(p, (list, tuple)) and len(p) >= 2]
    result["batch_size"] = len(pairs)

    if not pairs:
        result["errors"].append("No valid pairs found in pairs_json")
        return json.dumps(sanitize_for_json(result), indent=2)

    data_path = Path(data_dir).expanduser().resolve()
    evidence_dir = data_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    try:
        batch_results, csv_data = batch_census_lr_pairs(
            pairs=pairs,
            disease=disease,
            target_cell_type=target_cell_type,
            organism=organism,
            census_version=census_version,
            max_cells=max_cells,
        )

        # Write per-pair CSV files and populate results
        for pair_result in batch_results:
            gene_a = pair_result.get("gene_a", "")
            gene_b = pair_result.get("gene_b", "")
            pair_key = (gene_a, gene_b)

            # Write CSV — use resolved_cell_type so Stage 1 validation finds the file
            resolved_ct = pair_result.get("resolved_cell_type", target_cell_type)
            csv_name = (
                f"census_{_sanitize_token(gene_a)}_{_sanitize_token(gene_b)}_"
                f"{_sanitize_token(resolved_ct)}.csv"
            )
            csv_path = evidence_dir / csv_name
            csv_rows = csv_data.get(pair_key, [])
            if csv_rows:
                write_census_csv(csv_path, csv_rows)

            pair_result["data_dir"] = str(data_path)
            pair_result["csv_file"] = csv_name
            pair_result["csv_exists"] = csv_path.exists()
            result["results"].append(pair_result)

            if pair_result.get("executed"):
                result["success_count"] += 1

    except MemoryError as exc:
        result["errors"].append(str(exc))
    except Exception as exc:
        result["errors"].append(f"Batch Census failed: {exc}")

    return json.dumps(sanitize_for_json(result), indent=2)


__all__ = ["run_compare_census_lr_pair", "run_batch_census_lr_pairs"]

