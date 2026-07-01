"""Integration test for REPORTER subagent.

Runs the REPORTER subagent standalone against configured analysis data
and validates synthesis.md + CCI_Analysis_Report.html output.

Prerequisites:
- analysis directory with all analysis files
- part1_final.md, part2_final.md, part3_final.md (written by INTERPRETER)
- interpretation_guide.md (written by PLANNER)
- data_path.txt (written by PLANNER)
- papers.json (written by SEARCHER)

Usage:
    python tests/test_reporter.py
    DEEP_INTERPRETER_DATA_DIR=/path/to/final_bc python tests/test_reporter.py
    REPORTER_PROVIDER=openai python tests/test_reporter.py   # override provider
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set data directory BEFORE any project imports
DATA_DIR = os.getenv("DEEP_INTERPRETER_DATA_DIR", str(PROJECT_ROOT / "res_bc"))
os.environ["DEEP_INTERPRETER_DATA_DIR"] = DATA_DIR

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


# ── Provider selection ────────────────────────────────────────────────────────
# Use openai (gpt-4.1-mini) by default for REPORTER — needs structured output.
# Override: REPORTER_PROVIDER=openrouter python tests/test_reporter.py
PROVIDER = os.getenv("REPORTER_PROVIDER", "openai")


# ── REPORTER invocation message ──────────────────────────────────────────────
REPORTER_MESSAGE = {
    "messages": [
        {
            "role": "user",
            "content": (
                "You are the REPORTER subagent. Your task is to synthesize findings "
                "from Part 1, 2, and 3 and generate the final report.\n\n"
                "## Your Workflow (Phase 1-5)\n\n"
                "### Phase 1: Read All Inputs\n"
                "1. read_file('/data_path.txt') to get data directory\n"
                "2. read_file('/part1_final.md') — Part 1 interpretation\n"
                "3. read_file('/part2_final.md') — Part 2 interpretation\n"
                "4. read_file('/part3_final.md') — Part 3 interpretation\n"
                "5. read_file('/interpretation_guide.md') — focus areas\n"
                "6. read_file('/papers.json') — Literature references (all Parts)\n"
                "8. load_analysis_data(data_dir=...) — figure paths\n\n"
                "### Phase 2-4: Cross-Part Synthesis\n"
                "- Identify 4+ cross-part themes connecting Part 1, 2, and 3\n"
                "- Theme 1: Spatial Organization\n"
                "- Theme 2: Cell Communication Axis\n"
                "- Theme 3: Pathway Integration\n"
                "- Theme 4: Disease Mechanism\n"
                "- Identify emergent themes\n"
                "- **write_file('/synthesis.md', content=...)** — MUST call this\n\n"
                "### Phase 4.5: Validate Synthesis with Literature\n"
                "1. Extract synthesis context (genes, pathways, celltypes from themes)\n"
                "2. Strategic planning with think_tool (3 thoughts)\n"
                "3. search_literature_dynamic with integration-focused terms, output_path='synthesis_papers.json'\n"
                "4. Quality reflection (think_tool)\n"
                "5. Validate claims and write:\n"
                "   - Update /synthesis.md with validated claims\n"
                "   - write_file('/synthesis_validation.json', ...) — validation results\n\n"
                "### Phase 4.7: Part 4 Therapeutic Synthesis\n"
                "1. read_file('/part4_therapeutic_synthesis.md') as the canonical Part 4 narrative\n"
                "2. read_file('/drug.md') only as supporting therapeutic assessment detail\n"
                "3. Add a concise Therapeutic Implications section to /synthesis.md\n"
                "4. write_file('/synthesis_targets.json', ...) with canonical/supporting source tracking\n\n"
                "### Phase 5: Generate HTML Report\n"
                "Call generate_html_report with parts dict containing:\n"
                "- template_mode='comprehensive'\n"
                "- analysis_config, quality_score, references\n"
                "- output_path='CCI_Analysis_Report.html'\n"
                "- data_dir from /data_path.txt\n\n"
                "## CRITICAL RULES:\n"
                "- You MUST call write_file to save /synthesis.md\n"
                "- You MUST call write_file to save /synthesis_validation.json\n"
                "- You MUST call write_file to save /synthesis_targets.json\n"
                "- You MUST call generate_html_report to create the HTML report\n"
                "- Do NOT generate part1_html/part2_html/part3_html/summary_html/therapeutic_html; use template_mode='comprehensive'\n"
                "- Do NOT just output text — all outputs must be persisted to disk\n"
                "- synthesis.md MUST include: Executive Summary, Cross-Part Themes 1-4, "
                "Emergent Themes, Limitations\n\n"
                "Begin now."
            ),
        }
    ]
}


# ── Runner ────────────────────────────────────────────────────────────────────


async def run_reporter():
    """Run REPORTER subagent and return the final state."""
    from src.agents.deep_interpreter.graph_builder import create_subagent_graph

    print(f"Provider : {PROVIDER}")
    print(f"Data dir : {DATA_DIR}")

    # create_subagent_graph already applies recursion_limit=200
    graph = create_subagent_graph("reporter", provider=PROVIDER)

    print("\n" + "=" * 60)
    print("Invoking REPORTER subagent...")
    print("=" * 60 + "\n")

    result = await graph.ainvoke(REPORTER_MESSAGE)
    return result


def _extract_synthesis_from_response(result: dict) -> str | None:
    """Extract synthesis.md content from agent's last message as fallback.

    Some models generate the synthesis inline instead of calling write_file.
    This extracts that content so we can still validate and persist it.
    """
    if not result or "messages" not in result:
        return None

    for msg in reversed(result["messages"]):
        text = getattr(msg, "content", None)
        if isinstance(text, list):
            for part in text:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part["text"]
                    break
            else:
                continue
        if not isinstance(text, str):
            continue

        # Look for synthesis markdown (must have Executive Summary + themes)
        if "Executive Summary" in text and "Cross-Part" in text:
            match = re.search(r"(# Integrated Biological Narrative.*)", text, re.DOTALL)
            if match:
                return match.group(1).strip()

    return None


# ── Verification ──────────────────────────────────────────────────────────────


def verify_output():
    """Verify REPORTER output exists and meets quality criteria.

    Returns:
        dict with quality checks and pass/fail status
    """
    data_dir = Path(DATA_DIR)
    synthesis_path = data_dir / "synthesis.md"
    html_path = data_dir / "CCI_Analysis_Report.html"
    synthesis_papers_path = data_dir / "synthesis_papers.json"
    synthesis_validation_path = data_dir / "synthesis_validation.json"
    synthesis_targets_path = data_dir / "synthesis_targets.json"

    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    issues = []

    # ── 1. synthesis.md ──────────────────────────────────────────────────
    print("\n--- synthesis.md ---")
    if synthesis_path.exists():
        content = synthesis_path.read_text(encoding="utf-8")
        byte_size = synthesis_path.stat().st_size
        word_count = len(content.split())
        print(f"[OK] synthesis.md exists  ({byte_size:,} bytes, {word_count:,} words)")

        # Required sections
        required_sections = [
            "Executive Summary",
            "Cross-Part Theme",  # partial match for "Cross-Part Themes" or "Cross-Part Theme 1"
            "Theme 1",
            "Theme 2",
            "Theme 3",
            "Theme 4",
            "Emergent Theme",
            "Limitation",
        ]
        content_lower = content.lower()
        missing_sections = []
        for section in required_sections:
            found = section.lower() in content_lower
            print(f"  [{'OK' if found else 'MISS'}] {section}")
            if not found:
                missing_sections.append(section)

        if missing_sections:
            issues.append(f"synthesis.md missing sections: {missing_sections}")

        # Check for new L-R pairs from Part 2/3
        lr_keywords = ["EGFR", "ERBB3", "VEGFA", "FLT1", "TGFB1", "LAMA5", "SDC1", "EFNB2"]
        lr_found = [kw for kw in lr_keywords if kw in content]
        lr_missing = [kw for kw in lr_keywords if kw not in content]
        print(f"\n  L-R pairs reflected: {len(lr_found)}/{len(lr_keywords)}")
        for kw in lr_found:
            print(f"    [OK] {kw}")
        for kw in lr_missing:
            print(f"    [MISS] {kw}")

        if len(lr_found) < 3:
            issues.append(f"synthesis.md reflects too few L-R pairs ({len(lr_found)}/8)")

    else:
        print("[FAIL] synthesis.md NOT FOUND")
        issues.append("synthesis.md not found")
        content = ""

    # ── 2. CCI_Analysis_Report.html ──────────────────────────────────────
    print("\n--- CCI_Analysis_Report.html ---")
    if html_path.exists():
        html_size = html_path.stat().st_size
        print(f"[OK] CCI_Analysis_Report.html exists  ({html_size:,} bytes)")

        # Basic HTML structure check
        html_content = html_path.read_text(encoding="utf-8")
        html_checks = {
            "DOCTYPE": "<!DOCTYPE html" in html_content or "<!doctype html" in html_content.lower(),
            "<html": "<html" in html_content.lower(),
            "Part 1 tab": "part1" in html_content.lower(),
            "Part 2 tab": "part2" in html_content.lower(),
            "Part 3 tab": "part3" in html_content.lower(),
            "Summary tab": "summary" in html_content.lower(),
        }
        for check_name, passed in html_checks.items():
            print(f"  [{'OK' if passed else 'MISS'}] {check_name}")
            if not passed:
                issues.append(f"HTML missing: {check_name}")

        density_checks = {
            ">=10 embedded images": html_content.count("<img ") >= 10,
            ">=5 tables": html_content.count("<table") >= 5,
            "Part 4/Therapeutic source": "part4_therapeutic_synthesis.md" in html_content
            or "Therapeutic Implications" in html_content,
        }
        for check_name, passed in density_checks.items():
            print(f"  [{'OK' if passed else 'MISS'}] {check_name}")
            if not passed:
                issues.append(f"HTML density missing: {check_name}")
    else:
        print("[FAIL] CCI_Analysis_Report.html NOT FOUND")
        issues.append("CCI_Analysis_Report.html not found")

    # ── 3. synthesis_papers.json ─────────────────────────────────────────
    print("\n--- synthesis_papers.json ---")
    if synthesis_papers_path.exists():
        try:
            papers_data = json.loads(synthesis_papers_path.read_text(encoding="utf-8"))
            if isinstance(papers_data, list):
                paper_count = len(papers_data)
            elif isinstance(papers_data, dict):
                paper_count = len(papers_data.get("papers", papers_data.get("results", [])))
            else:
                paper_count = 0
            print(f"[OK] synthesis_papers.json exists  ({paper_count} papers)")
        except json.JSONDecodeError as e:
            print(f"[WARN] synthesis_papers.json parse error: {e}")
            issues.append("synthesis_papers.json invalid JSON")
    else:
        print("[WARN] synthesis_papers.json not found (Phase 4.5 may have been skipped)")
        # Not a hard failure — search may fail due to API limits

    # ── 4. synthesis_validation.json ─────────────────────────────────────
    print("\n--- synthesis_validation.json ---")
    if synthesis_validation_path.exists():
        try:
            val_data = json.loads(synthesis_validation_path.read_text(encoding="utf-8"))
            claims_count = val_data.get("claims_validated", 0) if isinstance(val_data, dict) else 0
            confidence = val_data.get("overall_confidence", 0) if isinstance(val_data, dict) else 0
            print(f"[OK] synthesis_validation.json exists  "
                  f"(claims: {claims_count}, confidence: {confidence})")
        except json.JSONDecodeError as e:
            print(f"[WARN] synthesis_validation.json parse error: {e}")
            issues.append("synthesis_validation.json invalid JSON")
    else:
        print("[WARN] synthesis_validation.json not found")
        # Soft warning — validation may fail due to RAG unavailability

    # ── 5. synthesis_targets.json ────────────────────────────────────────
    print("\n--- synthesis_targets.json ---")
    if synthesis_targets_path.exists():
        try:
            targets_data = json.loads(synthesis_targets_path.read_text(encoding="utf-8"))
            if isinstance(targets_data, dict):
                summary = targets_data.get("summary", {})
                print(f"[OK] synthesis_targets.json exists  "
                      f"(genes: {summary.get('total_genes_evaluated', '?')}, "
                      f"druggable: {summary.get('druggable_count', '?')})")
                canonical = targets_data.get("canonical_source")
                supporting = targets_data.get("supporting_source")
                print(f"  canonical_source: {canonical}")
                print(f"  supporting_source: {supporting}")
                if canonical != "part4_therapeutic_synthesis.md":
                    issues.append(
                        "synthesis_targets.json canonical_source is not "
                        "part4_therapeutic_synthesis.md"
                    )
                if supporting not in {"drug.md", None}:
                    issues.append(
                        "synthesis_targets.json supporting_source should be drug.md or null"
                    )
            else:
                print(f"[OK] synthesis_targets.json exists")
        except json.JSONDecodeError as e:
            print(f"[WARN] synthesis_targets.json parse error: {e}")
            issues.append("synthesis_targets.json invalid JSON")
    else:
        print("[WARN] synthesis_targets.json not found (Phase 4.7 may have failed)")
        # Soft warning — OpenTargets API may be unavailable

    # ── Summary ──────────────────────────────────────────────────────────
    # Hard requirements: synthesis.md + HTML report
    hard_pass = synthesis_path.exists() and html_path.exists()
    # Soft requirements: papers, validation, targets
    soft_pass = synthesis_papers_path.exists() and synthesis_validation_path.exists()

    print(f"\n{'=' * 60}")
    if hard_pass and not issues:
        print("RESULT: PASS (all checks passed)")
    elif hard_pass:
        print(f"RESULT: PARTIAL PASS (hard requirements met, {len(issues)} issues)")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print(f"RESULT: FAIL ({len(issues)} issues)")
        for issue in issues:
            print(f"  - {issue}")
    print("=" * 60)

    return {
        "hard_pass": hard_pass,
        "soft_pass": soft_pass,
        "issues": issues,
        "synthesis_exists": synthesis_path.exists(),
        "html_exists": html_path.exists(),
        "papers_exists": synthesis_papers_path.exists(),
        "validation_exists": synthesis_validation_path.exists(),
        "targets_exists": synthesis_targets_path.exists(),
    }


# ── Main ──────────────────────────────────────────────────────────────────────


async def main():
    data_dir = Path(DATA_DIR)
    synthesis_path = data_dir / "synthesis.md"
    html_path = data_dir / "CCI_Analysis_Report.html"
    output_paths = [
        synthesis_path,
        html_path,
        data_dir / "synthesis_papers.json",
        data_dir / "synthesis_validation.json",
        data_dir / "synthesis_targets.json",
    ]

    # Back up previous outputs if they exist
    for path in output_paths:
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            path.rename(backup)
            print(f"Backed up existing {path.name} -> {backup.name}")

    try:
        result = await run_reporter()

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

        # Fallback: if agent didn't call write_file for synthesis, extract from response
        if not synthesis_path.exists():
            print("\n[WARN] write_file not called for synthesis.md — extracting from response...")
            extracted = _extract_synthesis_from_response(result)
            if extracted:
                synthesis_path.write_text(extracted, encoding="utf-8")
                print(f"[WARN] Saved extracted content ({len(extracted):,} chars) to synthesis.md")
            else:
                print("[ERR]  Could not extract synthesis from agent response")

        return verify_output()

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

        # Restore backups if run failed and no new output was produced
        for path in output_paths:
            backup = path.with_suffix(path.suffix + ".bak")
            if backup.exists() and not path.exists():
                backup.rename(path)
                print(f"Restored backup of {path.name}")
        raise


if __name__ == "__main__":
    result = asyncio.run(main())
