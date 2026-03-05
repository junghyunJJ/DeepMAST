"""Integration test for Part 2 INTERPRETER subagent.

Runs the INTERPRETER subagent standalone against res_bc data
and validates Part 2 output quality.

Prerequisites:
- res_bc/ directory with all analysis files
- papers.json (searched by SEARCHER)
- interpretation_guide.md (written by PLANNER)
- data_path.txt (written by PLANNER)

Usage:
    python tests/test_part2_interpreter.py
    PART2_PROVIDER=openai python tests/test_part2_interpreter.py   # override provider
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
# Use openai (gpt-4.1-mini) by default — openrouter can hang on Part 2.
# Override: PART2_PROVIDER=openrouter python tests/test_part2_interpreter.py
PROVIDER = os.getenv("PART2_PROVIDER", "openai")


# ── Part 2 invocation message ────────────────────────────────────────────────
PART2_MESSAGE = {
    "messages": [
        {
            "role": "user",
            "content": (
                "You are the INTERPRETER subagent. Your task is to interpret **Part 2 ONLY**.\n\n"
                "## Part 2: CCI and NMF Analyses\n\n"
                "Required analyses:\n"
                "- 2-6 LIANA Moran's R (Top spatially co-localized L-R pairs)\n"
                "- 2-7 NMF Factor Spatial Patterns\n"
                "- 2-8 Pathway-Factor Enrichment (includes GenePT scores)\n\n"
                "Input files:\n"
                "- /papers.json (literature references)\n"
                "- /interpretation_guide.md\n"
                "- /data_path.txt\n\n"
                "Output: **/part2_final.md** (MUST be written via write_file tool)\n\n"
                "## MANDATORY WORKFLOW:\n"
                "1. read_file('/data_path.txt') to get data directory\n"
                "2. read_file('/interpretation_guide.md') for context\n"
                "3. read_file('/papers.json') to load citation source\n"
                "4. load_analysis_data(data_dir=...) to get Part 2 analysis data\n"
                "5. Write detailed interpretation for ALL 3 analyses (2-6, 2-7, 2-8)\n"
                "6. validate_quality(interpretation=...) — target score >= 0.8\n"
                "7. **write_file(file_path='/part2_final.md', content=...)** to save output\n\n"
                "## CRITICAL: QUANTITATIVE STATISTICS REQUIREMENT\n"
                "Part 2 requires RICH quantitative evidence. For EACH analysis section, include:\n"
                "- **Moran's R / Moran's I scores** with exact values (e.g., 'Moran's R = 0.4776')\n"
                "- **p-values** for statistical significance (e.g., 'p < 0.001', 'p = 0.0')\n"
                "- **Fold changes** for enrichment comparisons (e.g., '2.5-fold enrichment')\n"
                "- **Percentages** for composition or coverage (e.g., '35% of total interactions')\n"
                "- **Counts** (e.g., '449 unique genes', '15 significant L-R pairs')\n"
                "- **NMF factor scores** with exact values (e.g., 'Factor3 mean score = 0.74')\n"
                "You MUST include at least 4 different quantitative statistics per analysis.\n"
                "The quality validator will score statistics heavily (20% of total score).\n\n"
                "## CRITICAL: TEMPLATE STRUCTURE\n"
                "Each analysis section MUST include ALL of these subsections:\n"
                "### Figure Description\n"
                "### Quantitative Findings\n"
                "### Biological Interpretation\n"
                "### Novel Findings\n"
                "### Cross-Analysis Connections\n"
                "### References\n\n"
                "The Part MUST end with:\n"
                "## Part 2 Summary\n"
                "### Key Findings\n"
                "### Cross-Part Connections\n"
                "### Limitations and Caveats\n"
                "### Quality Metrics\n\n"
                "## Part 2 Depth Requirements:\n"
                "- For LIANA Moran's R (2-6): Analyze at least 5 specific L-R pairs with source cell type, "
                "target cell type, pathway context, and spatial co-localization evidence (Moran's R values)\n"
                "- For NMF Factor (2-7): Describe spatial distribution of each significant factor with "
                "exact scores and biological meaning in tissue architecture\n"
                "- For Pathway-Factor (2-8): Connect pathway enrichment to NMF factors AND to L-R pairs "
                "from 2-6, creating a narrative thread through all Part 2 analyses\n"
                "- Cross-reference: Every L-R pair discussed in 2-6 should be linked to relevant "
                "NMF factors (2-7) and pathways (2-8)\n\n"
                "## CRITICAL RULE:\n"
                "You MUST call the **write_file** tool to save /part2_final.md.\n"
                "Do NOT just output the interpretation as text — it must be persisted to disk.\n\n"
                "Begin now."
            ),
        }
    ]
}


# ── Runner ────────────────────────────────────────────────────────────────────


async def run_part2_interpreter():
    """Run Part 2 interpreter subagent and return the final state."""
    from src.agents.deep_interpreter.graph_builder import create_subagent_graph

    print(f"Provider : {PROVIDER}")
    print(f"Data dir : {DATA_DIR}")

    # create_subagent_graph already applies recursion_limit=200
    graph = create_subagent_graph("interpreter", provider=PROVIDER)

    print("\n" + "=" * 60)
    print("Invoking Part 2 INTERPRETER subagent...")
    print("=" * 60 + "\n")

    result = await graph.ainvoke(PART2_MESSAGE)
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

        # Look for Part 2 markdown content (must have the heading + analysis sections)
        if "# Part 2" in text and ("## Analysis 2-6" in text or "## Analysis 2-7" in text):
            # Extract from the first heading to end
            match = re.search(r"(# Part 2.*)", text, re.DOTALL)
            if match:
                return match.group(1).strip()

    return None


# ── Verification ──────────────────────────────────────────────────────────────


def verify_output():
    """Verify Part 2 output exists and meets quality criteria.

    Returns:
        dict with quality scores and pass/fail status
    """
    from src.agents.deep_interpreter.tools.quality import _calculate_basic_score

    part2_path = Path(DATA_DIR) / "part2_final.md"

    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # 1. File existence
    assert part2_path.exists(), f"part2_final.md not found at {part2_path}"
    content = part2_path.read_text()
    byte_size = part2_path.stat().st_size
    word_count = len(content.split())
    print(f"[OK] part2_final.md exists  ({byte_size:,} bytes, {word_count:,} words)")

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
        "# Part 2",
        "## Analysis 2-6",
        "## Analysis 2-7",
        "## Analysis 2-8",
        "### Figure Description",
        "### Quantitative Findings",
        "### Biological Interpretation",
        "### Cross-Analysis Connections",
        "### References",
        "## Part 2 Summary",
    ]

    content_lower = content.lower()
    missing = []
    print("\nTemplate Sections:")
    for section in required_sections:
        found = section.lower() in content_lower
        print(f"  [{'OK' if found else 'MISS'}] {section}")
        if not found:
            missing.append(section)

    # 4. Part-2–specific: statistics evidence check
    stats_patterns = [
        (r"moran'?s?\s+[RI]\s*[=:]\s*\d+\.?\d*", "Moran's R/I values"),
        (r"p\s*[<>=]\s*\d+\.?\d*", "p-values"),
        (r"\d+\.?\d*-?fold", "fold changes"),
        (r"\d+\.?\d*%", "percentages"),
    ]
    print(f"\nStatistics Evidence:")
    for pattern, label in stats_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        mark = "OK" if len(matches) >= 2 else "LOW"
        print(f"  [{mark}] {label}: {len(matches)} found")

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
    part2_path = Path(DATA_DIR) / "part2_final.md"

    # Back up previous output if it exists
    if part2_path.exists():
        backup = part2_path.with_suffix(".md.bak")
        part2_path.rename(backup)
        print(f"Backed up existing part2_final.md -> {backup.name}")

    try:
        result = await run_part2_interpreter()

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
        if not part2_path.exists():
            print("\n[WARN] write_file not called by agent — extracting from response...")
            extracted = _extract_markdown_from_response(result)
            if extracted:
                part2_path.write_text(extracted, encoding="utf-8")
                print(f"[WARN] Saved extracted content ({len(extracted):,} chars) to {part2_path.name}")
            else:
                print("[ERR]  Could not extract markdown from agent response")

        return verify_output()

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

        # Restore backup if run failed and no new output was produced
        backup = part2_path.with_suffix(".md.bak")
        if backup.exists() and not part2_path.exists():
            backup.rename(part2_path)
            print("Restored backup of part2_final.md")
        raise


if __name__ == "__main__":
    result = asyncio.run(main())
