#!/usr/bin/env python3
"""DrugTarget agent traced execution — step-by-step local tracing without LangSmith.

Uses astream(stream_mode="updates", subgraphs=True) to print each node
transition in real time, plus optional set_debug(True) and FileCallbackHandler
for full LLM/tool call logging.

Usage:
    # Mock data (e2e) with full debug
    python scripts/run_drug_target_traced.py

    # Real data
    python scripts/run_drug_target_traced.py --data-dir res_bc_ollama --disease "breast cancer"

    # Force Ollama on port 6000 for this run
    python scripts/run_drug_target_traced.py --port 6000

    # Node tracing only (no verbose LLM debug output)
    python scripts/run_drug_target_traced.py --no-debug
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Force LangSmith OFF before any LangChain import
# ---------------------------------------------------------------------------
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

# ---------------------------------------------------------------------------
# Project bootstrap
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=False)

# Re-enforce after dotenv (dotenv won't override, but be explicit)
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

# ---------------------------------------------------------------------------
# Mock data (same as run_drug_target_e2e.py)
# ---------------------------------------------------------------------------
MOCK_LR_CANDIDATES = {
    "disease": "breast cancer",
    "disease_context": "Triple-negative breast cancer",
    "pairs": [
        {"ligand": "TGFB1", "receptor": "TGFBR2", "score": 0.95},
        {"ligand": "CDH1", "receptor": "ITGB1", "score": 0.92},
        {"ligand": "SPP1", "receptor": "CD44", "score": 0.90},
        {"ligand": "VEGFA", "receptor": "FLT1", "score": 0.88},
        {"ligand": "WNT5A", "receptor": "FZD7", "score": 0.85},
        {"ligand": "CXCL12", "receptor": "CXCR4", "score": 0.83},
        {"ligand": "HGF", "receptor": "MET", "score": 0.80},
        {"ligand": "FGF2", "receptor": "FGFR1", "score": 0.78},
        {"ligand": "PDGFB", "receptor": "PDGFRB", "score": 0.76},
        {"ligand": "BMP2", "receptor": "BMPR1A", "score": 0.74},
        {"ligand": "EFNA1", "receptor": "EPHA2", "score": 0.72},
        {"ligand": "JAG1", "receptor": "NOTCH1", "score": 0.70},
        {"ligand": "DLL4", "receptor": "NOTCH3", "score": 0.68},
        {"ligand": "GDF15", "receptor": "GFRAL", "score": 0.65},
        {"ligand": "TNFSF10", "receptor": "TNFRSF10B", "score": 0.62},
    ],
}

MOCK_SELECTED_TOP3 = [
    {"ligand": "TGFB1", "receptor": "TGFBR2"},
    {"ligand": "SPP1", "receptor": "CD44"},
    {"ligand": "VEGFA", "receptor": "FLT1"},
]


def _parse_port(value: str) -> int:
    """Validate TCP port values for Ollama localhost overrides."""
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DrugTarget traced execution")
    p.add_argument(
        "--data-dir",
        default=None,
        help="Data directory with lr_candidates.json. If omitted, uses mock data in a temp dir.",
    )
    p.add_argument(
        "--disease",
        default="breast cancer",
        help="Disease context string (default: 'breast cancer').",
    )
    p.add_argument(
        "--provider",
        default="ollama",
        help="LLM provider (default: ollama).",
    )
    p.add_argument(
        "--port",
        type=_parse_port,
        default=None,
        help="Override Ollama port for this run (localhost only, ollama provider only).",
    )
    p.add_argument(
        "--no-debug",
        action="store_true",
        help="Disable set_debug(True) — only show node transitions.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in minutes (default: 120).",
    )
    p.add_argument(
        "--census",
        action="store_true",
        default=True,
        help="Enable Census API tools (query_cellxgene_lr_context, run_compare_census_lr_pair). "
             "Disabled by default due to slow API response times.",
    )
    p.add_argument(
        "--skip-evidence-assessor",
        action="store_true",
        default=False,
        help="Skip the evidence_assessor subagent (resume mode). Assumes evidence/*.json "
             "files are already on disk from a prior partial run. Orchestrator runs only "
             "hypothesis_writer, then the finalize_report node. Sets env var "
             "DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1 before agent construction.",
    )
    args = p.parse_args(argv)
    if args.port is not None and args.provider.lower() != "ollama":
        p.error("--port can only be used with --provider ollama")
    return args


def _configure_ollama_port_override(args: argparse.Namespace) -> str | None:
    """Apply an Ollama localhost port override for the current process."""
    if args.provider.lower() != "ollama" or args.port is None:
        return None

    base_url = f"http://localhost:{args.port}"
    os.environ["OLLAMA_BASE_URL"] = base_url
    os.environ["OLLAMA_HOST"] = base_url
    return base_url


def _setup_mock_data() -> Path:
    """Create a temp directory with mock input files."""
    tmpdir = tempfile.mkdtemp(prefix="drug_target_traced_")
    data_dir = Path(tmpdir)
    (data_dir / "lr_candidates.json").write_text(
        json.dumps(MOCK_LR_CANDIDATES, indent=2)
    )
    (data_dir / "selected_top3_lr.json").write_text(
        json.dumps(MOCK_SELECTED_TOP3, indent=2)
    )
    return data_dir


def _format_update_summary(update: dict) -> str:
    """Extract a short summary from a node's update dict."""
    parts = []
    for key, value in update.items():
        if key == "messages" and isinstance(value, list):
            for msg in value:
                msg_type = getattr(msg, "type", type(msg).__name__)
                content = getattr(msg, "content", "")
                # Tool calls
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    names = [tc.get("name", "?") for tc in tool_calls]
                    parts.append(f"tool_calls=[{', '.join(names)}]")
                elif isinstance(content, str) and content:
                    preview = content[:120].replace("\n", " ")
                    parts.append(f"{msg_type}: {preview}...")
                elif isinstance(content, list):
                    parts.append(f"{msg_type}: [multipart, {len(content)} blocks]")
        else:
            parts.append(f"{key}={type(value).__name__}")
    return " | ".join(parts) if parts else "(empty update)"


def _capture_drug_md_from_update(node_data: dict, holder: dict) -> None:
    """Capture drug.md content from Command(update={'files': ...}) state updates.

    The LLM sometimes uses Command(files=...) to put drug.md into LangGraph
    state instead of calling save_drug_md. This scans each streamed update
    for such content so we can write it to disk as a fallback.
    """
    # Check for 'files' key in the update (from Command(update={'files': ...}))
    files = node_data.get("files") if isinstance(node_data, dict) else None
    if isinstance(files, dict):
        for file_key, file_val in files.items():
            if "drug.md" in str(file_key):
                # file_val may be a dict with 'content' or a string
                if isinstance(file_val, dict):
                    content = file_val.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(str(c) for c in content)
                elif isinstance(file_val, str):
                    content = file_val
                else:
                    content = str(file_val)
                if len(content) > 2000:
                    holder["content"] = content

    # Also scan messages for drug.md-like content (same heuristic as e2e script)
    messages = node_data.get("messages") if isinstance(node_data, dict) else None
    if isinstance(messages, list):
        for msg in messages:
            content = getattr(msg, "content", None)
            if not isinstance(content, str):
                continue
            if (
                len(content) > 2000
                and "executive summary" in content.lower()
                and ("featured candidate" in content.lower() or "druggability" in content.lower())
            ):
                holder["content"] = content


_VALIDATE_TOOL_RE = re.compile(
    r"""(?:name=["']validate_drug_md["']|tool_calls=\[[^\]]*\bvalidate_drug_md\b[^\]]*\])"""
)
_VALIDATE_PASS_RE = re.compile(r"""["']valid["']\s*:\s*(?:true|True)""")


def _validate_report_finalization(data_dir: Path) -> dict:
    """Run the host-side finalization validator and return its parsed JSON."""
    try:
        from src.agents.drug_target.tools.stage_logic import (
            validate_drug_report_finalization,
        )

        impl = (
            getattr(validate_drug_report_finalization, "func", None)
            or validate_drug_report_finalization
        )
        raw = impl(data_dir=str(data_dir))
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        return {
            "valid": False,
            "issue_count": 1,
            "issues": [{"code": "REPORT_FINALIZATION_VALIDATOR_ERROR", "message": str(exc)}],
        }


def _json_tool_result(raw: object) -> dict:
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, dict):
        return raw
    return {"result": raw}


def _is_hypothesis_writer_stream_node(node_path: str, node_name: str) -> bool:
    path_parts = [part.strip().casefold() for part in node_path.split(">")]
    return (
        node_name.casefold() == "hypothesis_writer"
        or "hypothesis_writer" in path_parts
    )


def _hypothesis_budget_exceeded(
    started_at: float | None,
    now: float,
    budget_seconds: int,
) -> bool:
    return started_at is not None and now - started_at >= budget_seconds


def _hypothesis_stream_budget_seconds() -> int:
    raw = os.environ.get("DRUG_TARGET_HYPOTHESIS_STREAM_BUDGET_SECONDS", "120")
    try:
        return max(1, int(raw))
    except ValueError:
        return 120


def _annotation_field(source_field: object) -> str:
    field = str(source_field or "").rsplit("::", 1)[-1].rsplit(".", 1)[-1]
    return field if re.match(r"^[a-z_][a-z0-9_]*$", field, re.IGNORECASE) else "interpretation"


def _slot_meta_from_id(slot_id: str) -> dict:
    meta: dict[str, object] = {"slot_id": slot_id}
    for part in str(slot_id).split("|"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        meta[key] = value
    return meta


def _provenance_gene(entry: dict) -> str:
    source_field = str(entry.get("source_field") or "")
    if "::" in source_field:
        return source_field.split("::", 1)[0].strip().upper()
    source_file = str(entry.get("source_file") or "")
    match = re.search(r"(?:ot|stage3)_([A-Za-z0-9_-]+)\.json$", source_file)
    return match.group(1).upper() if match else ""


def _slot_provenance_score(entry: dict, slot: dict) -> int:
    source_class = str(entry.get("source_class") or "").casefold()
    source_field = str(entry.get("source_field") or "")
    field = _annotation_field(source_field).casefold()
    slot_gene = str(slot.get("gene") or "").strip().upper()
    slot_text = " ".join(
        str(slot.get(key) or "")
        for key in ("section", "slot", "instruction", "slot_id")
    ).casefold()
    score = 0
    if slot_gene and _provenance_gene(entry) == slot_gene:
        score += 100
    if "preclinical" in slot_text:
        if source_class == "chembl_preclinical" or field == "preclinical_compounds":
            score += 40
        elif field == "clinical_drugs":
            score -= 10
    elif "clinical" in slot_text or "approved" in slot_text:
        if source_class == "opentargets_clinical" or field == "clinical_drugs":
            score += 40
        elif field == "preclinical_compounds":
            score -= 10
    elif "drug_profile" in slot_text or "what drugs exist" in slot_text:
        if field in {"clinical_drugs", "preclinical_compounds"}:
            score += 25
        if source_class == "opentargets_clinical":
            score += 5
    if any(token in slot_text for token in ("rubric", "scoring", "recommendation", "biological_context", "stage1")):
        if source_class == "deepmast_rubric":
            score += 30
    if "hypothesis" in slot_text and source_class == "deepmast_rubric":
        score += 10
    return score


def _select_template_provenance(
    slot_id: str,
    slot_metadata: dict,
    provenance_entries: list[dict],
    fallback_provenance: dict,
    index: int,
) -> tuple[dict, str | None]:
    slot = slot_metadata.get(slot_id)
    if not isinstance(slot, dict):
        slot = _slot_meta_from_id(slot_id)
    if not provenance_entries:
        return dict(fallback_provenance), "provenance_index_missing"
    scored = [
        (_slot_provenance_score(entry, slot), position, entry)
        for position, entry in enumerate(provenance_entries)
    ]
    best_score, _, best_entry = max(scored, key=lambda item: (item[0], -item[1]))
    if best_score > 0:
        return dict(best_entry), None
    return (
        dict(provenance_entries[index % len(provenance_entries)]),
        "no_slot_specific_provenance_match",
    )


def _load_json_or_default(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _artifact_predates_run(path: Path, run_started_at: float) -> bool:
    try:
        return not path.exists() or path.stat().st_mtime < run_started_at
    except OSError:
        return True


def _host_hypothesis_fallback_enabled() -> bool:
    value = os.environ.get("DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK", "")
    return value.strip().casefold() in {"1", "true", "yes", "on", "smoke", "recovery"}


def _build_hypothesis_retry_message(data_dir: Path, disease: str) -> str:
    return (
        "The previous run completed Stage 1-3 evidence collection "
        "but hypothesis_report.json was NOT saved or is stale. You MUST now "
        "invoke ONLY the hypothesis_writer subagent to recover "
        "hypothesis generation. Do not re-run evidence_assessor "
        "or deep_diver. Do not re-run report_writer or summarizer. Emit exactly "
        "one tool call:\n\n"
        f"  task(subagent_type=\"hypothesis_writer\", instruction=\""
        f"Recovery run for {disease}: load_evidence_files(data_dir='{data_dir}', "
        f"scope='hypothesis'), generate 4-6 mechanistic hypotheses across MoA / "
        f"Therapeutic / Cross-Target / Novel Pathway categories, "
        f"call validate_evidence_references with every filename you "
        f"plan to cite, then immediately call "
        f"save_evidence(data_dir='{data_dir}', "
        f"filename='hypothesis_report.json', data=<the JSON "
        f"payload>). Do NOT call sequential_thinking more than 6 "
        f"times. If sequential_thinking returns an error about a "
        f"degenerate loop, STOP thinking and call save_evidence "
        f"immediately with your best draft.\")\n\n"
        "After the hypothesis_writer task returns, emit the "
        "message 'Hypothesis fixup complete.' and stop."
    )


def _build_early_retry_message(data_dir: Path, disease: str) -> str:
    return (
        "You MUST execute the full pipeline using the `task` tool. "
        "Do NOT stop until evidence_assessor, hypothesis_writer, and summarizer complete.\n"
        f"Step 1: Call load_lr_candidates(data_dir=\"{data_dir}\", disease=\"{disease}\")\n"
        f"Step 2: IMMEDIATELY call task(subagent_type=\"evidence_assessor\", "
        f"instruction=\"Run full 3-stage evidence assessment for {disease}. "
        f"Data dir: {data_dir}.\")\n"
        f"Step 3: After evidence_assessor completes, call "
        f"task(subagent_type=\"hypothesis_writer\", instruction=\"Generate "
        f"hypothesis_report.json for {disease}. Data dir: {data_dir}.\")\n"
        f"Step 4: After hypothesis_writer saves hypothesis_report.json, call "
        f"task(subagent_type=\"summarizer\", instruction=\"Generate drug.md "
        f"and final report artifacts for {disease}. Data dir: {data_dir}.\")"
    )


def _hypothesis_report_ready_for_finalization(path: Path, run_started_at: float) -> bool:
    if _artifact_predates_run(path, run_started_at):
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if payload.get("host_finalized") and payload.get("fallback_quality") == "degraded":
        return _host_hypothesis_fallback_enabled()
    return True


def _evidence_ready_for_hypothesis(data_dir: Path) -> bool:
    evidence_dir = data_dir / "evidence"
    assessment = _load_json_or_default(evidence_dir / "assessment_results.json", {})
    candidates = assessment.get("stage3_candidates", []) if isinstance(assessment, dict) else []
    genes = [
        str(row.get("gene") or row.get("gene_symbol") or "").strip().upper()
        for row in candidates
        if isinstance(row, dict) and str(row.get("gene") or row.get("gene_symbol") or "").strip()
    ]
    if not genes:
        return False
    if not (
        (evidence_dir / "stage1_filter_results.json").exists()
        or (evidence_dir / "stage1_filter_results.csv").exists()
    ):
        return False
    return all((evidence_dir / f"stage3_{gene}.json").exists() for gene in genes)


def _host_stage1_rows(evidence_dir: Path) -> list[dict]:
    rows = _load_json_or_default(evidence_dir / "stage1_filter_results.json", [])
    return rows if isinstance(rows, list) else []


def _stage1_filename(ligand: str, receptor: str) -> str:
    return f"stage1_{ligand.upper()}--{receptor.upper()}.json"


def _host_hypothesis_refs_for_gene(
    gene: str,
    evidence_dir: Path,
    passed_rows: list[dict],
) -> tuple[list[str], list[dict]]:
    gene = gene.upper()
    refs: list[str] = []
    details: list[dict] = []

    def add_ref(filename: str, usage: str) -> None:
        if filename in refs or not (evidence_dir / filename).exists():
            return
        refs.append(filename)
        stage1_status = "not_stage1"
        if filename.startswith("stage1_"):
            stage1_status = "passed"
        details.append(
            {
                "filename": filename,
                "usage": usage,
                "stage1_pair_status": stage1_status,
                "display_reference": filename,
            }
        )

    add_ref(f"stage3_{gene}.json", "primary")
    add_ref(f"ot_{gene}.json", "supporting")

    for row in passed_rows:
        ligand = str(row.get("ligand") or "").strip().upper()
        receptor = str(row.get("receptor") or "").strip().upper()
        if not ligand or not receptor or gene not in {ligand, receptor}:
            continue
        add_ref(_stage1_filename(ligand, receptor), "supporting")

    return refs, details


def _build_host_hypothesis_report(data_dir: Path, disease: str) -> dict:
    evidence_dir = data_dir / "evidence"
    assessment = _load_json_or_default(evidence_dir / "assessment_results.json", {})
    candidates = assessment.get("stage3_candidates", []) if isinstance(assessment, dict) else []
    featured_genes = [
        str(row.get("gene") or row.get("gene_symbol") or "").strip().upper()
        for row in candidates
        if isinstance(row, dict) and str(row.get("gene") or row.get("gene_symbol") or "").strip()
    ]
    rows = _host_stage1_rows(evidence_dir)
    passed_rows = [row for row in rows if isinstance(row, dict) and row.get("passed") is True]

    categories = [
        "Mechanism of Action",
        "Therapeutic Strategy",
        "Cross-Target Interaction",
        "Novel Pathway",
    ]
    hypotheses: list[dict] = []
    referenced: set[str] = set()
    for index, gene in enumerate(featured_genes, start=1):
        refs, details = _host_hypothesis_refs_for_gene(gene, evidence_dir, passed_rows)
        referenced.update(refs)
        category = categories[(index - 1) % len(categories)]
        hypotheses.append(
            {
                "rank": index,
                "title": f"[FEATURED-GAP] {gene} evidence-backed target hypothesis",
                "category": category,
                "core_claim": (
                    f"{gene} remains a testable {disease} target because the current "
                    "Stage 3 target evidence and eligible Stage 1 support converge on "
                    "a disease-relevant mechanism. Failed Stage 1 pairs are excluded "
                    "from the support set and are not used as mechanistic evidence."
                ),
                "evidence_references": refs,
                "evidence_reference_details": details,
                "contrast_references": [],
                "biological_entities": {
                    "genes": [gene],
                    "pathways": [],
                    "cell_types": [],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    f"Perturbing {gene} will produce a measurable disease-relevant "
                    "phenotype change compared with matched controls."
                ),
                "validation_approach": (
                    f"Test {gene} perturbation in disease-relevant cell models with "
                    "matched negative controls and orthogonal readouts."
                ),
                "scores": {
                    "evidence_coverage": 1.0 if refs else 0.5,
                    "specificity": 0.7,
                    "novelty": 0.6,
                    "actionability": 0.7,
                    "composite": 0.75,
                },
            }
        )

    eligible: set[str] = set()
    for gene in featured_genes:
        stage3_name = f"stage3_{gene}.json"
        if (evidence_dir / stage3_name).exists():
            eligible.add(stage3_name)
    for row in passed_rows:
        ligand = str(row.get("ligand") or "").strip().upper()
        receptor = str(row.get("receptor") or "").strip().upper()
        if not ligand or not receptor:
            continue
        filename = _stage1_filename(ligand, receptor)
        if (evidence_dir / filename).exists():
            eligible.add(filename)

    return {
        "schema_version": "hypothesis_report.v2",
        "disease": disease,
        "hypotheses_generated": len(hypotheses),
        "hypotheses_retained": len(hypotheses),
        "hypotheses": hypotheses,
        "gap_analysis": {
            "total_evidence_files": len(eligible),
            "referenced_files": len(referenced & eligible),
            "orphan_files": sorted(eligible - referenced),
        },
        "host_finalized": True,
        "fallback_quality": "degraded",
        "host_finalization_reason": "deterministic fallback after traced hypothesis phase",
    }


def _run_host_hypothesis_fallback(
    data_dir: Path,
    disease: str,
    trace_log_path: Path,
) -> dict:
    """Persist a schema-valid hypothesis_report.json without the LLM writer.

    This recovery path is intentionally conservative: it covers every current
    Stage 3 candidate, cites only existing Stage 3/OpenTargets files and Stage
    1 pair files whose filter row has passed=true, and never restores the
    legacy _FAILED suffix.
    """
    result: dict = {"saved": False, "errors": [], "path": None}

    def record(message: str) -> None:
        with open(trace_log_path, "a", encoding="utf-8") as fp:
            fp.write(f"\n[HOST-HYPOTHESIS-FIXUP] {message}\n")

    try:
        from src.agents.drug_target.tools.hypothesis_schema import (
            persist_hypothesis_report,
        )

        report = _build_host_hypothesis_report(data_dir, disease)
        if not report["hypotheses"]:
            result["errors"].append("no stage3_candidates available for host hypothesis fixup")
            record(result["errors"][-1])
            return result

        persist_result = persist_hypothesis_report(data_dir, report)
        result.update(persist_result)
        if persist_result.get("saved"):
            record(
                "save_hypothesis_report completed with "
                f"{report['hypotheses_retained']} hypotheses"
            )
        else:
            record(f"save_hypothesis_report failed: {persist_result}")
        return result
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        record(result["errors"][-1])
        return result


def _build_template_expansions(spec_path: Path) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    fallback_provenance = dict(spec["example_sentence"]["source_provenance"])
    reference_card = _load_json_or_default(spec_path.with_name("drug_report_reference_card.json"), {})
    provenance_index = (
        reference_card.get("provenance_index", {})
        if isinstance(reference_card, dict)
        else {}
    )
    slot_metadata = {
        str(slot.get("slot_id")): slot
        for slot in (
            reference_card.get("expansion_slots", [])
            if isinstance(reference_card, dict)
            else []
        )
        if isinstance(slot, dict) and slot.get("slot_id")
    }
    provenance_entries = [
        dict(entry)
        for _, entry in sorted(provenance_index.items())
        if isinstance(entry, dict)
    ]
    required_slots = list(spec["required_slot_ids"])

    def sentence_for_slot(slot_id: str, index: int) -> dict:
        provenance, degraded_reason = _select_template_provenance(
            slot_id,
            slot_metadata,
            provenance_entries,
            fallback_provenance,
            index,
        )
        source_field = str(provenance.get("source_field") or "interpretation")
        field = _annotation_field(source_field)
        source_class = str(provenance.get("source_class") or "interpretation")
        provenance.setdefault("claim_type", "direct_value")
        if "source_value" not in provenance:
            provenance["source_value"] = None
        sentence = {
            "text": (
                "This section is limited to evidence fields captured by the run "
                f"for {slot_id}. [source: {source_class}:{field}]"
            ),
            "source_fields": [source_field, field] if source_field != field else [field],
            "source_provenance": provenance,
            "interpretation": False,
            "hedging_verbs_present": False,
        }
        if degraded_reason:
            sentence["fallback_quality"] = "degraded"
            sentence["fallback_reason"] = degraded_reason
        return sentence

    return {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": slot_id,
                "sentences": [sentence_for_slot(slot_id, index)],
            }
            for index, slot_id in enumerate(required_slots)
        ],
    }


def _inspect_report_outputs(data_dir: Path, trace_log_path: Path) -> dict:
    """Inspect whether the traced run produced a fully finalized report."""
    evidence_dir = data_dir / "evidence"
    drug_md_path = data_dir / "drug.md"
    drug_html_path = data_dir / "drug_report.html"
    drug_md_content = (
        drug_md_path.read_text(encoding="utf-8") if drug_md_path.exists() else ""
    )
    expand_marker_count = drug_md_content.count("EXPAND")
    finalization_result = _validate_report_finalization(data_dir)
    report_finalization_valid = bool(finalization_result.get("valid"))
    validate_check = finalization_result.get("checks", {}).get("validate_drug_md", {})
    validate_passed = (
        validate_check.get("status") == "pass"
        if validate_check
        else report_finalization_valid
    )

    status = {
        "evidence_count": len(list(evidence_dir.glob("*.json"))) if evidence_dir.exists() else 0,
        "assessment_exists": (evidence_dir / "assessment_results.json").exists()
        if evidence_dir.exists()
        else False,
        "target_assessment_exists": (data_dir / "target_assessment.json").exists(),
        "drug_md_exists": drug_md_path.exists(),
        "drug_html_exists": drug_html_path.exists(),
        "expand_marker_count": expand_marker_count,
        "validate_drug_md_passed": validate_passed,
        "report_finalization_valid": report_finalization_valid,
        "report_finalization_issue_count": finalization_result.get("issue_count"),
        "report_finalization_issues": finalization_result.get("issues", []),
        "missing_requirements": [],
    }

    if status["evidence_count"] <= 0:
        status["missing_requirements"].append("evidence files present")
    if not status["assessment_exists"]:
        status["missing_requirements"].append("assessment_results.json present")
    if not status["target_assessment_exists"]:
        status["missing_requirements"].append("target_assessment.json present")
    if not status["drug_md_exists"]:
        status["missing_requirements"].append("drug.md present")
    if not status["drug_html_exists"]:
        status["missing_requirements"].append("drug_report.html present")
    if expand_marker_count:
        status["missing_requirements"].append("no EXPAND markers")
    if not report_finalization_valid:
        status["missing_requirements"].append("validate_drug_report_finalization valid=true")

    status["finalized"] = not status["missing_requirements"]
    return status


async def run_traced(args: argparse.Namespace) -> int:
    """Run the DrugTarget agent with step-by-step tracing."""

    ollama_base_url = _configure_ollama_port_override(args)

    # ── Debug mode ────────────────────────────────────────────────────
    if not args.no_debug:
        from langchain_core.globals import set_debug
        set_debug(True)
        print("[CONFIG] LangChain debug mode: ON")
    else:
        print("[CONFIG] LangChain debug mode: OFF (node tracing only)")

    # ── Data directory ────────────────────────────────────────────────
    if args.data_dir:
        data_dir = Path(args.data_dir)
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
        data_dir = data_dir.resolve()
        if not (data_dir / "lr_candidates.json").exists():
            print(f"ERROR: lr_candidates.json not found in {data_dir}")
            return 1
        print(f"[CONFIG] Data dir: {data_dir} (user-provided)")
    else:
        data_dir = _setup_mock_data()
        print(f"[CONFIG] Data dir: {data_dir} (mock data)")

    os.environ["DRUG_TARGET_DATA_DIR"] = str(data_dir)

    # ── Trace log file ────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_log_path = data_dir / f"trace_{timestamp}.log"

    from langchain_core.callbacks import FileCallbackHandler
    file_handler = FileCallbackHandler(str(trace_log_path))
    trace_log_fp = open(trace_log_path, "a")  # append structured markers alongside FileCallbackHandler
    print(f"[CONFIG] Trace log: {trace_log_path}")

    # ── Token usage tracker ──────────────────────────────────────────
    from scripts.token_tracker import TokenUsageTracker
    token_tracker = TokenUsageTracker()
    token_usage_path = data_dir / f"token_usage_{timestamp}.json"

    # ── Resume mode env-var (must be set BEFORE agent construction) ──
    if args.skip_evidence_assessor:
        os.environ["DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR"] = "1"
        print("[CONFIG] RESUME mode — evidence_assessor will be skipped "
              "(env DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1)")

    # ── Create agent ──────────────────────────────────────────────────
    from src.agents.drug_target.agent import (
        DrugTargetConfig,
        create_drug_target_agent,
    )

    config = DrugTargetConfig(
        provider=args.provider,
        data_dir=str(data_dir),
        disease=args.disease,
        use_checkpointer=True,
        enable_census=args.census,
    )
    agent, backend = create_drug_target_agent(config)
    print(f"[CONFIG] Agent created (provider={args.provider})")
    print(f"[CONFIG] Disease: {args.disease}")
    if ollama_base_url:
        print(f"[CONFIG] Ollama base URL: {ollama_base_url}")
    print(f"[CONFIG] Census API: {'ENABLED' if args.census else 'DISABLED'}")

    # ── Stream with tracing ───────────────────────────────────────────
    initial_message = (
        f"Run the full drug target assessment pipeline for {args.disease}."
    )
    thread_id = str(uuid.uuid4())

    print(f"\n{'=' * 70}")
    print(f"STREAMING — thread_id={thread_id}")
    print(f"{'=' * 70}\n")

    start = time.time()
    node_counter = 0
    timeout_seconds = args.timeout * 60
    hypothesis_budget_seconds = _hypothesis_stream_budget_seconds()
    hypothesis_started_at: float | None = None
    evidence_ready_started_at: float | None = None
    hypothesis_budget_aborted = False
    captured_drug_md_holder = {"content": None}  # Fallback: capture drug.md from Command(files=...)
    # Capture finalize_report state fields from stream updates
    captured_finalization_state: dict = {"report_finalization_error": None, "evidence_truncated": False}
    # Record whether drug.md existed before this run (for idempotency SOP message)
    pre_run_drug_md_exists = (data_dir / "drug.md").exists()

    try:
        async for chunk in agent.astream(
            {"messages": [{"role": "user", "content": initial_message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "callbacks": [file_handler, token_tracker],
            },
            stream_mode="updates",
            subgraphs=True,
        ):
            elapsed = time.time() - start
            if elapsed > timeout_seconds:
                print(f"\n[TIMEOUT] {args.timeout}m limit reached")
                break

            namespace, update = chunk
            node_path = " > ".join(namespace) if namespace else "orchestrator"
            abort_for_hypothesis_budget = False

            for node_name, node_data in update.items():
                now = time.time()
                hypothesis_path = data_dir / "evidence" / "hypothesis_report.json"
                if (
                    evidence_ready_started_at is None
                    and _evidence_ready_for_hypothesis(data_dir)
                    and _artifact_predates_run(hypothesis_path, start)
                ):
                    evidence_ready_started_at = now
                if (
                    _hypothesis_budget_exceeded(
                        evidence_ready_started_at,
                        now,
                        hypothesis_budget_seconds,
                    )
                    and _artifact_predates_run(hypothesis_path, start)
                ):
                    message = (
                        "[HYPOTHESIS-BUDGET] evidence has been ready for "
                        f"{hypothesis_budget_seconds}s but no fresh "
                        "hypothesis_report.json was saved; switching to "
                        "hypothesis_writer retry before any host fallback."
                    )
                    print(f"\n{message}")
                    trace_log_fp.write(f"\n{message}\n")
                    trace_log_fp.flush()
                    hypothesis_budget_aborted = True
                    abort_for_hypothesis_budget = True
                    break

                if (
                    hypothesis_started_at is None
                    and _is_hypothesis_writer_stream_node(node_path, node_name)
                ):
                    hypothesis_started_at = now
                if (
                    _hypothesis_budget_exceeded(
                        hypothesis_started_at,
                        now,
                        hypothesis_budget_seconds,
                    )
                    and (data_dir / "evidence" / "assessment_results.json").exists()
                    and (data_dir / "evidence" / "stage1_filter_results.json").exists()
                ):
                    message = (
                        "[HYPOTHESIS-BUDGET] hypothesis_writer stream exceeded "
                        f"{hypothesis_budget_seconds}s after deterministic evidence "
                        "artifacts were written; retrying hypothesis_writer before "
                        "any host fallback."
                    )
                    print(f"\n{message}")
                    trace_log_fp.write(f"\n{message}\n")
                    trace_log_fp.flush()
                    hypothesis_budget_aborted = True
                    abort_for_hypothesis_budget = True
                    break

                node_counter += 1
                print(
                    f"\n[{elapsed:7.1f}s] #{node_counter} [{node_path}] "
                    f"Node: {node_name}"
                )
                print(f"  {_format_update_summary({node_name: node_data})}")
                print(f"  {'─' * 60}")

                # Write structured node transition to trace log
                trace_log_fp.write(f"\n{'═' * 62}\n")
                trace_log_fp.write(
                    f"[{elapsed:7.1f}s] #{node_counter} [{node_path}] "
                    f"Node: {node_name}\n"
                )
                trace_log_fp.write(f"  {_format_update_summary({node_name: node_data})}\n")
                trace_log_fp.write(f"{'─' * 62}\n")
                trace_log_fp.flush()

                # Capture drug.md content from Command(files=...) state updates
                _capture_drug_md_from_update(node_data, captured_drug_md_holder)
                # Capture finalize_report state fields when the node emits them
                if isinstance(node_data, dict):
                    if "report_finalization_error" in node_data:
                        captured_finalization_state["report_finalization_error"] = (
                            node_data["report_finalization_error"]
                        )
                    if "evidence_truncated" in node_data:
                        captured_finalization_state["evidence_truncated"] = bool(
                            node_data["evidence_truncated"]
                        )
            if abort_for_hypothesis_budget:
                break

    except asyncio.CancelledError:
        elapsed = time.time() - start
        print(
            f"\n[CANCELLED at {elapsed:.1f}s] Graph task cancelled — "
            f"downstream fixup/fallback will decide whether outputs are complete."
        )
        trace_log_fp.write(
            f"\n[CANCELLED] at {elapsed:.1f}s — graceful shutdown, not re-raised\n"
        )
        trace_log_fp.flush()
        # Do NOT re-raise; let the STAGE1-FIXUP / fallback tail run.
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n[ERROR at {elapsed:.1f}s] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        trace_log_fp.close()
        if backend and hasattr(backend, "cleanup"):
            backend.cleanup()

    elapsed = time.time() - start

    # ── Stage 1 fixup: auto-run if evidence_assessor skipped it ────
    evidence_dir = data_dir / "evidence"
    assessment_path = evidence_dir / "assessment_results.json"
    stage1_pair_files = list(evidence_dir.glob("stage1_*--*.json")) if evidence_dir.exists() else []
    if assessment_path.exists() and len(stage1_pair_files) == 0:
        print(f"\n[STAGE1-FIXUP] assessment_results.json exists but no stage1 pair files.")
        print(f"[STAGE1-FIXUP] Running run_stage1_batch programmatically...")
        try:
            from src.agents.drug_target.tools.stage_domain_tools import run_stage1_batch
            stage1_result_raw = run_stage1_batch.invoke({
                "data_dir": str(data_dir),
                "disease": args.disease,
                "target_cell_type": "",
                "enable_census": args.census,
            })
            stage1_result = json.loads(stage1_result_raw) if isinstance(stage1_result_raw, str) else stage1_result_raw
            pairs_done = stage1_result.get("pairs_processed", 0)
            stage1_errors = stage1_result.get("errors", [])
            print(f"[STAGE1-FIXUP] Completed: {pairs_done} pairs saved")
            if stage1_errors:
                print(f"[STAGE1-FIXUP] Errors: {stage1_errors}")
            with open(trace_log_path, "a") as fp:
                fp.write(f"\n[STAGE1-FIXUP] run_stage1_batch: {pairs_done} pairs, errors={stage1_errors}\n")
        except Exception as exc:
            print(f"[STAGE1-FIXUP] Failed: {exc}")
            import traceback
            traceback.print_exc()

    # ── Hypothesis writer fixup: auto-retry if hypothesis_report.json missing
    # or stale after evidence assessment. This must run before host fallback so
    # deterministic degraded output cannot mask a missing writer artifact.
    hypothesis_path = evidence_dir / "hypothesis_report.json"
    hypothesis_stale = False
    if hypothesis_path.exists():
        try:
            hypothesis_stale = hypothesis_path.stat().st_mtime < start
        except OSError:
            hypothesis_stale = False
    if assessment_path.exists() and (
        hypothesis_budget_aborted or not hypothesis_path.exists() or hypothesis_stale
    ):
        try:
            assessment = json.loads(assessment_path.read_text())
            stage3_candidates = assessment.get("stage3_candidates", [])
        except Exception:
            stage3_candidates = []
        if stage3_candidates:
            print(
                f"\n[HYPOTHESIS-FIXUP] assessment_results.json has "
                f"{len(stage3_candidates)} stage3_candidates but "
                f"hypothesis_report.json is missing. Re-running "
                f"hypothesis_writer via a narrow task instruction."
            )
            with open(trace_log_path, "a") as fp:
                fp.write(
                    f"\n[HYPOTHESIS-FIXUP] {len(stage3_candidates)} candidates, "
                    f"hypothesis_report.json missing/stale — retrying narrowly\n"
                )

            hyp_retry_message = _build_hypothesis_retry_message(data_dir, args.disease)
            hyp_retry_thread_id = str(uuid.uuid4())
            hyp_retry_start = time.time()
            trace_log_fp = open(trace_log_path, "a")

            try:
                async for chunk in agent.astream(
                    {"messages": [{"role": "user", "content": hyp_retry_message}]},
                    config={
                        "configurable": {"thread_id": hyp_retry_thread_id},
                        "callbacks": [file_handler, token_tracker],
                    },
                    stream_mode="updates",
                    subgraphs=True,
                ):
                    elapsed = time.time() - start
                    if elapsed > timeout_seconds:
                        print(f"\n[HYPOTHESIS-FIXUP TIMEOUT] {args.timeout}m limit reached")
                        break
                    # Abandon the fixup if it itself burns > 10 minutes —
                    # we fall through to the remaining recovery branches.
                    if time.time() - hyp_retry_start > 600:
                        print("\n[HYPOTHESIS-FIXUP ABORT] > 600s budget exceeded")
                        trace_log_fp.write(
                            "\n[HYPOTHESIS-FIXUP ABORT] > 600s budget exceeded\n"
                        )
                        break

                    namespace, update = chunk
                    node_path = " > ".join(namespace) if namespace else "orchestrator"
                    for node_name, node_data in update.items():
                        node_counter += 1
                        print(
                            f"\n[{elapsed:7.1f}s] #{node_counter} "
                            f"[{node_path}] Node: {node_name}"
                        )
                        print(f"  {_format_update_summary({node_name: node_data})}")
                        print(f"  {'─' * 60}")
                        trace_log_fp.write(f"\n{'═' * 62}\n")
                        trace_log_fp.write(
                            f"[{elapsed:7.1f}s] #{node_counter} "
                            f"[{node_path}] Node: {node_name}\n"
                        )
                        trace_log_fp.write(
                            f"  {_format_update_summary({node_name: node_data})}\n"
                        )
                        trace_log_fp.write(f"{'─' * 62}\n")
                        trace_log_fp.flush()
                        _capture_drug_md_from_update(node_data, captured_drug_md_holder)
            except asyncio.CancelledError:
                print("\n[HYPOTHESIS-FIXUP CANCELLED]")
            except Exception as exc:
                print(f"\n[HYPOTHESIS-FIXUP ERROR] {type(exc).__name__}: {exc}")
                import traceback
                traceback.print_exc()
            finally:
                trace_log_fp.close()

            if hypothesis_path.exists():
                print("[HYPOTHESIS-FIXUP] SUCCESS — hypothesis_report.json now present")
            else:
                print("[HYPOTHESIS-FIXUP] FAILED — hypothesis_report.json still missing")

    # ── Host hypothesis fixup: deterministic degraded recovery. This is
    # disabled for normal production runs unless explicitly enabled for smoke
    # or recovery runs via DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK.
    hypothesis_stale = False
    if hypothesis_path.exists():
        try:
            hypothesis_stale = hypothesis_path.stat().st_mtime < start
        except OSError:
            hypothesis_stale = False
    if assessment_path.exists() and (
        hypothesis_budget_aborted or not hypothesis_path.exists() or hypothesis_stale
    ):
        reasons = []
        if hypothesis_budget_aborted:
            reasons.append("hypothesis_writer budget exceeded")
        if not hypothesis_path.exists():
            reasons.append("hypothesis_report.json missing")
        if hypothesis_stale:
            reasons.append("hypothesis_report.json predates this run")
        if not _host_hypothesis_fallback_enabled():
            print(
                "\n[HOST-HYPOTHESIS-FIXUP] SKIPPED — "
                + "; ".join(reasons)
                + "; set DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK=1 "
                "only for smoke/recovery runs."
            )
            with open(trace_log_path, "a") as fp:
                fp.write(
                    "\n[HOST-HYPOTHESIS-FIXUP] skipped because fallback is disabled; "
                    + "; ".join(reasons)
                    + "\n"
                )
        else:
            print(
                "\n[HOST-HYPOTHESIS-FIXUP] "
                + "; ".join(reasons)
                + "; writing degraded deterministic hypothesis_report.json."
            )
            fixup_result = _run_host_hypothesis_fallback(
                data_dir,
                args.disease,
                trace_log_path,
            )
            if fixup_result.get("saved"):
                print("[HOST-HYPOTHESIS-FIXUP] SUCCESS — degraded hypothesis_report.json saved")
            else:
                print(
                    "[HOST-HYPOTHESIS-FIXUP] FAILED — "
                    + "; ".join(fixup_result.get("errors", [])[:5])
                )

    # ── Retry on early termination ───────────────────────────────
    evidence_count = len(list(evidence_dir.glob("*.json"))) if evidence_dir.exists() else 0
    if evidence_count == 0 and elapsed < 300:
        print(f"\n[RETRY] Agent terminated early ({elapsed:.0f}s, 0 evidence files). "
              f"Retrying with explicit task-tool instructions...")
        with open(trace_log_path, "a") as fp:
            fp.write(f"\n[RETRY] Early termination detected at {elapsed:.1f}s — retrying\n")

        retry_message = _build_early_retry_message(data_dir, args.disease)
        retry_thread_id = str(uuid.uuid4())
        retry_start = time.time()
        trace_log_fp = open(trace_log_path, "a")

        try:
            async for chunk in agent.astream(
                {"messages": [{"role": "user", "content": retry_message}]},
                config={
                    "configurable": {"thread_id": retry_thread_id},
                    "callbacks": [file_handler, token_tracker],
                },
                stream_mode="updates",
                subgraphs=True,
            ):
                elapsed = time.time() - start
                if elapsed > timeout_seconds:
                    print(f"\n[TIMEOUT] {args.timeout}m limit reached during retry")
                    break

                namespace, update = chunk
                node_path = " > ".join(namespace) if namespace else "orchestrator"

                for node_name, node_data in update.items():
                    node_counter += 1
                    print(
                        f"\n[{elapsed:7.1f}s] #{node_counter} [{node_path}] "
                        f"Node: {node_name}"
                    )
                    print(f"  {_format_update_summary({node_name: node_data})}")
                    print(f"  {'─' * 60}")

                    trace_log_fp.write(f"\n{'═' * 62}\n")
                    trace_log_fp.write(
                        f"[{elapsed:7.1f}s] #{node_counter} [{node_path}] "
                        f"Node: {node_name}\n"
                    )
                    trace_log_fp.write(f"  {_format_update_summary({node_name: node_data})}\n")
                    trace_log_fp.write(f"{'─' * 62}\n")
                    trace_log_fp.flush()

                    _capture_drug_md_from_update(node_data, captured_drug_md_holder)

        except asyncio.CancelledError:
            elapsed = time.time() - start
            print(
                f"\n[RETRY CANCELLED at {elapsed:.1f}s] Retry graph task cancelled — "
                f"falling through to downstream completion checks."
            )
            trace_log_fp.write(
                f"\n[RETRY CANCELLED] at {elapsed:.1f}s — graceful shutdown, not re-raised\n"
            )
            trace_log_fp.flush()
        except Exception as e:
            elapsed = time.time() - start
            print(f"\n[RETRY ERROR at {elapsed:.1f}s] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            trace_log_fp.close()

        elapsed = time.time() - start
        print(f"\n[RETRY] Completed in {time.time() - retry_start:.1f}s")

    # ── Fallback: write drug.md from captured stream state ────────
    drug_md_path = data_dir / "drug.md"
    if not drug_md_path.exists() and captured_drug_md_holder["content"]:
        content = captured_drug_md_holder["content"]
        drug_md_path.write_text(content)
        print(f"  [FALLBACK] Extracted drug.md from stream state ({len(content):,} chars)")
        with open(trace_log_path, "a") as fp:
            fp.write(f"\n[FALLBACK] drug.md extracted from Command(files=...) state update\n")

    # ── finalize_report node — the new super-graph node that follows the
    # inner DeepAgents runnable in the production super-graph. The trace
    # script invokes agent.astream() directly on the inner agent (bypassing
    # the super-graph for streaming visibility), so we must invoke
    # finalize_report manually here to reach the post-agent stage.
    if not drug_md_path.exists():
        print("\n[FINALIZE_REPORT] Invoking super-graph finalize_report node...")
        finalize_start = time.time()
        try:
            from src.agents.drug_target.finalize_report import finalize_report
            finalize_state = {
                "data_dir": str(data_dir),
                "disease": args.disease,
            }
            finalize_result = await finalize_report(finalize_state, {"recursion_limit": 100})
            finalize_elapsed = time.time() - finalize_start
            finalize_err = finalize_result.get("report_finalization_error")
            evidence_trunc_now = finalize_result.get("evidence_truncated", False)
            captured_finalization_state["report_finalization_error"] = finalize_err
            captured_finalization_state["evidence_truncated"] = evidence_trunc_now
            status = "OK" if finalize_err is None else f"ERROR: {finalize_err[:120]}"
            print(f"  [FINALIZE_REPORT] {finalize_elapsed:.1f}s — {status}")
            with open(trace_log_path, "a") as fp:
                fp.write(
                    f"\n[FINALIZE_REPORT] {finalize_elapsed:.1f}s — {status}\n"
                )
        except Exception as exc:  # noqa: BLE001 — fail-closed surfaces in summary
            finalize_elapsed = time.time() - finalize_start
            captured_finalization_state["report_finalization_error"] = (
                f"finalize_report_exception: {type(exc).__name__}: {exc}"
            )
            print(f"  [FINALIZE_REPORT] {finalize_elapsed:.1f}s — EXCEPTION: {exc}")
            with open(trace_log_path, "a") as fp:
                fp.write(
                    f"\n[FINALIZE_REPORT] EXCEPTION ({type(exc).__name__}): {exc}\n"
                )

    elapsed = time.time() - start

    # ── Output summary ────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"TRACE COMPLETE — {elapsed:.1f}s ({node_counter} node transitions)")
    print(f"{'=' * 70}\n")

    report_status = _inspect_report_outputs(data_dir, trace_log_path)
    evidence_count = report_status["evidence_count"]

    finalization_error = captured_finalization_state["report_finalization_error"]
    evidence_truncated = captured_finalization_state["evidence_truncated"]

    print(f"  Evidence files:      {evidence_count}")
    print(f"  assessment_results:  {'YES' if report_status['assessment_exists'] else 'NO'}")
    print(
        f"  target_assessment:   "
        f"{'YES' if report_status['target_assessment_exists'] else 'NO'}"
    )
    print(f"  drug.md:             {'YES' if report_status['drug_md_exists'] else 'NO'}")
    print(
        f"  drug_report.html:    "
        f"{'YES' if report_status['drug_html_exists'] else 'NO'}"
    )
    print(f"  EXPAND markers:      {report_status['expand_marker_count']}")
    print(
        f"  validate_drug_md:    "
        f"{'PASS' if report_status['validate_drug_md_passed'] else 'NO PASS'}"
    )
    print(
        f"  host_finalization:   "
        f"{'PASS' if report_status['report_finalization_valid'] else 'NO PASS'}"
    )
    print(f"  REPORT_FINALIZATION_ERROR: {finalization_error if finalization_error else '—'}")
    print(f"  EVIDENCE_TRUNCATED:  {evidence_truncated}")
    print(f"  report_finalized:    {'YES' if report_status['finalized'] else 'NO'}")
    if report_status["missing_requirements"]:
        print(
            "  missing_finalization: "
            + "; ".join(report_status["missing_requirements"])
        )
    print(f"  Trace log:           {trace_log_path}")
    print(f"  Workspace:           {data_dir}")
    print(f"  Runtime:             {elapsed:.1f}s")

    # Write summary to trace log
    with open(trace_log_path, "a") as fp:
        fp.write(f"\n{'=' * 62}\n")
        fp.write(f"TRACE COMPLETE — {elapsed:.1f}s ({node_counter} node transitions)\n")
        fp.write(f"{'=' * 62}\n")
        fp.write(f"  Evidence files:      {evidence_count}\n")
        fp.write(
            f"  assessment_results:  "
            f"{'YES' if report_status['assessment_exists'] else 'NO'}\n"
        )
        fp.write(
            f"  target_assessment:   "
            f"{'YES' if report_status['target_assessment_exists'] else 'NO'}\n"
        )
        fp.write(f"  drug.md:             {'YES' if report_status['drug_md_exists'] else 'NO'}\n")
        fp.write(
            f"  drug_report.html:    "
            f"{'YES' if report_status['drug_html_exists'] else 'NO'}\n"
        )
        fp.write(f"  EXPAND markers:      {report_status['expand_marker_count']}\n")
        fp.write(
            f"  validate_drug_md:    "
            f"{'PASS' if report_status['validate_drug_md_passed'] else 'NO PASS'}\n"
        )
        fp.write(
            f"  host_finalization:   "
            f"{'PASS' if report_status['report_finalization_valid'] else 'NO PASS'}\n"
        )
        fp.write(
            f"  REPORT_FINALIZATION_ERROR: "
            f"{finalization_error if finalization_error else '—'}\n"
        )
        fp.write(f"  EVIDENCE_TRUNCATED:  {evidence_truncated}\n")
        fp.write(f"  report_finalized:    {'YES' if report_status['finalized'] else 'NO'}\n")
        if report_status["missing_requirements"]:
            fp.write(
                "  missing_finalization: "
                + "; ".join(report_status["missing_requirements"])
                + "\n"
            )
        fp.write(f"  Runtime:             {elapsed:.1f}s\n")

    if report_status["drug_md_exists"]:
        content = (data_dir / "drug.md").read_text()
        print(f"\n  drug.md: {len(content):,} chars")

    # ── Idempotency SOP: hint when finalize_report was skipped ───────────
    if report_status["finalized"] and pre_run_drug_md_exists:
        print(
            "\nNOTE: finalize_report may have been skipped because drug.md already"
            " existed in the data_dir before this run.",
            file=sys.stderr,
        )
        print(
            "To force re-run, delete the four artifacts first:\n"
            f"  rm -f {data_dir}/drug.md {data_dir}/drug_report.html"
            f" {data_dir}/target_assessment.json {data_dir}/report_expansions.json",
            file=sys.stderr,
        )

    # ── Token usage report ────────────────────────────────────────────
    token_tracker.print_summary()
    token_tracker.save_report(token_usage_path)
    print(f"  Token usage report: {token_usage_path}")

    # ── CI smoke fail on evidence truncation (Decision 10 / CP-P0-011) ──
    if evidence_truncated:
        print(
            "\n[CI FAIL] evidence_truncated=True — finalize_report aborted due to"
            " evidence budget exceeded. Delete stale artifacts and re-run after"
            " evidence cap is resolved.",
            file=sys.stderr,
        )
        return 2

    success = report_status["finalized"]
    print(f"\n  {'SUCCESS' if success else 'PARTIAL'}")
    return 0 if success else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    args = parse_args()
    sys.exit(asyncio.run(run_traced(args)))
