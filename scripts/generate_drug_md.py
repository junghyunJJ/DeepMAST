#!/usr/bin/env python3
"""Generate drug.md from target_assessment.json + evidence files using LLM.

This script reads the already-generated target_assessment.json and evidence
files, then uses an LLM to produce the final drug.md report.
"""

import asyncio
import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.agents.model import create_llm
from src.agents.drug_target.tools.stage1_normalization import (
    load_stage1_json,
    resolve_stage1_context,
)

PROVIDER = "openrouter"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "data_dir",
        nargs="?",
        default="res_bc_ollama",
        help="Data directory that contains target_assessment.json and evidence/",
    )
    return parser.parse_args()


DATA_DIR = PROJECT_ROOT / "res_bc_ollama"

def load_all_evidence() -> dict:
    """Load target_assessment.json and key evidence files."""
    evidence_dir = DATA_DIR / "evidence"

    data = {}

    # Main assessment
    ta_path = DATA_DIR / "target_assessment.json"
    if ta_path.exists():
        data["target_assessment"] = json.loads(ta_path.read_text())
    data["resolved_context"] = resolve_stage1_context(
        DATA_DIR,
        allow_existing_evidence_fallback=True,
    )

    # Key evidence files
    for fname in [
        "rubric_scores.json",
        "stage1_evidence.json",
        "stage2_evidence.json",
        "assessment_results.json",
        "gene_drug_scores.json",
        "known_drugs.json",
        "gene_manifest.json",
        "stage1_confidence.json",
    ]:
        fpath = evidence_dir / fname
        if fpath.exists():
            data[fname.replace(".json", "")] = json.loads(fpath.read_text())

    # Load a few featured candidate stage1 files for deep dive detail
    ta = data.get("target_assessment", {})
    featured = [
        dd["gene_symbol"]
        for dd in ta.get("featured_candidates_deep_dive", [])
    ]
    stage1_details = {}
    for f in evidence_dir.glob("stage1_*.json"):
        if f.name in ("stage1_evidence.json", "stage1_confidence.json",
                       "stage1_cellxgene_all_pairs.json", "stage1_audit.json"):
            continue
        detail, repairs = load_stage1_json(f)
        if repairs:
            detail["file_repairs"] = repairs
        stage1_details[f.stem] = detail
    data["stage1_details"] = stage1_details

    # OpenTargets per-gene
    ot_details = {}
    for f in evidence_dir.glob("ot_*.json"):
        ot_details[f.stem] = json.loads(f.read_text())
    data["opentargets_details"] = ot_details
    data["resolved_disease"] = data["resolved_context"]["disease"]

    return data


def _build_stage1_table(evidence: dict) -> str:
    """Build a pre-computed Stage 1 markdown table from individual stage1 data."""
    confidence = evidence.get("stage1_confidence", {})
    details = evidence.get("stage1_details", {})

    def _extract_ids_and_names(entries: list, id_key: str) -> tuple[set[str], dict[str, str]]:
        ids: set[str] = set()
        names: dict[str, str] = {}
        for entry in entries:
            if isinstance(entry, dict):
                entry_id = entry.get(id_key)
                entry_name = entry.get("name", entry_id)
                if entry_id:
                    ids.add(str(entry_id))
                    if entry_name:
                        names[str(entry_id)] = str(entry_name)
            elif isinstance(entry, str):
                names[entry] = entry
        return ids, names

    rows = []
    for pair_key, conf in confidence.items():
        if not pair_key or "^" not in pair_key:
            continue
        # Find matching detail file
        ligand, receptor = pair_key.split("^", 1)
        detail_key = f"stage1_{ligand}--{receptor}"
        detail = details.get(detail_key, {})

        # STRING PPI
        string_ppi = conf.get("string_score", 0)

        # Shared pathways (KEGG + Reactome)
        kegg = detail.get("kegg_pathways", {})
        kegg_lig, kegg_lig_names = _extract_ids_and_names(
            kegg.get("ligand_pathways", []),
            "pathway_id",
        )
        kegg_rec, kegg_rec_names = _extract_ids_and_names(
            kegg.get("receptor_pathways", []),
            "pathway_id",
        )
        shared_kegg = kegg_lig & kegg_rec
        shared_kegg_names = {
            name
            for name in kegg_lig_names.values()
            if name in kegg_rec_names.values()
        }

        reactome = detail.get("reactome_pathways", {})
        react_lig, react_lig_names = _extract_ids_and_names(
            reactome.get("ligand_pathways", []),
            "reactome_id",
        )
        react_rec, react_rec_names = _extract_ids_and_names(
            reactome.get("receptor_pathways", []),
            "reactome_id",
        )
        shared_reactome = react_lig & react_rec
        shared_reactome_names = {
            name
            for name in react_lig_names.values()
            if name in react_rec_names.values()
        }

        shared_names = []
        if shared_kegg:
            name_map = {}
            for p in kegg.get("ligand_pathways", []) + kegg.get("receptor_pathways", []):
                if not isinstance(p, dict):
                    continue
                pid = p.get("pathway_id", "")
                name = p.get("name", pid)
                name = name.split(" - Homo sapiens")[0] if " - Homo sapiens" in name else name
                name_map[pid] = name
            shared_names.extend(name_map[pid] for pid in shared_kegg if pid in name_map)
        if shared_kegg_names:
            shared_names.extend(
                name.split(" - Homo sapiens")[0] if " - Homo sapiens" in name else name
                for name in sorted(shared_kegg_names)
            )
        if shared_reactome:
            name_map = {}
            for p in reactome.get("ligand_pathways", []) + reactome.get("receptor_pathways", []):
                if not isinstance(p, dict):
                    continue
                pid = p.get("reactome_id", "")
                name = p.get("name", pid)
                name_map[pid] = name
            shared_names.extend(name_map[pid] for pid in shared_reactome if pid in name_map)
        if shared_reactome_names:
            shared_names.extend(sorted(shared_reactome_names))

        pathway_str = ", ".join(dict.fromkeys(shared_names)) if shared_names else "—"

        # Census coexpression
        census = detail.get("census_validation", {})
        tvr = census.get("target_vs_rest", {})
        coexpr = tvr.get("coexpression", {})
        p_val = coexpr.get("p_value")
        rr = coexpr.get("risk_ratio")

        if p_val is not None:
            if p_val < 1e-99:
                p_str = "<1e-99"
            elif p_val < 1e-10:
                p_str = f"<1e-{int(-1 * __import__('math').log10(p_val))}"
            else:
                p_str = f"{p_val:.2e}"
        else:
            p_str = "—"
        rr_str = f"{rr:.2f}" if rr is not None else "—"

        conf_val = conf.get("confidence", 0)
        rows.append((conf_val, pair_key, string_ppi, pathway_str, p_str, rr_str))

    # Sort by confidence descending
    rows.sort(key=lambda r: -r[0])

    lines = [
        "| L-R Pair | Confidence | STRING PPI | Shared Pathways | Census p-value | Census RR |",
        "|----------|-----------|-----------|-----------------|---------------|----------|",
    ]
    for conf_val, pair_key, string_ppi, pathway_str, p_str, rr_str in rows:
        pair_display = pair_key.replace("^", "\\_")
        lines.append(
            f"| {pair_display} | {conf_val:.2f} | {string_ppi:.3f} | {pathway_str} | {p_str} | {rr_str} |"
        )

    return "\n".join(lines)


def _build_stage1_context_notes(evidence: dict) -> str:
    """Build a short deterministic note block for microenvironment-tagged pairs."""
    details = evidence.get("stage1_details", {})
    confidence = evidence.get("stage1_confidence", {})
    resolved_context = evidence.get("resolved_context", {})
    primary_target_cell_type = (
        resolved_context.get("resolved_target_cell_type")
        or resolved_context.get("requested_target_cell_type")
        or "primary target cell type"
    )
    notes = []

    ranked_pairs = sorted(
        confidence,
        key=lambda pair_key: confidence.get(pair_key, {}).get("confidence", 0),
        reverse=True,
    )
    for pair_key in ranked_pairs:
        if "^" not in pair_key:
            continue
        ligand, receptor = pair_key.split("^", 1)
        detail = details.get(f"stage1_{ligand}--{receptor}", {})
        annotation = detail.get("stage1_annotations", {})
        if not annotation.get("microenvironment_candidate"):
            continue
        notes.append(
            "- "
            f"`{pair_key}` shows weak coexpression in the primary target cell type "
            f"({primary_target_cell_type}) but strong "
            f"{annotation.get('supporting_cell_type', 'supporting')} support "
            f"({annotation.get('supporting_coexpression_pct', 0):.2f}% coexpression); "
            "interpret as a vascular microenvironment candidate rather than a primary target-cell candidate."
        )

    if not notes:
        return ""
    return "\n".join(["**Context Notes**", *notes])


def _replace_stage1_table(content: str, evidence: dict) -> str:
    """Replace the LLM-generated Stage 1 table with the pre-computed one.

    LLMs often ignore 'copy exactly' instructions, so we programmatically
    find the Stage 1 table region and swap it in.
    """
    import re

    correct_table = _build_stage1_table(evidence)
    context_notes = _build_stage1_context_notes(evidence)
    replacement = correct_table
    if context_notes:
        replacement += "\n\n" + context_notes

    # Find the Stage 1 table region: starts with the header row, ends before
    # the Confidence Score Formula line or the next ## heading.
    pattern = re.compile(
        r"(\| L-R Pair \|.*?\n\|[-| ]+\n)"  # header + separator
        r"((?:\|.*\n)*)",                      # all data rows
        re.MULTILINE,
    )
    match = pattern.search(content)
    if match:
        content = content[:match.start()] + replacement + "\n" + content[match.end():]
        print("  Post-processed: replaced Stage 1 table with pre-computed values")
    else:
        print("  WARNING: Could not find Stage 1 table to replace")

    return content


def build_prompt(evidence: dict) -> str:
    """Build the LLM prompt for generating drug.md."""
    ta = evidence["target_assessment"]
    meta = ta["project_meta"]
    matrix = ta["druggability_matrix"]
    deep_dives = ta["featured_candidates_deep_dive"]

    # Summarize key data
    featured_pairs = [r for r in matrix if r.get("track") == "FEATURED"]
    novel_pairs = [r for r in matrix if r.get("track") == "NOVEL"]

    rubric = evidence.get("rubric_scores", [])
    known_drugs = evidence.get("known_drugs", {})
    disease_focus = evidence["resolved_context"]["disease"]

    # Build pre-computed Stage 1 table from individual stage1 details
    stage1_table = _build_stage1_table(evidence)
    stage1_context_notes = _build_stage1_context_notes(evidence)

    prompt = f"""Generate a comprehensive drug.md report for therapeutic target assessment.

## Context
- Disease: {disease_focus}
- Total L-R pairs assessed: {meta.get('total_input_pairs', len(matrix))}
- Data sources: {', '.join(meta.get('data_sources', []))}
- Featured candidates: {len(featured_pairs)}
- Novel candidates: {len(novel_pairs)}

## target_assessment.json data

### Druggability Matrix (all {len(matrix)} pairs):
{json.dumps(matrix, indent=2)}

### Featured Candidates Deep Dive ({len(deep_dives)} entries):
{json.dumps(deep_dives, indent=2)}

## Rubric Scores:
{json.dumps(rubric[:10], indent=2)}
... ({len(rubric)} total)

## Known Drugs:
{json.dumps(known_drugs, indent=2)}

## Stage 1 — Biological Context Validation (PRE-COMPUTED TABLE — USE EXACTLY AS-IS):
{stage1_table}

## Stage 1 Context Notes (PRE-COMPUTED — USE EXACTLY AS-IS IF PRESENT):
{stage1_context_notes or "(none)"}

## Stage 1 Confidence Scores (per-pair):
{json.dumps(evidence.get('stage1_confidence', {}), indent=2)}

## Stage 2 Evidence Summary:
{json.dumps(evidence.get('stage2_evidence', {}), indent=2)[:3000]}

## Assessment Results:
{json.dumps(evidence.get('assessment_results', [])[:5], indent=2)}

---

## INSTRUCTIONS

Write a complete drug.md document following this exact structure:

# Therapeutic Target Assessment Report — {disease_focus.title()}

## 1. Executive Summary
- Assessment scope (N L-R pairs, disease)
- [FEATURED] candidates listed FIRST with key findings
- [NOVEL] candidates listed after
- Key therapeutic opportunities and next steps

## 2. Stage 1 — Biological Context Validation
COPY THE PRE-COMPUTED TABLE FROM "Stage 1 — Biological Context Validation" SECTION ABOVE EXACTLY AS-IS.
Do NOT recalculate or modify the Confidence, STRING PPI, Census p-value, or Census RR values.
If the "Stage 1 Context Notes" section is not "(none)", copy it exactly below the table.
Add a footnote explaining: Confidence = 0.35×STRING + 0.30×Census + 0.20×Pathway + 0.15×Expression.
Describe the Confidence Score formula components: STRING PPI (35%), Census coexpression (30%), shared KEGG/Reactome pathways (20%), gene expression availability (15%).
Note Census p-value and RR are from a two-proportion z-test comparing coexpression rates in the target cell type vs. all other cells.
Sort by Confidence Score descending.

## 3. Stage 2 — Target Validation & Rubric Scoring
(Same as current Section 3 in the existing report — include rubric table with all pairs)

## 3.1. Pan-Disease Target Druggability Matrix
A markdown table with ALL pairs:
| Rank | L-R Pair | Track | OT Score | Max Clinical Phase | Genetic Flag | Tractability |
Featured and Novel rows bolded and listed first.

For each featured candidate:
### [FEATURED] GENE — Priority: HIGH/MEDIUM
A. Clinical & Safety Profile
B. Biological Context & Pathway
C. Rubric Assessment Summary
D. Therapeutic Recommendation

## 5. [NOVEL] Candidate Deep Dives
For each novel candidate (if any):
### [NOVEL] GENE — Priority
A. Why This Is Novel
B. Biological Evidence
C. Drug Development Potential

## 6. Pipeline Execution Summary & Recommendations
- Statistics
- Four recommendation categories (Validated, Exploratory, Novel, Insufficient)
- Next steps

IMPORTANT:
- Output ONLY the markdown content, no code fences
- Make it publication-quality, detailed, with evidence citations
- Bold featured/novel rows in tables
- Include specific scores and data from the evidence
"""
    return prompt


async def main():
    global DATA_DIR
    args = _parse_args()
    DATA_DIR = (PROJECT_ROOT / args.data_dir).resolve()

    print("Generating drug.md from existing evidence...")
    t0 = time.time()

    evidence = load_all_evidence()
    print(f"  Loaded evidence: {list(evidence.keys())}")

    prompt = build_prompt(evidence)
    print(f"  Prompt length: {len(prompt)} chars")

    llm = create_llm(provider=PROVIDER, max_tokens=16384)

    print("  Calling LLM...")
    response = await llm.ainvoke(prompt)

    content = response.content
    print(f"  Response length: {len(content)} chars")

    # Post-process: replace LLM-generated Stage 1 table with pre-computed one
    content = _replace_stage1_table(content, evidence)

    # Write drug.md
    out_path = DATA_DIR / "drug.md"
    out_path.write_text(content, encoding="utf-8")

    elapsed = time.time() - t0
    print(f"\ndrug.md generated in {elapsed:.1f}s")
    print(f"  Path: {out_path}")
    print(f"  Size: {len(content)} chars")


if __name__ == "__main__":
    asyncio.run(main())
