# Inline Citation Prompt Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing semantic repair prompt for unsupported inline citations, prove the exact failed artifact reaches zero errors, then complete one fresh no-SNI/SNI pair.

**Architecture:** Add one prompt-only contract to `_build_claim_prompt`; keep the structured decision schema, target splicing, validators, retries, and guardrail controller unchanged. A disposable canonical artifact replay gates the final full pair.

**Tech Stack:** Python 3.12, pytest, existing Pydantic/LangChain structured repair, Ollama qwen3.5:122b, SGCP-RAG.

**Spec:** `docs/superpowers/specs/2026-08-20-inline-citation-prompt-recovery-design.md`

## Global Constraints

- Modify only the semantic repair prompt in production code.
- Do not add error-code repair dispatch, deterministic rewrite templates, or deletion fallback.
- Preserve current-analysis pair names, measurements, and scores.
- Remove a flagged unsupported inline PMID when evidence reports no supporting PMID.
- Separate dataset-derived observation from literature attribution and mechanism.
- Keep exact target matching, structured `replace|delete`, heading checks, no-new-PMID checks, bounded retries, and fail-closed behavior unchanged.
- Do not change validators, controller, Report Guardrail, save recovery, Part generation, Reporter, RAG, SNI, or collections.
- Run a disposable exact-artifact replay before a fresh pair.
- Use ports 4000/6000, API 8883, `qwen3.5:122b`, fixed UUID `a208e916-bd32-405a-9eee-de4cd82b2a3b`, 100 documents, and 1,553 chunks.
- Run pair 05 globally serial, no-SNI first; SNI starts only after no-SNI passes.
- Follow RED → GREEN TDD and Lore commits.

---

### Task 1: Add the unsupported-inline-citation prompt contract

**Files:**
- Modify: `scripts/repair_report.py:261-282`
- Modify: `tests/scripts/test_repair_report.py`

**Interfaces:**
- Preserve: `_build_claim_prompt(issues: list[dict[str, Any]], claim: str) -> str`.
- Preserve: `RepairDecision`, `_invoke_repair_decision`, `_safe_semantic_decision`, `repair_issues`, and `repair_report`.

- [ ] **Step 1: Write the RED prompt-contract test**

Add this production-shaped test:

```python
def test_inline_unsupported_prompt_removes_pmid_and_preserves_dataset_observation() -> None:
    target = (
        "CDH1-ERBB3 emerges as the dominant spatial communication network "
        "(Moran's R = 0.4767, combined score = 0.8141) "
        "(PMID: 28174229)"
    )
    prompt = repair_report._build_claim_prompt(
        [
            {
                "code": "inline_citation_unsupported",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Part 2 Summary",
                "value": target,
                "target_text": target,
                "inline_pmid": "28174229",
                "evidence": "The claim is unsupported. PMIDs: none.",
                "repair_instruction": (
                    "Remove the unsupported assertion or mark it as a hypothesis; "
                    "do not add a new PMID."
                ),
            }
        ],
        target,
    )

    assert "never retain the flagged inline PMID" in prompt
    assert "current analysis" in prompt
    assert "Preserve measured values and pair names" in prompt
    assert "Remove unsupported literature attribution" in prompt
    assert "Choose delete only when no supported dataset-derived observation remains" in prompt
```

- [ ] **Step 2: Verify RED**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_repair_report.py::test_inline_unsupported_prompt_removes_pmid_and_preserves_dataset_observation
```

Expected: FAIL because the binding phrases are absent.

- [ ] **Step 3: Add the minimal prompt instructions**

Insert these instructions in `_build_claim_prompt` before the final output
format requirement:

```text
For inline citation issues whose evidence reports no supporting PMID:
- never retain the flagged inline PMID;
- preserve measured values and pair names as observations from the current analysis;
- remove unsupported literature attribution, causal interpretation, and mechanistic extension;
- do not present dataset-derived measurements as literature-supported findings;
- choose delete only when no supported dataset-derived observation remains.
```

Do not add Python branching on issue codes.

- [ ] **Step 4: Run focused and regression tests to GREEN**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run ruff check scripts/repair_report.py tests/scripts/test_repair_report.py
uv run python -m py_compile scripts/repair_report.py
git diff --check
```

- [ ] **Step 5: Commit Task 1 with Lore trailers**

```bash
git add scripts/repair_report.py tests/scripts/test_repair_report.py
git add -f \
  docs/superpowers/plans/2026-08-20-inline-citation-prompt-recovery.md \
  docs/superpowers/specs/2026-08-20-inline-citation-prompt-recovery-design.md
git commit -m "Keep unsupported citations out of dataset observations

Constraint: Preserve measured values while removing unsupported inline evidence
Rejected: Per-code deterministic rewrite | The common semantic contract remains sufficient
Rejected: Automatic citation stripping | Final meaning still requires semantic repair
Confidence: high
Scope-risk: narrow
Directive: Treat PMIDs-none inline issues as current-analysis observations or delete them
Tested: repair, validate-repair, and guardrail middleware suites; Ruff; py_compile; diff check
Not-tested: Live qwen3.5:122b artifact replay"
```

---

### Task 2: Replay the exact failed no-SNI artifact from one error to zero

**Files:**
- Verification only; mutate a `mktemp -d` copy.

**Interfaces:**
- Consume: Task 1 prompt contract.
- Produce: final error count zero, preserved headings/PMIDs, fixed UUID audit, and immutable source evidence.

- [ ] **Step 1: Copy and bind the exact failed artifact**

```bash
inline_replay_source="res/deep_interpreter/bc/sni_repair_ablation/save_recovery_20260820T041110Z/pairs/pair-05/wiki-off"
inline_replay_dir="$(mktemp -d /tmp/deepmast-inline-citation-replay.XXXXXX)"
inline_pristine_dir="$(mktemp -d /tmp/deepmast-inline-citation-pristine.XXXXXX)"
cp -R "${inline_replay_source}/." "${inline_replay_dir}/"
cp -R "${inline_replay_source}/." "${inline_pristine_dir}/"
diff -qr "${inline_replay_source}" "${inline_replay_dir}"
diff -qr "${inline_replay_source}" "${inline_pristine_dir}"
```

- [ ] **Step 2: Run the canonical bounded guardrail with raw logging**

```bash
inline_replay_log="$(pwd)/.superpowers/sdd/2026-08-20-inline-citation-prompt-recovery/task-2-replay.log"
set -o pipefail
CCI_RAG_BASE_URL=http://localhost:8883 \
OLLAMA_BASE_URL=http://localhost:6000 \
OLLAMA_MODEL=qwen3.5:122b \
OLLAMA_REASONING=true \
OLLAMA_REQUEST_TIMEOUT_SECONDS=10800 \
CLAIM_RAG_JUDGE_NUM_PREDICT=3000 \
CLAIM_RAG_JUDGE_TIMEOUT_SECONDS=300 \
CLAIM_RAG_PRIMARY_JUDGE_TIMEOUT_SECONDS=180 \
CLAIM_RAG_SINGLE_CLAIM_TIMEOUT_SECONDS=120 \
LLM_PROVIDER=ollama \
DEEP_INTERPRETER_USE_WIKI_CONTEXT=false \
DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true \
DEEP_INTERPRETER_FIXED_COLLECTION_ID=a208e916-bd32-405a-9eee-de4cd82b2a3b \
DEEP_INTERPRETER_RAG_AUDIT_PATH="${inline_replay_dir}/rag_audit_inline_replay.jsonl" \
uv run python - "${inline_replay_dir}" <<'PY' 2>&1 | tee "${inline_replay_log}"
import json
import sys
from pathlib import Path

from src.agents.deep_interpreter.report_guardrails import run_report_guardrail

data_dir = Path(sys.argv[1]).resolve()
(data_dir / "repair_trace.jsonl").touch()
result = run_report_guardrail(data_dir, provider="ollama")
initial = json.loads((data_dir / "report_validation_initial.json").read_text())
final = json.loads((data_dir / "report_validation_final.json").read_text())
initial_errors = [issue for issue in initial["issues"] if issue.get("severity") == "error"]
final_errors = [issue for issue in final["issues"] if issue.get("severity") == "error"]
print(json.dumps({"result": result, "initial_errors": initial_errors, "final_errors": final_errors}, indent=2))
assert len(initial_errors) == 1
assert initial_errors[0]["code"] == "inline_citation_unsupported"
assert result["status"] == "passed"
assert result["final_error_count"] == 0
assert not final_errors
PY
inline_replay_rc=$?
test "${inline_replay_rc}" -eq 0
```

Require fresh `initial_error_count == 1`, code
`inline_citation_unsupported`, `status == "passed"`, and
`final_error_count == 0`.

- [ ] **Step 3: Verify the exact target and invariants**

Require:

- the flagged PMID 28174229 is absent from the repaired exact target;
- Moran's R `0.4767` and combined score `0.8141` remain unless the model chose
  structured delete for the complete target;
- before/after heading sequences match;
- no new PMID appears;
- every RAG audit row uses fixed UUID
  `a208e916-bd32-405a-9eee-de4cd82b2a3b` and wiki context false; and
- the historical source equals the pristine copy.

- [ ] **Step 4: Stop on replay failure**

Do not launch a full pair unless every replay assertion passes.

---

### Task 3: Complete one fresh no-SNI then SNI pair

**Files:**
- Live verification only.

**Interfaces:**
- Consume: reviewed Task 1 and passed Task 2 replay.
- Produce: both pair-05 condition manifests passed and comparison metrics.

- [ ] **Step 1: Recheck dependencies and invariants**

Confirm 4000/6000 model health including a real 6000 generate, 8883 health,
fixed collection UUID/counts, exact source/collection 100-PMID identity,
no-SNI → SNI order, and no active runner.

- [ ] **Step 2: Launch a new globally serial pair**

```bash
inline_recovery_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
inline_recovery_root="res/deep_interpreter/bc/sni_repair_ablation/inline_recovery_${inline_recovery_stamp}/pairs"
uv run python scripts/run_bc_sni_repair_ablation.py \
  --pair 5 \
  --output-root "${inline_recovery_root}" \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc \
  --manifest res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json
```

No external total timeout. Fail-fast remains binding.

- [ ] **Step 3: Verify and summarize**

Require no-SNI passed before SNI, both final report/synthesis hard-error counts
zero, headings preserved, no new PMIDs, fixed 100-PMID identity, safe repair
audit, both manifests passed, summary generated, and no lingering runner.

Report per condition: initial/final errors, regular/terminal/total repairs,
deterministic/replace/delete counts when auditable, changed targets, retrieval
attempts/positive/zero-hit/unique PMIDs/time, total elapsed, and PMID flow.

---

## Plan Self-Review

- Prompt-only production scope is enforced.
- The exact failing claim shape is represented in RED.
- Replay is the proof gate for real qwen3.5:122b behavior.
- The final pair is blocked after any replay failure.
- No validator/controller/architecture change or per-code repair branch exists.
- All functions, tests, commands, values, stop conditions, and Lore trailers are explicit.
