# Minimal Hybrid Report Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Deep Interpreter Report Guardrail with a minimal field-driven hybrid repair path, prove it with a fast Part 1/2 smoke and saved-artifact replay, then complete one canonical no-SNI/SNI pair.

**Architecture:** Existing validator issues keep their current shape and may add `target_text` and `replacement_text`. The existing repair module resolves exact or whitespace-normalized local targets, applies validator-provided deterministic replacements when available, otherwise performs one constrained exact-text LLM rewrite, and fails closed when target resolution or safety is ambiguous. The production middleware remains unchanged by default; an explicit Part 1/2 smoke scope reuses the same guardrail loop.

**Tech Stack:** Python 3.12, pytest, Ruff, stdlib JSON/regex/path handling, existing Ollama and Claim-RAG integrations.

**Spec:** `docs/superpowers/specs/2026-08-18-minimal-hybrid-report-repair-design.md`

## Global Constraints

- Keep the existing Report Guardrail; do not add an agent, middleware, dependency, registry, or repository-wide repair subsystem.
- Keep the existing issue JSON fields and add only optional `target_text` and `replacement_text`.
- Generic repair dispatch is field-driven, not an expanding issue-code repair table.
- Exact target matching is attempted first; fallback matching normalizes whitespace and soft line wraps only.
- Numbers, signs, PMIDs, gene names, punctuation, and case are never normalized.
- Repeated targets are repairable only when grouped issue count equals target occurrence count.
- Generic replacements are non-empty, contain no Markdown heading, introduce no new PMID, and retain at least 50% of target non-whitespace content.
- The existing trusted one-digit PMID correction remains the only exception to the generic no-new-PMID rule.
- Every character outside resolved targets and every Markdown heading remain unchanged.
- Ambiguous, stale, missing, unsupported, or unsafe targets fail closed and remain hard errors.
- No whole-section LLM fallback or fuzzy/embedding matching.
- Production Part guardrail behavior still defaults to Part 1+2+3; filename scoping is explicit and used for smoke only.
- Canonical live runs retain source/collection equality for exactly 100 PMIDs, RAG backend port 4000, Interpreter/Reporter port 6000, model `qwen3.5:122b`, pair 05 no-SNI then SNI, and no external total timeout.
- no-SNI must pass before SNI starts.
- Every production behavior change follows RED to GREEN TDD and ends in a Lore-format commit.

---

### Task 1: Add the field-driven generic repair executor

**Files:**
- Modify: `scripts/repair_report.py`
- Modify: `tests/scripts/test_repair_report.py`

**Interfaces:**
- Produce: `repair_issues(data_dir: Path, issues: list[dict[str, Any]], *, llm: Any | None = None, provider: str | None = None, claim_validation: list[dict[str, Any]] | None = None) -> int`.
- Keep: `repair_report(...) -> int` as a file-loading wrapper around `repair_issues(...)`.
- Produce: `_target_spans(section_text: str, target_text: str) -> tuple[str, list[tuple[int, int]]]`, where mode is `exact`, `whitespace_normalized`, or `missing`.
- Consume: optional issue fields `target_text` and `replacement_text`.
- Preserve: existing trusted PMID and supported-sibling citation handlers.

- [ ] **Step 1: Write failing deterministic and semantic target tests**

Add tests that exercise real file output:

```python
def test_repair_uses_validator_replacement_text_without_llm(tmp_path: Path) -> None:
    original = "## Results\nLRIG1-ERBB3 Moran's R = 0.4213.\n"
    issue = {
        "code": "lr_metric_value_mismatch",
        "severity": "error",
        "file": "part2_final.md",
        "section": "## Results",
        "value": "legacy diagnostic label",
        "target_text": "LRIG1-ERBB3 Moran's R = 0.4213.",
        "replacement_text": "LRIG1-ERBB3 Moran's R = 0.3629.",
    }
    # Write report + issues, use FailLLM, call repair_report.
    assert changed == 1
    assert report.read_text() == "## Results\nLRIG1-ERBB3 Moran's R = 0.3629.\n"
```

Add a semantic companion with `target_text` but no `replacement_text`, a fake LLM returning one safe sentence, and assertions that unrelated text and headings remain exact.

- [ ] **Step 2: Verify RED**

Run the two new node IDs. Expected: current code ignores `replacement_text` and dispatches from issue-code sets instead of fields.

- [ ] **Step 3: Write failing locator and fail-closed tests**

Cover these literal behaviors separately:

- exact match;
- one soft-wrapped whitespace-normalized match;
- repeated target with matching issue count;
- repeated target with mismatched issue count;
- ambiguous normalized match;
- missing target;
- unsafe empty/heading/new-PMID/under-50% LLM replacement; and
- error issue with no supported target.

Each failure case must assert `changed == 0`, exact file preservation, and a metadata-only `repair_trace.jsonl` rejection row.

- [ ] **Step 4: Implement minimal field-driven execution**

Refactor `repair_report(...)` to call `repair_issues(...)`. Group targetable issues by `(file, section, target_text)`. Resolve target spans within the named section, verify repeated counts, choose deterministic `replacement_text` or one LLM claim rewrite, validate the replacement with the existing local safety predicate, and splice spans in reverse order.

Remove whole-section LLM dispatch for hard errors. Issues without optional fields may only use existing trusted deterministic handlers; otherwise record `unhandled_repair_target` and leave the report unchanged.

- [ ] **Step 5: Run Task 1 verification**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py
uv run ruff check scripts/repair_report.py tests/scripts/test_repair_report.py
uv run python -m py_compile scripts/repair_report.py
git diff --check
```

- [ ] **Step 6: Commit Task 1**

Commit only the repair executor and tests. Lore trailers must record whole-section fallback, fuzzy matching, and a strategy registry as rejected alternatives.

---

### Task 2: Make Part validators emit generic targets and deterministic replacements

**Files:**
- Modify: `scripts/validate_report.py`
- Modify: `tests/scripts/test_validate_report.py`
- Modify: `tests/scripts/test_validate_repair_report.py`

**Interfaces:**
- Extend: `_issue(..., target_text: str = "", replacement_text: str = "") -> dict[str, str]`, omitting empty optional fields from serialized issues.
- Produce deterministic `target_text` + `replacement_text` for `lr_metric_value_mismatch` when the actual metric is known from `sig_liana.csv`.
- Produce `target_text` without replacement for semantic/directional issues whose exact wording cannot be deterministically reconstructed.
- Preserve existing issue code, `value`, evidence, severity, and repair instructions.

- [ ] **Step 1: Write failing LR metric contract test**

Extend the existing LR mismatch fixture and assert literal fields:

```python
issue = next(i for i in issues if i["code"] == "lr_metric_value_mismatch")
assert issue["target_text"] == "LRIG1-ERBB3 Moran's R = 0.4213."
assert issue["replacement_text"] == "LRIG1-ERBB3 Moran's R = 0.3629."
```

Assert that the replacement changes only the metric token belonging to the named pair when a sentence mentions more than one pair.

- [ ] **Step 2: Verify LR RED, then implement**

Run the exact LR tests. Expected: optional fields are absent. Add optional `_issue` parameters and build the corrected window from the matched numeric span using `expected:.4f`.

- [ ] **Step 3: Write failing target-only validator tests**

For each hard-error producer below, assert `target_text` is an exact substring of the named section and `replacement_text` is absent unless the validator can construct the entire correction safely:

- `unsupported_mechanistic_interpretation`;
- `unsupported_pathway_factor_significance`;
- `factor_pathway_direction_mismatch`; and
- `part3_therapeutic_spillover`.

Retain current warnings as non-repairing warnings.

- [ ] **Step 4: Implement target-only emission**

Use the already extracted claim window as `target_text`. Do not invent deterministic wording for pathway direction or mechanistic interpretation; their evidence and repair instruction constrain the exact-text LLM path.

- [ ] **Step 5: Verify validate to repair to validate flow**

Add an integration fixture with one deterministic LR metric mismatch and one target-only direction mismatch. Use a fake LLM for the semantic issue, then assert final hard-error count zero and unchanged headings.

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_repair_report.py
uv run ruff check scripts/validate_report.py tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py
uv run python -m py_compile scripts/validate_report.py
git diff --check
```

- [ ] **Step 6: Commit Task 2**

Commit validator optional fields and tests separately from the repair executor.

---

### Task 3: Integrate Claim-RAG and synthesis without replacing trusted repairs

**Files:**
- Modify: `src/agents/deep_interpreter/claim_rag_validation.py`
- Modify: `src/agents/deep_interpreter/report_guardrails.py`
- Modify: `src/agents/deep_interpreter/synthesis_consistency_validation.py`
- Modify: `tests/agents/deep_interpreter/test_claim_rag_validation.py`
- Modify: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`
- Modify: `tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`

**Interfaces:**
- Extend Claim-RAG `_issue_for(...)` issues with `target_text=result["claim"]` for hard semantic and inline citation issues.
- Extend `_synthesis_issue(...)` with optional `target_text` and `replacement_text`.
- Extend synthesis consistency `_add_issue(...)` to mirror existing `value`/`replacement` into `target_text`/`replacement_text` when `repairable` is true.
- Reuse Task 1 `repair_issues(...)` for targetable synthesis issues while preserving explicit inline contradiction repair and existing consistency validation.

- [ ] **Step 1: Write failing Claim-RAG issue-field tests**

Extend current `_issue_for` tests:

```python
issue = claim_rag_validation._issue_for(overclaimed_result)
assert issue["target_text"] == overclaimed_result["claim"]
assert "replacement_text" not in issue
```

Warnings must not gain repair fields.

- [ ] **Step 2: Verify RED, then add Claim-RAG targets**

Run exact issue-field tests, observe missing `target_text`, and add the field only to hard-error issues.

- [ ] **Step 3: Write failing synthesis field tests**

Assert synthesis semantic issues expose exact target text. Assert repairable consistency issues expose both generic fields while unrepairable issues do not.

- [ ] **Step 4: Wire generic synthesis repair conservatively**

In `repair_synthesis_report(...)`, run existing trusted supported-sibling and explicit-contradiction handlers first. Then pass still-present targetable issues to `repair_report_script.repair_issues(...)`. Keep consistency revalidation and the three-pass/terminal-pass bounds unchanged.

- [ ] **Step 5: Run Task 3 verification**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_synthesis_consistency_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/scripts/test_repair_report.py
uv run ruff check \
  src/agents/deep_interpreter/claim_rag_validation.py \
  src/agents/deep_interpreter/report_guardrails.py \
  src/agents/deep_interpreter/synthesis_consistency_validation.py
uv run python -m py_compile \
  src/agents/deep_interpreter/claim_rag_validation.py \
  src/agents/deep_interpreter/report_guardrails.py \
  src/agents/deep_interpreter/synthesis_consistency_validation.py
git diff --check
```

- [ ] **Step 6: Commit Task 3**

Commit semantic/synthesis integration and tests with Lore trailers naming existing trusted deterministic handlers as preserved constraints.

---

### Task 4: Add an explicit Part 1/2 scoped guardrail smoke

**Files:**
- Modify: `src/agents/deep_interpreter/report_guardrails.py`
- Modify: `scripts/run_bc_sni_repair_ablation.py`
- Modify: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`
- Modify: `tests/test_sni_ablation_runner.py`

**Interfaces:**
- Extend: `run_report_guardrail(data_dir, *, provider=None, filenames=REQUIRED_PART_FILES) -> dict[str, Any]`.
- Extend: `_validate_part_reports(..., filenames: tuple[str, ...])` and required-file checks to use the explicit scope.
- Add CLI mode: `--part12-smoke PAIR_ID`.
- Add: `_default_part12_stage_runner(data_dir: Path, env: dict[str, str]) -> int`, running only Part 1 and Part 2 then invoking the same guardrail with `filenames=("part1_final.md", "part2_final.md")`.
- Preserve: default middleware call and full pair behavior without a filenames argument.

- [ ] **Step 1: Write failing scoped guardrail tests**

Create Part 1 and Part 2 fixtures with no Part 3 and assert:

```python
result = run_report_guardrail(
    tmp_path,
    filenames=("part1_final.md", "part2_final.md"),
)
assert result["status"] == "passed"
```

Add a companion proving the default call still returns `{"status": "skipped", "missing": ["part3_final.md"]}`.

- [ ] **Step 2: Verify RED, then implement filename scope**

Run exact tests. Expected: current function rejects the `filenames` argument. Thread the explicit scope through missing-file checks and Claim-RAG validation; keep deterministic validation on the files present in the fresh smoke directory.

- [ ] **Step 3: Write failing runner-stage tests**

Use injected stage functions to assert `--part12-smoke 5` executes only `[("part1", 1), ("part2", 2)]`, invokes scoped guardrail once, never invokes Part 3/Reporter, and writes a passed manifest only after zero hard errors.

- [ ] **Step 4: Implement minimal CLI mode and stage runner**

Reuse condition-copy, exact 100-PMID preflight, environment binding, RAG audit validation, source immutability checks, manifest writing, and diff generation. Run the no-SNI condition only. Do not duplicate the full condition runner.

- [ ] **Step 5: Run Task 4 verification**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/test_sni_ablation_runner.py
uv run ruff check \
  src/agents/deep_interpreter/report_guardrails.py \
  scripts/run_bc_sni_repair_ablation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/test_sni_ablation_runner.py
uv run python -m py_compile src/agents/deep_interpreter/report_guardrails.py scripts/run_bc_sni_repair_ablation.py
git diff --check
```

- [ ] **Step 6: Commit Task 4**

Commit the explicit smoke scope and tests. Lore trailers must state that production default scope remains unchanged.

---

### Task 5: Verify increasing-cost gates before a full pair

**Files:**
- Verification only; copy artifacts to explicit temporary directories.
- Write local reports under the plan's ignored SDD workspace.

**Interfaces:**
- Consumes all prior tasks.
- Produces gate evidence for Part 1/2 smoke and Part 3/synthesis artifact replay.

- [ ] **Step 1: Run combined regression and static checks**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_synthesis_consistency_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/test_rag_path_resolution.py \
  tests/test_sni_ablation_runner.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py
```

Run Ruff on every changed Python file, `py_compile` on changed production modules, `git diff --check`, and Pyright if available. Record Pyright as unavailable when absent.

- [ ] **Step 2: Run one real Part 1/2 no-SNI smoke**

Use `--part12-smoke 5`, canonical source, a fresh output root, RAG backend 4000, and Interpreter backend 6000. Require exact 100-PMID identity, zero final hard errors, unchanged headings, no Part 3/Reporter outputs, and a passed run manifest.

- [ ] **Step 3: Replay saved Part 3 and synthesis artifacts**

Copy this representative complete artifact to a new temporary directory:

`res/deep_interpreter/bc/sni_repair_ablation/task6_20260817T072643Z/pairs/pair-05/wiki-off`

Run `run_report_guardrail(..., filenames=("part3_final.md",))` and the synthesis guardrail on copies only, so historical Part 1/2 content cannot contaminate this gate. Require zero final hard errors, unchanged Part 3/synthesis heading sequences, source immutability, and metadata-only repair audit. Record that generation was skipped while Claim-RAG/LLM repair could still use ports 4000/6000.

- [ ] **Step 4: Stop or release the full run**

If either gate fails, preserve evidence and return to the owning task's TDD loop. If both pass, release Task 6 without an additional human approval.

---

### Task 6: Complete and compare one fresh canonical no-SNI/SNI pair

**Files:**
- Verification/live execution only; generated outputs remain ignored.

**Interfaces:**
- Consumes the passed Task 5 gates.
- Produces one complete pair 05 comparison.

- [ ] **Step 1: Recheck dependencies and collection invariants**

Confirm `qwen3.5:122b` on ports 4000 and 6000, RAG API health, fixed collection UUID `a208e916-bd32-405a-9eee-de4cd82b2a3b`, 100 documents, 1,553 chunks, and no active matching runner.

- [ ] **Step 2: Start one fresh serial pair without an external cutoff**

```bash
uv run python scripts/run_bc_sni_repair_ablation.py \
  --pair 5 \
  --output-root res/deep_interpreter/bc/sni_repair_ablation/hybrid_<UTC>/pairs \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc \
  --manifest res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json
```

Do not wrap with `timeout`. Keep fail-fast: no-SNI must pass before SNI starts.

- [ ] **Step 3: Monitor to terminal and summarize**

Send progress at Part transitions and condition boundaries. Run `--summarize` with the same manifest after terminal completion.

- [ ] **Step 4: Independently verify both conditions**

Require both manifests passed, exact source/collection 100-PMID equality, zero final hard errors, preserved headings, no unsafe repair candidate, and no lingering process.

- [ ] **Step 5: Compare no-SNI and SNI**

Report regular/terminal/total repair counts, changed targets, Claim-RAG selection and cache hits, RAG attempts/positive/zero-hit/unique PMIDs/elapsed time, total condition time, and citation/PMID flow. Create no empty verification commit.

---

## Plan Self-Review

- Every design requirement maps to a task.
- Generic repair dispatch is field-driven; validators supply fields without creating new repair-engine branches.
- Existing trusted deterministic repair and bounded retry behavior are preserved.
- Production full-scope behavior remains the default; Part 1/2 scope is explicit.
- Part 1/2 smoke and artifact replay gate the expensive full pair.
- No placeholder, fuzzy matching, whole-section fallback, dependency, SGCP-RAG change, or collection mutation is introduced.
- All production tasks contain RED and GREEN commands and independent commit/review boundaries.
