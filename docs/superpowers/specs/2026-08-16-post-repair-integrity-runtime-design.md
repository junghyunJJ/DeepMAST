# Post-Repair Integrity and Runtime Design

## Goal

Make the BC SNI/no-SNI pilot scientifically valid and bounded before any replicate study by fixing the source/corpus mismatch, rejecting destructive report repairs, eliminating repeated Claim-RAG retrieval across revalidation and reporter recovery, and resuming reporter output generation from valid completed artifacts.

## Observed failures

1. The ablation runner copies `res/bc_interpreter`, a legacy 50-paper handoff, while the fixed SGCP collection contains the 100 PMIDs selected by `res/deep_interpreter/bc/bc/papers.json`.
2. Section repair accepts any LLM replacement and can overwrite a complete section with a truncated response.
3. Persistent Claim-RAG checkpoints cache judgments only after evidence retrieval, so a new process repeats agentic retrieval even when the judgment is cached.
4. Reporter recovery rebuilds `synthesis.md` after a timeout even when a valid synthesis already exists and only validation/HTML outputs are missing.
5. RAG audit rows lack request latency, rewrite, document, and PMID fields needed to explain runtime and retrieval-to-citation attrition.

## Design

### 1. Bind the runner to the canonical BC handoff

- Resolve the default source from the repository root as `res/deep_interpreter/bc/bc`; do not use an absolute user path.
- Before running either condition, load the 100 PMIDs from source `papers.json` and retrieve every collection document page through the SGCP REST pagination API.
- Derive collection PMIDs from `metadata.filename` values shaped as `pmid_<digits>.txt`.
- Fail before stage execution unless the source and collection PMID sets are exactly equal and both contain 100 PMIDs.
- Preserve the existing immutable UUID, document-count, chunk-count, and before/after collection checks.

### 2. Reject destructive section replacements before write

- Keep deterministic PMID and inline-citation repairs unchanged.
- For LLM section rewrites, compare the original section and candidate before `Path.write_text`.
- Accept only when the exact Markdown heading sequence is unchanged and the candidate contains at least 50% of the original non-whitespace characters.
- An unsafe candidate is not written and does not increment `changed_sections`; the existing no-progress behavior leaves original content intact and returns a failed guardrail result when errors remain.
- Do not add a new middleware, LLM call, retry loop, configuration layer, or dependency.

### 3. Persist retrieval results before judgment caching

- Extend `claim_rag_checkpoint.json` with an optional `retrievals` mapping while retaining version `1` and the existing `batches` mapping.
- Key retrieval entries by the claim text, ordered candidate PMIDs, fixed collection ID, wiki-context condition, and evidence-policy version.
- Cache only completed evidence results. Do not persist transport failures or incomplete judge results.
- Check the retrieval cache before calling `search_literature_fulltext`; checkpoint hits must produce zero new RAG audit events.
- Record retrieval-cache hits in claim-selection statistics.

### 4. Make RAG latency and evidence flow auditable

- Each `rag_audit.jsonl` row records elapsed seconds, rewrite count, retrieved-document count, relevant-document count, selected-wiki-page count, and unique result PMIDs when available.
- Preserve the existing endpoint, collection UUID, condition, success, error type, query hash, and result count contract.
- Extend the ablation summary with unique query count, duplicate attempt count, retrieval-cache hit count, and unique result PMID count.
- Audit additions are observational and must not change retrieval ranking or citation selection.

### 5. Resume reporter work from a valid synthesis

- After the first attempt, classify an existing non-empty `synthesis.md` with the deterministic synthesis-format validator.
- If synthesis Markdown is structurally valid and only downstream reporter outputs are missing, the recovery prompt must preserve `synthesis.md` and call `generate_html_report` once.
- Rebuild synthesis only when it is absent, empty, or deterministically invalid.
- Preserve the two-attempt cap, fresh message context, audit file, and failure propagation.

## Validation

- Use strict TDD for every behavior change.
- Run focused tests after each task and the combined Deep Interpreter repair/reporter/runner suite before live execution.
- Run Ruff and Python compilation on changed Python files; report Pyright as unavailable if it remains absent.
- Run one serial no-SNI to SNI smoke against the canonical 100-PMID source and fixed collection.
- Accept the smoke only when both conditions finish with zero final hard errors, no integrity rejection, exact source/collection PMID equality, and total pair runtime at or below four hours.

## Out of scope

- New SGCP-RAG endpoints or changes in the SGCP-RAG repository.
- Citation-diversity quotas or changes to evidence-ranking policy.
- Changing the 122B Interpreter/Reporter model.
- Ten replicate pairs before the four-hour smoke gate passes.
