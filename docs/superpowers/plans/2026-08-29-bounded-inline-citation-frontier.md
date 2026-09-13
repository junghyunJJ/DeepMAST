# Bounded Inline Citation Frontier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep synthesis guardrail progress strict and repair Pair-15's actual failure by removing all non-supported inline PMIDs for one exact claim target in one deterministic pass.

**Round 2 ruling:** The original equal-count frontier design is disproven. Live Pair-15 revalidation increased hard errors from 1 to 2, so `_strict_phase_progress` must retain aggregate same-phase decrease. When a hard repairable inline issue triggers and no supported sibling exists for its exact `(file, section, source_claim_index)`, `_repair_inline_citation_issues` removes all matching non-supported PMIDs (`overclaimed`, `unsupported`, and `unverifiable`) together. Supported siblings are preserved; reference-only deletion is unchanged.

**Architecture:** Restore strict `_strict_phase_progress`; make the narrow repair-root change in `scripts/repair_report.py` and cover it with three-PMID unit and synthesis guardrail regressions.

**Tech Stack:** Python 3.12, pathlib, JSON, pytest, existing DeepMAST guardrails/Reporter finalizer, Ollama `qwen3.5:122b`, SGCP-RAG, tmux

**Spec:** `docs/superpowers/specs/2026-08-29-bounded-inline-citation-frontier-design.md`

## Global Constraints

- Keep explicit `inline_citation_unsupported` and `inline_citation_overclaimed` findings hard until repaired.
- Keep uncited semantic findings warning-only under the high-precision guardrail design.
- Keep strict same-phase hard-error decrease for every non-inline or mixed frontier.
- Equal-count progress is allowed only for non-empty, disjoint semantic hard-error key sets whose codes are all in `REPAIRABLE_INLINE_CITATION_CODES` before and after repair.
- Keep three regular synthesis repair passes, optional terminal repair, `MAX_REPORTER_ATTEMPTS = 2`, and all timeout values unchanged.
- Do not change Reporter recovery, rendering, SGCP-RAG, RAG audit validity, SNI selection, query count, Claim-RAG selection/batching/cache, collection binding, model, or ports.
- Do not relax Pair-13 R1 pathway validation or convert Pair-13 R2 `AgenticError` into success.
- Preserve original Pair-13 and Pair-15 results as immutable evidence.
- Do not run a full pair until tests, review, finalizer replay, and Reporter-only replay pass.
- Add no dependency, module, graph node, manifest, timeout, attempt, or speculative abstraction.
- Every commit follows the repository Lore protocol.

## File Structure

- Modify `src/agents/deep_interpreter/report_guardrails.py`: bounded explicit-inline progress in `_strict_phase_progress`.
- Modify `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`: Pair-15 cascade and negative boundaries.
- Create no other tracked production/test file.
- Create replay evidence only under validated `/tmp/deepmast-p15-*` paths.
- Create pair orchestration only under ignored `res/deep_interpreter/bc/sni_repair_ablation/` output.

---

### Task 1: Lock and fix the bounded explicit-inline frontier

**Files:**
- Modify: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py:635-730`
- Modify: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py:829-1020`
- Modify: `src/agents/deep_interpreter/report_guardrails.py:138-150`

**Interfaces:**
- Consumes: `repair_report_script.REPAIRABLE_INLINE_CITATION_CODES`, `_issue_claim_key(issue)`, `_error_count(issues)`, `ValidationPhase`
- Produces: `_strict_phase_progress(before, before_phase, after, after_phase) -> bool` with bounded explicit-inline semantics
- Preserves: `run_synthesis_guardrail(...)`, repair limits, atomic rollback, and every public interface

- [ ] **Step 1: Add the focused progress-policy RED test**

Add beside the existing `_strict_phase_progress` tests:

```python
def test_strict_phase_progress_allows_only_disjoint_inline_citation_frontier() -> None:
    from src.agents.deep_interpreter import report_guardrails

    first = {
        "severity": "error",
        "code": "inline_citation_overclaimed",
        "file": "synthesis.md",
        "section": "## Cross-Part Themes",
        "value": "Mechanism A (PMID: 11111111; PMID: 22222222).",
        "inline_pmid": "11111111",
    }
    second = {
        **first,
        "value": "Mechanism A (PMID: 22222222).",
        "inline_pmid": "22222222",
    }
    generic = {
        "severity": "error",
        "code": "synthesis_consistency_unresolved",
        "file": "synthesis.md",
        "section": "## Cross-Part Themes",
        "value": "Different semantic target",
    }

    assert report_guardrails._strict_phase_progress(
        [first], "semantic", [second], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [first], "semantic", [first], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [first], "semantic", [generic], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [first], "semantic", [second, generic], "semantic"
    )
```

- [ ] **Step 2: Run the policy test and verify RED**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_allows_only_disjoint_inline_citation_frontier
```

Expected: FAIL on the first assertion because current same-phase progress requires a lower aggregate hard-error count.

- [ ] **Step 3: Add the Pair-15-shaped cascading-PMID RED test**

Add beside the existing synthesis inline-citation tests:

```python
def test_run_synthesis_guardrail_repairs_cascading_inline_citation_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    pmids = ("11111111", "22222222")
    (tmp_path / "papers.json").write_text(
        json.dumps(
            {
                "papers": [
                    {"pmid": pmid, "abstract": "association-only evidence"}
                    for pmid in pmids
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "synthesis.md").write_text(
        "# Synthesis Report\n\n"
        "## Cross-Part Themes\n\n"
        "**Integration**: Mechanism A directly drives response "
        "(PMID: 11111111; PMID: 22222222).\n",
        encoding="utf-8",
    )

    def fake_claim_validate(
        _data_dir: Path,
        filenames: tuple[str, ...],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        assert filenames == ("synthesis.md",)
        text = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
        claim = next(line for line in text.splitlines() if line.startswith("**Integration**"))
        remaining = [pmid for pmid in pmids if f"PMID: {pmid}" in claim]
        claims = [
            {
                "file": "synthesis.md",
                "section": "## Cross-Part Themes",
                "source_claim_index": 0,
                "inline_pmid": pmid,
                "claim": claim,
                "status": "overclaimed" if pmid == remaining[0] else "unverifiable",
                "supporting_pmids": [],
                "evidence_quote": "association-only evidence",
                "reason": "the evidence does not support the asserted mechanism",
            }
            for pmid in remaining
        ]
        if remaining:
            issues = [
                {
                    "code": "inline_citation_overclaimed",
                    "severity": "error",
                    "file": "synthesis.md",
                    "section": "## Cross-Part Themes",
                    "source_claim_index": 0,
                    "inline_pmid": remaining[0],
                    "value": claim,
                    "target_text": claim,
                }
            ]
        else:
            claims = [
                {
                    "file": "synthesis.md",
                    "section": "## Cross-Part Themes",
                    "source_claim_index": 0,
                    "inline_pmid": None,
                    "claim": claim,
                    "status": "overclaimed",
                    "supporting_pmids": [],
                    "evidence_quote": "association-only evidence",
                    "reason": "the uncited interpretation remains a warning",
                }
            ]
            issues = [
                {
                    "code": "claim_rag_overclaimed",
                    "severity": "warning",
                    "file": "synthesis.md",
                    "section": "## Cross-Part Themes",
                    "value": claim,
                }
            ]
        return {
            "claims": claims,
            "issues": issues,
            "selection": {"selected_claim_count": len(claims)},
            "inline_citation_coverage": {
                "expected_count": len(remaining),
                "evaluated_count": len(remaining),
                "supported_count": 0,
                "coverage_complete": not remaining,
                "citations": claims,
            },
        }

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fake_claim_validate
    )
    monkeypatch.setattr(
        report_guardrails.repair_report_script,
        "_create_model",
        lambda *_: (_ for _ in ()).throw(AssertionError("model must not be called")),
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    synthesis = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 2
    assert result["changed_claims"] == 2
    assert result["final_error_count"] == 0
    assert "11111111" not in synthesis
    assert "22222222" not in synthesis
```

- [ ] **Step 4: Run the cascade test and verify RED**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_repairs_cascading_inline_citation_frontier
```

Expected: FAIL with `status == "failed"`; current code restores each equal-count candidate until the three-pass budget is exhausted.

- [ ] **Step 5: Implement the narrow production rule**

Replace the same-phase tail of `_strict_phase_progress` with:

```python
    before_count = _error_count(before)
    after_count = _error_count(after)
    if after_count < before_count:
        return True
    if before_phase != "semantic" or after_count != before_count or not before_count:
        return False

    before_errors = [issue for issue in before if issue.get("severity") == "error"]
    after_errors = [issue for issue in after if issue.get("severity") == "error"]
    repairable = repair_report_script.REPAIRABLE_INLINE_CITATION_CODES
    if any(
        issue.get("code") not in repairable
        for issue in (*before_errors, *after_errors)
    ):
        return False

    before_keys = {_issue_claim_key(issue) for issue in before_errors}
    after_keys = {_issue_claim_key(issue) for issue in after_errors}
    return bool(before_keys) and before_keys.isdisjoint(after_keys)
```

Do not add a helper or alter `_issue_claim_key`.

- [ ] **Step 6: Run new and adjacent tests**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_allows_only_disjoint_inline_citation_frontier \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_repairs_cascading_inline_citation_frontier \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_removes_only_unsupported_sibling_citation \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_removes_sole_failed_inline_pmid_without_model \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_does_not_terminally_retry_persistent_error
```

Expected: 5 passed.

- [ ] **Step 7: Commit the TDD slice**

```bash
git add src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git add -f \
  docs/superpowers/specs/2026-08-29-bounded-inline-citation-frontier-design.md \
  docs/superpowers/plans/2026-08-29-bounded-inline-citation-frontier.md
git commit -m "Let explicit citation repair advance across bounded targets" \
  -m "Constraint: Keep general same-count semantic movement rejected and retain the three-pass budget." \
  -m "Rejected: Restore broad semantic frontier acceptance | It conflicts with the high-precision guardrail design." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Directive: Equal-count progress remains limited to disjoint hard inline-citation targets." \
  -m "Tested: Pair-15-shaped RED/GREEN cascade and adjacent synthesis guardrail regressions." \
  -m "Not-tested: Live Pair-15 replay and full sequential pairs are gated later in this plan."
```

---

### Task 2: Run regression verification and independent review

**Files:**
- Verify: `src/agents/deep_interpreter/report_guardrails.py`
- Verify: `scripts/repair_report.py`
- Verify: `src/agents/deep_interpreter/reporter_recovery.py`
- Test: guardrail, repair, Reporter recovery, Claim-RAG, renderer, and SNI runner suites

**Interfaces:**
- Consumes: Task 1 commit
- Produces: fresh regression evidence and independent approval before live replay
- Preserves: no additional production change unless a reviewer demonstrates a concrete defect

- [ ] **Step 1: Run focused regression suites**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/scripts/test_repair_report.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/deep_interpreter/test_comprehensive_template_report.py \
  tests/test_sni_ablation_runner.py
```

Expected: all tests pass. Any failure blocks replay and returns to Task 1 with a focused RED test.

- [ ] **Step 2: Run static verification**

```bash
uv run ruff check \
  src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run python -m py_compile \
  src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git diff --check
git status --short
```

Expected: Ruff and `py_compile` pass, diff check is empty, and no production/test change is uncommitted.

- [ ] **Step 3: Request independent spec-compliance review**

Use a fresh reviewer with this exact brief:

```text
Review the Task 1 commit against
docs/superpowers/specs/2026-08-29-bounded-inline-citation-frontier-design.md.
Confirm that equal-count progress is accepted only for non-empty disjoint
semantic hard-error frontiers containing exclusively
REPAIRABLE_INLINE_CITATION_CODES. Confirm that persistent, overlapping, mixed,
generic semantic, phase-changing, and count-increasing cases remain rejected.
Report Critical, Important, and Minor findings with file/line evidence.
```

Expected: no Critical or Important finding.

- [ ] **Step 4: Request independent code-quality review**

Use a different fresh reviewer with this exact brief:

```text
Review the Task 1 diff for correctness, rollback safety, hidden guardrail-policy
widening, test realism, and unnecessary abstraction. Check the Pair-15
cascading-PMID reproduction and Lore commit evidence. Do not propose unrelated
cleanup. Report Critical, Important, and Minor findings with file/line evidence.
```

Expected: no Critical or Important finding. Address any such finding with a new RED test, rerun Steps 1-2, and make a Lore commit before continuing.

---

### Task 3: Replay Pair-15 deterministic finalization on an isolated copy

**Files:**
- Read/copy: `res/deep_interpreter/bc/sni_repair_ablation/post_deterministic_finalization_pair13r2_pair14_pair15_sequential_20260829T005328Z/pairs/pair-15/wiki-on/`
- Execute: `_finalize_reporter_artifacts(...)`
- Create runtime evidence: `/tmp/deepmast-p15-finalizer-frontier.*`

**Interfaces:**
- Consumes: reviewed Task 1 commit and exact failed Pair-15 SNI synthesis
- Produces: finalizer `passed`, hard errors zero, valid sidecars/HTML, unchanged Parts, untouched original

- [ ] **Step 1: Verify services and collection**

```bash
curl --fail --silent --show-error http://localhost:6000/api/tags >/dev/null
curl --fail --silent --show-error http://localhost:4000/api/tags >/dev/null
curl --fail --silent --show-error http://localhost:8883/health >/dev/null
curl --fail --silent --show-error \
  http://localhost:8883/collections/a208e916-bd32-405a-9eee-de4cd82b2a3b \
  | jq -e '.document_count == 100 and .chunk_count == 1553'
```

Expected: all commands exit zero. Stop without live-completion claims if a prerequisite is unavailable.

- [ ] **Step 2: Create a validated temporary copy and preserve hashes**

Run Steps 2-5 in the same shell session so `FINALIZER_REPLAY_ROOT` remains bound to the validated temporary directory.

```bash
FINALIZER_REPLAY_ROOT=$(mktemp -d /tmp/deepmast-p15-finalizer-frontier.XXXXXX)
case "$FINALIZER_REPLAY_ROOT" in
  /tmp/deepmast-p15-finalizer-frontier.*) ;;
  *) exit 2 ;;
esac
rsync -a \
  res/deep_interpreter/bc/sni_repair_ablation/post_deterministic_finalization_pair13r2_pair14_pair15_sequential_20260829T005328Z/pairs/pair-15/wiki-on/ \
  "$FINALIZER_REPLAY_ROOT/"
shasum -a 256 \
  "$FINALIZER_REPLAY_ROOT/part1_final.md" \
  "$FINALIZER_REPLAY_ROOT/part2_final.md" \
  "$FINALIZER_REPLAY_ROOT/part3_final.md" \
  > "$FINALIZER_REPLAY_ROOT/parts.before.sha256"
shasum -a 256 "$FINALIZER_REPLAY_ROOT/synthesis.md" \
  > "$FINALIZER_REPLAY_ROOT/synthesis.before.sha256"
```

- [ ] **Step 3: Remove only derived outputs in the validated copy**

```bash
case "$FINALIZER_REPLAY_ROOT" in
  /tmp/deepmast-p15-finalizer-frontier.*) ;;
  *) exit 2 ;;
esac
rm -f \
  "$FINALIZER_REPLAY_ROOT/synthesis_validation.json" \
  "$FINALIZER_REPLAY_ROOT/synthesis_targets.json" \
  "$FINALIZER_REPLAY_ROOT/CCI_Analysis_Report.html" \
  "$FINALIZER_REPLAY_ROOT/reporter_recovery.json"
```

Do not remove `synthesis.md`; this replay must exercise the failed Pair-15 synthesis.

- [ ] **Step 4: Run deterministic finalization only**

```bash
OPENAI_API_KEY=test \
LANGCHAIN_TRACING_V2=false \
LLM_PROVIDER=ollama \
LLM_MODEL=qwen3.5:122b \
OLLAMA_MODEL=qwen3.5:122b \
OLLAMA_BASE_URL=http://localhost:6000 \
OLLAMA_HOST=http://localhost:6000 \
OLLAMA_REASONING=true \
OLLAMA_REQUEST_TIMEOUT_SECONDS=10800 \
CCI_RAG_BASE_URL=http://localhost:8883 \
DEEP_INTERPRETER_FIXED_COLLECTION_ID=a208e916-bd32-405a-9eee-de4cd82b2a3b \
DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true \
DEEP_INTERPRETER_USE_WIKI_CONTEXT=true \
FINALIZER_REPLAY_ROOT="$FINALIZER_REPLAY_ROOT" \
uv run python - <<'PY'
import json
import os
from pathlib import Path

from src.agents.deep_interpreter.tools.report import _finalize_reporter_artifacts

root = Path(os.environ["FINALIZER_REPLAY_ROOT"])
result = _finalize_reporter_artifacts(
    parts={"template_mode": "comprehensive"},
    output_path="CCI_Analysis_Report.html",
    data_dir=str(root),
    required_refresh=(
        "synthesis_validation.json",
        "synthesis_targets.json",
        "CCI_Analysis_Report.html",
    ),
)
(root / "finalizer_replay.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
raise SystemExit(0 if result.get("status") == "passed" else 1)
PY
```

Expected: exit zero; no Reporter LLM attempt starts.

- [ ] **Step 5: Verify outputs and immutable Parts**

```bash
jq -e '
  .status == "passed"
  and .guardrail.status == "passed"
  and .guardrail.final_error_count == 0
' "$FINALIZER_REPLAY_ROOT/finalizer_replay.json"
jq -e '
  .synthesis_guardrail.status == "passed"
  and .synthesis_guardrail.final_error_count == 0
' "$FINALIZER_REPLAY_ROOT/synthesis_validation.json"
jq -e 'type == "object"' "$FINALIZER_REPLAY_ROOT/synthesis_targets.json"
test -s "$FINALIZER_REPLAY_ROOT/CCI_Analysis_Report.html"
grep -qi '<!doctype html' "$FINALIZER_REPLAY_ROOT/CCI_Analysis_Report.html"
grep -qi '</html>' "$FINALIZER_REPLAY_ROOT/CCI_Analysis_Report.html"
shasum -a 256 \
  "$FINALIZER_REPLAY_ROOT/part1_final.md" \
  "$FINALIZER_REPLAY_ROOT/part2_final.md" \
  "$FINALIZER_REPLAY_ROOT/part3_final.md" \
  > "$FINALIZER_REPLAY_ROOT/parts.after.sha256"
diff -u "$FINALIZER_REPLAY_ROOT/parts.before.sha256" \
  "$FINALIZER_REPLAY_ROOT/parts.after.sha256"
```

Expected: every command exits zero. Record the replay path and synthesis before/after hashes.

---

### Task 4: Run Reporter-only replay on a second Pair-15 copy

**Files:**
- Read/copy: original Pair-15 SNI directory
- Execute: `scripts/run_deep_interpreter_agent.py --subagent reporter`
- Create runtime evidence: `/tmp/deepmast-p15-reporter-frontier.*`

**Interfaces:**
- Consumes: passed finalizer replay and reviewed code
- Produces: Reporter exit zero, Attempt 1 completion, no recovery, valid artifacts, unchanged Parts

- [ ] **Step 1: Create a clean Reporter-only copy**

Run Steps 1-3 in the same shell session so `REPORTER_REPLAY_ROOT` remains bound to the validated temporary directory.

```bash
REPORTER_REPLAY_ROOT=$(mktemp -d /tmp/deepmast-p15-reporter-frontier.XXXXXX)
case "$REPORTER_REPLAY_ROOT" in
  /tmp/deepmast-p15-reporter-frontier.*) ;;
  *) exit 2 ;;
esac
rsync -a \
  res/deep_interpreter/bc/sni_repair_ablation/post_deterministic_finalization_pair13r2_pair14_pair15_sequential_20260829T005328Z/pairs/pair-15/wiki-on/ \
  "$REPORTER_REPLAY_ROOT/"
shasum -a 256 \
  "$REPORTER_REPLAY_ROOT/part1_final.md" \
  "$REPORTER_REPLAY_ROOT/part2_final.md" \
  "$REPORTER_REPLAY_ROOT/part3_final.md" \
  > "$REPORTER_REPLAY_ROOT/parts.before.sha256"
case "$REPORTER_REPLAY_ROOT" in
  /tmp/deepmast-p15-reporter-frontier.*) ;;
  *) exit 2 ;;
esac
rm -f \
  "$REPORTER_REPLAY_ROOT/synthesis.md" \
  "$REPORTER_REPLAY_ROOT/synthesis_validation.json" \
  "$REPORTER_REPLAY_ROOT/synthesis_targets.json" \
  "$REPORTER_REPLAY_ROOT/CCI_Analysis_Report.html" \
  "$REPORTER_REPLAY_ROOT/reporter_recovery.json" \
  "$REPORTER_REPLAY_ROOT/synthesis_reporter_attempt1.md"
```

- [ ] **Step 2: Run Reporter only with Pair-15 SNI settings**

```bash
OPENAI_API_KEY=test \
LANGCHAIN_TRACING_V2=false \
LLM_PROVIDER=ollama \
LLM_MODEL=qwen3.5:122b \
OLLAMA_MODEL=qwen3.5:122b \
OLLAMA_BASE_URL=http://localhost:6000 \
OLLAMA_HOST=http://localhost:6000 \
OLLAMA_REASONING=true \
OLLAMA_REQUEST_TIMEOUT_SECONDS=10800 \
REPORTER_ATTEMPT_TIMEOUT_SECONDS=10800 \
CCI_RAG_BASE_URL=http://localhost:8883 \
DEEP_INTERPRETER_FIXED_COLLECTION_ID=a208e916-bd32-405a-9eee-de4cd82b2a3b \
DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true \
DEEP_INTERPRETER_USE_WIKI_CONTEXT=true \
uv run python scripts/run_deep_interpreter_agent.py \
  --subagent reporter \
  --data-dir "$REPORTER_REPLAY_ROOT" \
  --traceback
```

Expected: exit zero. Do not run Parts or a full condition.

- [ ] **Step 3: Verify Attempt 1 deterministic completion**

```bash
jq -e '
  .status == "passed"
  and .attempt_count == 1
  and .recovery_used == false
  and .attempts[0].completion.complete == true
  and .attempts[0].finalizer.status == "passed"
' "$REPORTER_REPLAY_ROOT/reporter_recovery.json"
jq -e '
  .synthesis_guardrail.status == "passed"
  and .synthesis_guardrail.final_error_count == 0
' "$REPORTER_REPLAY_ROOT/synthesis_validation.json"
jq -e 'type == "object"' "$REPORTER_REPLAY_ROOT/synthesis_targets.json"
test -s "$REPORTER_REPLAY_ROOT/CCI_Analysis_Report.html"
shasum -a 256 \
  "$REPORTER_REPLAY_ROOT/part1_final.md" \
  "$REPORTER_REPLAY_ROOT/part2_final.md" \
  "$REPORTER_REPLAY_ROOT/part3_final.md" \
  > "$REPORTER_REPLAY_ROOT/parts.after.sha256"
diff -u "$REPORTER_REPLAY_ROOT/parts.before.sha256" \
  "$REPORTER_REPLAY_ROOT/parts.after.sha256"
```

Expected: every command exits zero. A second Reporter attempt, incomplete artifact, changed Part hash, or hard error blocks batch launch.

---

### Task 5: Launch Pair-15-R2 through Pair-20 sequentially in tmux

**Files:**
- Reuse: `res/deep_interpreter/bc/sni_repair_ablation/post_deterministic_finalization_pair13r2_pair14_pair15_sequential_20260829T005328Z/run_sequence_pair13r2_pair14_pair15.py`
- Create runtime-only: `res/deep_interpreter/bc/sni_repair_ablation/post_bounded_inline_frontier_pair15r2_pair20_sequential_${SEQUENCE_UTC}/`
- Create runtime-only: sequence script, launcher, manifest source, config, preflight, status, logs, and pair outputs

**Interfaces:**
- Consumes: approved code HEAD, passed Tasks 2-4, ports 6000/4000/8883, collection `a208e916-bd32-405a-9eee-de4cd82b2a3b`
- Produces: Pair order `15-R2, 16, 17, 18, 19, 20`; condition order `no-SNI, SNI`; per-pair exit markers; endpoint-aware continuation

- [ ] **Step 1: Re-run preflight immediately before launch**

```bash
test -z "$(pgrep -af 'pair15r2_pair20|pair-15-R2|pair-16|pair-17|pair-18|pair-19|pair-20' || true)"
curl --fail --silent --show-error http://localhost:6000/api/tags >/dev/null
curl --fail --silent --show-error http://localhost:4000/api/tags >/dev/null
curl --fail --silent --show-error http://localhost:8883/health >/dev/null
curl --fail --silent --show-error \
  http://localhost:8883/collections/a208e916-bd32-405a-9eee-de4cd82b2a3b \
  | jq -e '.document_count == 100 and .chunk_count == 1553'
git status --short
git rev-parse --short HEAD
```

Expected: no duplicate process, all services healthy, collection 100/1553, and clean worktree.

- [ ] **Step 2: Copy the proven runtime harness**

Run Steps 2-6 in the same shell session so `SEQUENCE_UTC` and `SEQUENCE_ROOT` remain bound to this run.

```bash
SEQUENCE_UTC=$(date -u '+%Y%m%dT%H%M%SZ')
SEQUENCE_ROOT="res/deep_interpreter/bc/sni_repair_ablation/post_bounded_inline_frontier_pair15r2_pair20_sequential_${SEQUENCE_UTC}"
SOURCE_SEQUENCE_ROOT="res/deep_interpreter/bc/sni_repair_ablation/post_deterministic_finalization_pair13r2_pair14_pair15_sequential_20260829T005328Z"
mkdir -p "$SEQUENCE_ROOT"
cp "$SOURCE_SEQUENCE_ROOT/manifest_source.json" "$SEQUENCE_ROOT/manifest_source.json"
cp "$SOURCE_SEQUENCE_ROOT/run_sequence_pair13r2_pair14_pair15.py" \
  "$SEQUENCE_ROOT/run_sequence_pair15r2_pair20.py"
cp "$SOURCE_SEQUENCE_ROOT/launch_sequence.zsh" "$SEQUENCE_ROOT/launch_sequence.zsh"
```

Edit copied runtime files with `apply_patch`.

- [ ] **Step 3: Set exact pair order and endpoint-only stop policy**

In `run_sequence_pair15r2_pair20.py`, set:

```python
sequence: dict[str, Any] = {
    "status": "running",
    "started_at": utc_now(),
    "pair_order": ["15-R2", "16", "17", "18", "19", "20"],
    "condition_order": ["no-SNI", "SNI"],
    "runs": [],
}

PAIR_SEQUENCE = (
    ("15-R2", "16"),
    ("16", "17"),
    ("17", "18"),
    ("18", "19"),
    ("19", "20"),
    ("20", None),
)

for pair_id, next_pair_id in PAIR_SEQUENCE:
    run_record = {
        "pair_id": pair_id,
        "started_at": utc_now(),
        "status": "running",
    }
    sequence["runs"].append(run_record)
    write_status(sequence)
    exception_repr = None
    try:
        return_code = runner.run_pair(
            pair_config(pair_id),
            source=SOURCE,
            output_root=OUTPUT_ROOT,
            stage_runner=runner._default_stage_runner,
            collection_snapshot=runner._default_collection_snapshot,
        )
    except Exception as exc:
        return_code = 1
        exception_repr = repr(exc)
    run_record["return_code"] = return_code
    run_record["finished_at"] = utc_now()
    run_record["endpoint_status_after"] = endpoint_status()
    (RUN_ROOT / f"pair{pair_id}.exit_code").write_text(
        f"{return_code}\n", encoding="utf-8"
    )
    runner.summarize(OUTPUT_ROOT)
    if return_code == 0:
        run_record["status"] = "passed"
    else:
        overall_return_code = 1
        run_record["status"] = "failed"
        run_record["failure_classification"] = classify_failure(
            pair_id, exception_repr
        )
        if exception_repr:
            run_record["exception_repr"] = exception_repr
    if next_pair_id and not all(run_record["endpoint_status_after"].values()):
        overall_return_code = 1
        sequence[f"pair{next_pair_id}_skipped"] = True
        sequence[f"pair{next_pair_id}_skip_reason"] = (
            f"infrastructure_after_pair{pair_id}"
        )
        break
    write_status(sequence)
```

Content, guardrail, Reporter, and unknown failures continue when all endpoints are healthy. Endpoint failure alone stops the next Pair.

- [ ] **Step 4: Make the launcher portable and preserve settings**

Point the launcher to the new root/script and use:

```zsh
export LLM_MODEL=qwen3.5:122b
export OLLAMA_MODEL=qwen3.5:122b
export OLLAMA_BASE_URL=http://localhost:6000
export OLLAMA_REQUEST_TIMEOUT_SECONDS=10800
export REPORTER_ATTEMPT_TIMEOUT_SECONDS=10800
export CCI_RAG_BASE_URL=http://localhost:8883
export DEEP_INTERPRETER_FIXED_COLLECTION_ID=a208e916-bd32-405a-9eee-de4cd82b2a3b
export DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true

uv run python "$run_root/run_sequence_pair15r2_pair20.py"
run_exit_code=$?
printf '%s\n' "$run_exit_code" > "$run_root/sequence.exit_code"
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$run_root/finished_at.txt"
exit "$run_exit_code"
```

Use `printf`, not zsh-only `print`, so the exit marker works even if the launcher is interpreted by `sh`.

- [ ] **Step 5: Validate before pair output exists**

```bash
uv run python -m py_compile "$SEQUENCE_ROOT/run_sequence_pair15r2_pair20.py"
zsh -n "$SEQUENCE_ROOT/launch_sequence.zsh"
grep -q '"15-R2", "16", "17", "18", "19", "20"' \
  "$SEQUENCE_ROOT/run_sequence_pair15r2_pair20.py"
test ! -e "$SEQUENCE_ROOT/pairs"
git status --short
```

Expected: syntax checks pass, pair order is exact, no output exists, and tracked worktree is clean.

- [ ] **Step 6: Launch tmux and prove Pair-15-R2 no-SNI Part 1 started**

```bash
SESSION="deepmast-pair15r2-pair20-sequential-${SEQUENCE_UTC}"
tmux new-session -d -s "$SESSION" -c \
  /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/fix/post-repair-integrity zsh
tmux send-keys -t "$SESSION":0.0 \
  "zsh $SEQUENCE_ROOT/launch_sequence.zsh > $SEQUENCE_ROOT/sequence.stdout_stderr.log 2>&1" \
  C-m
sleep 8
tmux list-panes -t "$SESSION" \
  -F 'session=#{session_name} dead=#{pane_dead} command=#{pane_current_command} pid=#{pane_pid}'
jq -e '
  .status == "running"
  and .pair_order == ["15-R2", "16", "17", "18", "19", "20"]
  and .runs[0].pair_id == "15-R2"
  and .runs[0].status == "running"
' "$SEQUENCE_ROOT/sequence_status.json"
test -f "$SEQUENCE_ROOT/pairs/pair-15-R2/wiki-off/logs/part1.stdout.log"
test -f "$SEQUENCE_ROOT/pairs/pair-15-R2/wiki-off/logs/part1.stderr.log"
```

Expected: live tmux pane, running Pair-15-R2, and no-SNI Part 1 logs.

---

### Task 6: Verify the completed six-pair sequence

**Files:**
- Read: `$SEQUENCE_ROOT/sequence_status.json`, `pairs/summary.json`, condition manifests, guardrail results, recovery audits, timings, and exit markers
- Modify: no tracked file

**Interfaces:**
- Consumes: finished Task 5 sequence
- Produces: Pair-15-R2 through Pair-20 outcome table with exact failure boundaries

- [ ] **Step 1: Wait for terminal sequence evidence**

Monitor status, tmux/process liveness, latest file timestamps, and endpoints. A quiet model call is not failure while process and services remain live.

Require:

```bash
jq -e '.status == "passed" or .status == "failed"' \
  "$SEQUENCE_ROOT/sequence_status.json"
test -f "$SEQUENCE_ROOT/sequence.exit_code"
test -f "$SEQUENCE_ROOT/finished_at.txt"
```

- [ ] **Step 2: Inspect every started Pair and condition**

```bash
jq . "$SEQUENCE_ROOT/sequence_status.json"
find "$SEQUENCE_ROOT" -maxdepth 1 -name 'pair*.exit_code' \
  -print -exec cat {} \;
find "$SEQUENCE_ROOT/pairs" -name run_manifest.json -print | sort | \
  while read -r manifest; do
    jq -c '{pair_id,condition_label,return_status,error,metrics}' "$manifest"
  done
```

Expected: every started Pair has a terminal record and marker. A failed Pair continues unless endpoint state is unhealthy.

- [ ] **Step 3: Verify passed conditions and classify failed ones**

Verify all passed condition manifests with this loop:

```bash
find "$SEQUENCE_ROOT/pairs" -name run_manifest.json -print | sort | \
  while read -r manifest; do
    if jq -e '.return_status == "passed"' "$manifest" >/dev/null; then
      jq -e \
        '([.metrics.artifacts[]?.final_error_count] | all(. == 0))' \
        "$manifest"
    fi
  done
```

For each failure, report the first exact boundary from manifest, guardrail result, Reporter recovery, RAG audit, or stderr. Do not relabel content/Reporter/RAG failure as infrastructure.

- [ ] **Step 4: Verify repository and original evidence integrity**

```bash
git status --short
git diff --check
test -f \
  res/deep_interpreter/bc/sni_repair_ablation/post_deterministic_finalization_pair13r2_pair14_pair15_sequential_20260829T005328Z/pairs/pair-15/wiki-on/run_manifest.json
```

Expected: clean tracked worktree, clean diff check, and original Pair-15 evidence present.

- [ ] **Step 5: Deliver the evidence-backed sequence report**

Include reviewed code HEAD; both replay paths/results; sequence root and tmux terminal state; Pair-15-R2 through Pair-20 no-SNI/SNI status; final hard-error counts; Reporter recovery use/attempt count; RAG or endpoint failures; skipped Pairs; collection 100/1553 confirmation; and original evidence integrity.

---

## Self-review Checklist

- [ ] Only one production function and one existing test file change.
- [ ] Pair-15 RED uses real deterministic repair and forbids model fallback.
- [ ] General equal-count semantic progress remains rejected.
- [ ] Same-target, overlapping, mixed, phase-changing, and count-increasing cases remain rejected.
- [ ] Explicit inline-citation errors remain hard until removed.
- [ ] Reporter recovery, timeouts, attempts, RAG, SGCP-RAG, and Parts are unchanged.
- [ ] Both isolated replays precede full-pair execution.
- [ ] Original Pair-15 and Part files remain immutable.
- [ ] Batch continuation distinguishes content/Reporter failures from endpoint failure.
- [ ] Launcher uses portable `printf`, so `sequence.exit_code` is always written.
- [ ] Named functions, fields, IDs, ports, UUID, and paths are consistent.
- [ ] No unresolved marker, dependency, speculative abstraction, or unrelated cleanup remains.
