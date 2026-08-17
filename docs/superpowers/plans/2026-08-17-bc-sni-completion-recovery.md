# BC SNI Completion Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the two defects exposed by the timed smoke, then complete one fresh canonical BC no-SNI to SNI pair without an external total-pair cutoff.

**Architecture:** Keep repair at the narrowest existing boundary. Failed inline citations receive an exact-claim replacement while all other section content remains byte-for-byte unchanged; non-inline issues retain the existing guarded whole-section path. Normalize malformed retrieval cache state at checkpoint load, then prove recovery on a disposable artifact copy before starting a fresh serial pair.

**Tech Stack:** Python 3.12, pytest, Ruff, stdlib JSON/regex/path handling, existing DeepMAST report guardrails and ablation runner.

## Global Constraints

- Canonical source is `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc` for the live pair; the failed condition directory is diagnostic input only.
- Fixed collection UUID is `a208e916-bd32-405a-9eee-de4cd82b2a3b`, and source/collection PMID sets must be exactly equal with 100 PMIDs.
- Port 4000 is the RAG model backend; port 6000 is the Interpreter/Reporter model backend; both use `qwen3.5:122b`.
- Pair 05 remains globally serial in frozen order no-SNI then SNI.
- No external total-pair timeout is applied; existing call-level and reporter-attempt failure boundaries remain.
- Unsupported or overclaimed content is rewritten at exact-claim scope, not deleted.
- A claim replacement must be non-empty, contain no Markdown heading, and introduce no PMID absent from the original claim.
- Every character outside the exact claim remains unchanged; the existing exact-heading and 50% whole-section guard is not relaxed.
- Malformed retrieval checkpoint state is normalized at load and never treated as a cache hit.
- No new dependency, middleware, SGCP-RAG change, collection mutation, evidence-ranking change, or replicate run.
- Every production behavior change follows RED to GREEN TDD and ends in a Lore-format commit.

---

### Task 1: Add safe exact-claim repair for unresolved inline citations

**Files:**
- Modify: `scripts/repair_report.py`
- Modify: `tests/scripts/test_repair_report.py`

**Interfaces:**
- Produces: `_safe_claim_replacement(original: str, candidate: str) -> bool`.
- Produces: `_build_claim_prompt(issues: list[dict[str, Any]], claim: str) -> str`.
- Extends: `repair_report(...)` groups unresolved `inline_citation_unsupported` and `inline_citation_overclaimed` rows by `(file, section, value)` and invokes the model once per unique claim.
- Preserves: `_repair_inline_citation_issue(...)` supported-sibling behavior and guarded whole-section repair for non-inline issue codes.

- [ ] **Step 1: Write the failing exact-claim repair regression**

Add a test with a section containing multiple subheadings, unrelated text, and one claim that has two failed inline PMIDs. Use a fake model that returns only this literal replacement:

```python
replacement = (
    "ERBB2 overexpression is associated with breast-cancer progression "
    "(PMID: 28174229), while NRG1-ERBB3 signaling was required for "
    "circulating-tumor-cell survival in the cited model (PMID: 39753722)."
)
```

Assert that `repair_report(...)` invokes the fake model once, returns `1`, replaces only the exact original claim, preserves every heading in order, and leaves unrelated section text unchanged.

- [ ] **Step 2: Verify RED**

Run the exact new node ID. Expected: the current whole-section path prepends the section heading to a claim-only response, rejects it under `_safe_section_replacement`, and returns zero changes.

- [ ] **Step 3: Add unsafe candidate regressions**

Parameterize candidates that are empty, contain a Markdown heading, or introduce `PMID: 99999999`. Assert zero changes and exact original-file preservation. Name the production mutations caught: accepting deletion, accepting nested section output, and accepting invented evidence.

- [ ] **Step 4: Implement the minimal claim-scoped path**

After deterministic repair, collect unresolved inline issues by exact claim identity. Require the claim to occur exactly once in the named section. Invoke one claim-only prompt with all issue rows for that claim, validate the candidate with `_safe_claim_replacement`, and splice only that substring. Do not send unresolved inline issues to the whole-section rewrite path.

The claim prompt must require preservation of supported quantitative observations, separation of dataset-derived observations from literature-supported context, no new PMID, and claim-only Markdown output.

- [ ] **Step 5: Run repair verification**

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run ruff check scripts/repair_report.py tests/scripts/test_repair_report.py
uv run python -m py_compile scripts/repair_report.py tests/scripts/test_repair_report.py
git diff --check
```

- [ ] **Step 6: Commit Task 1**

Commit only repair code and tests. The Lore record must name rejected claim deletion and relaxed section-integrity checks.

---

### Task 2: Normalize malformed retrieval checkpoints and remove tracked SDD scratch

**Files:**
- Modify: `src/agents/deep_interpreter/claim_rag_validation.py`
- Modify: `tests/agents/deep_interpreter/test_claim_rag_validation.py`
- Untrack while preserving locally: `.superpowers/sdd/2026-08-16-post-repair-integrity-runtime/task-3-report.md`

**Interfaces:**
- Extends: `_load_checkpoint(path: Path) -> dict[str, Any]` returns a dictionary-valued `retrievals` field for every accepted version-1 checkpoint.
- Preserves: a valid `batches` mapping when only `retrievals` is malformed.

- [ ] **Step 1: Write the failing malformed-checkpoint regression**

Create a real `claim_rag_checkpoint.json` with:

```python
{"version": 1, "batches": {}, "retrievals": []}
```

Run `validate_claims(...)` with the existing fake search/model pattern. Assert one retrieval occurs, validation returns normally, and the rewritten checkpoint contains a dictionary-valued `retrievals` field.

- [ ] **Step 2: Verify RED**

Run the exact new node ID. Expected: `AttributeError: 'list' object has no attribute 'get'` from `_judge_group`.

- [ ] **Step 3: Implement normalization at the load boundary**

After version and `batches` validation, replace any non-dictionary `retrievals` value with `{}`. Do not add duplicate defensive branches to `_judge_group`; all persisted checkpoint input enters through `_load_checkpoint`.

- [ ] **Step 4: Remove only the tracked scratch entry**

Use `git rm --cached` for the ignored Task 3 SDD report so the local ledger evidence remains available but the branch no longer adds orchestration scratch.

- [ ] **Step 5: Run Claim-RAG verification**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run ruff check \
  src/agents/deep_interpreter/claim_rag_validation.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py
uv run python -m py_compile \
  src/agents/deep_interpreter/claim_rag_validation.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py
git diff --check
```

- [ ] **Step 6: Commit Task 2**

Commit checkpoint normalization, its regression, and the index-only scratch cleanup with Lore trailers.

---

### Task 3: Prove recovery and complete a fresh canonical pair

**Files:**
- Verification only; generated artifacts remain under ignored result or temporary directories.
- Do not commit live result folders.

**Interfaces:**
- Consumes: the completed Task 1 and Task 2 behavior.
- Produces: one fresh pair 05 result with complete no-SNI and SNI manifests plus a comparison summary.

- [ ] **Step 1: Run the combined regression suite and static checks**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/test_rag_path_resolution.py \
  tests/test_sni_ablation_runner.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py
```

Run Ruff on every changed Python file, `py_compile` on changed production modules, `git diff --check`, and Pyright if available. Record Pyright as a validation gap when unavailable.

- [ ] **Step 2: Replay the failed no-SNI guardrail on a disposable copy**

Copy the failed no-SNI condition to a newly created temporary directory, preserve the original artifact, and run `run_report_guardrail(...)` with the same no-SNI RAG binding and port-6000 model settings. Compare heading sequences before and after.

Require `status == "passed"`, `final_error_count == 0`, and exact heading equality for all three part reports. If this fails, return to Task 1's TDD loop; do not start the full pair.

- [ ] **Step 3: Recheck live dependencies**

Verify `qwen3.5:122b` appears on both Ollama endpoints, the API on 8883 is healthy, and the fixed collection still reports 100 documents and 1,553 chunks. Let the runner independently prove exact 100-PMID equality.

- [ ] **Step 4: Start one fresh serial pair without an external total cutoff**

```bash
uv run python scripts/run_bc_sni_repair_ablation.py \
  --pair 5 \
  --output-root res/deep_interpreter/bc/sni_repair_ablation/completion_<UTC>/pairs \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc \
  --manifest res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json
```

Do not wrap this command with `timeout`. Monitor stage progress and stop only for an actual terminal error, user cancellation, or unrecoverable infrastructure loss.

- [ ] **Step 5: Validate and summarize both conditions**

Run the runner's `--summarize` mode. Independently inspect both condition manifests and validation artifacts for passed status, exact PMID identity, zero final hard errors, preserved headings, repair counts, retrieval-cache hits, RAG elapsed time, unique queries, duplicate attempts, and unique result PMIDs.

- [ ] **Step 6: Record Task 3 evidence**

Create no empty commit. Append the output root, commands, elapsed times, and comparison to the SDD report and ledger.

---

## Plan Self-Review

- Every design requirement maps to one task.
- Claim deletion, section-guard relaxation, SGCP-RAG changes, collection mutation, and partial-run reuse are explicitly excluded.
- The malformed checkpoint fix is located at the persisted-input boundary only.
- Live completion uses the canonical source and a fresh root, not the diagnostic artifact.
- The external four-hour cutoff is removed, while existing bounded internal attempts remain.
- All production changes have explicit RED and GREEN commands and separate reviewable commits.
