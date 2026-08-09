# BC 100-paper SNI smoke-test design

**Status:** approved to proceed (2026-08-09)

## Objective

Build or rebuild the Summary Navigation Index (SNI/LLM Wiki) for the existing
100-paper BC collection, then prove that the same SGCP-RAG agentic-search API
can run with SNI enabled and disabled. Record the SNI build duration.

## Fixed scope

- Collection: `a208e916-bd32-405a-9eee-de4cd82b2a3b`
- Name: `deep_interpreter_bc_cfd96ddb_all`
- Expected immutable collection contents: 100 documents and 1,553 chunks.
- SNI build model: SGCP-RAG's existing `ollama` / `qwen3.5:122b` configuration.
- No paper ingestion, deletion, re-chunking, or collection replacement.
- No Deep Interpreter repair runs and no 6–10 replicate A/B experiment in this
  smoke-test phase.

## Design decision

Use SGCP-RAG's existing public API instead of adding a DeepMAST setting:

1. `POST /collections/{id}/llm-wiki/rebuild` builds the SNI for the selected
   collection.
2. `POST /collections/{id}/agentic-search` with `use_wiki_context: true` is
   the SNI-on condition.
3. The same endpoint and otherwise identical request with
   `use_wiki_context: false` is the SNI-off condition.

This holds the collection, search endpoint, question, result limit, and agent
model constant. It isolates SNI context use; routing SNI-off through the old
chunk-search fallback would confound the comparison with a different retrieval
pipeline.

### Rejected alternatives

- **Add an application-level SNI switch now:** defer until the later
  Deep Interpreter repair-replicate experiment needs it. The SGCP-RAG API
  already supplies the required switch.
- **Make a second collection:** rejected because it would confound SNI with
  corpus construction and violates the fixed-collection requirement.
- **Use failed SNI calls as the off condition:** rejected because failure is
  not an experimental condition.

## Smoke-test procedure

1. Fetch and save a pre-build collection snapshot.
2. Rebuild SNI using `ollama` and `qwen3.5:122b`; measure elapsed monotonic
   wall-clock time and save the raw response.
3. Fetch and save a post-build collection snapshot. Require the same UUID,
   document count (100), and chunk count (1,553).
4. Run these fixed questions with `limit: 5` in both conditions:
   - `What evidence supports EGF-ERBB2 signaling in the breast cancer tumor microenvironment?`
   - `Which ligand-receptor interactions are implicated in breast cancer cell-cell communication?`
   - `What stromal or vascular signaling programs are reported in the breast cancer microenvironment?`
5. Save each raw request/response pair and a compact summary under
   `res/deep_interpreter/bc/bc/sni_smoke_test/`.

## Acceptance criteria

- SNI rebuild returns success and its duration is recorded.
- Collection contents meet the pre/post invariants above.
- Each SNI-on query returns at least one result and reports that wiki context
  was selected/used.
- Each SNI-off query returns at least one result and does not use wiki context.
- The final report distinguishes a smoke-test routing result from a claim that
  SNI improves repair outcomes.

## Stop condition

Stop after the artifacts and acceptance checks are complete. If an external
SGCP-RAG request fails, preserve its response and report the failure; do not
re-ingest papers or substitute a different collection.
