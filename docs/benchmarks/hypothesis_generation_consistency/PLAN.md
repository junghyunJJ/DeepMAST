# Hypothesis Generation Consistency Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a benchmark that runs the real DrugTarget `hypothesis_writer` LLM subagent 10 times on `res_ipf_ollama_tmp/evidence` and reports output consistency, validator pass rate, and content drift.

**Architecture:** Each trial copies `res_ipf_ollama_tmp` into an isolated workspace, removes any stale `evidence/hypothesis_report.json`, then invokes the existing DeepAgents orchestrator in resume mode (`DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1`) so only `hypothesis_writer` runs. The runner records one JSONL row per trial, preserves each run's `hypothesis_report.json`, then aggregates structural metrics and pairwise content similarity into JSON and Markdown summaries.

**Tech Stack:** Python 3.12, `deepagents`, LangGraph/LangChain tools already used by `src.agents.drug_target`, pytest, standard-library `json`, `asyncio`, `shutil`, `difflib`, `collections`.

---

## File Structure

- Create `docs/benchmarks/hypothesis_generation_consistency/__init__.py`
  - Marks the benchmark package importable for tests.
- Create `docs/benchmarks/hypothesis_generation_consistency/analysis.py`
  - Pure functions for loading `hypothesis_report.json`, extracting structural metrics, computing Jaccard/SequenceMatcher similarities, and aggregating trial rows.
- Create `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`
  - CLI entry point. Owns workspace copying, actual LLM subagent invocation, per-trial JSONL logging, resume behavior, and summary writing.
- Create `docs/benchmarks/hypothesis_generation_consistency/README.md`
  - Short runbook with command lines and artifact interpretation.
- Create `tests/benchmarks/test_hypothesis_generation_consistency.py`
  - Unit tests for workspace preparation, report summarization, similarity metrics, aggregate summary behavior, and dry-run evidence checks.
- Modify `.gitignore`
  - Already updated in this planning step to unignore this benchmark folder while keeping `results/` and `workspaces/` out of git.

Runtime outputs:

- `docs/benchmarks/hypothesis_generation_consistency/workspaces/ipf_hypothesis_consistency_20260527T000000Z/run_XX/`
  - Per-run copied workspaces. Not committed.
- `docs/benchmarks/hypothesis_generation_consistency/results/ipf_hypothesis_consistency_20260527T000000Z/trials.jsonl`
  - Append-only per-trial rows. Not committed.
- `docs/benchmarks/hypothesis_generation_consistency/results/ipf_hypothesis_consistency_20260527T000000Z/benchmark_results.json`
  - Aggregate machine-readable summary. Not committed.
- `docs/benchmarks/hypothesis_generation_consistency/results/ipf_hypothesis_consistency_20260527T000000Z/benchmark_summary.md`
  - Human-readable summary. Not committed.

## Design Decisions

1. Use the actual `hypothesis_writer` subagent path, not a deterministic payload generator.
   - Implementation uses `create_drug_target_agent(DrugTargetConfig(...))` with `DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1`.
   - This keeps the benchmark on the same prompt, tools, middleware, and save gate as production hypothesis generation.
2. Run trials sequentially by default.
   - Local Ollama/OpenRouter providers and the DeepAgents tool loop are long-running. Sequential execution avoids provider overload and makes logs easier to debug.
3. Never mutate `res_ipf_ollama_tmp`.
   - Every trial copies the source directory into an isolated workspace and removes copied stale hypothesis output before invoking the subagent.
4. Treat missing/invalid `hypothesis_report.json` as a trial failure, not as a reason to run host fallback.
   - This benchmark measures LLM subagent reliability. It must not enable `DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK`.
5. Similarity is structural first, lexical second.
   - Primary consistency metrics: save success, validator-ready output, featured gene coverage, hypothesis count, category distribution, gene sets, evidence reference sets.
   - Secondary consistency metrics: title/core-claim lexical similarity via `difflib.SequenceMatcher`.

## Task 1: Package Scaffold and Import Contract

**Files:**
- Create: `docs/benchmarks/hypothesis_generation_consistency/__init__.py`
- Create: `docs/benchmarks/hypothesis_generation_consistency/README.md`
- Create: `tests/benchmarks/test_hypothesis_generation_consistency.py`

- [ ] **Step 1: Write the package import test**

Add this initial test file:

```python
from __future__ import annotations

import importlib


def test_hypothesis_generation_consistency_package_imports() -> None:
    module = importlib.import_module(
        "docs.benchmarks.hypothesis_generation_consistency"
    )
    assert module.__name__ == "docs.benchmarks.hypothesis_generation_consistency"
```

- [ ] **Step 2: Run test to verify it fails before package scaffold**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py::test_hypothesis_generation_consistency_package_imports
```

Expected:

```text
ModuleNotFoundError: No module named 'docs.benchmarks.hypothesis_generation_consistency'
```

- [ ] **Step 3: Create package marker**

Create `docs/benchmarks/hypothesis_generation_consistency/__init__.py`:

```python
"""Hypothesis generation consistency benchmark package."""
```

- [ ] **Step 4: Create README runbook shell**

Create `docs/benchmarks/hypothesis_generation_consistency/README.md`:

```markdown
# Hypothesis Generation Consistency Benchmark

Runs the real DrugTarget `hypothesis_writer` LLM subagent repeatedly on a frozen
IPF evidence workspace and measures output stability.

Default source workspace:

```bash
res_ipf_ollama_tmp
```

Dry run:

```bash
python docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  --source res_ipf_ollama_tmp \
  --runs 10 \
  --dry-run
```

Full 10-run benchmark:

```bash
python docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  --source res_ipf_ollama_tmp \
  --runs 10 \
  --provider "${LLM_PROVIDER:-ollama}" \
  --disease "pulmonary fibrosis"
```

Artifacts are written under `results/` and `workspaces/`; both directories are
local benchmark output and are ignored by git.
```

- [ ] **Step 5: Run import test again**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py::test_hypothesis_generation_consistency_package_imports
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Commit scaffold**

```bash
git add .gitignore docs/benchmarks/hypothesis_generation_consistency/__init__.py docs/benchmarks/hypothesis_generation_consistency/README.md tests/benchmarks/test_hypothesis_generation_consistency.py
git commit -m "Add hypothesis consistency benchmark scaffold

Constraint: benchmark artifacts must live under docs/benchmarks but runtime outputs remain ignored.
Confidence: high
Scope-risk: narrow
Directive: keep source workspaces immutable; only copy into benchmark workspaces.
Tested: pytest package import test
Not-tested: LLM benchmark execution"
```

## Task 2: Pure Analysis Helpers

**Files:**
- Create: `docs/benchmarks/hypothesis_generation_consistency/analysis.py`
- Modify: `tests/benchmarks/test_hypothesis_generation_consistency.py`

- [ ] **Step 1: Add analysis tests**

Append these tests:

```python
from docs.benchmarks.hypothesis_generation_consistency.analysis import (
    aggregate_trial_rows,
    jaccard,
    summarize_report,
)


def _report_one() -> dict:
    return {
        "schema_version": "hypothesis_report.v2",
        "hypotheses": [
            {
                "title": "ICAM1 ITGB2 adhesion",
                "category": "Mechanism of Action",
                "core_claim": "ICAM1 and ITGB2 drive adhesion.",
                "evidence_references": ["stage1_ICAM1--ITGB2.json", "stage3_ICAM1.json"],
                "biological_entities": {"genes": ["ICAM1", "ITGB2"]},
            },
            {
                "title": "CD47 checkpoint",
                "category": "Therapeutic Strategy",
                "core_claim": "CD47 blockade changes clearance.",
                "evidence_references": ["stage1_THBS1--CD47.json", "stage3_CD47.json"],
                "biological_entities": {"genes": ["THBS1", "CD47"]},
            },
        ],
        "topn_coverage": {"covered": ["CD47", "ICAM1", "ITGB2"], "missing": []},
        "evidence_coverage_pct": 87.5,
        "prediction_grounding_summary": {"unverified": 0, "qualitative": 2},
    }


def _report_two() -> dict:
    report = _report_one()
    report["hypotheses"][0]["title"] = "ICAM1-ITGB2 adhesion signaling"
    report["hypotheses"][0]["core_claim"] = "ICAM1 with ITGB2 supports adhesion."
    return report


def test_jaccard_handles_empty_and_nonempty_sets() -> None:
    assert jaccard(set(), set()) == 1.0
    assert jaccard({"A"}, set()) == 0.0
    assert jaccard({"A", "B"}, {"B", "C"}) == 1 / 3


def test_summarize_report_extracts_structure() -> None:
    summary = summarize_report(_report_one())
    assert summary["schema_version"] == "hypothesis_report.v2"
    assert summary["hypothesis_count"] == 2
    assert summary["category_counts"] == {
        "Mechanism of Action": 1,
        "Therapeutic Strategy": 1,
    }
    assert summary["covered_genes"] == ["CD47", "ICAM1", "ITGB2", "THBS1"]
    assert summary["evidence_refs"] == [
        "stage1_ICAM1--ITGB2.json",
        "stage1_THBS1--CD47.json",
        "stage3_CD47.json",
        "stage3_ICAM1.json",
    ]
    assert summary["topn_missing"] == []
    assert summary["unverified_numeric_predictions"] == 0


def test_aggregate_trial_rows_reports_pairwise_consistency() -> None:
    rows = [
        {
            "run_id": "run_01",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_one()),
        },
        {
            "run_id": "run_02",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_two()),
        },
    ]
    aggregate = aggregate_trial_rows(rows)
    assert aggregate["total_runs"] == 2
    assert aggregate["success_rate"] == 1.0
    assert aggregate["validation_pass_rate"] == 1.0
    assert aggregate["hypothesis_count_values"] == [2]
    assert aggregate["mean_pairwise_gene_jaccard"] == 1.0
    assert 0.0 < aggregate["mean_pairwise_title_similarity"] <= 1.0
```

- [ ] **Step 2: Run analysis tests to verify missing module failure**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected:

```text
ModuleNotFoundError: No module named 'docs.benchmarks.hypothesis_generation_consistency.analysis'
```

- [ ] **Step 3: Implement `analysis.py`**

Create `docs/benchmarks/hypothesis_generation_consistency/analysis.py`:

```python
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from statistics import mean
from typing import Any


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _sorted_strings(values: Any) -> list[str]:
    return sorted({str(v).strip() for v in _as_list(values) if str(v).strip()})


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left or "", right or "").ratio()


def summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    hypotheses = _as_list(report.get("hypotheses"))
    category_counts: Counter[str] = Counter()
    genes: set[str] = set()
    refs: set[str] = set()
    titles: list[str] = []
    core_claims: list[str] = []

    for hyp in hypotheses:
        if not isinstance(hyp, dict):
            continue
        category = str(hyp.get("category") or "").strip()
        if category:
            category_counts[category] += 1
        entities = hyp.get("biological_entities") if isinstance(hyp.get("biological_entities"), dict) else {}
        genes.update(g.upper() for g in _sorted_strings(entities.get("genes")))
        refs.update(_sorted_strings(hyp.get("evidence_references")))
        title = str(hyp.get("title") or "").strip()
        claim = str(hyp.get("core_claim") or "").strip()
        if title:
            titles.append(title)
        if claim:
            core_claims.append(claim)

    topn = report.get("topn_coverage") if isinstance(report.get("topn_coverage"), dict) else {}
    grounding = (
        report.get("prediction_grounding_summary")
        if isinstance(report.get("prediction_grounding_summary"), dict)
        else {}
    )
    return {
        "schema_version": report.get("schema_version"),
        "hypothesis_count": len(hypotheses),
        "category_counts": dict(sorted(category_counts.items())),
        "covered_genes": sorted(genes),
        "evidence_refs": sorted(refs),
        "titles_joined": "\n".join(titles),
        "core_claims_joined": "\n".join(core_claims),
        "topn_covered": _sorted_strings(topn.get("covered")),
        "topn_missing": _sorted_strings(topn.get("missing")),
        "topn_coverage_pct": topn.get("coverage_pct"),
        "evidence_coverage_pct": report.get("evidence_coverage_pct"),
        "unverified_numeric_predictions": int(grounding.get("unverified") or 0),
    }


def _successful_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row["report_summary"]
        for row in rows
        if row.get("success") and isinstance(row.get("report_summary"), dict)
    ]


def _mean_pairwise(summaries: list[dict[str, Any]], key: str, mode: str) -> float | None:
    if len(summaries) < 2:
        return None
    scores: list[float] = []
    for left, right in combinations(summaries, 2):
        if mode == "set":
            scores.append(jaccard(set(left.get(key, [])), set(right.get(key, []))))
        elif mode == "text":
            scores.append(text_similarity(str(left.get(key, "")), str(right.get(key, ""))))
        else:
            raise ValueError(f"unsupported pairwise mode: {mode}")
    return round(mean(scores), 4) if scores else None


def aggregate_trial_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    successes = [row for row in rows if row.get("success")]
    validation_passes = [row for row in rows if row.get("validation_passed")]
    summaries = _successful_summaries(rows)
    count_values = sorted({int(s.get("hypothesis_count") or 0) for s in summaries})
    category_distributions = [
        s.get("category_counts", {})
        for s in summaries
    ]
    return {
        "total_runs": total,
        "successful_runs": len(successes),
        "validation_passed_runs": len(validation_passes),
        "success_rate": round(len(successes) / total, 4) if total else 0.0,
        "validation_pass_rate": round(len(validation_passes) / total, 4) if total else 0.0,
        "hypothesis_count_values": count_values,
        "category_distributions": category_distributions,
        "mean_pairwise_gene_jaccard": _mean_pairwise(summaries, "covered_genes", "set"),
        "mean_pairwise_ref_jaccard": _mean_pairwise(summaries, "evidence_refs", "set"),
        "mean_pairwise_title_similarity": _mean_pairwise(summaries, "titles_joined", "text"),
        "mean_pairwise_core_claim_similarity": _mean_pairwise(summaries, "core_claims_joined", "text"),
        "topn_missing_by_run": {
            row["run_id"]: row.get("report_summary", {}).get("topn_missing", [])
            for row in rows
            if row.get("run_id")
        },
        "unverified_numeric_predictions_by_run": {
            row["run_id"]: row.get("report_summary", {}).get("unverified_numeric_predictions")
            for row in rows
            if row.get("run_id")
        },
    }
```

- [ ] **Step 4: Run analysis tests**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit analysis helpers**

```bash
git add docs/benchmarks/hypothesis_generation_consistency/analysis.py tests/benchmarks/test_hypothesis_generation_consistency.py
git commit -m "Add hypothesis consistency analysis helpers

Constraint: benchmark scoring must be deterministic and not call LLMs.
Confidence: high
Scope-risk: narrow
Directive: keep structural metrics primary and lexical similarity secondary.
Tested: pytest tests/benchmarks/test_hypothesis_generation_consistency.py
Not-tested: actual hypothesis_writer execution"
```

## Task 3: Workspace Preparation and Dry-Run Evidence Check

**Files:**
- Create: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`
- Modify: `tests/benchmarks/test_hypothesis_generation_consistency.py`

- [ ] **Step 1: Add workspace and dry-run tests**

Append:

```python
import json
from pathlib import Path

from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import (
    check_hypothesis_scope,
    prepare_trial_workspace,
)


def test_prepare_trial_workspace_copies_source_and_removes_stale_report(tmp_path: Path) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    evidence.mkdir(parents=True)
    (source / "lr_candidates.json").write_text("{}", encoding="utf-8")
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report.json").write_text('{"stale": true}', encoding="utf-8")

    workspace = prepare_trial_workspace(source, tmp_path / "workspaces", "run_01", force=True)

    assert (workspace / "evidence" / "assessment_results.json").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()


def test_check_hypothesis_scope_reports_loader_errors(tmp_path: Path) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    result = check_hypothesis_scope(source)
    assert result["scope"] == "hypothesis"
    assert result["file_count"] == 0
    assert result["errors"]
```

- [ ] **Step 2: Run tests to verify missing runner failure**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected:

```text
ModuleNotFoundError: No module named 'docs.benchmarks.hypothesis_generation_consistency.run_benchmark'
```

- [ ] **Step 3: Implement runner foundation**

Create `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py` with:

```python
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from docs.benchmarks.hypothesis_generation_consistency.analysis import (
    aggregate_trial_rows,
    summarize_report,
)
from src.agents.drug_target.tools.evidence_loader import (
    check_hypothesis_completion,
    load_evidence_files,
)

load_dotenv(PROJECT_ROOT / ".env", override=False)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def prepare_trial_workspace(
    source: Path,
    workspace_root: Path,
    run_id: str,
    *,
    force: bool,
) -> Path:
    source = source.resolve()
    workspace = workspace_root / run_id
    if workspace.exists():
        if not force:
            raise FileExistsError(f"workspace already exists: {workspace}")
        shutil.rmtree(workspace)
    shutil.copytree(source, workspace)
    stale_report = workspace / "evidence" / "hypothesis_report.json"
    stale_report.unlink(missing_ok=True)
    return workspace


def check_hypothesis_scope(data_dir: Path) -> dict[str, Any]:
    raw = load_evidence_files.invoke({"data_dir": str(data_dir), "scope": "hypothesis"})
    loaded = json.loads(raw)
    return {
        "scope": loaded.get("scope"),
        "file_count": loaded.get("file_count"),
        "contrast_count": loaded.get("contrast_count"),
        "errors": loaded.get("errors", []),
        "first_files": sorted((loaded.get("files") or {}).keys())[:20],
        "excluded_count": len(loaded.get("excluded_files") or []),
    }


@contextmanager
def patched_env(values: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
```

- [ ] **Step 4: Run workspace and dry-run tests**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected:

```text
6 passed
```

- [ ] **Step 5: Run dry-run evidence check against the real source manually**

After the CLI is completed in Task 5, this command must report nonzero file count and no errors:

```bash
python docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  --source res_ipf_ollama_tmp \
  --runs 10 \
  --dry-run
```

Expected core evidence:

```text
"file_count": 64
"contrast_count": 10
"errors": []
```

- [ ] **Step 6: Commit runner foundation**

```bash
git add docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py tests/benchmarks/test_hypothesis_generation_consistency.py
git commit -m "Add hypothesis consistency workspace preparation

Constraint: each benchmark trial must isolate source evidence from generated artifacts.
Confidence: high
Scope-risk: narrow
Directive: never mutate res_ipf_ollama_tmp directly from this benchmark.
Tested: pytest tests/benchmarks/test_hypothesis_generation_consistency.py
Not-tested: LLM hypothesis_writer invocation"
```

## Task 4: Actual `hypothesis_writer` Trial Execution

**Files:**
- Modify: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`
- Modify: `tests/benchmarks/test_hypothesis_generation_consistency.py`

- [ ] **Step 1: Add no-LLM validation extraction test**

Append:

```python
from docs.benchmarks.hypothesis_generation_consistency.run_benchmark import validate_trial_output


def test_validate_trial_output_marks_missing_report_as_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "evidence").mkdir(parents=True)
    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)
    assert row["run_id"] == "run_01"
    assert row["success"] is False
    assert row["validation_passed"] is False
    assert "hypothesis_report.json missing" in row["error"]
```

- [ ] **Step 2: Implement trial output validation**

Append to `run_benchmark.py`:

```python
def validate_trial_output(
    run_id: str,
    workspace: Path,
    *,
    elapsed_s: float,
    error: str | None,
) -> dict[str, Any]:
    report_path = workspace / "evidence" / "hypothesis_report.json"
    completion = json.loads(
        check_hypothesis_completion.invoke({"data_dir": str(workspace)})
    )
    if error is not None:
        return {
            "run_id": run_id,
            "workspace": str(workspace),
            "hypothesis_report": str(report_path),
            "success": False,
            "validation_passed": False,
            "elapsed_s": round(elapsed_s, 3),
            "error": error,
            "completion": completion,
            "report_summary": None,
        }
    if not report_path.exists():
        return {
            "run_id": run_id,
            "workspace": str(workspace),
            "hypothesis_report": str(report_path),
            "success": False,
            "validation_passed": False,
            "elapsed_s": round(elapsed_s, 3),
            "error": "hypothesis_report.json missing",
            "completion": completion,
            "report_summary": None,
        }
    try:
        report = read_json(report_path)
    except Exception as exc:
        return {
            "run_id": run_id,
            "workspace": str(workspace),
            "hypothesis_report": str(report_path),
            "success": False,
            "validation_passed": False,
            "elapsed_s": round(elapsed_s, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "completion": completion,
            "report_summary": None,
        }
    summary = summarize_report(report)
    validation_passed = (
        bool(completion.get("hypothesis_complete"))
        and not summary["topn_missing"]
        and summary["unverified_numeric_predictions"] == 0
    )
    return {
        "run_id": run_id,
        "workspace": str(workspace),
        "hypothesis_report": str(report_path),
        "success": True,
        "validation_passed": validation_passed,
        "elapsed_s": round(elapsed_s, 3),
        "error": None,
        "completion": completion,
        "report_summary": summary,
    }
```

- [ ] **Step 3: Implement actual subagent invocation**

Append:

```python
async def run_hypothesis_writer_once(
    workspace: Path,
    *,
    disease: str,
    provider: str,
    timeout_s: int,
) -> None:
    from src.agents.drug_target.agent import DrugTargetConfig, create_drug_target_agent

    env = {
        "DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR": "1",
        "DRUG_TARGET_DATA_DIR": str(workspace),
        "DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK": None,
    }
    with patched_env(env):
        config = DrugTargetConfig(
            provider=provider,  # type: ignore[arg-type]
            data_dir=str(workspace),
            disease=disease,
            use_checkpointer=False,
        )
        agent, backend = create_drug_target_agent(config)
        try:
            await asyncio.wait_for(
                agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    "Run resume-mode hypothesis generation only. "
                                    "Use the hypothesis_writer subagent and save "
                                    "evidence/hypothesis_report.json."
                                ),
                            }
                        ]
                    },
                    config={"configurable": {"thread_id": str(uuid.uuid4())}},
                ),
                timeout=timeout_s,
            )
        finally:
            if backend is not None and hasattr(backend, "cleanup"):
                backend.cleanup()  # type: ignore[union-attr]


async def run_trial(
    *,
    run_id: str,
    source: Path,
    workspace_root: Path,
    disease: str,
    provider: str,
    timeout_s: int,
    force: bool,
) -> dict[str, Any]:
    workspace = prepare_trial_workspace(source, workspace_root, run_id, force=force)
    started = time.time()
    error = None
    try:
        await run_hypothesis_writer_once(
            workspace,
            disease=disease,
            provider=provider,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.time() - started
    return validate_trial_output(run_id, workspace, elapsed_s=elapsed, error=error)
```

- [ ] **Step 4: Run unit tests**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected:

```text
7 passed
```

- [ ] **Step 5: Commit actual trial execution code**

```bash
git add docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py tests/benchmarks/test_hypothesis_generation_consistency.py
git commit -m "Add actual hypothesis writer trial execution

Constraint: benchmark must invoke the real LLM hypothesis_writer path without evidence reassessment.
Confidence: medium
Scope-risk: moderate
Directive: keep host fallback disabled so failures are visible in trial rows.
Tested: pytest tests/benchmarks/test_hypothesis_generation_consistency.py
Not-tested: live LLM trial"
```

## Task 5: CLI, Resume, and Summary Artifacts

**Files:**
- Modify: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`
- Modify: `docs/benchmarks/hypothesis_generation_consistency/README.md`

- [ ] **Step 1: Implement summary Markdown formatter**

Append:

```python
def format_markdown_summary(aggregate: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Hypothesis Generation Consistency Benchmark Summary",
        "",
        f"- Total runs: {aggregate['total_runs']}",
        f"- Successful runs: {aggregate['successful_runs']}",
        f"- Validation-passed runs: {aggregate['validation_passed_runs']}",
        f"- Success rate: {aggregate['success_rate']:.2%}",
        f"- Validation pass rate: {aggregate['validation_pass_rate']:.2%}",
        f"- Hypothesis count values: {aggregate['hypothesis_count_values']}",
        f"- Mean pairwise gene Jaccard: {aggregate['mean_pairwise_gene_jaccard']}",
        f"- Mean pairwise evidence-reference Jaccard: {aggregate['mean_pairwise_ref_jaccard']}",
        f"- Mean pairwise title similarity: {aggregate['mean_pairwise_title_similarity']}",
        f"- Mean pairwise core-claim similarity: {aggregate['mean_pairwise_core_claim_similarity']}",
        "",
        "## Runs",
        "",
        "| Run | Success | Validation | Hypotheses | TOP-N missing | Unverified numeric | Elapsed s |",
        "| --- | --- | --- | ---: | --- | ---: | ---: |",
    ]
    for row in rows:
        summary = row.get("report_summary") or {}
        lines.append(
            "| {run_id} | {success} | {validation} | {count} | {missing} | {unverified} | {elapsed} |".format(
                run_id=row.get("run_id"),
                success=row.get("success"),
                validation=row.get("validation_passed"),
                count=summary.get("hypothesis_count", 0),
                missing=", ".join(summary.get("topn_missing", [])) or "-",
                unverified=summary.get("unverified_numeric_predictions", "-"),
                elapsed=row.get("elapsed_s"),
            )
        )
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 2: Implement CLI orchestration**

Append:

```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeated real hypothesis_writer trials on frozen evidence."
    )
    parser.add_argument("--source", default="res_ipf_ollama_tmp")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--disease", default="pulmonary fibrosis")
    parser.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "ollama"))
    parser.add_argument("--timeout-s", type=int, default=1800)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    source = resolve_path(args.source)
    if not source.exists():
        raise SystemExit(f"source workspace does not exist: {source}")
    scope = check_hypothesis_scope(source)
    if args.dry_run:
        print(json.dumps(scope, indent=2, ensure_ascii=False))
        return 0 if not scope["errors"] else 1
    if scope["errors"]:
        raise SystemExit(f"hypothesis scope loader errors: {scope['errors']}")

    stem = Path(args.output_root).name if args.output_root else f"ipf_hypothesis_consistency_{utc_stamp()}"
    output_root = (
        resolve_path(args.output_root)
        if args.output_root
        else PROJECT_ROOT / "docs/benchmarks/hypothesis_generation_consistency/results" / stem
    )
    workspace_root = (
        PROJECT_ROOT / "docs/benchmarks/hypothesis_generation_consistency/workspaces" / stem
    )
    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    trials_path = output_root / "trials.jsonl"
    rows: list[dict[str, Any]] = []
    for index in range(1, args.runs + 1):
        run_id = f"run_{index:02d}"
        row = await run_trial(
            run_id=run_id,
            source=source,
            workspace_root=workspace_root,
            disease=args.disease,
            provider=args.provider,
            timeout_s=args.timeout_s,
            force=args.force,
        )
        rows.append(row)
        append_jsonl(trials_path, row)
        print(json.dumps(row, ensure_ascii=False))

    aggregate = aggregate_trial_rows(rows)
    result_payload = {
        "source": str(source),
        "provider": args.provider,
        "disease": args.disease,
        "runs_requested": args.runs,
        "hypothesis_scope": scope,
        "aggregate": aggregate,
        "trials": rows,
    }
    write_json(output_root / "benchmark_results.json", result_payload)
    (output_root / "benchmark_summary.md").write_text(
        format_markdown_summary(aggregate, rows),
        encoding="utf-8",
    )
    print(f"wrote {output_root / 'benchmark_results.json'}")
    print(f"wrote {output_root / 'benchmark_summary.md'}")
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Update README with artifact schema**

Add:

```markdown
## Output Interpretation

`trials.jsonl` contains one JSON object per run:

- `success`: `hypothesis_report.json` exists and is parseable.
- `validation_passed`: completion check passed, TOP-N missing is empty, and unverified numeric prediction count is zero.
- `report_summary.covered_genes`: union of genes listed in retained hypotheses.
- `report_summary.evidence_refs`: all cited evidence filenames.
- `report_summary.topn_missing`: featured genes missed by the saved report.
- `report_summary.unverified_numeric_predictions`: numeric predictions that are not file-grounded.

`benchmark_results.json` contains the aggregate metrics used for consistency checks.
`benchmark_summary.md` is the short human-readable report.
```

- [ ] **Step 4: Run dry-run**

Run:

```bash
python docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  --source res_ipf_ollama_tmp \
  --runs 10 \
  --dry-run
```

Expected:

```text
{
  "scope": "hypothesis",
  "file_count": 64,
  "contrast_count": 10,
  "errors": [],
  ...
}
```

- [ ] **Step 5: Run unit tests**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected:

```text
7 passed
```

- [ ] **Step 6: Commit CLI and summary writer**

```bash
git add docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py docs/benchmarks/hypothesis_generation_consistency/README.md tests/benchmarks/test_hypothesis_generation_consistency.py
git commit -m "Add hypothesis consistency benchmark CLI

Constraint: benchmark must produce resumable local artifacts without committing run outputs.
Confidence: high
Scope-risk: moderate
Directive: use --dry-run before live LLM trials to verify hypothesis-scope evidence readiness.
Tested: dry-run command; pytest tests/benchmarks/test_hypothesis_generation_consistency.py
Not-tested: full 10-run LLM benchmark"
```

## Task 6: Live 10-Run Benchmark Execution

**Files:**
- Runtime only: `docs/benchmarks/hypothesis_generation_consistency/results/ipf_hypothesis_consistency_20260527T000000Z/`
- Runtime only: `docs/benchmarks/hypothesis_generation_consistency/workspaces/ipf_hypothesis_consistency_20260527T000000Z/`

- [ ] **Step 1: Confirm provider environment**

Run:

```bash
python - <<'PY'
import os
print("LLM_PROVIDER=", os.getenv("LLM_PROVIDER", "ollama"))
print("OLLAMA_BASE_URL=", os.getenv("OLLAMA_BASE_URL", "http://localhost:6000"))
print("OLLAMA_MODEL=", os.getenv("OLLAMA_MODEL", "qwen3.5:122b"))
print("SUBAGENT_HYPOTHESIS_WRITER_PROVIDER=", os.getenv("SUBAGENT_HYPOTHESIS_WRITER_PROVIDER"))
print("SUBAGENT_HYPOTHESIS_WRITER_MODEL=", os.getenv("SUBAGENT_HYPOTHESIS_WRITER_MODEL"))
PY
```

Expected:

```text
LLM_PROVIDER= ollama
```

The subagent override lines may be empty. Empty means `hypothesis_writer` inherits the default model.

- [ ] **Step 2: Run one live smoke trial**

Run:

```bash
python docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  --source res_ipf_ollama_tmp \
  --runs 1 \
  --provider "${LLM_PROVIDER:-ollama}" \
  --disease "pulmonary fibrosis" \
  --timeout-s 1800 \
  --force
```

Expected:

```text
"run_id": "run_01"
"success": true
```

If this fails due to provider connection, stop and fix provider configuration before the 10-run benchmark.

- [ ] **Step 3: Run full 10-trial benchmark**

Run:

```bash
python docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  --source res_ipf_ollama_tmp \
  --runs 10 \
  --provider "${LLM_PROVIDER:-ollama}" \
  --disease "pulmonary fibrosis" \
  --timeout-s 1800 \
  --force
```

Expected:

```text
wrote .../benchmark_results.json
wrote .../benchmark_summary.md
```

- [ ] **Step 4: Inspect aggregate summary**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
base = max(Path("docs/benchmarks/hypothesis_generation_consistency/results").iterdir(), key=lambda p: p.stat().st_mtime)
data = json.loads((base / "benchmark_results.json").read_text())
print(json.dumps(data["aggregate"], indent=2))
print(base / "benchmark_summary.md")
PY
```

Expected quality bar for the first benchmark:

```text
"success_rate": 1.0
"validation_pass_rate": 1.0
```

Similarity metrics are descriptive, not hard pass/fail, on the first run.

- [ ] **Step 5: Archive human-readable summary if needed**

If the result should be committed as a benchmark snapshot, copy only `benchmark_summary.md` into a dated tracked file:

```bash
LATEST_RESULTS=$(ls -td docs/benchmarks/hypothesis_generation_consistency/results/* | head -1)
cp "$LATEST_RESULTS/benchmark_summary.md" \
  "docs/benchmarks/hypothesis_generation_consistency/SUMMARY-$(basename "$LATEST_RESULTS").md"
```

Do not commit `workspaces/` or full `results/` unless explicitly requested.

## Self-Review

### Spec Coverage

- Actual LLM `hypothesis_writer` repeated 10 times: Task 4 and Task 6.
- Uses `res_ipf_ollama_tmp/evidence`: Task 5 dry-run and Task 6 commands use `--source res_ipf_ollama_tmp`.
- Creates a folder under `docs/benchmarks`: this plan lives in `docs/benchmarks/hypothesis_generation_consistency/`.
- Preserves original workspace: Task 3 `prepare_trial_workspace` copies source and removes only copied stale output.
- Consistency metrics requested in the interview: Task 2 aggregate metrics and Task 5 summary artifacts.

### Placeholder Scan

No task depends on undefined file paths, delayed-fill markers, or unspecified validation instructions.

### Type Consistency

- `report_summary` is a dict returned by `summarize_report(report)`.
- `aggregate_trial_rows(rows)` accepts a list of trial row dicts and returns aggregate metrics consumed by `format_markdown_summary`.
- `run_trial(...)` returns the same row shape consumed by `append_jsonl`, `aggregate_trial_rows`, and Markdown formatting.
