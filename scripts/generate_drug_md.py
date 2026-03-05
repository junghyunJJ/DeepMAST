#!/usr/bin/env python3
"""Generate drug.md from target_assessment.json + evidence files using LLM.

This script reads the already-generated target_assessment.json and evidence
files, then uses an LLM to produce the final drug.md report.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.agents.model import create_llm

DATA_DIR = PROJECT_ROOT / "res_bc_ollama"
DISEASE = "breast cancer"
PROVIDER = "openrouter"


def load_all_evidence() -> dict:
    """Load target_assessment.json and key evidence files."""
    evidence_dir = DATA_DIR / "evidence"

    data = {}

    # Main assessment
    ta_path = DATA_DIR / "target_assessment.json"
    if ta_path.exists():
        data["target_assessment"] = json.loads(ta_path.read_text())

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
                       "stage1_cellxgene_all_pairs.json"):
            continue
        stage1_details[f.stem] = json.loads(f.read_text())
    data["stage1_details"] = stage1_details

    # OpenTargets per-gene
    ot_details = {}
    for f in evidence_dir.glob("ot_*.json"):
        ot_details[f.stem] = json.loads(f.read_text())
    data["opentargets_details"] = ot_details

    return data


def _build_stage1_table(evidence: dict) -> str:
    """Build a pre-computed Stage 1 markdown table from individual stage1 data."""
    confidence = evidence.get("stage1_confidence", {})
    details = evidence.get("stage1_details", {})

    rows = []
    for pair_key, conf in confidence.items():
        if not pair_key or "^" not in pair_key:
            continue
        # Find matching detail file
        ligand, receptor = pair_key.split("^", 1)
        detail_key = f"stage1_{ligand}_{receptor}"
        detail = details.get(detail_key, {})

        # STRING PPI
        string_ppi = conf.get("string_score", 0)

        # Shared pathways (KEGG + Reactome)
        kegg = detail.get("kegg_pathways", {})
        kegg_lig = {p["pathway_id"] for p in kegg.get("ligand_pathways", []) if "pathway_id" in p}
        kegg_rec = {p["pathway_id"] for p in kegg.get("receptor_pathways", []) if "pathway_id" in p}
        shared_kegg = kegg_lig & kegg_rec

        reactome = detail.get("reactome_pathways", {})
        react_lig = {p["reactome_id"] for p in reactome.get("ligand_pathways", []) if "reactome_id" in p}
        react_rec = {p["reactome_id"] for p in reactome.get("receptor_pathways", []) if "reactome_id" in p}
        shared_reactome = react_lig & react_rec

        shared_names = []
        if shared_kegg:
            name_map = {}
            for p in kegg.get("ligand_pathways", []) + kegg.get("receptor_pathways", []):
                pid = p.get("pathway_id", "")
                name = p.get("name", pid)
                name = name.split(" - Homo sapiens")[0] if " - Homo sapiens" in name else name
                name_map[pid] = name
            shared_names.extend(name_map[pid] for pid in shared_kegg if pid in name_map)
        if shared_reactome:
            name_map = {}
            for p in reactome.get("ligand_pathways", []) + reactome.get("receptor_pathways", []):
                pid = p.get("reactome_id", "")
                name = p.get("name", pid)
                name_map[pid] = name
            shared_names.extend(name_map[pid] for pid in shared_reactome if pid in name_map)

        pathway_str = ", ".join(shared_names) if shared_names else "—"

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


def _replace_stage1_table(content: str, evidence: dict) -> str:
    """Replace the LLM-generated Stage 1 table with the pre-computed one.

    LLMs often ignore 'copy exactly' instructions, so we programmatically
    find the Stage 1 table region and swap it in.
    """
    import re

    correct_table = _build_stage1_table(evidence)

    # Find the Stage 1 table region: starts with the header row, ends before
    # the Confidence Score Formula line or the next ## heading.
    pattern = re.compile(
        r"(\| L-R Pair \|.*?\n\|[-| ]+\n)"  # header + separator
        r"((?:\|.*\n)*)",                      # all data rows
        re.MULTILINE,
    )
    match = pattern.search(content)
    if match:
        content = content[:match.start()] + correct_table + "\n" + content[match.end():]
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

    # Build pre-computed Stage 1 table from individual stage1 details
    stage1_table = _build_stage1_table(evidence)

    prompt = f"""Generate a comprehensive drug.md report for therapeutic target assessment.

## Context
- Disease: {meta.get('disease_focus', DISEASE)}
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

## Stage 1 Confidence Scores (per-pair):
{json.dumps(evidence.get('stage1_confidence', {}), indent=2)}

## Stage 2 Evidence Summary:
{json.dumps(evidence.get('stage2_evidence', {}), indent=2)[:3000]}

## Assessment Results:
{json.dumps(evidence.get('assessment_results', [])[:5], indent=2)}

---

## INSTRUCTIONS

Write a complete drug.md document following this exact structure:

# Therapeutic Target Assessment Report — {meta.get('disease_focus', DISEASE).title()}

## 1. Executive Summary
- Assessment scope (N L-R pairs, disease)
- [FEATURED] candidates listed FIRST with key findings
- [NOVEL] candidates listed after
- Key therapeutic opportunities and next steps

## 2. Stage 1 — Biological Context Validation
COPY THE PRE-COMPUTED TABLE FROM "Stage 1 — Biological Context Validation" SECTION ABOVE EXACTLY AS-IS.
Do NOT recalculate or modify the Confidence, STRING PPI, Census p-value, or Census RR values.
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
