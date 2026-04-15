#!/usr/bin/env python3
"""Drug-target run diagnostics.

Parses a single trace log (produced by `scripts/run_drug_target_traced.py`)
plus the matching data directory and reports whether the run exhibits any
of the failure modes documented in
`~/.claude/plans/iterative-painting-parrot.md`:

    1. Subagent entry/exit timeline (was hypothesis_writer even reached?).
    2. sequential_thinking call counts and thoughtNumber stagnation
       (the degenerate loop that killed the qwen1 run).
    3. save_evidence calls and which mandatory artifacts are missing
       (hypothesis_report.json, target_assessment.json, assessment_results.json).
    4. drug.md EXPAND placeholder leftover scan.
    5. evidence_references vs real files in evidence/ diff — the
       hallucinated-filename failure mode observed in qwen2/qwen3.

The script is read-only: it emits a Markdown report to stdout (or
``--output <path>``) and never mutates any file. Intended to give a
one-minute root-cause readout without needing to spelunk a 2 MB trace.

Usage:
    python scripts/diagnose_drug_target_run.py \
        --data-dir res_ipf_qwen \
        --trace res_ipf_qwen/trace_20260412_185215.log
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Subagent names expected in the Drug Target pipeline trace.
SUBAGENTS = [
    "evidence_assessor",
    "deep_diver",
    "hypothesis_writer",
    "report_writer",
]

# Mandatory evidence artifacts whose absence means the pipeline failed.
REQUIRED_ARTIFACTS = [
    "assessment_results.json",
    "rubric_scores.csv",
    "hypothesis_report.json",
]

# Root-level files (not inside evidence/).
REQUIRED_ROOT_FILES = [
    "target_assessment.json",
    "drug.md",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--data-dir",
        required=True,
        type=Path,
        help="Run directory (contains drug.md, evidence/, trace_*.log).",
    )
    p.add_argument(
        "--trace",
        type=Path,
        default=None,
        help="Path to the trace_*.log file. If omitted, the most recent "
        "trace_*.log under --data-dir is used.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the report to this Markdown file instead of stdout.",
    )
    return p.parse_args()


def _resolve_trace(data_dir: Path, trace: Path | None) -> Path:
    if trace is not None:
        return trace
    candidates = sorted(
        data_dir.glob("trace_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(
            f"ERROR: no trace_*.log found under {data_dir}. Pass --trace explicitly."
        )
    return candidates[0]


# ---------------------------------------------------------------------------
# Trace log parsing
# ---------------------------------------------------------------------------

_NODE_LINE_RE = re.compile(
    r"^\[\s*(?P<elapsed>[\d.]+)s\]\s+#\d+\s+\[(?P<path>[^\]]+)\]\s+Node:\s*(?P<node>\S+)"
)
_TOOL_CALL_RE = re.compile(r"tool_calls=\[(?P<names>[^\]]*)\]")
_THOUGHT_NUMBER_RE = re.compile(r'"?thoughtNumber"?\s*[:=]\s*(\d+)')
_THOUGHT_HISTORY_RE = re.compile(r'"?thoughtHistoryLength"?\s*[:=]\s*(\d+)')


def parse_trace(trace_path: Path) -> dict[str, Any]:
    """Walk the trace log and extract subagent/tool statistics."""
    subagent_events: dict[str, dict[str, float]] = {}
    tool_counts: dict[str, int] = {}
    sequential_thinking_hits: list[tuple[float, int]] = []
    thought_history_max = 0
    fixup_markers: list[str] = []
    current_subagent: str | None = None
    seq_thinking_count = 0

    with trace_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")

            # Detect subagent boundary via node_path containing a subagent name.
            m_node = _NODE_LINE_RE.search(line)
            if m_node:
                elapsed = float(m_node.group("elapsed"))
                path = m_node.group("path")
                for sub in SUBAGENTS:
                    if sub in path:
                        ev = subagent_events.setdefault(
                            sub, {"first_seen": elapsed, "last_seen": elapsed}
                        )
                        ev["last_seen"] = elapsed
                        current_subagent = sub
                        break

            # Tool call names (from _format_update_summary output).
            for m_tool in _TOOL_CALL_RE.finditer(line):
                names = [n.strip().strip('"').strip("'") for n in m_tool.group("names").split(",")]
                for n in names:
                    if not n:
                        continue
                    tool_counts[n] = tool_counts.get(n, 0) + 1
                    if n == "sequential_thinking":
                        seq_thinking_count += 1

            # Thought number traces (emitted inside the tool result payload).
            m_tn = _THOUGHT_NUMBER_RE.search(line)
            if m_tn:
                try:
                    tn = int(m_tn.group(1))
                    m_node_ts = _NODE_LINE_RE.search(line)
                    ts = float(m_node_ts.group("elapsed")) if m_node_ts else 0.0
                    sequential_thinking_hits.append((ts, tn))
                except ValueError:
                    pass
            m_th = _THOUGHT_HISTORY_RE.search(line)
            if m_th:
                try:
                    thought_history_max = max(thought_history_max, int(m_th.group(1)))
                except ValueError:
                    pass

            if "STAGE1-FIXUP" in line:
                fixup_markers.append(line.strip())
            if "HYPOTHESIS-FIXUP" in line:
                fixup_markers.append(line.strip())
            if "degenerate_loop_detected" in line:
                fixup_markers.append(line.strip())

    # Analyze stagnation: how long is the longest run of repeated thoughtNumber?
    longest_stagnation = 0
    current_n = None
    current_run = 0
    for _, tn in sequential_thinking_hits:
        if tn == current_n:
            current_run += 1
        else:
            current_n = tn
            current_run = 1
        longest_stagnation = max(longest_stagnation, current_run)

    return {
        "trace_path": str(trace_path),
        "subagent_events": subagent_events,
        "tool_counts": tool_counts,
        "sequential_thinking_calls": seq_thinking_count,
        "thought_number_samples": len(sequential_thinking_hits),
        "longest_thought_stagnation": longest_stagnation,
        "thought_history_max": thought_history_max,
        "fixup_markers": fixup_markers,
    }


# ---------------------------------------------------------------------------
# Artifact + drug.md checks
# ---------------------------------------------------------------------------


def audit_artifacts(data_dir: Path) -> dict[str, Any]:
    evidence_dir = data_dir / "evidence"
    present_in_evidence: set[str] = set()
    if evidence_dir.exists():
        present_in_evidence = {p.name for p in evidence_dir.iterdir() if p.is_file()}

    missing_required = [
        name for name in REQUIRED_ARTIFACTS if name not in present_in_evidence
    ]
    missing_root = [
        name for name in REQUIRED_ROOT_FILES if not (data_dir / name).exists()
    ]
    return {
        "evidence_dir_exists": evidence_dir.exists(),
        "evidence_file_count": len(present_in_evidence),
        "missing_required": missing_required,
        "missing_root_files": missing_root,
        "stage1_pair_files": sorted(
            f for f in present_in_evidence if f.startswith("stage1_") and "--" in f
        ),
        "ot_gene_files": sorted(f for f in present_in_evidence if f.startswith("ot_")),
        "stage3_gene_files": sorted(f for f in present_in_evidence if f.startswith("stage3_")),
    }


def scan_drug_md(data_dir: Path) -> dict[str, Any]:
    drug_md_path = data_dir / "drug.md"
    if not drug_md_path.exists():
        return {"exists": False}
    text = drug_md_path.read_text(errors="replace")
    expand_markers = re.findall(r"<!--\s*EXPAND:([^>]*?)-->", text)
    hypothesis_section_present = bool(
        re.search(r"^##\s+4\.\s*Hypothesis", text, re.MULTILINE)
    )
    hypothesis_placeholder = "No hypothesis analysis available" in text
    return {
        "exists": True,
        "char_count": len(text),
        "line_count": text.count("\n") + 1,
        "unexpanded_placeholder_count": len(expand_markers),
        "unexpanded_samples": [m.strip()[:120] for m in expand_markers[:3]],
        "hypothesis_section_present": hypothesis_section_present,
        "hypothesis_section_empty": hypothesis_placeholder,
    }


def scan_hypothesis_refs(data_dir: Path) -> dict[str, Any]:
    evidence_dir = data_dir / "evidence"
    hyp_path = evidence_dir / "hypothesis_report.json"
    if not hyp_path.exists():
        return {"hypothesis_report_exists": False}

    try:
        hyp = json.loads(hyp_path.read_text())
    except Exception as exc:
        return {"hypothesis_report_exists": True, "parse_error": str(exc)}

    real = {p.name for p in evidence_dir.iterdir() if p.is_file()}
    cited: set[str] = set()
    for h in hyp.get("hypotheses", []):
        for ref in h.get("evidence_references", []):
            if not isinstance(ref, str):
                continue
            m = re.search(r"([A-Za-z0-9_.\-]+\.json)", ref)
            if m:
                cited.add(m.group(1))

    missing = sorted(cited - real)
    return {
        "hypothesis_report_exists": True,
        "hypothesis_count": len(hyp.get("hypotheses", [])),
        "cited_reference_count": len(cited),
        "missing_references": missing,
        "missing_reference_count": len(missing),
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_markdown(
    data_dir: Path,
    trace_stats: dict[str, Any],
    artifacts: dict[str, Any],
    drug_md: dict[str, Any],
    refs: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append(f"# Drug Target Run Diagnostic — `{data_dir}`\n")
    lines.append(f"Trace: `{trace_stats['trace_path']}`\n")

    # 1. Subagent timeline
    lines.append("## 1. Subagent timeline")
    if not trace_stats["subagent_events"]:
        lines.append("- NO subagent node transitions detected. Orchestrator never delegated.")
    else:
        for sub in SUBAGENTS:
            ev = trace_stats["subagent_events"].get(sub)
            if ev is None:
                lines.append(f"- **{sub}**: NEVER ENTERED")
            else:
                duration = ev["last_seen"] - ev["first_seen"]
                lines.append(
                    f"- **{sub}**: first={ev['first_seen']:.1f}s  "
                    f"last={ev['last_seen']:.1f}s  "
                    f"window={duration:.1f}s"
                )
    lines.append("")

    # 2. sequential_thinking stats
    lines.append("## 2. sequential_thinking usage")
    st_count = trace_stats["sequential_thinking_calls"]
    stagnation = trace_stats["longest_thought_stagnation"]
    hist_max = trace_stats["thought_history_max"]
    lines.append(f"- Total sequential_thinking tool calls: **{st_count}**")
    lines.append(f"- Thought-number samples inspected: {trace_stats['thought_number_samples']}")
    lines.append(f"- Longest run of repeated thoughtNumber: **{stagnation}**")
    lines.append(f"- Max observed thoughtHistoryLength: **{hist_max}**")
    if stagnation >= 3 or hist_max > 30:
        lines.append(
            "- **DEGENERATE LOOP SIGNATURE** — ≥3 consecutive identical "
            "thoughtNumber or history > 30. This matches the qwen1 failure "
            "mode. The new sequential_thinking guard should block this now."
        )
    else:
        lines.append("- No degenerate-loop signature detected.")
    lines.append("")

    # 3. Tool call histogram
    lines.append("## 3. Tool call histogram")
    if not trace_stats["tool_counts"]:
        lines.append("- No tool calls observed.")
    else:
        for name, count in sorted(trace_stats["tool_counts"].items(), key=lambda x: -x[1]):
            lines.append(f"- `{name}`: {count}")
    lines.append("")

    # 4. Fixup markers
    lines.append("## 4. Fixup / guard markers in trace")
    if trace_stats["fixup_markers"]:
        for m in trace_stats["fixup_markers"][:20]:
            lines.append(f"- `{m}`")
        if len(trace_stats["fixup_markers"]) > 20:
            lines.append(f"- ... {len(trace_stats['fixup_markers']) - 20} more")
    else:
        lines.append("- None.")
    lines.append("")

    # 5. Required artifacts
    lines.append("## 5. Required artifacts")
    lines.append(f"- `evidence/` exists: {artifacts['evidence_dir_exists']}")
    lines.append(f"- Files in `evidence/`: {artifacts['evidence_file_count']}")
    lines.append(f"- Stage 1 pair files: {len(artifacts['stage1_pair_files'])}")
    lines.append(f"- OpenTargets per-gene files: {len(artifacts['ot_gene_files'])}")
    lines.append(f"- Stage 3 per-gene files: {len(artifacts['stage3_gene_files'])}")
    if artifacts["missing_required"]:
        lines.append(
            f"- **MISSING REQUIRED**: {', '.join(artifacts['missing_required'])}"
        )
    if artifacts["missing_root_files"]:
        lines.append(
            f"- **MISSING ROOT**: {', '.join(artifacts['missing_root_files'])}"
        )
    if not artifacts["missing_required"] and not artifacts["missing_root_files"]:
        lines.append("- All required artifacts present.")
    lines.append("")

    # 6. drug.md placeholder scan
    lines.append("## 6. drug.md scan")
    if not drug_md["exists"]:
        lines.append("- **drug.md missing**")
    else:
        lines.append(f"- Characters: {drug_md['char_count']:,}")
        lines.append(f"- Lines: {drug_md['line_count']:,}")
        lines.append(
            f"- Hypothesis section present: {drug_md['hypothesis_section_present']}"
        )
        if drug_md["hypothesis_section_empty"]:
            lines.append(
                "- **Hypothesis section is a placeholder** — "
                "hypothesis_writer failed to save hypothesis_report.json."
            )
        if drug_md["unexpanded_placeholder_count"]:
            lines.append(
                f"- **UNEXPANDED EXPAND markers: "
                f"{drug_md['unexpanded_placeholder_count']}** "
                "— report_writer skipped Phase 2 expand."
            )
            for sample in drug_md["unexpanded_samples"]:
                lines.append(f"  - {sample}")
        else:
            lines.append("- No unexpanded EXPAND markers.")
    lines.append("")

    # 7. evidence_references diff
    lines.append("## 7. hypothesis_report.json evidence_references")
    if not refs.get("hypothesis_report_exists"):
        lines.append("- hypothesis_report.json missing — cannot check references.")
    elif "parse_error" in refs:
        lines.append(f"- Parse error: {refs['parse_error']}")
    else:
        lines.append(f"- Hypotheses: {refs['hypothesis_count']}")
        lines.append(f"- Unique citations: {refs['cited_reference_count']}")
        if refs["missing_references"]:
            lines.append(
                f"- **HALLUCINATED FILENAMES: "
                f"{refs['missing_reference_count']}**"
            )
            for ref in refs["missing_references"][:15]:
                lines.append(f"  - `{ref}`")
        else:
            lines.append("- All citations resolve to real files.")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    problems = []
    if artifacts["missing_required"] or artifacts["missing_root_files"]:
        problems.append("missing artifacts")
    if drug_md.get("hypothesis_section_empty"):
        problems.append("empty hypothesis section")
    if drug_md.get("unexpanded_placeholder_count", 0) > 0:
        problems.append("unexpanded drug.md placeholders")
    if refs.get("missing_reference_count", 0) > 0:
        problems.append("hallucinated evidence references")
    if trace_stats["longest_thought_stagnation"] >= 3:
        problems.append("degenerate sequential_thinking loop")
    if problems:
        lines.append("- **ISSUES**: " + "; ".join(problems))
    else:
        lines.append("- Clean run — no red flags detected.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    if not data_dir.exists():
        print(f"ERROR: data dir not found: {data_dir}", file=sys.stderr)
        return 1
    trace_path = _resolve_trace(data_dir, args.trace)

    trace_stats = parse_trace(trace_path)
    artifacts = audit_artifacts(data_dir)
    drug_md = scan_drug_md(data_dir)
    refs = scan_hypothesis_refs(data_dir)

    report = render_markdown(data_dir, trace_stats, artifacts, drug_md, refs)

    if args.output:
        args.output.write_text(report)
        print(f"Diagnostic report written to {args.output}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
