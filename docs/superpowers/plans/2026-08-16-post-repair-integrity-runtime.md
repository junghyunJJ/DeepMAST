# Post-Repair Integrity and Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one canonical BC no-SNI/SNI pair safe, corpus-aligned, resumable, and measurable before any replicated experiment.

**Architecture:** Keep every change at an existing boundary: runner preflight for corpus identity, `repair_report` before-write validation, Claim-RAG's persistent checkpoint for retrieval reuse, the existing RAG audit writer for observability, and reporter recovery prompt selection for resume. No new middleware, service, dependency, or SGCP-RAG repository change is introduced.

**Tech Stack:** Python 3.12, pytest, Ruff, stdlib JSON/hash/regex/time/urllib, existing DeepMAST report and RAG modules.

## Global Constraints

- Canonical BC source is exactly `res/deep_interpreter/bc/bc`.
- Fixed collection UUID remains `a208e916-bd32-405a-9eee-de4cd82b2a3b` with 100 source PMIDs and 1,553 chunks.
- Source `papers.json` and collection document filenames must contain the same 100 PMIDs before a stage runs.
- Unsafe section repair preserves the original section, reports zero change for that candidate, and performs no automatic retry.
- Section repair preserves the exact Markdown heading sequence and at least 50% of original non-whitespace characters.
- Retrieval cache identity includes claim text, ordered candidate PMIDs, fixed collection ID, wiki-context condition, and evidence-policy version.
- Transport/infrastructure retrieval failures are never persisted as successful cache entries.
- RAG audit additions are observational and do not change retrieval ranking or citation selection.
- Valid existing synthesis is preserved during reporter recovery; invalid or absent synthesis is rebuilt.
- No new dependency, SGCP-RAG repository change, citation-diversity quota, model change, or ten-pair execution.
- Every production behavior change follows RED → GREEN TDD and each task ends in a Lore-format commit.

---

### Task 1: Bind the ablation runner to the canonical 100-PMID corpus

**Files:**
- Modify: `scripts/run_bc_sni_repair_ablation.py:20-130,590-665`
- Modify: `tests/test_sni_ablation_runner.py`

**Interfaces:**
- Produces: `BC_SOURCE = REPO_ROOT / "res/deep_interpreter/bc/bc"`.
- Produces: `_papers_pmids(path: Path) -> set[str]`.
- Produces: `_collection_pmids(api_url: str) -> set[str]`, paginating `/collections/{BC_COLLECTION_ID}/documents?limit=100&offset=N` and parsing `metadata.filename` with `^pmid_(\d+)\.txt$`.
- Consumes: existing collection metadata snapshot and `source / "papers.json"`.

- [ ] **Step 1: Write failing source-path and PMID-set tests**

Add tests that assert the default source is repository-relative and that a run fails before `stage_runner` when source and collection PMIDs differ:

```python
def test_bc_runner_defaults_to_canonical_bc_source() -> None:
    assert bc_runner.BC_SOURCE == bc_runner.REPO_ROOT / "res/deep_interpreter/bc/bc"


def test_bc_runner_rejects_collection_pmid_mismatch_before_stage(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    (source / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": str(i)} for i in range(100)]}),
        encoding="utf-8",
    )
    stage_called = False

    def stage_runner(_data_dir: Path, _env: dict[str, str]) -> int:
        nonlocal stage_called
        stage_called = True
        return 0

    rc = bc_runner.run_condition(
        source=source,
        output_root=tmp_path / "runs",
        pair=_pair("01"),
        condition=bc_runner.CONDITION_BY_LABEL["no-SNI"],
        stage_runner=stage_runner,
        collection_snapshot=lambda _url: stack.BC_COLLECTION_SNAPSHOT,
        collection_pmids=lambda _url: {str(i) for i in range(99)},
    )

    assert rc == 1
    assert stage_called is False
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/test_sni_ablation_runner.py::test_bc_runner_defaults_to_canonical_bc_source \
  tests/test_sni_ablation_runner.py::test_bc_runner_rejects_collection_pmid_mismatch_before_stage
```

Expected: failures because the legacy absolute source and no PMID preflight are still present.

- [ ] **Step 3: Implement the minimal corpus preflight**

Implement repository-relative source resolution, PMID parsing, REST pagination, an injectable `CollectionPmids` callable, and an equality check before `stage_runner`. Store source/collection PMID counts and a stable SHA-256 of the sorted set in `collection_before.json` or `run_manifest.json`; do not store duplicate full lists in every artifact.

- [ ] **Step 4: Run focused and runner suites**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q tests/test_sni_ablation_runner.py
uv run ruff check scripts/run_bc_sni_repair_ablation.py tests/test_sni_ablation_runner.py
uv run python -m py_compile scripts/run_bc_sni_repair_ablation.py tests/test_sni_ablation_runner.py
git diff --check
```

Expected: all runner tests pass and output is clean.

- [ ] **Step 5: Commit Task 1**

Commit only the runner and its tests with a Lore message explaining why corpus identity is now checked, the rejected count-only alternative, and the exact focused test evidence.

---

### Task 2: Reject structurally destructive LLM section repair

**Files:**
- Modify: `scripts/repair_report.py:15-45,185-238`
- Modify: `tests/scripts/test_repair_report.py`

**Interfaces:**
- Produces: `_markdown_headings(text: str) -> list[str]`.
- Produces: `_safe_section_replacement(original: str, candidate: str) -> bool`.
- Consumes: original `section_text` and normalized LLM `replacement` immediately before write.

- [ ] **Step 1: Write failing destructive-replacement tests**

Add one fake LLM that returns the section heading plus a truncated first subsection and tests:

```python
def test_repair_rejects_truncated_section_and_preserves_original(tmp_path: Path) -> None:
    original = (
        "## Analysis 2-8\n"
        "### Figure Description\nFull figure description.\n"
        "### Quantitative Findings\nMeasured values remain.\n"
        "### Biological Interpretation\nOriginal unsupported claim.\n"
        "### References\n- PMID: 12345678\n"
    )
    # Arrange one repairable error and an LLM response missing later headings.
    # Call repair_report(...).
    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
```

Add a companion test proving a shorter candidate with the exact heading sequence and at least half the non-whitespace content is accepted.

- [ ] **Step 2: Run the two tests and verify RED**

Run the exact test node IDs. Expected: the truncated replacement is currently written or the helper is missing.

- [ ] **Step 3: Implement the minimal before-write predicate**

Use stdlib regex and character counting only. Exact heading equality is required; character retention is:

```python
len(re.sub(r"\s+", "", candidate)) >= 0.5 * len(re.sub(r"\s+", "", original))
```

Skip unsafe writes and leave `changed` unchanged. Do not add retry, config, logging framework, or a new guardrail layer.

- [ ] **Step 4: Run repair and guardrail suites**

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run ruff check scripts/repair_report.py tests/scripts/test_repair_report.py
uv run python -m py_compile scripts/repair_report.py tests/scripts/test_repair_report.py
git diff --check
```

- [ ] **Step 5: Commit Task 2**

Commit only repair code and its tests with Lore trailers recording the 50% catastrophe threshold and the rejected new-middleware design.

---

### Task 3: Persist Claim-RAG retrieval before judgment caching

**Files:**
- Modify: `src/agents/deep_interpreter/claim_rag_validation.py:35-75,400-690,729-875`
- Modify: `tests/agents/deep_interpreter/test_claim_rag_validation.py`

**Interfaces:**
- Extends checkpoint shape to `{"version": 1, "batches": {...}, "retrievals": {...}}`.
- Produces: `_retrieval_checkpoint_key(item: dict[str, Any]) -> str` using claim, candidate PMIDs, collection ID, wiki condition, and policy version.
- Produces: selection field `retrieval_cache_hits: int`.

- [ ] **Step 1: Write a failing cross-invocation retrieval-cache test**

Use a counting fake for `search_literature_fulltext.invoke`, call `validate_claims` twice with separate in-memory `cache={}` values and the same `data_dir`, and assert:

```python
assert retrieval_calls == 1
assert second["selection"]["retrieval_cache_hits"] == 1
assert json.loads((tmp_path / "claim_rag_checkpoint.json").read_text())["retrievals"]
```

Add a failure test proving `Literature retrieval failed:` results are not persisted.

- [ ] **Step 2: Verify RED with the exact tests**

Expected: retrieval runs twice and `retrievals`/`retrieval_cache_hits` are absent.

- [ ] **Step 3: Implement minimal persistent retrieval reuse**

Initialize `retrievals` with `setdefault`, check it before `_retrieve_evidence_status`, persist completed evidence plus `unverifiable_reason`, and flush through the existing checkpoint writer. Do not change judge batching, claim selection, evidence ranking, or issue severity.

- [ ] **Step 4: Run Claim-RAG and report guardrail suites**

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

- [ ] **Step 5: Commit Task 3**

Commit Claim-RAG and tests with Lore trailers naming repeated reporter-process retrieval as the constraint and transport-failure caching as rejected.

---

### Task 4: Record request latency and PMID flow in the existing RAG audit

**Files:**
- Modify: `src/agents/deep_interpreter/tools/literature_rag.py:130-175,1440-1580`
- Modify: `scripts/run_bc_sni_repair_ablation.py:470-540`
- Modify: `tests/test_rag_path_resolution.py`
- Modify: `tests/test_sni_ablation_runner.py`

**Interfaces:**
- Extends each audit row with optional `elapsed_seconds`, `rewrite_count`, `retrieved_document_count`, `relevant_document_count`, `selected_wiki_page_count`, and `result_pmids`.
- Extends retrieval summary with `unique_query_count`, `duplicate_attempt_count`, `unique_result_pmid_count`, `retrieval_cache_hits`, and `elapsed_seconds_total`.

- [ ] **Step 1: Write failing audit behavior tests**

Use a real temporary audit file and a representative agentic payload containing `retrieved_document_ids`, `relevant_documents`, `selected_wiki_pages`, `rewrite_count`, and source filenames. Assert literal fields and deduplicated PMIDs in the emitted JSON row. Add a runner aggregation fixture with repeated hashes and overlapping PMIDs.

- [ ] **Step 2: Verify RED**

Run the exact new tests. Expected: extended fields and aggregate metrics are absent.

- [ ] **Step 3: Add observational fields only**

Measure with `time.monotonic`, extract PMIDs from `metadata.filename`/`metadata.source`, retain existing success/error semantics, and aggregate without changing `_validate_rag_audit` acceptance rules beyond permitting the optional fields.

- [ ] **Step 4: Run focused RAG and runner suites**

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/test_rag_path_resolution.py \
  tests/test_sni_ablation_runner.py
uv run ruff check \
  src/agents/deep_interpreter/tools/literature_rag.py \
  scripts/run_bc_sni_repair_ablation.py \
  tests/test_rag_path_resolution.py \
  tests/test_sni_ablation_runner.py
uv run python -m py_compile \
  src/agents/deep_interpreter/tools/literature_rag.py \
  scripts/run_bc_sni_repair_ablation.py
git diff --check
```

- [ ] **Step 5: Commit Task 4**

Commit audit/aggregation changes and tests separately from retrieval behavior.

---

### Task 5: Resume Reporter from valid synthesis instead of rebuilding it

**Files:**
- Modify: `src/agents/deep_interpreter/reporter_recovery.py:100-190`
- Modify: `tests/agents/deep_interpreter/test_reporter_recovery.py`

**Interfaces:**
- Produces: `_valid_existing_synthesis(data_dir: Path) -> bool` using the existing deterministic `synthesis_not_markdown` check.
- Extends: `build_reporter_recovery_message(data_dir: Path, *, preserve_synthesis: bool) -> str`.

- [ ] **Step 1: Write failing valid-synthesis resume test**

The first attempt writes a Markdown title and substantive `##` section but omits downstream outputs. Assert the second prompt says to preserve `synthesis.md`, does not instruct a rebuild, and invokes `generate_html_report` once. Preserve the existing invalid-HTML-fragment rebuild test.

- [ ] **Step 2: Verify RED**

Expected: current recovery always says to rebuild synthesis.

- [ ] **Step 3: Implement conditional recovery prompt**

Use a local import of the deterministic synthesis validator to avoid module-import cycles. Only the `synthesis_not_markdown` code controls this branch; semantic warnings and errors do not force regeneration here because `generate_html_report` owns the guardrail checkpoint.

- [ ] **Step 4: Run recovery and reporter suites**

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py
uv run ruff check \
  src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
uv run python -m py_compile \
  src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
git diff --check
```

- [ ] **Step 5: Commit Task 5**

Commit recovery behavior and tests with Lore trailers recording full Reporter regeneration as the rejected alternative.

---

### Task 6: Verify the integrated branch and run one canonical pair

**Files:**
- Verify only; modify production code only if a failing integration test identifies a task-owned defect.
- Generated run artifacts stay under the existing ignored ablation result hierarchy and are not committed.

**Interfaces:**
- Consumes: all prior task interfaces and canonical BC source/collection.
- Produces: fresh test evidence and one pair summary with runtime/evidence-flow metrics.

- [ ] **Step 1: Run the combined targeted suite**

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

- [ ] **Step 2: Run static validation**

Run Ruff on every changed Python file, `py_compile` on production modules, `git diff --check`, and Pyright if available. Record an explicit validation gap if Pyright is unavailable.

- [ ] **Step 3: Run one serial canonical no-SNI → SNI pair**

Use the configured 6000 Interpreter/Reporter lane and 4000 RAG backend with a fresh output root. Validate the canonical 100-PMID preflight before the first stage. Do not start ten pairs.

- [ ] **Step 4: Evaluate the four-hour gate**

Require both conditions to finish with zero final hard errors, no rejected repair candidate, exact PMID equality, and total pair runtime no greater than four hours. If infrastructure is unavailable or the runtime gate fails, stop after preserving audit evidence and report the exact failing stage; do not weaken the gate.

- [ ] **Step 5: Commit verification-only follow-up if needed**

If no production fix is needed, create no empty commit. If Task 6 exposes a task-owned defect, follow a new RED/GREEN cycle, commit only that fix, and record it in the implementation report.

---

## Plan Self-Review

- Every design requirement maps to a task.
- No task introduces an SGCP-RAG repository change or citation-diversity behavior.
- Function names and checkpoint/audit fields are consistent across tasks.
- All code changes have explicit RED and GREEN commands.
- Live execution is bounded to one pair and a four-hour hard gate.
