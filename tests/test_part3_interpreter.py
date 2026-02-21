"""Integration test for Part 3 INTERPRETER subagent.

Runs the INTERPRETER subagent standalone against res_bc data
and validates Part 3 output quality.

Prerequisites:
- res_bc/ directory with all analysis files
- liana_papers.json (searched by SEARCHER)
- interpretation_guide.md (written by PLANNER)
- data_path.txt (written by PLANNER)

Usage:
    python tests/test_part3_interpreter.py
    PART3_PROVIDER=openai python tests/test_part3_interpreter.py   # override provider
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
# Use openrouter (kimi-k2.5) by default — gpt-4.1-mini often skips write_file.
# Override: PART3_PROVIDER=openai python tests/test_part3_interpreter.py
PROVIDER = os.getenv("PART3_PROVIDER", "openrouter")


# ── Part 3 invocation message ────────────────────────────────────────────────
PART3_MESSAGE = {
    "messages": [
        {
            "role": "user",
            "content": (
                "You are the INTERPRETER subagent. Your task is to interpret **Part 3 ONLY**.\n\n"
                "## Part 3: L-R Interaction Details\n\n"
                "Required analyses:\n"
                "- 3-9 NMF Quadrant with GenePT\n"
                "- 3-10 Spatial L-R Visualization\n"
                "- 3-11 L-R Interaction Summary\n\n"
                "Input files:\n"
                "- /liana_papers.json (shared with Part 2)\n"
                "- /interpretation_guide.md\n"
                "- /data_path.txt\n\n"
                "Output: **/part3_final.md** (MUST be written via write_file tool)\n\n"
                "## MANDATORY WORKFLOW:\n"
                "1. read_file('/data_path.txt') to get data directory\n"
                "2. read_file('/interpretation_guide.md') for context\n"
                "3. read_file('/liana_papers.json') to load citation source\n"
                "4. load_analysis_data(data_dir=...) to get Part 3 analysis data\n"
                "5. prioritize_top_lr_pairs(data_dir=...) to get candidate L-R pairs\n"
                "6. Select top 3 most interesting L-R pairs and document selection reasoning\n"
                "7. Write detailed interpretation for ALL 3 analyses (3-9, 3-10, 3-11)\n"
                "8. validate_quality(interpretation=...) — target score >= 0.8\n"
                "9. **write_file(file_path='/part3_final.md', content=...)** to save output\n\n"
                "## CRITICAL RULE:\n"
                "You MUST call the **write_file** tool to save /part3_final.md.\n"
                "Do NOT just output the interpretation as text — it must be persisted to disk.\n\n"
                "Begin now."
            ),
        }
    ]
}


# ── Runner ────────────────────────────────────────────────────────────────────


async def run_part3_interpreter():
    """Run Part 3 interpreter subagent and return the final state."""
    from src.agents.deep_interpreter.graph_builder import create_subagent_graph

    print(f"Provider : {PROVIDER}")
    print(f"Data dir : {DATA_DIR}")

    # create_subagent_graph already applies recursion_limit=200
    graph = create_subagent_graph("interpreter", provider=PROVIDER)

    print("\n" + "=" * 60)
    print("Invoking Part 3 INTERPRETER subagent...")
    print("=" * 60 + "\n")

    result = await graph.ainvoke(PART3_MESSAGE)
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

        # Look for Part 3 markdown content (must have the heading + analysis sections)
        if "# Part 3" in text and ("## Analysis 3-9" in text or "## Analysis 3-10" in text):
            # Extract from the first heading to end
            match = re.search(r"(# Part 3.*)", text, re.DOTALL)
            if match:
                return match.group(1).strip()

    return None


# ── Verification ──────────────────────────────────────────────────────────────


def verify_output():
    """Verify Part 3 output exists and meets quality criteria.

    Returns:
        dict with quality scores and pass/fail status
    """
    from src.agents.deep_interpreter.tools.quality import _calculate_basic_score

    part3_path = Path(DATA_DIR) / "part3_final.md"

    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # 1. File existence
    assert part3_path.exists(), f"part3_final.md not found at {part3_path}"
    content = part3_path.read_text()
    byte_size = part3_path.stat().st_size
    word_count = len(content.split())
    print(f"[OK] part3_final.md exists  ({byte_size:,} bytes, {word_count:,} words)")

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
        "# Part 3",
        "## Analysis 3-9",
        "## Analysis 3-10",
        "## Analysis 3-11",
        "### Figure Description",
        "### Quantitative Findings",
        "### Biological Interpretation",
        "### References",
        "## Part 3 Summary",
    ]

    content_lower = content.lower()
    missing = []
    print("\nTemplate Sections:")
    for section in required_sections:
        found = section.lower() in content_lower
        print(f"  [{'OK' if found else 'MISS'}] {section}")
        if not found:
            missing.append(section)

    # 4. Part-3–specific: L-R pair selection evidence
    lr_keywords = ["prioritize_top_lr_pairs", "selected", "top 3",
                   "candidate", "selection criteria", "novel"]
    has_lr_evidence = any(kw in content_lower for kw in lr_keywords)
    print(f"\n[{'OK' if has_lr_evidence else 'MISS'}] L-R pair selection documented")

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
    part3_path = Path(DATA_DIR) / "part3_final.md"

    # Back up previous output if it exists
    if part3_path.exists():
        backup = part3_path.with_suffix(".md.bak")
        part3_path.rename(backup)
        print(f"Backed up existing part3_final.md -> {backup.name}")

    try:
        result = await run_part3_interpreter()

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
        if not part3_path.exists():
            print("\n[WARN] write_file not called by agent — extracting from response...")
            extracted = _extract_markdown_from_response(result)
            if extracted:
                part3_path.write_text(extracted, encoding="utf-8")
                print(f"[WARN] Saved extracted content ({len(extracted):,} chars) to {part3_path.name}")
            else:
                print("[ERR]  Could not extract markdown from agent response")

        return verify_output()

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

        # Restore backup if run failed and no new output was produced
        backup = part3_path.with_suffix(".md.bak")
        if backup.exists() and not part3_path.exists():
            backup.rename(part3_path)
            print("Restored backup of part3_final.md")
        raise


if __name__ == "__main__":
    result = asyncio.run(main())
