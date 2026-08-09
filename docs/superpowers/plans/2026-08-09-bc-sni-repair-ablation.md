# BC SNI repair ablation execution plan

> **Execution mode:** paired, port-pinned BC end-to-end experiment. The plan
> continues directly into implementation and execution under the active Goal.

**Goal:** measure whether enabling the existing Summary Navigation Index (SNI)
changes repair burden in the Deep Interpreter BC workflow, without changing the
100-paper collection or its SNI pages.

**Primary outcome:** `total_repair_attempts = parts_repair_attempt_count +
synthesis_repair_attempt_count + synthesis_terminal_repair_count`.

**Secondary outcomes:** initial/final error counts, part changed sections,
synthesis changed claims, stage duration, and agentic-RAG audit counts,
including valid agentic zero-hit (`no_relevant_context`) counts.

**Fixed experimental constants**

- Collection: `a208e916-bd32-405a-9eee-de4cd82b2a3b`
  (`100` documents, `1553` chunks); existing SNI pack is reused unchanged.
- Dataset input: `res/bc_interpreter`; every condition writes to an isolated
  copied run directory and never writes to this source.
- Model: `qwen3.5:122b`; provider `ollama`; reasoning and decoding limits
  match the successful BC reference run.
- Conditions differ only in agentic-search `use_wiki_context`: on = `true`,
  no-SNI = `false`. Both use the same agentic endpoint; multi-query fallback is
  prohibited for an experiment run.
- Four SGCP-RAG API containers bind agentic RAG to Ollama ports
  `4000/5000/6000/7000`, respectively. Deep Interpreter and its paired RAG API
  use the same assigned port.

## Task 1: Make SNI an explicit, auditable per-run switch

**Files:**

- Modify: `src/agents/deep_interpreter/tools/literature_rag.py`
- Modify: `tests/test_rag_path_resolution.py`

1. Add one environment-derived boolean,
   `DEEP_INTERPRETER_USE_WIKI_CONTEXT`, defaulting to `true` to preserve
   current behaviour.
2. Pass that value to the existing `agentic_search` MCP tool instead of the
   hard-coded `true`.
3. When `DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true`, raise a RAG error if the
   agentic call yields no usable results. This prevents a failed agentic call
   from silently changing an ablation run into the multi-query control path.
4. Append a compact JSONL audit record when
   `DEEP_INTERPRETER_RAG_AUDIT_PATH` is set: endpoint, collection UUID,
   condition boolean, success/result count, and error type. Do not record
   paper content.
5. Test the default-on path, explicit off path, and required-agentic failure
   path before implementation. Existing non-experiment fallback behaviour must
   remain covered.

**Verification:** targeted pytest proves only the boolean changes between
request payloads, default behaviour remains SNI-on, and required-agentic mode
does not call the fallback.

## Task 2: Provide reproducible four-API topology control

**Files:**

- Create: `scripts/sgcp_rag_sni_ablation.compose.yml`
- Create: `scripts/sni_ablation_api_stack.py`
- Create: `tests/test_sni_ablation_runner.py`

1. Define four API-only services, joined to the existing
   `langconnect_mcp_langconnect-network` and PostgreSQL service. They reuse the
   existing SGCP-RAG API image and database; they do not start a second
   PostgreSQL service and do not rebuild SNI.
2. Configure each service with the unchanged SGCP `.env` plus a distinct
   `AGENT_LLM_BASE_URL`/`OLLAMA_BASE_URL` to its assigned Ollama port. Expose
   host API ports `8881..8884` for backends `4000..7000`.
3. Add a small control command that starts, checks, and stops only the four
   ablation API containers. It writes no credentials and never recreates the
   existing `langconnect-api`, PostgreSQL, collection, or Wiki records.
4. The health check must verify each container API, assigned Ollama
   `/api/tags` model, exact collection snapshot, and paired direct agentic
   queries (`use_wiki_context=true/false`) with expected
   `selected`/`disabled` statuses.

**Verification:** topology smoke produces a machine-readable report proving
all four agentic endpoints use `qwen3.5:122b`, preserve the collection snapshot,
and honor both conditions.

## Task 3: Build the paired BC runner and metric extractor

**Files:**

- Create: `scripts/run_bc_sni_repair_ablation.py`
- Create: `tests/test_sni_ablation_runner.py`

1. Reuse the established BC dataset-run sequence: read-only collection binding,
   remove collection-preparation tools, Part 1 → Part 2 → Part 3 → Reporter,
   guardrail capture, before/after report snapshots, and collection snapshots.
2. Copy `res/bc_interpreter` for each condition, remove only prior generated
   report artifacts, and retain immutable input hashes in `source_manifest.json`.
   No source or collection write is allowed.
3. Persist `run_manifest.json` for each condition with collection invariants,
   condition, backend port, RAG API URL, model settings, ordered pair ID, and
   return status. Make the run fail if source hashes, collection snapshot,
   RAG audit, or final guardrail requirements are not valid.
4. Extract each guardrail field as emitted: aggregate parts attempts and
   changed sections; synthesis attempts, terminal repair, and changed claims;
   per-artifact initial/final errors. Do not invent per-part repair-attempt
   counts because the parts guardrail reports one aggregate pass.
5. Provide `--smoke`, `--pair N`, `--all`, and `--summarize` commands. A pair
   executes its two conditions sequentially; `--all` schedules at most one
   pair per backend port concurrently.

**Verification:** unit tests use a temporary source and mocked runner to prove
copy isolation, deterministic schedule, endpoint/boolean mapping, no fallback
condition, metric accounting, and collection-drift failure handling.

## Task 4: Freeze the 10-pair schedule and preflight it

**Files:**

- Create: `res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest.json`
- Create: `res/deep_interpreter/bc/sni_repair_ablation/topology_smoke.json`

1. Generate and persist this seeded (`20260809`) schedule before any full run:

   | Pair IDs | Ollama port | API port | First condition |
   | --- | ---: | ---: | --- |
   | 01–03 | 4000 | 8881 | no-SNI, SNI, no-SNI |
   | 04–06 | 5000 | 8882 | no-SNI, SNI, SNI |
   | 07–08 | 6000 | 8883 | no-SNI, no-SNI |
   | 09–10 | 7000 | 8884 | SNI, SNI |

2. Record one manifest containing source hashes, expected collection counts,
   API/port map, model configuration, schedule seed, and fixed run settings.
3. Start the API topology, run the four-port smoke, and stop before the full
   experiment if any condition is not `selected` (SNI) or `disabled` (no-SNI),
   if the collection drifts, or if a backend lacks the requested model.

**Verification:** manifest and smoke JSON validate with `jq`; collection UUID,
documents, and chunks are unchanged on every API endpoint.

## Task 5: Execute the 10 paired replicates

**Files:**

- Create: `res/deep_interpreter/bc/sni_repair_ablation/pairs/pair_*/`

1. Launch the API topology and invoke `--all` once. Run at most four pairs at
   a time, one per port; conditions inside each pair remain sequential in their
   frozen randomized order.
2. For each of 20 condition directories, persist raw stage logs, timing,
   `parts_guardrail_result.json`, `synthesis_guardrail_result.json`, initial
   and final validators, collection before/after snapshots, report diffs, and
   `rag_agentic_audit.jsonl`.
3. Treat a failed/incomplete condition, any final guardrail error, unexpected
   fallback, missing agentic audit event, source hash drift, collection drift,
   or agentic error other than the endpoint's explicit
   `no_relevant_context` response as invalid. Record that explicit response as
   a valid zero-hit retrieval outcome with `result_count: 0`; preserve all
   artifacts. Never retry an invalid condition in place. A replacement run
   gets a new explicit run ID and is reported as such.
4. Keep the four API containers alive only for this run and stop them after the
   final collection-invariant check.

**Verification:** all 20 condition manifests are complete and valid; all
collection before/after snapshots equal `a208…2a3b`, `100`, and `1553`.

## Task 6: Aggregate, review, and report the paired outcome

**Files:**

- Create: `res/deep_interpreter/bc/sni_repair_ablation/repair_metrics.csv`
- Create: `res/deep_interpreter/bc/sni_repair_ablation/paired_summary.json`
- Create: `res/deep_interpreter/bc/sni_repair_ablation/paired_summary.md`

1. Emit one condition row and one paired row, keeping raw metrics and
`no_SNI − SNI` differences for total repairs plus all secondary outcomes.
2. Report means, medians, pairwise win/loss/tie counts, and a deterministic
   exact sign-flip test for the primary paired difference. Present this as an
   estimate of repair burden, not proof of biological-answer quality.
3. Independently inspect the manifests, audit files, collection snapshots, and
   extracted metric totals. Run targeted regression tests plus the new harness
   tests and review the final diff.
4. Commit the minimal code, plan, runner documentation, and compact aggregate
   evidence using a Lore-protocol commit. Do not commit 20 bulky raw-run
   directories unless they are intentionally force-added after review; their
   reproducible local paths and checksums remain in the aggregate manifest.

## Task 7: Classify agentic zero-hit outcomes without weakening invariants

**Files:**

- Modify: `src/agents/deep_interpreter/tools/literature_rag.py`
- Modify: `scripts/run_bc_sni_repair_ablation.py`
- Modify: `tests/test_rag_path_resolution.py`
- Modify: `tests/test_sni_ablation_runner.py`

1. Map an explicit agentic payload error `no_relevant_context`, or a
   structurally valid agentic payload with an empty `sources` list, to the
   explicit audit type `NoRelevantContext`; preserve all other payload and
   transport errors as invalid error types.
2. Permit the runner to accept exactly two audit outcomes: a successful
   positive-result agentic call, or `NoRelevantContext` with
   `success: false` and `result_count: 0`. It must continue rejecting missing
   audits, wrong endpoint/UUID/condition, malformed counts, and every other
   error type.
3. Include retrieval attempt, positive-result, and zero-hit counts in each
   condition's saved metrics so the final paired analysis can report them
   alongside repair burden. Do not change RAG queries, collection data, SNI
   pages, fallback behavior, model settings, or the frozen schedule.
4. Use test-first coverage for the explicit no-context payload, accepted
   zero-hit audit, and rejected non-no-context error. Run the focused suites
   before committing.

**Verification:** targeted tests prove the new audit distinction, no fallback,
strict rejection of all true agentic failures, and saved retrieval metrics.

## Task 8: Classify empty agentic sources as a zero-hit outcome

**Files:**

- Modify: `src/agents/deep_interpreter/tools/literature_rag.py`
- Modify: `tests/test_rag_path_resolution.py`

1. When the agentic response is a structurally valid payload with
   `sources: []`, audit it as `NoRelevantContext`, with `success: false` and
   `result_count: 0`. This is the second zero-hit response shape observed in
   the live no-SNI run.
2. Do not treat missing or non-list `sources`, transport exceptions, JSON
   decode errors, or other payload errors as zero hits. They must continue to
   produce a non-`NoRelevantContext` invalid audit type.
3. Add test-first coverage for the empty-list payload and an invalid
   `sources` shape. Keep the existing explicit-error and runner acceptance
   tests unchanged.

**Verification:** the focused tests fail before implementation, then prove
that only valid empty sources become `NoRelevantContext` while malformed
payloads remain invalid.

## Task 9: Split the shared RAG lane from BC inference

**Files:**

- Modify: `scripts/sgcp_rag_sni_ablation.compose.yml`
- Modify: `scripts/sni_ablation_api_stack.py`
- Modify: `scripts/run_bc_sni_repair_ablation.py`
- Modify: `tests/test_sni_ablation_runner.py`
- Create: `res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json`

The `pairs-valid-run-03` invalid root showed that launching four full
qwen3.5:122b workflows concurrently causes two direct inference lanes to
timeout before their first RAG event.  Keep the existing root and its
manifest unchanged.  For the replacement run only, reserve port `4000` for
all SGCP-RAG agentic-search LLM requests and rotate direct Deep Interpreter
inference through ports `5000`, `6000`, and `7000`.

1. Bind every ablation SGCP-RAG API container's
   `AGENT_LLM_BASE_URL` and `OLLAMA_BASE_URL` to
   `http://host.docker.internal:4000`.  The topology smoke must report
   `backend_port: 4000` for all four containers.
2. Create a new explicit manifest for the replacement root.  It contains
   `rag_backend_port: 4000`, uses direct backend/API pairs
   `5000/8882`, `6000/8883`, and `7000/8884`, allocates ten pairs `4/3/3`
   across those direct ports, and counterbalances the first condition to
   five SNI and five no-SNI.  Preserve one SNI and one no-SNI condition per
   pair, and do not overwrite the earlier fixed manifest.

   | Pair IDs | Direct backend / API | First condition |
   | --- | --- | --- |
   | 01, 04, 07, 10 | `5000 / 8882` | no-SNI, SNI, no-SNI, SNI |
   | 02, 05, 08 | `6000 / 8883` | SNI, no-SNI, SNI |
   | 03, 06, 09 | `7000 / 8884` | no-SNI, SNI, no-SNI |
3. Validate the new manifest's dedicated RAG port, direct backend/API map,
   counterbalance, and exact pair schedule.  Persist both the direct backend
   and `rag_backend_port` in each condition manifest.
4. Execute `--all` as ten globally serial pair batches in manifest order.
   Port pinning remains fixed, but no two Deep Interpreter conditions or
   shared-RAG requests run concurrently.
5. Test first: prove the new topology exposes port 4000 as every RAG
   backend, the manifest parser rejects an incorrect RAG port or schedule,
   and `build_schedule` returns one pair per batch in frozen manifest order.
   Preserve the old-manifest behavior only as historical artifact; it does
   not need to be runnable under the replacement topology.

**Verification:** focused tests fail before the new behavior, then pass;
the replacement manifest validates; a live topology smoke proves all four
APIs still use `qwen3.5:122b`, the same fixed collection, and both SNI
states while their observed RAG backend is 4000.

**Completion criteria**

- All 10 pairs are valid, balanced `4/3/3` across direct inference ports
  `5000/6000/7000` while port `4000` exclusively serves agentic RAG, and
  contain exactly one SNI-on and one no-SNI agentic condition.
- No run changes the source dataset, fixed collection, or existing SNI pack.
- Every valid run reaches final guardrail error count `0`, with repair burden
  retained rather than hidden by that endpoint.
- The final paired report is auditable from saved manifests, guardrail outputs,
  RAG audit events, and collection snapshots.
