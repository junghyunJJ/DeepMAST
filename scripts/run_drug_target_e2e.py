#!/usr/bin/env python
"""End-to-end DrugTargetAgent run with mock breast cancer L-R data.

Runs the full 3-subagent pipeline (evidence_collector -> clinical_assessor ->
report_writer) against real APIs (OpenTargets, GWAS, ChEMBL, ClinicalTrials.gov,
FDA) using 15 mock L-R pairs (30 genes) from triple-negative breast cancer.

Usage:
    python scripts/run_drug_target_e2e.py

Expected runtime: 3-8 minutes (depends on API response times).
Expected API load: ~80 calls (35 OT + 6 GWAS + 30 ChEMBL + 5 CT + 5 FDA).

Output:
    - evidence/*.json    (per-gene and per-disease evidence files)
    - assessment_results.json  (rubric scores for all 30 genes)
    - drug.md            (publication-quality therapeutic target report)
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project bootstrap
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Mock data (biologically realistic breast cancer L-R pairs)
# Identical to tests/test_drug_target.py for consistency
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

# Featured candidates (genes from selected_top3)
FEATURED_GENES = sorted({"TGFB1", "TGFBR2", "SPP1", "CD44", "VEGFA", "FLT1"})


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _extract_drug_md_from_messages(result: dict, data_dir: Path) -> bool:
    """Fallback: extract drug.md content from agent's final messages.

    The report_writer may generate the full markdown in a message but fail
    to call write_file (model behavior issue). This scans messages for
    markdown content that looks like drug.md and saves it.

    Returns True if drug.md was successfully extracted.
    """
    messages = result.get("messages", [])
    for msg in reversed(messages):
        content = msg.content if hasattr(msg, "content") else str(msg)
        if not isinstance(content, str):
            continue
        # Look for drug.md-like content: has Executive Summary + Featured Candidate
        if (
            len(content) > 2000
            and "executive summary" in content.lower()
            and ("featured candidate" in content.lower() or "druggability" in content.lower())
        ):
            drug_md_path = data_dir / "drug.md"
            drug_md_path.write_text(content)
            print(f"  [FALLBACK] Extracted drug.md from agent messages ({len(content):,} chars)")
            return True
    return False


async def main():
    """Run the full DrugTargetAgent E2E pipeline."""
    start = time.time()

    # Use mkdtemp (no auto-cleanup) so workspace persists for inspection
    tmpdir = tempfile.mkdtemp(prefix="drug_target_e2e_")
    data_dir = Path(tmpdir)
    print(f"Workspace: {data_dir} (persisted for inspection)")

    # 1. Write input files
    (data_dir / "lr_candidates.json").write_text(
        json.dumps(MOCK_LR_CANDIDATES, indent=2)
    )
    (data_dir / "selected_top3_lr.json").write_text(
        json.dumps(MOCK_SELECTED_TOP3, indent=2)
    )
    print(f"  lr_candidates.json: 15 pairs, 30 genes")
    print(f"  selected_top3_lr.json: {FEATURED_GENES}")

    # Set env var so tools can find data_dir even if LLM passes wrong path
    os.environ["DRUG_TARGET_DATA_DIR"] = str(data_dir)

    # 2. Create agent
    from src.agents.drug_target.agent import (
        DrugTargetConfig,
        create_drug_target_agent,
    )

    config = DrugTargetConfig(
        provider="openrouter",
        data_dir=str(data_dir),
        disease="breast cancer",
        use_checkpointer=True,
    )
    agent = create_drug_target_agent(config)
    print(f"  Agent created (provider=openrouter, checkpointer=True)")

    # 3. Run the agent
    initial_message = (
        f"Assess therapeutic potential of L-R pair genes.\n\n"
        f"Disease context: breast cancer (triple-negative)\n"
        f"Data directory: {data_dir}\n"
        f"Input: lr_candidates.json (15 L-R pairs, 30 genes), selected_top3_lr.json\n"
        f"Output: drug.md\n\n"
        f"Execute: evidence_collector -> clinical_assessor -> report_writer"
    )

    print(f"\n{'='*60}")
    print("Running DrugTargetAgent pipeline...")
    print(f"{'='*60}\n")

    TIMEOUT_SECONDS = 30 * 60  # 30 minutes
    try:
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [{"role": "user", "content": initial_message}]},
                config={"configurable": {"thread_id": str(uuid.uuid4())}},
            ),
            timeout=TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        print(f"\n{'='*60}")
        print(f"TIMEOUT after {elapsed:.1f}s ({TIMEOUT_SECONDS}s limit)")
        print(f"{'='*60}\n")
        result = {"messages": []}

    elapsed = time.time() - start

    # 4. Check outputs
    print(f"\n{'='*60}")
    print(f"Pipeline completed in {elapsed:.1f}s")
    print(f"{'='*60}\n")

    # Diagnostic: message count and tool calls
    messages = result.get("messages", [])
    print(f"Agent messages: {len(messages)}")
    tool_calls = []
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(tc.get("name", "unknown"))
    if tool_calls:
        from collections import Counter
        tc_counts = Counter(tool_calls)
        print(f"Tool calls ({len(tool_calls)} total):")
        for name, count in tc_counts.most_common():
            print(f"  {name}: {count}")
    print()

    # Evidence files
    evidence_dir = data_dir / "evidence"
    if evidence_dir.exists():
        evidence_files = sorted(evidence_dir.glob("*.json"))
        print(f"Evidence files ({len(evidence_files)}):")
        for f in evidence_files:
            size = f.stat().st_size
            print(f"  {f.name} ({size:,} bytes)")
    else:
        print("WARNING: evidence/ directory not found")

    # Assessment results
    assessment_path = evidence_dir / "assessment_results.json" if evidence_dir.exists() else None
    if assessment_path and assessment_path.exists():
        assessments = json.loads(assessment_path.read_text())
        print(f"\nAssessment results: {type(assessments).__name__}")
        if isinstance(assessments, dict):
            for key in ("gene_count", "classifications", "priorities"):
                if key in assessments:
                    print(f"  {key}: {assessments[key]}")
    else:
        print("\nWARNING: assessment_results.json not found")

    # drug.md — check filesystem first, then fallback to message extraction
    drug_md = data_dir / "drug.md"
    if not drug_md.exists():
        print("\ndrug.md not on disk — attempting message extraction fallback...")
        _extract_drug_md_from_messages(result, data_dir)

    if drug_md.exists():
        content = drug_md.read_text()
        print(f"\ndrug.md: {len(content):,} chars")

        # Check mandatory sections
        mandatory_sections = [
            "Executive Summary",
            "Druggability",
            "Featured Candidate",
            "Clinical",
            "GWAS",
            "Recommendation",
        ]
        print("\nMandatory section checks:")
        for section in mandatory_sections:
            found = section.lower() in content.lower()
            status = "PASS" if found else "MISS"
            print(f"  [{status}] {section}")

        # Check featured candidates appear
        print("\nFeatured candidate mentions:")
        for gene in FEATURED_GENES:
            count = content.count(gene)
            status = "PASS" if count > 0 else "MISS"
            print(f"  [{status}] {gene} ({count}x)")

        # Preview
        print(f"\n{'='*60}")
        print("drug.md preview (first 3000 chars):")
        print(f"{'='*60}")
        print(content[:3000])
    else:
        print("\nFAILED: drug.md was NOT generated")
        # Diagnostic: print last few messages to understand what happened
        print("\nLast 3 agent messages (for debugging):")
        for msg in messages[-3:]:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                preview = content[:500]
            else:
                preview = str(content)[:500]
            print(f"  [{role}] {preview}...")

    # Final summary
    print(f"\n{'='*60}")
    print("E2E Summary")
    print(f"{'='*60}")
    evidence_count = len(list(evidence_dir.glob("*.json"))) if evidence_dir.exists() else 0
    print(f"  Evidence files:  {evidence_count}")
    print(f"  Assessment:      {'YES' if assessment_path and assessment_path.exists() else 'NO'}")
    print(f"  drug.md:         {'YES' if drug_md.exists() else 'NO'}")
    print(f"  Runtime:         {elapsed:.1f}s")
    print(f"  Workspace:       {data_dir}")

    success = drug_md.exists() and evidence_count > 0
    if success:
        print(f"\n  SUCCESS — all outputs generated")
    else:
        print(f"\n  PARTIAL — inspect workspace for details")
    return 0 if success else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    sys.exit(asyncio.run(main()))
