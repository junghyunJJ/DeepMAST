"""Evidence loading and saving tools for Drug Target Assessment Agent.

Handles loading lr_candidates.json (top-30 L-R pairs),
extracting gene symbols, and managing evidence JSON files.
selected_top3_lr.json is optional (legacy) — featured candidates
are now determined by rubric scoring in stage_logic.py.
"""

import functools
import json
import logging
import os
import re
from pathlib import Path
from typing import Union

from langchain_core.tools import tool
from src.agents.drug_target.tools.disease_context import initialize_disease_context
from src.agents.drug_target.tools.stage_logic import (
    classify_disease_type,
    infer_oncology_flag,
    normalize_st_colocalization_score,
)
from src.agents.drug_target.tools.stage2_service import extract_lr_pairs

# Module-level constant for overwrite protection (used in save_evidence)
_SAVE_PROTECTED_FILES = {"stage2_evidence.json", "known_drugs.json", "gene_manifest.json"}

# Files that are INVALID as hypothesis_writer inputs / citations.
# - Prior-run outputs (hypothesis_report, target_assessment) must not feed back
#   into the next generation's context (self-reference / loop-leak).
# - Legacy aggregates (stage1_audit/confidence/evidence) are superseded by
#   stage1_filter_results.json + per-pair stage1_<L>--<R>.json files.
_HYPOTHESIS_DENIED_CITATIONS: frozenset[str] = frozenset({
    "hypothesis_report.json",
    "target_assessment.json",
    "stage1_audit.json",
    "stage1_confidence.json",
    "stage1_evidence.json",
})

_HYPOTHESIS_CONTEXT_ONLY_CITATION_REASON = (
    "context-only cell-type resolution; cite Stage 1 pair files for Census evidence."
)
_HYPOTHESIS_CONTEXT_ONLY_CITATIONS: frozenset[str] = frozenset({
    "celltype_resolution.json",
})

# Files always loaded in full for hypothesis scope regardless of gene filter.
_HYPOTHESIS_ALWAYS_FULL: frozenset[str] = frozenset({
    "assessment_results.json",
    "celltype_resolution.json",
    "stage1_filter.json",
    "stage1_filter_results.json",
    "gene_manifest.json",
    "known_drugs.json",
    "rubric_scores.json",
})

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
    if disease:
        disease_source = "cli"
    elif lr_data.get("disease"):
        disease_source = "lr_candidates.json:disease"
    elif lr_data.get("disease_context"):
        disease_source = "lr_candidates.json:disease_context"
    else:
        disease_source = ""
    result["disease"] = disease or lr_data.get("disease", lr_data.get("disease_context", ""))
    if result["disease"]:
        try:
            initialize_disease_context(
                base / "evidence",
                input_disease=result["disease"],
                input_source=disease_source,
            )
        except Exception as exc:
            result["errors"].append(f"Failed to save disease_context.json: {exc}")
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


def _size_metadata_summary(data, size_bytes: int, content_limit: int) -> dict:
    """Return the generic oversized-file metadata summary used by scope=all."""
    summary: dict = {
        "size_bytes": size_bytes,
        "_note": (
            f"content omitted (> {content_limit} bytes); "
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
    return summary


def _load_featured_set(evidence_dir: Path) -> tuple[set[str], str | None]:
    """Return (uppercase featured-gene set, error_message_or_None).

    Reads `stage3_candidates` from assessment_results.json. Missing or
    malformed assessment is a hard error for hypothesis scope.
    """
    assessment_path = evidence_dir / "assessment_results.json"
    if not assessment_path.exists():
        return set(), f"assessment_results.json not found at {assessment_path}"
    try:
        assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    except Exception as e:
        return set(), f"Failed to parse assessment_results.json: {e}"
    candidates = assessment.get("stage3_candidates") if isinstance(assessment, dict) else None
    if not isinstance(candidates, list):
        return set(), "assessment_results.json has no stage3_candidates list"
    featured: set[str] = set()
    for c in candidates:
        if isinstance(c, dict):
            gene = (c.get("gene") or c.get("gene_symbol") or "").strip().upper()
            if gene:
                featured.add(gene)
    return featured, None


_STAGE3_NAME_RE = re.compile(r"^stage3_([A-Za-z0-9-]+)\.json$")
_OT_NAME_RE = re.compile(r"^ot_([A-Za-z0-9-]+)\.json$")
_STAGE1_PAIR_NAME_RE = re.compile(r"^stage1_([A-Za-z0-9-]+)--([A-Za-z0-9-]+)\.json$")


def _classify_hypothesis_scope_file(
    name: str,
    *,
    featured: set[str],
    filter_map: dict[str, bool],
) -> tuple[str, str | None]:
    """Return (action, reason) for a given filename under hypothesis scope.

    Actions:
      - "full"      : load full JSON content
      - "contrast"  : expose slim negative metadata outside support files
      - "stub_stale_stage3"
      - "stub_nonfeatured_ot"
      - "excluded"  : omit from files dict (record in excluded_files)
      - "fallback"  : defer to scope=all size-based logic
    """
    if name in _HYPOTHESIS_DENIED_CITATIONS:
        return "excluded", "legacy aggregate or prior-run output; not valid hypothesis input"
    if name in _HYPOTHESIS_ALWAYS_FULL:
        return "full", None

    m3 = _STAGE3_NAME_RE.match(name)
    if m3:
        gene = m3.group(1).upper()
        if gene in featured:
            return "full", None
        return "stub_stale_stage3", f"stale prior-run stage3 file; {gene} not in current stage3_candidates"

    mo = _OT_NAME_RE.match(name)
    if mo:
        gene = mo.group(1).upper()
        if gene in featured:
            return "full", None
        return "stub_nonfeatured_ot", "skipped: non-featured gene in hypothesis scope"

    mp = _STAGE1_PAIR_NAME_RE.match(name)
    if mp:
        pair_key = f"{mp.group(1).upper()}--{mp.group(2).upper()}"
        passed = filter_map.get(pair_key)
        if passed is True:
            return "full", None
        if passed is False:
            return "contrast", "failed Stage 1 pair; negative contrast metadata only"
        return "excluded", "Stage 1 pair missing from filter results; not valid hypothesis input"

    return "fallback", None


def _stage1_failed_contrast_metadata(
    filename: str,
    data: object,
    filter_metadata: dict[str, dict],
) -> dict:
    match = _STAGE1_PAIR_NAME_RE.match(filename)
    ligand = match.group(1).upper() if match else ""
    receptor = match.group(2).upper() if match else ""
    pair_key = f"{ligand}--{receptor}" if ligand and receptor else ""
    row = filter_metadata.get(pair_key, {})
    source = row if row else data if isinstance(data, dict) else {}
    failed_criteria = source.get("failed_criteria", [])
    if not isinstance(failed_criteria, list):
        failed_criteria = [str(failed_criteria)] if failed_criteria else []
    reason = (
        source.get("reason")
        or source.get("failure_reason")
        or source.get("failed_reason")
        or "failed Stage 1 filter"
    )
    return {
        "filename": filename,
        "role": "negative_contrast",
        "eligible_as_support": False,
        "ligand": ligand,
        "receptor": receptor,
        "pair_key": pair_key,
        "passed": False,
        "failed_criteria": failed_criteria,
        "reason": str(reason),
        "citation_policy": (
            "metadata-only negative contrast; do not cite as primary/support evidence"
        ),
    }


@tool
def load_evidence_files(data_dir: str, scope: str = "all") -> str:
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
        scope: "all" (default) preserves the legacy load-everything
            behavior. "hypothesis" restricts the payload to evidence that
            passed the evidence_assessor gates and is eligible for
            hypothesis_writer:
              * OpenTargets full content only for genes in stage3_candidates.
              * stage3_<GENE>.json full content only for current featured set
                (stale prior-run files are stubbed).
              * stage1_<L>--<R>.json full content only for PASSED pairs.
                FAILED pairs are excluded from ``files`` and exposed only as
                slim ``contrast_evidence`` metadata; unclassified pairs are
                excluded.
              * Legacy aggregates (stage1_audit/confidence/evidence) and
                prior-run outputs (hypothesis_report, target_assessment) are
                excluded entirely (not in ``files``, listed under
                ``excluded_files``). The ``save_evidence`` citation gate
                additionally rejects them as references.
              * Fail-closed: if stage1_filter_results.{json,csv} is missing or
                unparseable while per-pair Stage 1 files exist, hypothesis
                scope aborts with empty ``files`` instead of exposing
                unchecked Stage 1 content.

    Returns:
        JSON with ``files`` (filename -> full content or stub), ``excluded_files``
        (hypothesis scope only), ``file_count``, ``total_size_bytes``, and
        ``errors``. For stub entries, inspect the ``_note`` key.
    """
    CONTENT_SIZE_LIMIT = 200_000  # 200 KB

    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    result: dict = {
        "data_dir": str(base),
        "evidence_dir": str(evidence_dir),
        "scope": scope,
        "files": {},
        "contrast_evidence": {},
        "excluded_files": [],
        "file_count": 0,
        "contrast_count": 0,
        "total_size_bytes": 0,
        "errors": [],
    }

    if not evidence_dir.exists():
        result["errors"].append(f"evidence/ directory not found at {evidence_dir}")
        return json.dumps(result, indent=2)

    hypothesis_scope = (scope or "all").lower() == "hypothesis"
    featured: set[str] = set()
    filter_map: dict[str, bool] = {}
    filter_metadata: dict[str, dict] = {}

    if hypothesis_scope:
        featured, feat_err = _load_featured_set(evidence_dir)
        if feat_err:
            result["errors"].append(
                f"hypothesis scope aborted: {feat_err}. "
                "Fall back to scope='all' if the featured set cannot be resolved."
            )
            return json.dumps(result, indent=2)
        filter_map, filter_err = _load_stage1_filter_results_status(evidence_dir)
        any_pair_file = any(
            _STAGE1_PAIR_NAME_RE.match(p.name) for p in evidence_dir.glob("stage1_*.json")
        )
        if filter_err and any_pair_file:
            logger.warning(
                "hypothesis scope: stage1_filter_results.{json,csv} unavailable; "
                "aborting rather than exposing unchecked Stage 1 pair content."
            )
            result["errors"].append(
                f"hypothesis scope aborted: {filter_err}. "
                "Stage 1 pair files are hidden until pass/fail eligibility is available."
            )
            return json.dumps(result, indent=2)
        filter_metadata = _load_stage1_filter_results_metadata(evidence_dir)

    for path in sorted(evidence_dir.glob("*.json")):
        name = path.name
        try:
            size_bytes = path.stat().st_size
        except Exception as e:
            result["errors"].append(f"Failed to stat {name}: {e}")
            continue

        if hypothesis_scope:
            action, reason = _classify_hypothesis_scope_file(
                name,
                featured=featured,
                filter_map=filter_map,
            )
            if action == "excluded":
                result["excluded_files"].append({"name": name, "reason": reason or ""})
                continue
        else:
            action = "fallback"
            reason = None

        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            result["errors"].append(f"Failed to load {name}: {e}")
            continue

        if action == "contrast":
            result["contrast_evidence"][name] = _stage1_failed_contrast_metadata(
                name,
                data,
                filter_metadata,
            )
            result["excluded_files"].append({"name": name, "reason": reason or ""})
            result["contrast_count"] += 1
        elif action == "full":
            result["files"][name] = data
        elif action == "stub_stale_stage3" or action == "stub_nonfeatured_ot":
            stub: dict = {"size_bytes": size_bytes, "_note": reason or ""}
            if isinstance(data, dict):
                stub["top_keys"] = list(data.keys())[:5]
            result["files"][name] = stub
        else:  # "fallback" — size-based behavior (preserves scope=all logic)
            if size_bytes <= CONTENT_SIZE_LIMIT:
                result["files"][name] = data
            else:
                result["files"][name] = _size_metadata_summary(data, size_bytes, CONTENT_SIZE_LIMIT)

        if action != "contrast":
            result["file_count"] += 1
            result["total_size_bytes"] += size_bytes

    if hypothesis_scope:
        stage1_pair_files = sorted(
            name
            for name in result["files"]
            if _STAGE1_PAIR_NAME_RE.match(name)
            and filter_map.get(name[len("stage1_"):-len(".json")].upper()) is True
        )
        result.update(_stage1_pair_usage_guidance(evidence_dir, stage1_pair_files))

    return json.dumps(result, indent=2)


def _list_real_evidence_filenames(evidence_dir: Path) -> set[str]:
    """Return the set of real filenames currently in evidence/ (no dotfiles)."""
    if not evidence_dir.exists():
        return set()
    return {p.name for p in evidence_dir.iterdir() if not p.name.startswith(".")}


def _stage1_metric_direction(metric: object) -> str:
    if not isinstance(metric, dict):
        return "not_determined"
    risk_ratio = metric.get("risk_ratio")
    if isinstance(risk_ratio, (int, float)):
        if risk_ratio > 1:
            return "enriched"
        if risk_ratio < 1:
            return "depleted"
    diff = metric.get("diff")
    if isinstance(diff, (int, float)):
        if diff > 0:
            return "enriched"
        if diff < 0:
            return "depleted"
    return "not_determined"


def _stage1_target_vs_rest(payload: object) -> dict:
    census = payload.get("census_validation") if isinstance(payload, dict) else None
    if not isinstance(census, dict):
        return {}
    target_vs_rest = census.get("target_vs_rest")
    return target_vs_rest if isinstance(target_vs_rest, dict) else {}


def _stage1_usage_record(filename: str, payload: object) -> dict:
    """Classify a passed Stage 1 pair for hypothesis-writer cell-type usage."""
    pair_key = filename[len("stage1_"):-len(".json")].upper()
    target_vs_rest = _stage1_target_vs_rest(payload)
    directions = {
        key: _stage1_metric_direction(target_vs_rest.get(key))
        for key in ("gene_a", "gene_b", "coexpression")
    }
    target_cell_intrinsic = (
        directions["coexpression"] == "enriched"
        and directions["gene_a"] != "depleted"
        and directions["gene_b"] != "depleted"
    )
    target_cell_depleted_metrics = [
        key for key, direction in directions.items() if direction == "depleted"
    ]
    usage = "interest_cell_intrinsic" if target_cell_intrinsic else "spatial_niche_only"
    if target_cell_intrinsic:
        citation_policy = (
            "May support interest-cell intrinsic or resolved-Census-cell "
            "coexpression claims when the hypothesis names that cell type and "
            "the validation approach tests that cell context."
        )
    else:
        citation_policy = (
            "Passed Stage 1 pair, but not interest-cell intrinsic by "
            "target-vs-rest direction. Do not cite as AT2, Transitional AT2, "
            "pulmonary/alveolar epithelial, or resolved-Census-cell support; "
            "use only as secondary non-interest-cell spatial-niche/cross-cell "
            "framing, or cover the gene with stage3/ot evidence instead."
        )
    return {
        "filename": filename,
        "pair_key": pair_key,
        "usage": usage,
        "target_cell_intrinsic": target_cell_intrinsic,
        "target_vs_rest_directions": directions,
        "target_cell_depleted_metrics": target_cell_depleted_metrics,
        "citation_policy": citation_policy,
    }


def _stage1_pair_usage_guidance(
    evidence_dir: Path,
    stage1_pair_files: list[str],
) -> dict:
    records: list[dict] = []
    for filename in stage1_pair_files:
        path = evidence_dir / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        records.append(_stage1_usage_record(filename, payload))

    return {
        "stage1_pair_usage_guidance": records,
        "interest_cell_intrinsic_stage1_pair_files": [
            record["filename"]
            for record in records
            if record["usage"] == "interest_cell_intrinsic"
        ],
        "spatial_niche_only_stage1_pair_files": [
            record["filename"]
            for record in records
            if record["usage"] == "spatial_niche_only"
        ],
    }


def _validate_hypothesis_report_references(
    parsed: dict,
    evidence_dir: Path,
) -> list[str]:
    """Check hypotheses[*].evidence_references against real evidence/ files.

    Returns a list of human-readable error strings; empty if all references
    point to files that exist on disk. Purely syntactic — does not verify
    that the cited file contains the claimed quantitative value, only that
    the filename exists. Used by save_evidence to block hypothesis_writer
    from persisting hallucinated filenames like `stage1_CD4_ITGB2.json`
    (real convention uses `--`, not `_`).
    """
    if not isinstance(parsed, dict):
        return []
    hypotheses = parsed.get("hypotheses")
    if not isinstance(hypotheses, list):
        return []
    real = _list_real_evidence_filenames(evidence_dir)
    filter_results, filter_err = _load_stage1_filter_results_status(evidence_dir)
    errors: list[str] = []
    for idx, hyp in enumerate(hypotheses):
        if not isinstance(hyp, dict):
            continue
        refs = hyp.get("evidence_references", [])
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                continue
            if ".json_FAILED" in ref:
                errors.append(
                    f"hypotheses[{idx}].evidence_references cites '{ref}'. "
                    "The _FAILED suffix is not valid for new hypothesis reports; "
                    "failed Stage 1 pairs must be removed from hypothesis evidence."
                )
                continue
            ref_stripped = ref
            # evidence_references entries may include a qualifier such as
            # "stage1_FN1--ITGB2.json (passed filter)". Extract the leading
            # token ending in .json for comparison.
            token_match = re.search(r"([A-Za-z0-9_.\-]+\.json)", ref_stripped)
            if not token_match:
                continue
            token = token_match.group(1)
            if token in _HYPOTHESIS_DENIED_CITATIONS:
                errors.append(
                    f"hypotheses[{idx}].evidence_references cites '{token}' "
                    "which is a legacy aggregate or prior-run output forbidden "
                    "as hypothesis input."
                )
                continue
            if token in _HYPOTHESIS_CONTEXT_ONLY_CITATIONS:
                errors.append(
                    f"hypotheses[{idx}].evidence_references cites '{token}' "
                    f"which is {_HYPOTHESIS_CONTEXT_ONLY_CITATION_REASON}"
                )
                continue
            m = _STAGE1_PAIR_NAME_RE.match(token)
            if m:
                pair_key = f"{m.group(1).upper()}--{m.group(2).upper()}"
                if filter_results.get(pair_key) is not True:
                    reason = (
                        f"no passing Stage 1 filter entry found for '{pair_key}'"
                        if not filter_err
                        else filter_err
                    )
                    errors.append(
                        f"hypotheses[{idx}].evidence_references cites Stage 1 "
                        f"pair '{pair_key}' without proven passed=true status "
                        f"({reason}). Stage 1 pair citations must be eligible "
                        "hypothesis evidence."
                    )
                    continue
            if token not in real:
                errors.append(
                    f"hypotheses[{idx}].evidence_references cites '{token}' "
                    f"which is not in evidence/ directory."
                )
    return errors


# ---------------------------------------------------------------------------
# Deterministic TOP-N coverage + evidence_coverage_pct + FAILED-pair gate
# ---------------------------------------------------------------------------


def _stage1_filter_rows_to_map(rows: object) -> dict[str, bool]:
    """Return {"<LIGAND>--<RECEPTOR>": passed_bool} from filter rows."""
    if not isinstance(rows, list):
        return {}
    return {
        f"{(r.get('ligand') or '').upper()}--{(r.get('receptor') or '').upper()}": bool(r.get("passed"))
        for r in rows
        if isinstance(r, dict) and (r.get("ligand") or r.get("receptor"))
    }


def _stage1_filter_rows_to_metadata(rows: object) -> dict[str, dict]:
    """Return normalized Stage 1 row metadata keyed by ``<LIGAND>--<RECEPTOR>``."""
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ligand = str(row.get("ligand") or "").strip().upper()
        receptor = str(row.get("receptor") or "").strip().upper()
        if not ligand or not receptor:
            continue
        out[f"{ligand}--{receptor}"] = row
    return out


def _load_stage1_filter_results_status(evidence_dir: Path) -> tuple[dict[str, bool], str | None]:
    """Return Stage 1 pass/fail map plus a parse/presence error, if any."""
    json_path = evidence_dir / "stage1_filter_results.json"
    if json_path.exists():
        try:
            rows = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                return {}, "stage1_filter_results.json is not a list"
            return _stage1_filter_rows_to_map(rows), None
        except Exception as exc:
            return {}, f"Failed to parse stage1_filter_results.json: {exc}"
    csv_path = evidence_dir / "stage1_filter_results.csv"
    if csv_path.exists():
        import csv as _csv
        try:
            with open(csv_path, encoding="utf-8") as _f:
                return {
                    f"{(r.get('ligand') or '').upper()}--{(r.get('receptor') or '').upper()}":
                        str(r.get('passed', '')).lower() in ("true", "1", "yes")
                    for r in _csv.DictReader(_f)
                    if (r.get("ligand") or r.get("receptor"))
                }, None
        except Exception as exc:
            return {}, f"Failed to parse stage1_filter_results.csv: {exc}"
    return {}, "stage1_filter_results.json or stage1_filter_results.csv not found"


def _load_stage1_filter_results_metadata(evidence_dir: Path) -> dict[str, dict]:
    """Return raw Stage 1 filter rows keyed by pair, best-effort."""
    json_path = evidence_dir / "stage1_filter_results.json"
    if json_path.exists():
        try:
            return _stage1_filter_rows_to_metadata(
                json.loads(json_path.read_text(encoding="utf-8"))
            )
        except Exception:
            return {}
    csv_path = evidence_dir / "stage1_filter_results.csv"
    if csv_path.exists():
        import csv as _csv
        try:
            with open(csv_path, encoding="utf-8") as _f:
                return _stage1_filter_rows_to_metadata(list(_csv.DictReader(_f)))
        except Exception:
            return {}
    return {}


def _load_stage1_filter_results(evidence_dir: Path) -> dict[str, bool]:
    """Return {"<LIGAND>--<RECEPTOR>": passed_bool} from Stage 1 filter results.

    Falls back to the CSV if JSON sidecar is absent (back-compat with pre-PR-1 runs).
    Returns empty dict if neither file exists or parsing fails.
    """
    filter_map, _ = _load_stage1_filter_results_status(evidence_dir)
    return filter_map


def _split_stage1_pair_key(pair_key: str) -> tuple[str, str] | None:
    if "--" not in pair_key:
        return None
    ligand, receptor = pair_key.split("--", 1)
    ligand = ligand.strip().upper()
    receptor = receptor.strip().upper()
    if not ligand or not receptor:
        return None
    return ligand, receptor


def _stage1_filename_for_pair(pair_key: str) -> str | None:
    parts = _split_stage1_pair_key(pair_key)
    if not parts:
        return None
    return f"stage1_{parts[0]}--{parts[1]}.json"


def _eligible_hypothesis_stage_files(
    evidence_dir: Path,
    featured_genes: list[str],
    filter_results: dict[str, bool],
) -> set[str]:
    """Return real stage1/stage3 filenames eligible for hypothesis coverage."""
    real = _list_real_evidence_filenames(evidence_dir)
    eligible: set[str] = set()
    for gene in featured_genes:
        name = f"stage3_{gene.strip().upper()}.json"
        if name in real:
            eligible.add(name)
    for pair_key, passed in filter_results.items():
        if passed is not True:
            continue
        name = _stage1_filename_for_pair(pair_key)
        if name and name in real:
            eligible.add(name)
    return eligible


_PAIR_INTERACTION_CUE_RE = re.compile(
    r"\b("
    r"axis|axes|interact(?:ion|s|ing)?|pair|pairs|ppi|string|census|"
    r"co-?express(?:ion|ed)?|ligand[-\s]?receptor|l-r|binding|binds|"
    r"coupl(?:e|es|ing)|complex"
    r")\b",
    re.IGNORECASE,
)


def _failed_pair_text_pattern(ligand: str, receptor: str) -> re.Pattern[str]:
    sep = r"(?:\s*(?:--|[-/–—])\s*|\s+)"
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(ligand)}{sep}{re.escape(receptor)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _hypothesis_text_for_pair_check(hyp: dict) -> str:
    fields = (
        hyp.get("title", ""),
        hyp.get("core_claim", ""),
        hyp.get("falsifiable_prediction", ""),
    )
    return "\n".join(str(f) for f in fields if f)


def _validate_failed_pair_claims(
    hypotheses: list,
    filter_results: dict[str, bool],
) -> list[str]:
    """Reject failed Stage 1 pair citations and primary semantic pair claims."""
    errors: list[str] = []
    failed_pairs = [
        (pair_key, parts[0], parts[1])
        for pair_key, passed in filter_results.items()
        if passed is False and (parts := _split_stage1_pair_key(pair_key)) is not None
    ]
    if not failed_pairs or not isinstance(hypotheses, list):
        return errors

    for idx, hyp in enumerate(hypotheses):
        if not isinstance(hyp, dict):
            continue

        refs = hyp.get("evidence_references", [])
        if not isinstance(refs, list):
            refs = []
        for ref in refs:
            if not isinstance(ref, str):
                continue
            m = re.match(
                r"^(?:.*?)(stage1_([A-Za-z0-9-]+)--([A-Za-z0-9-]+)\.json)(?:_FAILED)?",
                ref,
            )
            if not m:
                continue
            pair_key = f"{m.group(2).upper()}--{m.group(3).upper()}"
            if filter_results.get(pair_key) is False:
                errors.append(
                    f"hypotheses[{idx}] cites failed Stage 1 pair '{pair_key}'. "
                    "Failed pairs are excluded from hypothesis generation; remove the "
                    "reference and rebuild the hypothesis from passed evidence."
                )

        text = _hypothesis_text_for_pair_check(hyp)
        upper_text = text.upper()
        entities = hyp.get("biological_entities", {}) or {}
        raw_genes = entities.get("genes", []) if isinstance(entities, dict) else []
        entity_genes = {
            str(g).strip().upper()
            for g in raw_genes
            if isinstance(g, str) and str(g).strip()
        }
        text_clauses = [
            clause
            for clause in re.split(r"[\n.;:]+", text)
            if clause.strip()
        ]
        for pair_key, ligand, receptor in failed_pairs:
            direct_pattern = _failed_pair_text_pattern(ligand, receptor)
            reverse_pattern = _failed_pair_text_pattern(receptor, ligand)
            if direct_pattern.search(upper_text) or reverse_pattern.search(upper_text):
                errors.append(
                    f"hypotheses[{idx}] makes a primary claim about failed Stage 1 "
                    f"pair '{pair_key}' in title/core_claim/falsifiable_prediction."
                )
                continue
            related_clause = any(
                ligand in clause.upper()
                and receptor in clause.upper()
                and _PAIR_INTERACTION_CUE_RE.search(clause)
                for clause in text_clauses
            )
            if ligand in entity_genes and receptor in entity_genes and related_clause:
                errors.append(
                    f"hypotheses[{idx}] lists both genes from failed Stage 1 pair "
                    f"'{pair_key}' while using pair/axis/interaction language. "
                    "Remove the failed pair claim or rebuild from passed evidence."
                )
    return errors


def _validate_hypothesis_report_topn_and_failed_pairs(
    parsed: dict,
    evidence_dir: Path,
) -> dict:
    """Deterministic gates for hypothesis_report.json.

    Returns a diagnostic dict with keys:
      - topn_coverage: {covered, missing, coverage_pct}
      - evidence_coverage_pct: deterministic float (0..100)
      - gap_analysis: {total_evidence_files, referenced_files, orphan_files}
      - failed_pair_violations: [strings] -- hypotheses citing or claiming failed Stage 1 pairs
      - reject_reason: str | None  (non-None means save_evidence MUST refuse)
    """
    diag: dict = {
        "topn_coverage": {"covered": [], "missing": [], "coverage_pct": 100.0},
        "evidence_coverage_pct": 0.0,
        "gap_analysis": {
            "total_evidence_files": 0,
            "referenced_files": 0,
            "orphan_files": [],
        },
        "failed_pair_violations": [],
        "reject_reason": None,
    }

    # 1. Resolve the FEATURED gene list from assessment_results.json.
    #    stage3_candidates is the single narrowed set (rubric ∩ Stage 1 PASS);
    #    hypothesis_writer must cover every gene in this list.
    assessment_path = evidence_dir / "assessment_results.json"
    featured_genes: list[str] = []
    if assessment_path.exists():
        try:
            assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
            validated = assessment.get("stage3_candidates", [])
            featured_genes = [
                (c.get("gene") or "").strip()
                for c in validated
                if isinstance(c, dict) and c.get("gene")
            ]
        except Exception:
            featured_genes = []

    # 2. Compute TOP-N coverage deterministically.
    hypotheses = parsed.get("hypotheses", []) if isinstance(parsed, dict) else []
    cited_genes: set[str] = set()
    if isinstance(hypotheses, list):
        for hyp in hypotheses:
            if not isinstance(hyp, dict):
                continue
            ents = hyp.get("biological_entities", {}) or {}
            for g in ents.get("genes", []) or []:
                if isinstance(g, str) and g.strip():
                    cited_genes.add(g.strip().upper())

    if featured_genes:
        upper_featured = {g.upper(): g for g in featured_genes}
        covered = sorted(g for upper, g in upper_featured.items() if upper in cited_genes)
        missing = sorted(g for upper, g in upper_featured.items() if upper not in cited_genes)
        diag["topn_coverage"] = {
            "covered": covered,
            "missing": missing,
            "coverage_pct": round(100.0 * len(covered) / len(featured_genes), 2),
        }
        if missing:
            diag["reject_reason"] = (
                f"topn_missing={missing}. hypothesis_writer MUST generate one "
                f"[FEATURED-GAP] hypothesis per missing gene before retrying. "
                f"Do NOT retry the same payload."
            )

    filter_results, filter_err = _load_stage1_filter_results_status(evidence_dir)

    # 3. Deterministic evidence_coverage_pct over eligible hypothesis evidence only:
    #    current stage3 candidate files plus Stage 1 pair files that passed the filter.
    stage_files = _eligible_hypothesis_stage_files(
        evidence_dir,
        featured_genes,
        filter_results,
    )
    cited_files: set[str] = set()
    if isinstance(hypotheses, list):
        for hyp in hypotheses:
            if not isinstance(hyp, dict):
                continue
            for ref in hyp.get("evidence_references", []) or []:
                if not isinstance(ref, str):
                    continue
                token_match = re.search(r"([A-Za-z0-9_.\-]+\.json)", ref.replace(".json_FAILED", ".json"))
                if token_match:
                    cited_files.add(token_match.group(1))
    cited_stage = cited_files & stage_files
    diag["gap_analysis"] = {
        "total_evidence_files": len(stage_files),
        "referenced_files": len(cited_stage),
        "orphan_files": sorted(stage_files - cited_stage),
    }
    if stage_files:
        diag["evidence_coverage_pct"] = round(100.0 * len(cited_stage) / len(stage_files), 2)

    # 4. Failed Stage 1 pair block. This is semantic as well as citation-based:
    #    failed pairs must not be primary hypotheses even if no failed file is cited.
    if filter_results and isinstance(hypotheses, list):
        diag["failed_pair_violations"].extend(
            _validate_failed_pair_claims(hypotheses, filter_results)
        )
        if diag["failed_pair_violations"] and not diag["reject_reason"]:
            diag["reject_reason"] = (
                f"{len(diag['failed_pair_violations'])} failed Stage 1 pair "
                "claim/reference violation(s). See failed_pair_violations for details."
            )

    return diag


# ---------------------------------------------------------------------------
# Hypothesis quantitative-prediction grounding check (soft flag, not reject)
# ---------------------------------------------------------------------------
#
# Four-tier classification (B7a, tightened regex + structured cross-validate):
#   qualitative       — no numeric effect-size token present
#   grounded_verified — numeric token AND a specific evidence file citation
#                       AND the number matches a value in that file (1% tol)
#   grounded          — numeric token AND a specific evidence file citation,
#                       but the cited number is not in the file (LLM cited
#                       the right file but fabricated the magnitude)
#   unverified        — numeric token present without any evidence-file cite
#
# The tightened regex requires `from stage\d_*.json` or `from ot_*.json`
# anywhere in the prediction — generic cues like "based on the passed
# filter" no longer qualify, fixing the false-positive storm from the
# prior (loose) regex.

_ROUND_PCT_RE = re.compile(r"\b(?:10|20|25|30|33|40|50|60|66|70|75|80|90)\s*%")
_FOLD_RE = re.compile(r"\b\d+(?:\.\d+)?\s*-?\s*fold\b", re.IGNORECASE)
_NUMERIC_TOKEN_RE = re.compile(r"\b\d+(?:\.\d+)?\b")

# File-anchored grounding cue: must name a real evidence file path.
_GROUND_CUE_RE = re.compile(
    r"from\s+(stage\d_[A-Za-z0-9\-]+(?:--[A-Za-z0-9\-]+)?\.json|ot_[A-Za-z0-9\-]+\.json)",
    re.IGNORECASE,
)


@functools.lru_cache(maxsize=64)
def _load_evidence_cached(path_str: str) -> dict | None:
    """Cache parsed evidence JSON so a hypothesis_report with 6-8 hypotheses
    each citing 4-6 files does not re-read the same stage1_*/ot_*.json a
    dozen times. Bounded by 500 KB file size to avoid memory surprises.
    """
    try:
        p = Path(path_str)
        if not p.exists() or p.stat().st_size > 500 * 1024:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _evidence_has_value(
    node: object, target: float, tolerance: float = 0.01
) -> bool:
    """Recursively search nested dict/list for a numeric value within
    ``tolerance`` (relative, on magnitude). Matches floats and int-likes.
    """
    if isinstance(node, bool):
        return False  # bools are ints in Python; avoid 1.0 ↔ True collisions
    if isinstance(node, (int, float)):
        try:
            target_f = float(target)
            scale = max(abs(target_f), 1.0)
            return abs(float(node) - target_f) <= tolerance * scale
        except (ValueError, TypeError):
            return False
    if isinstance(node, dict):
        return any(_evidence_has_value(v, target, tolerance) for v in node.values())
    if isinstance(node, list):
        return any(_evidence_has_value(v, target, tolerance) for v in node)
    return False


def _classify_prediction_grounding(
    prediction: str,
    evidence_dir: Path | None = None,
) -> tuple[str, list[str], list[str]]:
    """Classify a falsifiable_prediction string.

    Returns ``(label, matched_tokens, cited_files)`` where label ∈
    {qualitative, grounded_verified, grounded, unverified}. The
    ``cited_files`` list is populated only when the tightened regex matched.

    Percentage tokens like ``40%`` are compared against ``40`` and ``0.40``
    (both common representations in evidence JSON). Fold tokens like
    ``2-fold`` match on the integer ``2``.
    """
    if not isinstance(prediction, str) or not prediction.strip():
        return "qualitative", [], []

    # Collect effect-size tokens (percentages + fold changes)
    tokens: list[str] = []
    tokens.extend(m.group(0) for m in _ROUND_PCT_RE.finditer(prediction))
    tokens.extend(m.group(0) for m in _FOLD_RE.finditer(prediction))
    if not tokens:
        return "qualitative", [], []

    # Tightened cue: must reference a concrete evidence file
    cited_files = list({m.group(1) for m in _GROUND_CUE_RE.finditer(prediction)})
    if not cited_files:
        return "unverified", tokens, []

    # If no evidence_dir provided, stop at "grounded" (cue-only, not verified)
    if evidence_dir is None:
        return "grounded", tokens, cited_files

    # Extract numeric values adjacent to each token and cross-validate
    # against the referenced evidence files.
    def _token_as_float(tok: str) -> list[float]:
        """Return plausible numeric representations of an effect-size token.

        '40%' -> [40.0, 0.40]
        '2-fold' -> [2.0]
        '2.5-fold' -> [2.5]
        """
        t = tok.strip().lower()
        if t.endswith("%"):
            v = float(t.rstrip("%").strip())
            return [v, v / 100.0]
        m = re.match(r"(\d+(?:\.\d+)?)\s*-?\s*fold", t)
        if m:
            return [float(m.group(1))]
        return []

    verified = False
    for tok in tokens:
        candidate_values = _token_as_float(tok)
        if not candidate_values:
            continue
        for fname in cited_files:
            evidence = _load_evidence_cached(str(evidence_dir / fname))
            if not isinstance(evidence, dict):
                continue
            if any(_evidence_has_value(evidence, v) for v in candidate_values):
                verified = True
                break
        if verified:
            break

    return ("grounded_verified" if verified else "grounded", tokens, cited_files)


def _sanitize_gap_analysis(parsed: dict, evidence_dir: Path) -> int:
    """Strip `_FAILED` suffix from ``gap_analysis.orphan_files`` entries when
    the unsuffixed file actually exists on disk.

    Historical hypothesis reports may contain the legacy suffix. It does not
    belong on filesystem-grounded lists like ``orphan_files``, where every entry
    must correspond to a real file. Returns the number of entries sanitized.
    """
    if not isinstance(parsed, dict):
        return 0
    ga = parsed.get("gap_analysis")
    if not isinstance(ga, dict):
        return 0
    orphans = ga.get("orphan_files")
    if not isinstance(orphans, list):
        return 0
    real = _list_real_evidence_filenames(evidence_dir) if evidence_dir.exists() else set()
    cleaned: list = []
    n_stripped = 0
    for entry in orphans:
        if isinstance(entry, str) and entry.endswith("_FAILED"):
            base = entry[: -len("_FAILED")]
            if base in real:
                cleaned.append(base)
                n_stripped += 1
                continue
        cleaned.append(entry)
    if n_stripped:
        ga["orphan_files"] = cleaned
    return n_stripped


def _tag_hypothesis_prediction_grounding(
    parsed: dict, evidence_dir: Path | None = None
) -> dict:
    """Mutate each hypothesis in-place with ``prediction_grounding``,
    ``prediction_numeric_tokens``, and ``prediction_cited_files`` fields,
    and return a summary dict.

    When ``evidence_dir`` is passed, numeric tokens are cross-validated
    against the referenced evidence files — successful matches earn the
    ``grounded_verified`` label; a cue without a matching value stays
    ``grounded``. When no ``evidence_dir`` is provided, the classifier
    tops out at ``grounded`` (cue-only).
    """
    summary = {
        "grounded_verified": 0,
        "grounded": 0,
        "qualitative": 0,
        "unverified": 0,
        "grounded_indices": [],
        "unverified_indices": [],
    }
    hypotheses = parsed.get("hypotheses") if isinstance(parsed, dict) else None
    if not isinstance(hypotheses, list):
        return summary
    for idx, hyp in enumerate(hypotheses):
        if not isinstance(hyp, dict):
            continue
        label, tokens, cited = _classify_prediction_grounding(
            hyp.get("falsifiable_prediction", ""),
            evidence_dir=evidence_dir,
        )
        hyp["prediction_grounding"] = label
        if tokens:
            hyp["prediction_numeric_tokens"] = tokens
        if cited:
            hyp["prediction_cited_files"] = cited
        summary[label] = summary.get(label, 0) + 1
        if label == "grounded":
            summary["grounded_indices"].append(idx)
        if label == "unverified":
            summary["unverified_indices"].append(idx)
    return summary


# ---------------------------------------------------------------------------
# PR1-3: Path-traversal allow-list for save_evidence filename argument
# ---------------------------------------------------------------------------

# Positive allow-list: only safe characters + .json/.csv extension. No subdirs, no traversal.
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.(json|csv)$")


def _is_safe_filename(filename: str) -> bool:
    """True iff filename has no traversal vectors and matches the safe pattern."""
    if not isinstance(filename, str) or not filename:
        return False
    if ".." in filename or filename.startswith("/") or "\\" in filename or "\x00" in filename:
        return False
    return bool(_SAFE_FILENAME_RE.match(filename))


@tool
def save_evidence(data_dir: str, filename: str, data: Union[str, dict, list]) -> str:
    """Save evidence data as a JSON file in the evidence/ subdirectory.

    Creates the evidence/ directory if it doesn't exist.

    For ``filename == "hypothesis_report.json"``, the function additionally
    validates every ``hypotheses[*].evidence_references`` entry against the
    real evidence/ directory contents. If any cited filename is hallucinated
    (e.g. ``stage1_CD4_ITGB2.json`` with single underscore when the real
    convention is ``stage1_CD4--ITGB2.json`` with double hyphen, or a file
    that was never created), the file is NOT saved and the error list is
    returned so the model can rewrite with real filenames.

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

    # PR1-3: Path-traversal allow-list (OWASP A01).
    # Reject any filename containing "..", absolute paths, backslashes, null bytes,
    # subdirectories, or characters outside the safe set. Defense-in-depth: also assert
    # resolved parent matches evidence_dir.
    if not _is_safe_filename(filename):
        return json.dumps({
            "saved": False,
            "path": str(evidence_dir),
            "errors": [
                f"BLOCKED: unsafe filename {filename!r}. "
                f"Allowed: ^[A-Za-z0-9_.-]+\\.(json|csv)$ (no subdirs, no traversal)."
            ],
        }, indent=2)
    file_path = (evidence_dir / filename).resolve()
    if file_path.parent != evidence_dir.resolve():
        return json.dumps({
            "saved": False,
            "path": str(evidence_dir),
            "errors": [
                f"BLOCKED: filename {filename!r} resolves outside evidence_dir."
            ],
        }, indent=2)

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
        except Exception as exc:
            # PR1-8 (pulled forward from P2-5): surface corruption instead of silently allowing overwrite.
            logger.warning(
                "Existing protected file %s unparseable during overwrite check: %s. "
                "Allowing overwrite — operator should investigate.", file_path, exc,
            )

    parsed = None
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        # Try repairing trailing commas before falling back to raw text
        repaired = re.sub(r',\s*([}\]])', r'\1', data)
        try:
            parsed = json.loads(repaired)
            result["errors"].append(
                "Repaired trailing commas in JSON before saving"
            )
        except Exception as repair_err:
            result["saved"] = False
            result["errors"].append(
                f"Data is not valid JSON even after trailing-comma repair: {repair_err}. "
                "File NOT saved. Please pass valid JSON to save_evidence."
            )
            return json.dumps(result, indent=2)

    # hypothesis_report.json: validate every evidence_references citation
    # against real files before writing. Prevents hallucinated filenames
    # from polluting the hypothesis output.
    if filename == "hypothesis_report.json" and isinstance(parsed, dict):
        from src.agents.drug_target.tools.hypothesis_schema import (
            persist_hypothesis_report,
        )

        canonical_result = persist_hypothesis_report(base, parsed)
        if canonical_result.get("saved"):
            return json.dumps(canonical_result, indent=2)
        real = sorted(_list_real_evidence_filenames(evidence_dir))
        canonical_result.setdefault("available_files", real)
        return json.dumps(canonical_result, indent=2)

    try:
        with open(file_path, "w") as f:
            json.dump(parsed, f, indent=2)
        result["saved"] = True
    except Exception as e:
        result["errors"].append(f"Failed to save: {e}")

    return json.dumps(result, indent=2)


@tool
def validate_evidence_references(data_dir: str, references: list[str]) -> str:
    """Validate a list of filename citations against the real evidence/ dir.

    Use this tool from hypothesis_writer BEFORE calling save_evidence for
    hypothesis_report.json. It answers the question "are these filenames
    real?" so the model can fix hallucinated citations up-front rather than
    being blocked by save_evidence.

    Args:
        data_dir: Base data directory (same path passed to save_evidence)
        references: Flat list of filename strings from all hypotheses'
            evidence_references fields. Each entry may include a qualifier
            (e.g. "stage1_FN1--ITGB2.json (passed filter)") — only the
            leading ``*.json`` token is checked. The ``_FAILED`` suffix is
            invalid for new hypothesis reports.

    Returns:
        JSON with:
          - valid: bool (all references resolved)
          - invalid_references: list of citations that do not match any file
          - available_files: sorted list of every real file in evidence/
          - stage1_pair_files / eligible_stage1_pair_files: real Stage 1 pair
            files with ``passed=true`` in the Stage 1 filter results
          - naming_convention: human-readable note about the `--` separator
    """
    base = _resolve_data_dir(data_dir)
    evidence_dir = base / "evidence"
    real = _list_real_evidence_filenames(evidence_dir)
    filter_results, filter_err = _load_stage1_filter_results_status(evidence_dir)

    invalid: list[str] = []
    denied: list[dict] = []
    seen_tokens: list[str] = []
    for ref in references or []:
        if not isinstance(ref, str) or not ref:
            continue
        if ".json_FAILED" in ref:
            invalid.append(ref)
            denied.append({
                "reference": ref,
                "token": ref,
                "reason": (
                    "_FAILED suffixes are not valid for hypothesis_writer. "
                    "Failed Stage 1 pairs are excluded from hypothesis evidence; "
                    "remove the citation and rebuild from passed evidence."
                ),
            })
            continue
        token_match = re.search(r"([A-Za-z0-9_.\-]+\.json)", ref)
        if not token_match:
            invalid.append(ref)
            continue
        token = token_match.group(1)
        seen_tokens.append(token)
        if token in _HYPOTHESIS_DENIED_CITATIONS:
            invalid.append(ref)
            denied.append({
                "reference": ref,
                "token": token,
                "reason": (
                    "legacy aggregate or prior-run output forbidden as "
                    "hypothesis_writer input; remove the citation."
                ),
            })
            continue
        if token in _HYPOTHESIS_CONTEXT_ONLY_CITATIONS:
            invalid.append(ref)
            denied.append({
                "reference": ref,
                "token": token,
                "reason": _HYPOTHESIS_CONTEXT_ONLY_CITATION_REASON,
            })
            continue
        m = _STAGE1_PAIR_NAME_RE.match(token)
        if m:
            pair_key = f"{m.group(1).upper()}--{m.group(2).upper()}"
            if filter_results.get(pair_key) is not True:
                reason = (
                    f"no passing Stage 1 filter entry found for {pair_key}"
                    if not filter_err
                    else filter_err
                )
                invalid.append(ref)
                denied.append({
                    "reference": ref,
                    "token": token,
                    "reason": (
                        f"Stage 1 pair {pair_key} is not proven passed=true "
                        f"({reason}); exclude it from hypothesis generation."
                    ),
                })
                continue
        if token not in real:
            invalid.append(ref)

    stage1_pair_files = sorted(
        f for f in real
        if f.startswith("stage1_")
        and "--" in f
        and f.endswith(".json")
        and filter_results.get(f[len("stage1_"):-len(".json")].upper()) is True
    )
    usage_guidance = _stage1_pair_usage_guidance(evidence_dir, stage1_pair_files)

    return json.dumps({
        "valid": len(invalid) == 0,
        "checked_references_count": len(seen_tokens),
        "invalid_references": invalid,
        "denied_citations": denied,
        "available_files": sorted(real),
        "stage1_pair_files": stage1_pair_files,
        "eligible_stage1_pair_files": stage1_pair_files,
        **usage_guidance,
        "naming_convention": (
            "Stage 1 L-R pair evidence files use the convention "
            "`stage1_<LIGAND>--<RECEPTOR>.json` with TWO HYPHENS "
            "between the ligand and receptor symbols. Single-underscore "
            "variants like `stage1_CD4_ITGB2.json` are NOT written by the "
            "pipeline and will be rejected by save_evidence. Only pairs with "
            "`passed=true` in stage1_filter_results.json are eligible hypothesis "
            "citations."
        ),
    }, indent=2)


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
    hypothesis_writer. Returns a JSON object with stage1_complete flag,
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
    # check_stage1_completion gates the downstream hypothesis_writer stage.
    # Single narrowed set = stage3_candidates (rubric ∩ Stage 1 PASS).
    stage3_candidates = assessment.get("stage3_candidates", [])
    result["stage3_candidates_count"] = len(stage3_candidates)

    # 2. Zero candidates = valid state (no featured genes)
    if not stage3_candidates:
        result["stage1_complete"] = True
        result["recommendation"] = (
            "No stage3_candidates (zero featured genes). "
            "Skip hypothesis_writer, proceed to summarizer."
        )
        return json.dumps(result, indent=2)

    # 3. Check for stage1 evidence files
    stage1_files = list(evidence_dir.glob("stage1_*.json"))
    result["stage1_files_found"] = len(stage1_files)

    stage1_evidence_path = evidence_dir / "stage1_evidence.json"
    has_stage1_aggregate = stage1_evidence_path.exists()

    if stage1_files or has_stage1_aggregate:
        result["stage1_complete"] = True
        result["recommendation"] = "Stage 1 complete. Proceed to hypothesis_writer."
    else:
        result["stage1_complete"] = False
        result["recommendation"] = (
            "WARNING: Stage 1 was NOT completed. No stage1_*.json files found. "
            "evidence_assessor likely hit recursion limit before Stage 1. "
            "Proceeding to hypothesis_writer will produce incomplete results."
        )

    return json.dumps(result, indent=2)


@tool
def check_hypothesis_completion(data_dir: str) -> str:
    """Check whether hypothesis_writer produced hypothesis_report.json.

    Call this AFTER hypothesis_writer completes and BEFORE summarizer.
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
                "Do not proceed to summarizer for production output; retry hypothesis_writer "
                "or fail the hypothesis stage so Section 4 is not silently skipped."
            ),
        }, indent=2)

    try:
        hyp = json.loads(hyp_path.read_text())
        count = len(hyp.get("hypotheses", []))
        return json.dumps({
            "hypothesis_complete": True,
            "hypothesis_count": count,
            "recommendation": f"Found {count} hypotheses. Proceed to summarizer.",
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "hypothesis_complete": False,
            "recommendation": (
                f"hypothesis_report.json exists but is invalid: {e}. "
                "Retry hypothesis_writer or fail the hypothesis stage before summarizer."
            ),
        }, indent=2)
