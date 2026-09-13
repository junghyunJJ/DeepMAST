# High-Precision Guardrail Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Report Guardrail hard errors to high-confidence objective failures, move uncertain semantic judgments to warning-only audit, and delete semantic repair paths that no longer serve a hard gate.

**Architecture:** Keep exact target repair, atomic rollback, deterministic-first ordering, H1 normalization, and explicit citation repair. Reclassify uncited semantic judgments as warnings, use conservative high-precision rules for factor/pathway direction and Part3 boundary detection, then remove now-dead semantic heading/frontier repair branches.

**Tech Stack:** Python 3.12, pytest, existing Pydantic/LangChain/Ollama integration, SGCP-RAG, existing BC pair runner.

**Spec:** `docs/superpowers/specs/2026-08-22-high-precision-guardrail-simplification-design.md`

## Global Constraints

- Explicit inline citation unsupported/overclaimed remains hard.
- Missing/malformed artifacts, invalid PMID, exact metric mismatch, H1/HTML, and canonical consistency remain hard.
- Uncited Claim-RAG unsupported/overclaimed/unverifiable is warning-only and has no repair target.
- General mechanistic/therapeutic interpretation is warning-only and has no repair target.
- Factor/pathway direction is hard only for an exclusive polarity contradiction in a single-pathway claim.
- Mixed polarity or multi-pathway direction is warning-only.
- Part3 meta-language that reserves therapeutic content for Part4 is not spillover.
- Actual Part3 therapeutic recommendation/ranking remains hard.
- Delete general semantic heading repair, hypothesis-caveat append, and equal-count semantic frontier acceptance.
- Keep byte-exact rollback, deterministic-first, strict same-phase error decrease, and deterministic→semantic transition.
- Add no dependency or LLM validator.
- Use TDD, Lore commits, immutable replay copies, fixed UUID `a208e916-bd32-405a-9eee-de4cd82b2a3b`, and globally serial no-SNI→SNI.

---

### Task 1: Separate semantic warnings from hard evidence failures

**Files:**
- Modify: `src/agents/deep_interpreter/claim_rag_validation.py:741-789`
- Modify: `scripts/validate_report.py:313-340`
- Modify: `src/agents/deep_interpreter/report_guardrails.py:320-590`
- Test: `tests/agents/deep_interpreter/test_claim_rag_validation.py`
- Test: `tests/scripts/test_validate_report.py`
- Test: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`
- Add to commit: this plan and its spec.

**Interfaces:**
- Preserve `_issue_for(result) -> dict | None`.
- Preserve `validate_synthesis_report()` and guardrail result schemas.
- Produce warning issues without `target_text` for non-inline semantic judgments.

- [ ] **Step 1: Write RED Claim-RAG severity tests**

Add/replace tests so these assertions are explicit:

```python
def test_non_inline_overclaim_is_warning_without_repair_target() -> None:
    issue = claim_rag_validation._issue_for(
        {
            "status": "overclaimed",
            "hedged": False,
            "supporting_pmids": ["11111111"],
            "evidence_quote": "TGFB is associated with fibrosis.",
            "reason": "Association only.",
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": None,
            "claim": "TGFB drives fibrosis.",
        }
    )
    assert issue is not None
    assert issue["code"] == "claim_rag_overclaimed"
    assert issue["severity"] == "warning"
    assert "target_text" not in issue


def test_inline_overclaim_remains_hard_and_targeted() -> None:
    issue = claim_rag_validation._issue_for(
        {
            "status": "overclaimed",
            "hedged": True,
            "supporting_pmids": ["11111111"],
            "evidence_quote": "Association only.",
            "reason": "Citation does not support causality.",
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "11111111",
            "claim": "TGFB drives fibrosis (PMID: 11111111).",
        }
    )
    assert issue is not None
    assert issue["code"] == "inline_citation_overclaimed"
    assert issue["severity"] == "error"
    assert issue["target_text"] == issue["value"]
```

- [ ] **Step 2: Write RED general interpretation warning tests**

Add a Parts test proving an unhedged report-derived mechanism emits
`mechanistic_interpretation_warning`, severity warning, and no target. Add a
synthesis test proving an unhedged spatial therapeutic/mechanistic claim emits
`synthesis_overclaim_warning`, severity warning, and no target.

- [ ] **Step 3: Verify RED**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/scripts/test_validate_report.py -k 'mechanistic' \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py -k 'overclaim'
```

- [ ] **Step 4: Implement the hard/soft boundary**

In `_issue_for`, use:

```python
    hard_inline = bool(inline_pmid) and status in {"unsupported", "overclaimed"}
    severity = "error" if hard_inline else "warning"
```

Keep inline issue codes for inline citations and existing `claim_rag_*` codes
for non-inline audit. Add `target_text` only for `hard_inline`.

Make `_check_mechanistic_interpretations` always emit
`mechanistic_interpretation_warning`, severity warning, with no target.

Make synthesis mechanistic/therapeutic overclaims always emit
`synthesis_overclaim_warning`, severity warning, with no target. Structural H1
and HTML errors remain unchanged.

- [ ] **Step 5: Delete dead semantic repair paths**

Delete the trusted semantic-heading repair handler and its tests. Remove
`unsupported_synthesis_overclaim`, non-inline `claim_rag_unsupported`, and
non-inline `claim_rag_overclaimed` from automatic synthesis repair routing.
Delete automatic generic hypothesis-caveat appending for targetless semantic
issues.

Simplify `_strict_phase_progress` so same-phase progress again requires strict
hard-error decrease; retain deterministic→semantic acceptance and reject every
other phase change. Remove equal-count semantic frontier tests.

- [ ] **Step 6: Run regressions and commit**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_repair_report.py \
  tests/deep_interpreter/test_comprehensive_template_report.py
uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py \
  src/agents/deep_interpreter/report_guardrails.py scripts/validate_report.py
uv run python -m py_compile src/agents/deep_interpreter/claim_rag_validation.py \
  src/agents/deep_interpreter/report_guardrails.py scripts/validate_report.py
git diff --check
```

Commit with Lore trailers explaining that uncited semantic judgments moved to
audit while explicit citations remain hard.

---

### Task 2: Make direction and Part3 scope hard errors high precision

**Files:**
- Modify: `scripts/validate_report.py:40-70,585-668`
- Test: `tests/scripts/test_validate_report.py`

**Interfaces:**
- Preserve `validate_report(data_dir) -> list[issue]`.
- Add warning code `factor_pathway_direction_ambiguous` without target.
- Preserve hard `factor_pathway_direction_mismatch` and
  `part3_therapeutic_spillover` for high-confidence cases.

- [ ] **Step 1: Write RED metamorphic direction tests**

Use the exact current false-positive sentences and negative Factor3 estimates.
Require no hard mismatch and at least one ambiguity warning where direction is
mixed or multi-pathway:

```python
assert not [issue for issue in issues if issue["code"] == "factor_pathway_direction_mismatch"]
assert [issue for issue in issues if issue["code"] == "factor_pathway_direction_ambiguous"]
```

Keep two injected single-pathway tests hard:

- negative EGFR estimate + `Factor3 shows EGFR activation`;
- positive EGFR estimate + `Factor3 shows EGFR depletion`.

- [ ] **Step 2: Write RED Part4 boundary tests**

The exact sentence
`therapeutic synthesis and clinical prioritization are reserved for Part 4`
must not emit spillover. Existing actual recommendation tests remain hard.

- [ ] **Step 3: Implement conservative direction classification**

Extend polarity regexes to accept plural `enrichments` and `depletions`.
When an apparent contradiction occurs:

```python
    ambiguous = (positive and negative) or len(pathways) > 1
    if ambiguous:
        issues.append(
            _issue(
                code="factor_pathway_direction_ambiguous",
                severity="warning",
                file=path.name,
                section=str(section["heading"]),
                value=f"{factor_labels[factor]}: {pathway_labels[pathway]} estimate={estimate}",
                evidence="Mixed or multi-pathway wording prevents a high-confidence direction verdict.",
                repair_instruction="Leave unchanged and retain as an audit warning.",
            )
        )
    else:
        # existing hard mismatch issue
```

- [ ] **Step 4: Implement Part4 meta-boundary exclusion**

Add a narrow `PART4_BOUNDARY_RE` requiring both a Part4 reference and a boundary
verb (`reserve`, `defer`, `belong`, `own`, `exclude`, `avoid`). Skip spillover
only when both therapeutic vocabulary and this boundary pattern match.

- [ ] **Step 5: Run tests and commit**

```bash
OPENAI_API_KEY=test uv run pytest -q tests/scripts/test_validate_report.py
uv run ruff check scripts/validate_report.py tests/scripts/test_validate_report.py
uv run python -m py_compile scripts/validate_report.py tests/scripts/test_validate_report.py
git diff --check
```

Commit with Lore trailers documenting the high-precision hard-gate tradeoff.

---

### Task 3: Prove zero false-positive repairs before another pair

**Files:**
- Verification only, immutable temp copies.
- Report: `.superpowers/sdd/2026-08-22-high-precision-guardrail-simplification/task-3-validation-report.md`

**Interfaces:**
- Consume reviewed Tasks 1-2.
- Produce hard/warning counts, repair counts, byte invariants, and one fresh
  Part2/Part3 smoke result.

- [ ] **Step 1: Replay the latest failed no-SNI artifact**

Copy
`res/deep_interpreter/bc/sni_repair_ablation/atomic_repair_recovery_20260822T030707Z/pairs/pair-05/wiki-off`
to replay/pristine temp directories. Run scoped Parts guardrail.

Require:

- hard errors 0;
- accepted changes limited to exact validator-owned targets for explicit inline
  citation unsupported/overclaimed errors;
- all false-positive direction sentences byte-identical;
- the Part4 boundary sentence byte-identical;
- three unique direction warning values retained, allowing repeated occurrences
  in different sections;
- Part4 boundary sentence retained without spillover.
- immediate second guardrail run: hard errors 0, repair attempts 0, changed
  sections 0, and byte-identical to the first retained result.

- [ ] **Step 2: Replay the historical corpus**

Run the existing inline/direction/table corpus. Require final hard errors 0,
idempotence, and immutable sources. General semantic warnings may remain; explicit
inline citation hard errors must still repair to zero.

For the historical raw-HTML `synthesis.md` fixture, call
`run_synthesis_guardrail` directly and require deterministic fail-closed
evidence instead of repair success:

- final hard error is exactly `synthesis_not_markdown`;
- `synthesis.md` bytes are unchanged;
- claim RAG validation and synthesis consistency validation do not run;
- immediate second call returns the same hard rejection with identical bytes;
- `changed_claims` is 0.

Do not require repair attempts 0 if the controller records a bounded no-op
attempt. HTML in `synthesis.md` remains blocked from runtime publication.

- [ ] **Step 3: Run one fresh Part2/Part3-only smoke**

Use a fresh copy of the canonical BC source, fixed UUID, wiki-off, and
`qwen3.5:122b`. Generate Part2 then Part3 only and run the scoped guardrail.
Require zero false-positive hard errors and no repair of correct direction or
Part4-boundary wording.

- [ ] **Step 4: Record precision evidence**

Report:

- expected hard errors detected in injected tests;
- correct paraphrases producing no hard errors;
- warning counts by code;
- repair attempts and changed sections;
- RAG calls/time;
- source/pristine equality.

Do not start Task 4 on any failure.

---

### Task 4: Run one fresh no-SNI then SNI pair

**Files:**
- Live verification only.
- Report: `.superpowers/sdd/2026-08-22-high-precision-guardrail-simplification/task-4-final-pair-report.md`

- [ ] **Step 1: Preflight**

Verify reviewed HEAD, clean worktree, no runner, 4000/6000/8883 health, real
6000 generation, fixed UUID/counts, and exact 100-PMID identity.

- [ ] **Step 2: Launch durable tmux pair**

Use a fresh `high_precision_guardrail_<UTCSTAMP>/pairs` root and the existing
pair-05 runner. Run no-SNI first; SNI starts only after no-SNI passes.

- [ ] **Step 3: Verify and compare**

Require both manifests passed, objective hard errors 0, explicit inline citation
errors repaired, H1/HTML outputs present, no new PMID, warnings audited, fixed
identity, experiment summary, and no lingering runner.

Compare per condition:

- deterministic/semantic hard errors;
- warning counts by code;
- accepted repairs and changed targets;
- retrieval coverage and timing;
- total elapsed.

---

## Final Verification

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_repair_report.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/deep_interpreter/test_comprehensive_template_report.py \
  tests/test_sni_ablation_runner.py
uv run ruff check scripts/validate_report.py \
  src/agents/deep_interpreter/claim_rag_validation.py \
  src/agents/deep_interpreter/report_guardrails.py
uv run python -m py_compile scripts/validate_report.py \
  src/agents/deep_interpreter/claim_rag_validation.py \
  src/agents/deep_interpreter/report_guardrails.py
git diff --check
git status --short --branch
```

Do not claim completion until Task 3 precision gates and both final pair
conditions pass.
