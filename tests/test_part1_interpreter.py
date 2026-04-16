"""Integration test for Part 1 INTERPRETER subagent.

Runs the INTERPRETER subagent standalone against res_bc data
and validates Part 1 output quality.

Prerequisites:
- res_bc/ directory with all analysis files
- papers.json (searched by SEARCHER)
- interpretation_guide.md (written by PLANNER)
- data_path.txt (written by PLANNER)

Usage:
    python tests/test_part1_interpreter.py
    PART1_PROVIDER=openai python tests/test_part1_interpreter.py   # override provider
"""

import asyncio
import os
import re
import sys
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set data directory BEFORE any project imports
DATA_DIR = str(PROJECT_ROOT / "res_bc")
os.environ["DEEP_INTERPRETER_DATA_DIR"] = DATA_DIR

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


# ── Provider selection ────────────────────────────────────────────────────────
# Use openai (gpt-4.1-mini) by default.
# Override: PART1_PROVIDER=openrouter python tests/test_part1_interpreter.py
PROVIDER = os.getenv("PART1_PROVIDER", "openai")


# ── Part 1 invocation message ────────────────────────────────────────────────
PART1_MESSAGE = {
    "messages": [
        {
            "role": "user",
            "content": (
                "You are the INTERPRETER subagent. Your task is to interpret **Part 1 ONLY**.\n\n"
                "## Part 1: Spatial and Pathway Analysis\n\n"
                "Required analyses:\n"
                "- 1-1 Spatial Clustering (spatial distribution of clusters)\n"
                "- 1-2 Cell Type Composition (cell type enrichment per cluster)\n"
                "- 1-3 Neighborhood Enrichment (co-localization patterns, z-scores)\n"
                "- 1-4 Decoupler Pathway (pathway activity by cluster)\n"
                "- 1-5 MISTy (pathway-celltype spatial relationships)\n\n"
                "Input files:\n"
                "- /papers.json (literature references)\n"
                "- /interpretation_guide.md\n"
                "- /data_path.txt\n\n"
                "Output: **/part1_final.md** (MUST be written via write_file tool)\n\n"
                "## MANDATORY WORKFLOW (Phase 4 Steps A-E):\n"
                "1. read_file('/data_path.txt') to get data directory\n"
                "2. read_file('/interpretation_guide.md') for context\n"
                "3. read_file('/papers.json') to load citation source\n"
                "4. load_analysis_data(data_dir=...) to get Part 1 analysis data\n"
                "5. Step A — Draft detailed interpretation for ALL 5 analyses (1-1, 1-2, 1-3, 1-4, 1-5)\n"
                "6. Step B — MANDATORY think_tool(reflection=<self-critique>, score_threshold=0.8, "
                "max_iterations=3). think_tool is the ACTIVE reflection/completeness loop.\n"
                "7. Step C — Revise the draft if think_tool.should_continue=True; return to Step B.\n"
                "8. Step D — validate_quality(interpretation=..., use_llm=False) as the deterministic "
                "objective checkpoint (layered under the think_tool loop). Do NOT pass "
                "score_threshold here — it is not a validate_quality kwarg.\n"
                "9. Step E — Consumer-side gate: if result['score'] < 0.8, return to Step B. "
                "Max 3 total iterations across Steps B-D.\n"
                "10. **write_file(file_path='/part1_final.md', content=...)** to save output\n\n"
                "## CRITICAL: TEMPLATE STRUCTURE\n"
                "Each analysis section MUST include ALL of these subsections:\n"
                "### Figure Description\n"
                "{Detailed description: what the figure shows, axes, color scheme, key visual patterns}\n\n"
                "### Quantitative Findings\n"
                "{At least 4 specific statistics: p-values, fold changes, z-scores, percentages, counts}\n\n"
                "### Biological Interpretation\n"
                "{3 paragraphs: mechanism, spatial context, clinical/disease relevance. Cite PMIDs.}\n\n"
                "### Novel Findings\n"
                "{Observations not supported by literature, marked with reasoning for biological plausibility}\n\n"
                "### Cross-Analysis Connections\n"
                "{How this analysis connects to OTHER analyses within Part 1. E.g.:\n"
                "- Connection to Analysis 1-2: Cluster 17 enriched in invasive tumor (1-1) correlates with proliferative cell type enrichment (1-2)\n"
                "- Connection to Analysis 1-4: Spatial clustering patterns (1-1) align with EGFR pathway enrichment regions (1-4)}\n\n"
                "### References\n"
                "{At least 4 PMIDs with specific supporting evidence}\n\n"
                "The Part MUST end with:\n"
                "## Part 1 Summary\n"
                "### Key Findings\n"
                "### Cross-Part Connections\n"
                "### Limitations and Caveats\n"
                "### Quality Metrics\n\n"
                "## Part 1 Depth Requirements:\n"
                "- For each of the 5 analyses, write at least 3 paragraphs of biological interpretation\n"
                "- Connect spatial clustering patterns to cell type composition (1-1 <-> 1-2)\n"
                "- Link neighborhood enrichment z-scores to specific pathway activities (1-3 <-> 1-4)\n"
                "- Explain how MISTy results validate or extend the pathway findings (1-5 <-> 1-4)\n"
                "- Include at least 4 quantitative statistics per analysis\n"
                "- Cite at least 4 PMIDs per analysis from /papers.json\n\n"
                "## CRITICAL RULE:\n"
                "You MUST call the **write_file** tool to save /part1_final.md.\n"
                "Do NOT just output the interpretation as text — it must be persisted to disk.\n\n"
                "Begin now."
            ),
        }
    ]
}


# ── Runner ────────────────────────────────────────────────────────────────────


async def run_part1_interpreter():
    """Run Part 1 interpreter subagent and return the final state."""
    from src.agents.deep_interpreter.graph_builder import create_subagent_graph

    print(f"Provider : {PROVIDER}")
    print(f"Data dir : {DATA_DIR}")

    # create_subagent_graph already applies recursion_limit=200
    graph = create_subagent_graph("interpreter", provider=PROVIDER)

    print("\n" + "=" * 60)
    print("Invoking Part 1 INTERPRETER subagent...")
    print("=" * 60 + "\n")

    result = await graph.ainvoke(PART1_MESSAGE)
    return result


def _extract_markdown_from_response(result: dict) -> str | None:
    """Extract markdown content from agent's last message as fallback.

    Some models generate the interpretation inline instead of calling write_file.
    This extracts that content so we can still validate and persist it.
    """
    if not result or "messages" not in result:
        return None

    # Walk messages in reverse looking for substantial markdown content
    for msg in reversed(result["messages"]):
        text = getattr(msg, "content", None)
        if isinstance(text, list):
            # Multi-part content — find the text block
            for part in text:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part["text"]
                    break
            else:
                continue
        if not isinstance(text, str):
            continue

        # Look for Part 1 markdown content (must have the heading + analysis sections)
        if "# Part 1" in text and ("## Analysis 1-1" in text or "## Analysis 1-2" in text):
            # Extract from the first heading to end
            match = re.search(r"(# Part 1.*)", text, re.DOTALL)
            if match:
                return match.group(1).strip()

    return None


# ── Verification ──────────────────────────────────────────────────────────────


def verify_output():
    """Verify Part 1 output exists and meets quality criteria.

    Returns:
        dict with quality scores and pass/fail status
    """
    from src.agents.deep_interpreter.tools.quality import _calculate_basic_score

    part1_path = Path(DATA_DIR) / "part1_final.md"

    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # 1. File existence
    assert part1_path.exists(), f"part1_final.md not found at {part1_path}"
    content = part1_path.read_text()
    byte_size = part1_path.stat().st_size
    word_count = len(content.split())
    print(f"[OK] part1_final.md exists  ({byte_size:,} bytes, {word_count:,} words)")

    # 2. Quality score (basic / deterministic — no LLM call)
    quality = _calculate_basic_score(content)
    score = quality["score"]

    print(f"\nQuality Scores (threshold >= 0.8):")
    for key in ("statistics_score", "references_score", "mechanism_score",
                "specificity_score", "depth_score", "structure_score"):
        val = quality[key]
        mark = "OK" if val >= 0.7 else "LOW"
        print(f"  [{mark}] {key:20s} {val:.3f}")
    print(f"  ---- {'overall':20s} {score:.3f}  {'PASS' if score >= 0.8 else 'FAIL'}")

    if quality["feedback"] != "Quality criteria met.":
        print(f"  Feedback: {quality['feedback']}")

    # 3. Required template sections
    required_sections = [
        "# Part 1",
        "## Analysis 1-1",
        "## Analysis 1-2",
        "## Analysis 1-3",
        "## Analysis 1-4",
        "## Analysis 1-5",
        "### Figure Description",
        "### Quantitative Findings",
        "### Biological Interpretation",
        "### Cross-Analysis Connections",
        "### References",
        "## Part 1 Summary",
    ]

    content_lower = content.lower()
    missing = []
    print("\nTemplate Sections:")
    for section in required_sections:
        found = section.lower() in content_lower
        print(f"  [{'OK' if found else 'MISS'}] {section}")
        if not found:
            missing.append(section)

    # 4. Part-1–specific: spatial analysis evidence check
    spatial_keywords = ["cluster", "spatial", "enrichment", "z-score",
                        "neighborhood", "pathway", "misty"]
    has_spatial_evidence = sum(1 for kw in spatial_keywords if kw in content_lower)
    print(f"\n[{'OK' if has_spatial_evidence >= 5 else 'LOW'}] Spatial analysis keywords: {has_spatial_evidence}/7 found")

    # 5. Summary verdict
    all_pass = score >= 0.8 and not missing
    print(f"\n{'=' * 60}")
    if all_pass:
        print("RESULT: PASS")
    elif score < 0.8:
        print(f"RESULT: FAIL  (score {score:.3f} < 0.8)")
    else:
        print(f"RESULT: PARTIAL  (missing sections: {missing})")
    print("=" * 60)

    return {**quality, "missing_sections": missing, "all_pass": all_pass}


# ── Main ──────────────────────────────────────────────────────────────────────


async def main():
    part1_path = Path(DATA_DIR) / "part1_final.md"

    # Back up previous output if it exists
    if part1_path.exists():
        backup = part1_path.with_suffix(".md.bak")
        part1_path.rename(backup)
        print(f"Backed up existing part1_final.md -> {backup.name}")

    try:
        result = await run_part1_interpreter()

        # Show agent's final message (truncated)
        if result and "messages" in result:
            last_msg = result["messages"][-1]
            text = getattr(last_msg, "content", str(last_msg))
            if isinstance(text, str):
                print(f"\nAgent final message (first 500 chars):\n{text[:500]}")
            elif isinstance(text, list):
                for part in text:
                    if isinstance(part, dict) and part.get("type") == "text":
                        print(f"\nAgent final message (first 500 chars):\n{part['text'][:500]}")
                        break

        # Fallback: if agent didn't call write_file, extract content from response
        if not part1_path.exists():
            print("\n[WARN] write_file not called by agent — extracting from response...")
            extracted = _extract_markdown_from_response(result)
            if extracted:
                part1_path.write_text(extracted, encoding="utf-8")
                print(f"[WARN] Saved extracted content ({len(extracted):,} chars) to {part1_path.name}")
            else:
                print("[ERR]  Could not extract markdown from agent response")

        return verify_output()

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

        # Restore backup if run failed and no new output was produced
        backup = part1_path.with_suffix(".md.bak")
        if backup.exists() and not part1_path.exists():
            backup.rename(part1_path)
            print("Restored backup of part1_final.md")
        raise


if __name__ == "__main__":
    result = asyncio.run(main())
