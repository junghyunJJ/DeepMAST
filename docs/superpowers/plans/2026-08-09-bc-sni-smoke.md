# BC 100-paper SNI smoke-test execution plan

> **Execution mode:** direct SGCP-RAG API smoke test. No DeepMAST production
> code changes are required because the public API already exposes the SNI
> ablation switch.

**Goal:** build SNI for collection `a208e916-bd32-405a-9eee-de4cd82b2a3b`,
prove its SNI-on/off modes, preserve the collection, and record elapsed time.

**Artifacts:** `res/deep_interpreter/bc/bc/sni_smoke_test/`

## Task 1: Record the starting state and API contract

**Files:**
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/collection_before.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/api_contract.json`

1. Confirm `GET http://localhost:8888/health` reports `status: ok`.
2. Save `GET /collections/a208e916-bd32-405a-9eee-de4cd82b2a3b` as
   `collection_before.json`.
3. Fail the run before rebuild unless the saved UUID, `document_count`, and
   `chunk_count` equal the fixed values in the design (UUID, `100`, `1553`).
4. Save the relevant OpenAPI schemas for `llm-wiki/rebuild` and
   `agentic-search` as `api_contract.json`, proving that
   `use_wiki_context` is an existing API option rather than a local patch.

**Verification:** `jq -e` validates the collection invariant and confirms the
agentic query schema contains the boolean `use_wiki_context` property.

## Task 2: Rebuild SNI and measure its duration

**Files:**
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_request.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_response.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_timing.json`

1. Save this request body exactly:
   ```json
   {"llm_provider":"ollama","llm_model":"qwen3.5:122b"}
   ```
2. Record UTC start/end timestamps and a monotonic elapsed duration around one
   synchronous `POST /collections/{id}/llm-wiki/rebuild` call.
3. Save the complete response, HTTP status, and timing values.
4. Treat an HTTP failure, a non-success response, or a reported error as a
   smoke-test failure. Preserve the response; do not retry with a different
   model or collection.

**Verification:** response is successful and `elapsed_seconds` is a positive
number in `rebuild_timing.json`.

## Task 3: Prove the collection did not change

**Files:**
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/collection_after.json`

1. Fetch the same collection after SNI rebuild.
2. Compare `uuid`, `document_count`, and `chunk_count` with
   `collection_before.json`.
3. Write the comparison result into the final summary.

**Verification:** UUID remains `a208e916-bd32-405a-9eee-de4cd82b2a3b`; both
counts remain `100` and `1553`.

## Task 4: Run paired SNI-on/off agentic searches

**Files:**
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/query_01_sni_on.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/query_01_sni_off.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/query_02_sni_on.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/query_02_sni_off.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/query_03_sni_on.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/query_03_sni_off.json`

For each condition, call `POST /collections/{id}/agentic-search` with the
same `question`, `search_type: "hybrid"`, `search_limit: 5`,
`max_rewrites: 3`, `llm_provider: "ollama"`, and
`llm_model: "qwen3.5:122b"`. Change only `use_wiki_context`.

Questions, run serially to avoid competing for the 122b model:

1. `What evidence supports EGF-ERBB2 signaling in the breast cancer tumor microenvironment?`
2. `Which ligand-receptor interactions are implicated in breast cancer cell-cell communication?`
3. `What stromal or vascular signaling programs are reported in the breast cancer microenvironment?`

**Verification:** for every on response, require no `error`, at least one
`relevant_documents` entry, and `wiki_context_status == "selected"`; for
every off response, require no `error`, at least one `relevant_documents`
entry, and `wiki_context_status == "disabled"`.

## Task 5: Summarize, regression-check, and commit the evidence

**Files:**
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/summary.json`
- Create: `res/deep_interpreter/bc/bc/sni_smoke_test/summary.md`

1. Build a compact summary containing collection invariants, selected model,
   SNI elapsed seconds, and one status/result-count row for each paired query.
2. State explicitly that this is a mechanism smoke test, not a repair-quality
   or replicate result.
3. Run the existing regression test that checks DeepMAST passes
   `use_wiki_context: true` to its agentic RAG tool:
   ```bash
   pytest -q tests/test_rag_path_resolution.py \
     -k test_search_fulltext_rag_prefers_agentic_search_with_wiki_context
   ```
4. Validate all JSON files with `jq empty`, inspect the summary, then commit
   only the new SNI-smoke artifacts and this plan with a Lore-protocol message.

**Verification:** all assertions pass, the regression test passes, and
`git status --short` shows no changes from this plan outside its explicit
artifact paths.

## Completion criteria

- One successful 122b SNI rebuild with exact elapsed time.
- Identical pre/post collection UUID, document count, and chunk count.
- Three successful paired agentic searches with the expected SNI statuses.
- A persisted, committed summary and raw evidence for the later repair A/B
  experiment.
