"""Evidence loading and saving tools for Drug Target Assessment Agent.

Handles loading lr_candidates.json + selected_top3_lr.json,
extracting gene symbols, and managing evidence JSON files.
"""

import json
import logging
import os
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _resolve_data_dir(data_dir: str) -> Path:
    """Resolve data directory with user-provided path priority.

    LLMs frequently pass wrong paths (e.g. "evidence", relative paths,
    or hallucinated directories). When a user provides a valid path that exists,
    we use it. Otherwise, we fall back to env vars set by create_drug_target_agent.
    """
    # 1. User-provided path FIRST (if it actually exists)
    if data_dir:
        resolved = Path(data_dir).expanduser().resolve()
        if resolved.exists():
            return resolved

    # 2. Env vars as fallback (DRUG_TARGET_DATA_DIR preferred over shared DEEP_INTERPRETER_DATA_DIR)
    for env_key in ("DRUG_TARGET_DATA_DIR", "DEEP_INTERPRETER_DATA_DIR"):
        env_dir = os.getenv(env_key)
        if env_dir:
            p = Path(env_dir).expanduser().resolve()
            if p.exists():
                return p

    return Path("/tmp/deep_interpreter_workspace").resolve()


@tool
def load_lr_candidates(data_dir: str) -> str:
    """Load lr_candidates.json and selected_top3_lr.json for drug target assessment.

    Reads the top-15 L-R pairs from lr_candidates.json, marks which genes
    are in the selected_top3_lr.json, and extracts disease context.

    Args:
        data_dir: Directory containing lr_candidates.json and selected_top3_lr.json

    Returns:
        JSON with gene_symbols (unique), lr_pairs, selected_top3 info, disease context
    """
    base = _resolve_data_dir(data_dir)
    result = {
        "data_dir": str(base),
        "gene_symbols": [],
        "lr_pairs": [],
        "selected_top3": [],
        "selected_top3_genes": [],
        "disease": "",
        "errors": [],
    }

    # Load lr_candidates.json
    lr_path = base / "lr_candidates.json"
    if not lr_path.exists():
        result["errors"].append(f"lr_candidates.json not found at {lr_path}")
        return json.dumps(result, indent=2)

    try:
        with open(lr_path) as f:
            lr_data = json.load(f)
    except Exception as e:
        result["errors"].append(f"Failed to parse lr_candidates.json: {e}")
        return json.dumps(result, indent=2)

    # Extract disease context
    result["disease"] = lr_data.get("disease", lr_data.get("disease_context", ""))

    # Extract L-R pairs and gene symbols
    pairs = lr_data.get("pairs", lr_data.get("lr_pairs", lr_data.get("candidates", [])))
    all_genes = set()
    for pair in pairs:
        ligand = pair.get("ligand", pair.get("source", ""))
        receptor = pair.get("receptor", pair.get("target", ""))
        if ligand:
            all_genes.add(ligand.upper())
        if receptor:
            all_genes.add(receptor.upper())
        result["lr_pairs"].append({
            "ligand": ligand,
            "receptor": receptor,
            "score": pair.get("score", pair.get("rank_score")),
        })

    # Load selected_top3_lr.json
    top3_path = base / "selected_top3_lr.json"
    top3_genes = set()
    if top3_path.exists():
        try:
            with open(top3_path) as f:
                top3_data = json.load(f)
            top3_pairs = top3_data if isinstance(top3_data, list) else top3_data.get("pairs", top3_data.get("selected", []))
            for pair in top3_pairs:
                ligand = pair.get("ligand", pair.get("source", ""))
                receptor = pair.get("receptor", pair.get("target", ""))
                if ligand:
                    top3_genes.add(ligand.upper())
                if receptor:
                    top3_genes.add(receptor.upper())
                result["selected_top3"].append({
                    "ligand": ligand,
                    "receptor": receptor,
                })
        except Exception as e:
            result["errors"].append(f"Failed to parse selected_top3_lr.json: {e}")
    else:
        result["errors"].append("selected_top3_lr.json not found (optional)")

    result["gene_symbols"] = sorted(all_genes)
    result["selected_top3_genes"] = sorted(top3_genes)

    # Mark each gene with is_selected_top3
    result["gene_details"] = []
    for gene in sorted(all_genes):
        result["gene_details"].append({
            "symbol": gene,
            "is_selected_top3": gene in top3_genes,
        })

    return json.dumps(result, indent=2)


@tool
def load_evidence_files(data_dir: str) -> str:
    """Load all evidence JSON files from the evidence/ subdirectory.

    Reads all *.json files from {data_dir}/evidence/ and returns
    their contents as a structured dictionary.

    Args:
        data_dir: Directory containing evidence/ subdirectory

    Returns:
        JSON with filename -> content mapping for all evidence files
    """
    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    result = {
        "data_dir": str(base),
        "files": {},
        "file_count": 0,
        "errors": [],
    }

    if not evidence_dir.exists():
        result["errors"].append(f"evidence/ directory not found at {evidence_dir}")
        return json.dumps(result, indent=2)

    for path in sorted(evidence_dir.glob("*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
            result["files"][path.name] = data
            result["file_count"] += 1
        except Exception as e:
            result["errors"].append(f"Failed to load {path.name}: {e}")

    return json.dumps(result, indent=2)


@tool
def save_evidence(data_dir: str, filename: str, data: str) -> str:
    """Save evidence data as a JSON file in the evidence/ subdirectory.

    Creates the evidence/ directory if it doesn't exist.

    Args:
        data_dir: Base directory for evidence storage
        filename: Filename (e.g., "ot_TGFB1.json", "assessment_results.json")
        data: JSON string of data to save

    Returns:
        JSON with save status and file path
    """
    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    file_path = evidence_dir / filename
    result = {
        "saved": False,
        "path": str(file_path),
        "errors": [],
    }

    try:
        parsed = json.loads(data)
        with open(file_path, "w") as f:
            json.dump(parsed, f, indent=2)
        result["saved"] = True
    except json.JSONDecodeError as e:
        # Try saving as raw string if not valid JSON
        try:
            with open(file_path, "w") as f:
                f.write(data)
            result["saved"] = True
        except Exception as write_err:
            result["errors"].append(f"Failed to save: {write_err}")
    except Exception as e:
        result["errors"].append(f"Failed to save: {e}")

    return json.dumps(result, indent=2)
