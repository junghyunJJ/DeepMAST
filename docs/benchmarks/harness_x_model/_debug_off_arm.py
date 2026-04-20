"""Diagnostic: run one OFF-arm trial and dump the full message history.

Used to root-cause why strong_off / weak_* trials fail with papers_not_written.
Output: docs/benchmarks/harness_x_model/results/debug/strong_off_messages.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.harness_x_model.common import (
    build_searcher_for_trial,
    build_user_prompt,
    load_cases,
    normalize_case,
    prepare_trial_workspace,
)


def _serialize_message(msg) -> dict:
    out: dict = {"type": type(msg).__name__}
    if hasattr(msg, "content"):
        out["content"] = str(msg.content)[:5000]
    if hasattr(msg, "name") and msg.name:
        out["name"] = msg.name
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        out["tool_calls"] = [
            {
                "name": tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?"),
                "args": str(tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {}))[:2000],
            }
            for tc in msg.tool_calls
        ]
    if hasattr(msg, "tool_call_id") and msg.tool_call_id:
        out["tool_call_id"] = msg.tool_call_id
    return out


def main() -> None:
    case_id = "cci_full_17_COL1A1_CD93"
    cases = load_cases("docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json")
    case = next(c for c in cases if c["case_id"] == case_id)
    normalized = normalize_case(case)
    workspace = (
        Path("docs/benchmarks/harness_x_model/workspaces/debug_strong_off").resolve()
    )
    prepare_trial_workspace(workspace_dir=workspace, normalized_case=normalized, clean=True)

    print(f"[{time.strftime('%H:%M:%S')}] Building agent (strong_off, qwen3.5:122b)...")
    agent = build_searcher_for_trial(
        model_label="qwen3.5:122b",
        skill_on=False,
        workspace_dir=workspace,
        temperature=0.3,
    )
    prompt = build_user_prompt(normalized)

    print(f"[{time.strftime('%H:%M:%S')}] Invoking agent...")
    started = time.perf_counter()
    state = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    elapsed = time.perf_counter() - started
    print(f"[{time.strftime('%H:%M:%S')}] Done in {elapsed:.1f}s")

    msgs = state.get("messages", [])
    serialized = [_serialize_message(m) for m in msgs]

    out_dir = Path("docs/benchmarks/harness_x_model/results/debug")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "strong_off_messages.json"
    out_path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "elapsed_s": round(elapsed, 1),
                "n_messages": len(msgs),
                "papers_json_exists": (workspace / "papers.json").exists(),
                "search_context_json_exists": (workspace / "search_context.json").exists(),
                "messages": serialized,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[{time.strftime('%H:%M:%S')}] Wrote {out_path}")

    # Print a summary so we can see it in the run log too
    print("\n=== TOOL CALL SUMMARY ===")
    for i, m in enumerate(serialized):
        for tc in m.get("tool_calls", []):
            print(f"  msg {i:3d}: {tc['name']}({tc['args'][:150]})")
    print(f"\npapers.json exists: {(workspace / 'papers.json').exists()}")
    print(f"search_context.json exists: {(workspace / 'search_context.json').exists()}")


if __name__ == "__main__":
    main()
