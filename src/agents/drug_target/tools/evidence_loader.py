"""Evidence loading and saving tools for Drug Target Assessment Agent.

Handles loading lr_candidates.json (top-30 L-R pairs),
extracting gene symbols, and managing evidence JSON files.
selected_top3_lr.json is optional (legacy) — featured candidates
are now determined by rubric scoring in stage_logic.py.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Union

from langchain_core.tools import tool
from src.agents.drug_target.tools.stage_logic import (
    classify_disease_type,
    infer_oncology_flag,
    normalize_st_colocalization_score,
)
from src.agents.drug_target.tools.stage2_service import extract_lr_pairs

# Module-level constant for overwrite protection (used in save_evidence)
_SAVE_PROTECTED_FILES = {"stage2_evidence.json", "known_drugs.json", "gene_manifest.json"}

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
def load_lr_candidates(data_dir: str, disease: str = "") -> str:
    """Load lr_candidates.json for drug target assessment.

    Reads the top-30 L-R pairs from lr_candidates.json, optionally marks
    which genes are in selected_top3_lr.json (legacy), and extracts disease context.
    Featured candidates are determined by rubric scoring, not by selected_top3.

    Args:
        data_dir: Directory containing lr_candidates.json
        disease: Disease context from CLI (takes priority over lr_candidates.json)

    Returns:
        JSON with gene_symbols (unique), lr_pairs, selected_top3 info (legacy), disease context
    """
    base = _resolve_data_dir(data_dir)
    result = {
        "data_dir": str(base),
        "gene_symbols": [],
        "lr_pairs": [],
        "selected_top3": [],
        "selected_top3_genes": [],
        "interest_celltypes": [],
        "targets_json_found": False,
        "disease": "",
        "disease_type": "unknown",
        "oncology_flag": False,
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

    # Extract disease context: CLI param → lr_candidates.json → empty
    result["disease"] = disease or lr_data.get("disease", lr_data.get("disease_context", ""))
    result["disease_type"] = classify_disease_type(result["disease"])
    result["oncology_flag"] = infer_oncology_flag(result["disease"])

    # Extract L-R pairs and gene symbols
    pairs = extract_lr_pairs(lr_data)
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
            "st_colocalization_score": normalize_st_colocalization_score(
                pair.get(
                    "st_colocalization_score",
                    pair.get("score", pair.get("rank_score")),
                )
            ),
        })

    # Load selected_top3_lr.json
    top3_path = base / "selected_top3_lr.json"
    top3_genes = set()
    if top3_path.exists():
        try:
            with open(top3_path) as f:
                top3_data = json.load(f)
            top3_pairs = top3_data if isinstance(top3_data, list) else top3_data.get("selected_pairs", top3_data.get("pairs", top3_data.get("selected", [])))
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
        logger.info("selected_top3_lr.json not found (optional — featured candidates determined by rubric scoring)")

    result["gene_symbols"] = sorted(all_genes)
    result["selected_top3_genes"] = sorted(top3_genes)

    # Load optional targets.json for user-selected interest cell types
    targets_path = base / "targets.json"
    if targets_path.exists():
        result["targets_json_found"] = True
        try:
            with open(targets_path) as f:
                targets_data = json.load(f)
            interest = targets_data.get("interest_celltypes", [])
            if isinstance(interest, str):
                interest = [interest]
            if isinstance(interest, list):
                result["interest_celltypes"] = [
                    str(x).strip() for x in interest if str(x).strip()
                ]
        except Exception as e:
            result["errors"].append(f"Failed to parse targets.json: {e}")

    return json.dumps(result, indent=2)


@tool
def load_evidence_files(data_dir: str) -> str:
    """Load evidence JSON files from the evidence/ subdirectory.

    For files up to ~200 KB (stage1_filter.json, assessment_results.json,
    per-pair stage1_*.json, per-gene ot_*.json / stage3_*.json, rubric
    auxiliaries, etc.) this returns the FULL PARSED JSON CONTENT so
    subagents can actually read pass/fail flags, rubric scores, drug
    names, and filter data directly. Large files above the limit
    (currently only stage2_evidence.json ~1.5 MB) fall back to a
    lightweight metadata summary (size_bytes, top_keys, record_count)
    to protect subagent context window budgets.

    Args:
        data_dir: Directory containing evidence/ subdirectory

    Returns:
        JSON with filename -> full content (small files) or
        metadata summary (large files). Inspect the ``_note`` key on
        summary entries to distinguish the two.
    """
    # Files at or below this size get full content; larger files stay
    # as metadata summaries to protect context window budgets.
    CONTENT_SIZE_LIMIT = 200_000  # 200 KB

    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    result = {
        "data_dir": str(base),
        "evidence_dir": str(evidence_dir),
        "files": {},
        "file_count": 0,
        "total_size_bytes": 0,
        "errors": [],
    }

    if not evidence_dir.exists():
        result["errors"].append(f"evidence/ directory not found at {evidence_dir}")
        return json.dumps(result, indent=2)

    for path in sorted(evidence_dir.glob("*.json")):
        try:
            size_bytes = path.stat().st_size
            with open(path) as f:
                data = json.load(f)

            if size_bytes <= CONTENT_SIZE_LIMIT:
                # Return full JSON content — subagents need actual values
                # (filter pass/fail flags, rubric scores, drug names, etc.)
                result["files"][path.name] = data
            else:
                # Large file: metadata summary only (protects context window)
                summary = {
                    "size_bytes": size_bytes,
                    "_note": (
                        f"content omitted (> {CONTENT_SIZE_LIMIT} bytes); "
                        "inspect sub-fields via scope-specific tools"
                    ),
                }
                if isinstance(data, dict):
                    summary["top_keys"] = list(data.keys())[:20]
                    summary["record_count"] = len(data)
                elif isinstance(data, list):
                    summary["record_count"] = len(data)
                    if data and isinstance(data[0], dict):
                        summary["item_keys"] = list(data[0].keys())[:10]
                else:
                    summary["record_count"] = 1
                result["files"][path.name] = summary

            result["file_count"] += 1
            result["total_size_bytes"] += size_bytes
        except Exception as e:
            result["errors"].append(f"Failed to load {path.name}: {e}")

    return json.dumps(result, indent=2)


@tool
def save_evidence(data_dir: str, filename: str, data: Union[str, dict, list]) -> str:
    """Save evidence data as a JSON file in the evidence/ subdirectory.

    Creates the evidence/ directory if it doesn't exist.

    Args:
        data_dir: Base directory for evidence storage
        filename: Filename (e.g., "ot_TGFB1.json", "assessment_results.json")
        data: JSON string or dict/list of data to save

    Returns:
        JSON with save status and file path
    """
    # Normalize dict/list to JSON string (Ollama may pass raw objects)
    if isinstance(data, (dict, list)):
        data = json.dumps(data)

    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    file_path = evidence_dir / filename
    result = {
        "saved": False,
        "path": str(file_path),
        "errors": [],
    }

    # Overwrite protection: prevent LLM from replacing non-empty evidence with empty data
    if filename in _SAVE_PROTECTED_FILES and file_path.exists():
        try:
            existing = json.loads(file_path.read_text())
            new_parsed = json.loads(data) if isinstance(data, str) else data
            if isinstance(existing, dict) and isinstance(new_parsed, dict):
                existing_has_data = any(
                    v for v in existing.values()
                    if isinstance(v, (dict, list)) and len(v) > 0
                )
                new_is_empty = all(
                    not v or (isinstance(v, (dict, list)) and len(v) == 0)
                    for v in new_parsed.values()
                    if isinstance(v, (dict, list))
                )
                if existing_has_data and new_is_empty:
                    result["saved"] = False
                    result["errors"].append(
                        f"BLOCKED: refusing to overwrite non-empty {filename} with empty data. "
                        "Existing file preserved. Use load_evidence_files() to read the data."
                    )
                    return json.dumps(result, indent=2)
        except Exception:
            pass  # if we can't read existing, allow overwrite

    try:
        parsed = json.loads(data)
        with open(file_path, "w") as f:
            json.dump(parsed, f, indent=2)
        result["saved"] = True
    except json.JSONDecodeError as e:
        # Try repairing trailing commas before falling back to raw text
        repaired = re.sub(r',\s*([}\]])', r'\1', data)
        try:
            parsed = json.loads(repaired)
            with open(file_path, "w") as f:
                json.dump(parsed, f, indent=2)
            result["saved"] = True
            result["errors"].append(
                "Repaired trailing commas in JSON before saving"
            )
        except Exception as repair_err:
            result["saved"] = False
            result["errors"].append(
                f"Data is not valid JSON even after trailing-comma repair: {repair_err}. "
                "File NOT saved. Please pass valid JSON to save_evidence."
            )
    except Exception as e:
        result["errors"].append(f"Failed to save: {e}")

    return json.dumps(result, indent=2)


@tool
def validate_evidence_completeness(data_dir: str) -> str:
    """Check that evidence files are non-empty before report generation.

    Returns a structured report of which data sources succeeded/failed,
    with an overall readiness flag. Call this BEFORE writing drug.md.
    """
    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"

    checks: dict = {
        "stage1_evidence": {"file": "stage1_evidence.json", "status": "missing", "record_count": 0},
        "stage1_filter": {"file": "stage1_filter.json", "status": "missing", "record_count": 0},
        "stage2_evidence": {"file": "stage2_evidence.json", "status": "missing", "record_count": 0, "non_empty_genes": 0},
        "known_drugs": {"file": "known_drugs.json", "status": "missing", "record_count": 0},
        "gene_manifest": {"file": "gene_manifest.json", "status": "missing", "record_count": 0},
    }

    for key, check in checks.items():
        path = evidence_dir / check["file"]
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            check["status"] = "present"
            if isinstance(data, dict):
                check["record_count"] = len(data)
                if key == "stage2_evidence":
                    non_empty = sum(
                        1 for v in data.values()
                        if isinstance(v, dict) and any(
                            isinstance(sub, (list, dict)) and len(sub) > 0
                            for sub in v.values()
                        )
                    )
                    check["non_empty_genes"] = non_empty
                    if non_empty == 0 and len(data) > 0:
                        check["status"] = "present_but_empty"
            elif isinstance(data, list):
                check["record_count"] = len(data)
            if check.get("record_count", 0) == 0 and check["status"] == "present":
                check["status"] = "present_but_empty"
        except Exception as e:
            check["status"] = f"parse_error: {e}"

    # Count ot_*.json files
    ot_files = list(evidence_dir.glob("ot_*.json")) if evidence_dir.exists() else []

    has_stage2_data = checks["stage2_evidence"].get("non_empty_genes", 0) > 0
    has_stage1_data = (
        checks["stage1_evidence"]["status"] == "present"
        and checks["stage1_evidence"]["record_count"] > 0
    )

    warnings = []
    if not has_stage1_data:
        warnings.append("Stage 1 evidence empty or missing — Census cross-validation may have failed")
    if not has_stage2_data:
        warnings.append("Stage 2 evidence empty or missing — OpenTargets/GWAS data may not have been saved")
    if not ot_files:
        warnings.append("No ot_*.json per-gene files found")

    return json.dumps({
        "data_dir": str(base),
        "evidence_dir": str(evidence_dir),
        "checks": checks,
        "ot_gene_file_count": len(ot_files),
        "has_stage1_data": has_stage1_data,
        "has_stage2_data": has_stage2_data,
        "ready_for_report": has_stage1_data or has_stage2_data,
        "warnings": warnings,
    }, indent=2)


@tool
def check_stage1_completion(data_dir: str) -> str:
    """Check whether Stage 1 was completed by evidence_assessor.

    Call this AFTER evidence_assessor completes and BEFORE proceeding to
    deep_diver. Returns a JSON object with stage1_complete flag,
    stage3_candidates count, and a recommendation for next steps.
    """
    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"

    result = {
        "stage1_complete": False,
        "has_assessment_results": False,
        "stage3_candidates_count": 0,
        "stage1_files_found": 0,
        "recommendation": "",
    }

    # 1. Check assessment_results.json exists
    assessment_path = evidence_dir / "assessment_results.json"
    if not assessment_path.exists():
        result["recommendation"] = (
            "assessment_results.json not found. evidence_assessor may not have "
            "completed rubric scoring. Pipeline data will be incomplete."
        )
        return json.dumps(result, indent=2)

    try:
        assessment = json.loads(assessment_path.read_text())
    except Exception as e:
        result["recommendation"] = f"Cannot parse assessment_results.json: {e}"
        return json.dumps(result, indent=2)

    result["has_assessment_results"] = True
    stage3_candidates = assessment.get("stage3_candidates", [])
    result["stage3_candidates_count"] = len(stage3_candidates)

    # 2. Zero candidates = valid state (no featured genes)
    if not stage3_candidates:
        result["stage1_complete"] = True
        result["recommendation"] = (
            "No stage3_candidates (zero featured genes). "
            "Skip deep_diver and hypothesis_writer, proceed to report_writer."
        )
        return json.dumps(result, indent=2)

    # 3. Check for stage1 evidence files
    stage1_files = list(evidence_dir.glob("stage1_*.json"))
    result["stage1_files_found"] = len(stage1_files)

    stage1_evidence_path = evidence_dir / "stage1_evidence.json"
    has_stage1_aggregate = stage1_evidence_path.exists()

    if stage1_files or has_stage1_aggregate:
        result["stage1_complete"] = True
        result["recommendation"] = "Stage 1 complete. Proceed to deep_diver."
    else:
        result["stage1_complete"] = False
        result["recommendation"] = (
            "WARNING: Stage 1 was NOT completed. No stage1_*.json files found. "
            "evidence_assessor likely hit recursion limit before Stage 1. "
            "Proceeding to deep_diver will produce incomplete results."
        )

    return json.dumps(result, indent=2)


@tool
def check_hypothesis_completion(data_dir: str) -> str:
    """Check whether hypothesis_writer produced hypothesis_report.json.

    Call this AFTER hypothesis_writer completes and BEFORE report_writer.
    Returns JSON with completion status and recommendation.
    """
    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    hyp_path = evidence_dir / "hypothesis_report.json"

    if not hyp_path.exists():
        return json.dumps({
            "hypothesis_complete": False,
            "recommendation": (
                "hypothesis_report.json not found. hypothesis_writer may have failed. "
                "Proceed to report_writer — it will generate the report without hypotheses. "
                "Section 4 will note that hypothesis generation was not completed."
            ),
        }, indent=2)

    try:
        hyp = json.loads(hyp_path.read_text())
        count = len(hyp.get("hypotheses", []))
        return json.dumps({
            "hypothesis_complete": True,
            "hypothesis_count": count,
            "recommendation": f"Found {count} hypotheses. Proceed to report_writer.",
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "hypothesis_complete": False,
            "recommendation": f"hypothesis_report.json exists but is invalid: {e}",
        }, indent=2)
