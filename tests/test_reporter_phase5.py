"""Focused test for REPORTER Phase 4.7 + Phase 5.

Resumes from existing synthesis.md and therapeutic_targets.json to:
1. Add Therapeutic Implications section to synthesis.md (Phase 4.7 Step 3-4)
2. Let deterministic finalizer create synthesis_targets.json when missing
3. Hand off CCI_Analysis_Report.html generation to code (Phase 5)

Prerequisites:
- res_bc/synthesis.md (written by REPORTER Phase 1-4.5)
- res_bc/therapeutic_targets.json (written by assess_therapeutic_potential)
- res_bc/part1_final.md, part2_final.md, part3_final.md
- res_bc/data_path.txt

Usage:
    python tests/test_reporter_phase5.py
    REPORTER_PROVIDER=openai python tests/test_reporter_phase5.py
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Literal, cast

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = str(PROJECT_ROOT / "res_bc")
os.environ["DEEP_INTERPRETER_DATA_DIR"] = DATA_DIR

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

Provider = Literal["openai", "google", "ollama", "ollama-openai", "vllm", "claude", "openrouter"]
PROVIDER = cast(Provider, os.getenv("REPORTER_PROVIDER", "openai"))

# Focused message: skip Phase 1-4.5, resume from Phase 4.7 Step 3
PHASE5_MESSAGE = {
    "messages": [
        {
            "role": "user",
            "content": (
                "You are the REPORTER subagent. Phases 1-4.5 are ALREADY DONE.\n"
                "Your task is to complete Phase 4.7 (Steps 3-4) and Phase 5 ONLY.\n\n"
                "## Already completed (DO NOT redo):\n"
                "- synthesis.md written (Phase 1-4.5)\n"
                "- synthesis_validation.json written\n"
                "- therapeutic_targets.json written by assess_therapeutic_potential\n\n"
                "## Your tasks:\n\n"
                "### Step 1: Read existing files\n"
                "1. read_file('/data_path.txt') → data directory\n"
                "2. read_file('/synthesis.md') → current synthesis\n"
                "3. read_file('/therapeutic_targets.json') → drug target results\n"
                "   (NOTE: this is at data_dir path, not virtual path)\n"
                "4. read_file('/part1_final.md'), read_file('/part2_final.md'), read_file('/part3_final.md')\n"
                "5. read_file('/interpretation_guide.md')\n"
                "6. load_analysis_data(data_dir=...) → figure paths\n\n"
                "### Step 2: Interpret therapeutic results (think_tool)\n"
                "Use think_tool to interpret the therapeutic_targets.json findings:\n"
                "- Which L-R genes are druggable?\n"
                "- Existing approved drugs?\n"
                "- Novel targets?\n"
                "- Safety concerns?\n\n"
                "### Step 3: Update synthesis.md with Therapeutic Implications\n"
                "Read the current synthesis.md content, APPEND a new section:\n"
                "### Therapeutic Implications\n"
                "#### Druggable Targets\n"
                "#### Existing Drugs\n"
                "#### Novel Opportunities\n"
                "#### Safety Considerations\n"
                "Then write_file('/synthesis.md', ...) with the COMPLETE updated content.\n\n"
                "### Step 4: Hand off source tracking to deterministic code\n"
                "Do not write /synthesis_targets.json manually. Deterministic code detects\n"
                "part4_therapeutic_synthesis.md, drug.md, and therapeutic_targets.json and\n"
                "creates synthesis_targets.json when it is missing.\n\n"
                "### Step 5: Hand Off to Deterministic Finalization (Phase 5)\n"
                "Confirm /synthesis.md is complete, then stop after synthesis.md.\n"
                "The deterministic finalizer runs validation, writes targets, and renders HTML.\n\n"
                "## CRITICAL RULES:\n"
                "- MUST call write_file('/synthesis.md', ...) with updated content\n"
                "- MUST NOT call the HTML report tool\n"
                "- Deterministic code creates synthesis_validation.json, synthesis_targets.json, and HTML when missing\n"
                "- Do NOT re-run literature search or assess_therapeutic_potential\n"
                "- Do NOT hand-author part1_html, part2_html, part3_html, summary_html, or therapeutic_html\n"
                "- Do NOT write HTML yourself\n\n"
                "Begin now."
            ),
        }
    ]
}


def test_phase5_message_delegates_bookkeeping_artifacts_to_report_tool():
    content = PHASE5_MESSAGE["messages"][0]["content"]

    assert "deterministic finalizer runs validation, writes targets, and renders HTML" in content
    assert "generate_html_report" not in content
    assert not re.search(r"write_file\(['\"]/synthesis_targets\.json", content)
    assert "therapeutic_html (LLM-generated HTML" not in content


async def run_reporter_phase5():
    from src.agents.deep_interpreter.graph_builder import create_subagent_graph

    print(f"Provider : {PROVIDER}")
    print(f"Data dir : {DATA_DIR}")

    graph = create_subagent_graph("reporter", provider=PROVIDER)

    print("\n" + "=" * 60)
    print("Invoking REPORTER (Phase 4.7+5 only)...")
    print("=" * 60 + "\n")

    result = await graph.ainvoke(PHASE5_MESSAGE)
    return result


def verify_output():
    data_dir = Path(DATA_DIR)
    synthesis_path = data_dir / "synthesis.md"
    html_path = data_dir / "CCI_Analysis_Report.html"
    synthesis_targets_path = data_dir / "synthesis_targets.json"

    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    issues = []

    # 1. synthesis.md — check for Therapeutic Implications
    print("\n--- synthesis.md (Therapeutic section) ---")
    if synthesis_path.exists():
        content = synthesis_path.read_text(encoding="utf-8")
        has_therapeutic = "therapeutic" in content.lower() and "druggable" in content.lower()
        print(f"[{'OK' if has_therapeutic else 'MISS'}] Therapeutic Implications section")
        if not has_therapeutic:
            issues.append("synthesis.md missing Therapeutic Implications")

        # Check key druggable genes from therapeutic_targets.json
        drug_genes = ["ITGB1", "EGFR", "KDR", "NOTCH1", "ERBB2"]
        found = [g for g in drug_genes if g in content]
        print(f"  Druggable genes in synthesis: {len(found)}/{len(drug_genes)} {found}")
    else:
        print("[FAIL] synthesis.md not found")
        issues.append("synthesis.md not found")

    # 2. synthesis_targets.json
    print("\n--- synthesis_targets.json ---")
    if synthesis_targets_path.exists():
        try:
            targets = json.loads(synthesis_targets_path.read_text(encoding="utf-8"))
            summary = targets.get("summary", {}) if isinstance(targets, dict) else {}
            print(f"[OK] synthesis_targets.json exists  "
                  f"(genes: {summary.get('total_genes_evaluated', '?')}, "
                  f"druggable: {summary.get('druggable_count', '?')})")
        except json.JSONDecodeError as e:
            print(f"[WARN] Parse error: {e}")
            issues.append("synthesis_targets.json invalid JSON")
    else:
        print("[FAIL] synthesis_targets.json NOT FOUND")
        issues.append("synthesis_targets.json not found")

    # 3. CCI_Analysis_Report.html
    print("\n--- CCI_Analysis_Report.html ---")
    if html_path.exists():
        html_size = html_path.stat().st_size
        html_content = html_path.read_text(encoding="utf-8")
        has_therapeutic_tab = "therapeutic" in html_content.lower()
        print(f"[OK] CCI_Analysis_Report.html exists  ({html_size:,} bytes)")
        print(f"[{'OK' if has_therapeutic_tab else 'MISS'}] Therapeutic tab content")
        if not has_therapeutic_tab:
            issues.append("HTML missing therapeutic tab content")
    else:
        print("[FAIL] CCI_Analysis_Report.html NOT FOUND")
        issues.append("CCI_Analysis_Report.html not found")

    # Summary
    all_pass = not issues
    print(f"\n{'=' * 60}")
    if all_pass:
        print("RESULT: PASS")
    else:
        print(f"RESULT: FAIL ({len(issues)} issues)")
        for issue in issues:
            print(f"  - {issue}")
    print("=" * 60)

    return {"all_pass": all_pass, "issues": issues}


async def main():
    try:
        result = await run_reporter_phase5()

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

        return verify_output()

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    result = asyncio.run(main())
