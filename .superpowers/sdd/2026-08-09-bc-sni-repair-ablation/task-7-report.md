# Task 7 Report

## Outcome

Implemented the zero-hit audit distinction for BC SNI repair ablation:

- Agentic payload `{"error": "no_relevant_context"}` is audited as `NoRelevantContext`.
- The ablation runner accepts exactly two valid RAG audit outcomes:
  - successful positive-result agentic call
  - `NoRelevantContext` with `success: false` and `result_count: 0`
- The runner still rejects transport/payload failures, malformed counts, missing audits, wrong condition, wrong endpoint, and wrong collection UUID.
- Saved run metrics now include retrieval attempt, positive-result, and zero-hit counts.

No RAG queries, collection IDs, SNI pack behavior, fallback behavior, schedule, ports, model settings, or source dataset handling were changed.

## Files Changed

- `src/agents/deep_interpreter/tools/literature_rag.py`
  - Maps only payload error `no_relevant_context` to audit type `NoRelevantContext`; all other payload errors remain `AgenticError`.
- `scripts/run_bc_sni_repair_ablation.py`
  - Adds retrieval metrics from `rag_audit.jsonl`.
  - Accepts `NoRelevantContext` zero-hit audit records while preserving strict rejection for all other error records and malformed counts.
- `tests/test_rag_path_resolution.py`
  - Adds test coverage for no-context payload audit classification.
- `tests/test_sni_ablation_runner.py`
  - Adds tests for retrieval metrics, accepted no-context zero-hit audit, rejected non-no-context errors, and rejected malformed zero-hit counts.
- `.superpowers/sdd/2026-08-09-bc-sni-repair-ablation/task-7-report.md`
  - This report.

## RED

Command:

```bash
pytest tests/test_rag_path_resolution.py::TestRagSniIntegration::test_search_fulltext_rag_audits_no_relevant_context_payload tests/test_sni_ablation_runner.py::test_bc_runner_metrics_count_terminal_synthesis_repair tests/test_sni_ablation_runner.py::test_bc_runner_accepts_no_relevant_context_zero_hit_audit tests/test_sni_ablation_runner.py::test_bc_runner_rejects_non_no_relevant_context_error_audit | tee /tmp/task7-red.txt
```

Output:

```text
collected 4 items

tests/test_rag_path_resolution.py F                                      [ 25%]
tests/test_sni_ablation_runner.py FF.                                    [100%]

FAILED tests/test_rag_path_resolution.py::TestRagSniIntegration::test_search_fulltext_rag_audits_no_relevant_context_payload
AssertionError: {'error_type': 'AgenticError'} != {'error_type': 'NoRelevantContext'}

FAILED tests/test_sni_ablation_runner.py::test_bc_runner_metrics_count_terminal_synthesis_repair
KeyError: 'retrieval'

FAILED tests/test_sni_ablation_runner.py::test_bc_runner_accepts_no_relevant_context_zero_hit_audit
RuntimeError: invalid RAG audit record: {'endpoint': 'agentic_search', 'collection_uuid': 'a208e916-bd32-405a-9eee-de4cd82b2a3b', 'use_wiki_context': False, 'success': False, 'error_type': 'NoRelevantContext', 'result_count': 0}

==================== 3 failed, 1 passed, 1 warning in 3.48s ====================
```

Additional malformed-count RED after finding Python `False == 0` would otherwise weaken the invariant:

```bash
pytest tests/test_sni_ablation_runner.py::test_bc_runner_rejects_malformed_zero_hit_result_count | tee /tmp/task7-red-malformed-count.txt
```

Output:

```text
collected 1 item

tests/test_sni_ablation_runner.py F                                      [100%]

FAILED tests/test_sni_ablation_runner.py::test_bc_runner_rejects_malformed_zero_hit_result_count
E       Failed: DID NOT RAISE <class 'RuntimeError'>

============================== 1 failed in 0.12s ===============================
```

## GREEN

Focused new behavior command:

```bash
pytest tests/test_rag_path_resolution.py::TestRagSniIntegration::test_search_fulltext_rag_audits_no_relevant_context_payload tests/test_sni_ablation_runner.py::test_bc_runner_metrics_count_terminal_synthesis_repair tests/test_sni_ablation_runner.py::test_bc_runner_accepts_no_relevant_context_zero_hit_audit tests/test_sni_ablation_runner.py::test_bc_runner_rejects_non_no_relevant_context_error_audit | tee /tmp/task7-green-focused.txt
```

Output:

```text
collected 4 items

tests/test_rag_path_resolution.py .                                      [ 25%]
tests/test_sni_ablation_runner.py ...                                    [100%]

========================= 4 passed, 1 warning in 2.67s =========================
```

Malformed-count command after predicate fix:

```bash
pytest tests/test_sni_ablation_runner.py::test_bc_runner_rejects_malformed_zero_hit_result_count | tee /tmp/task7-green-malformed-count.txt
```

Output:

```text
collected 1 item

tests/test_sni_ablation_runner.py .                                      [100%]

============================== 1 passed in 0.02s ===============================
```

Focused suites:

```bash
pytest tests/test_rag_path_resolution.py tests/test_sni_ablation_runner.py | tee /tmp/task7-green-suites-2.txt
```

Output:

```text
collected 82 items

tests/test_rag_path_resolution.py ...................................... [ 46%]
...............                                                          [ 64%]
tests/test_sni_ablation_runner.py .............................          [100%]

======================== 82 passed, 1 warning in 3.18s =========================
```

Static checks:

```bash
python -m py_compile src/agents/deep_interpreter/tools/literature_rag.py scripts/run_bc_sni_repair_ablation.py tests/test_rag_path_resolution.py tests/test_sni_ablation_runner.py
```

Output: no output, exit 0.

```bash
ruff check src/agents/deep_interpreter/tools/literature_rag.py scripts/run_bc_sni_repair_ablation.py tests/test_rag_path_resolution.py tests/test_sni_ablation_runner.py
```

Output:

```text
All checks passed!
```

```bash
git diff --check -- src/agents/deep_interpreter/tools/literature_rag.py scripts/run_bc_sni_repair_ablation.py tests/test_rag_path_resolution.py tests/test_sni_ablation_runner.py
```

Output: no output, exit 0.

## Self-Review

- The payload classifier only special-cases the exact string `no_relevant_context`; every other payload error still audits as `AgenticError`.
- The runner audit validator still rejects malformed counts using `type(result_count) is int`, so booleans are not accepted as counts.
- Retrieval metrics are derived from saved audit records and do not replace validation.
- Existing no-fallback behavior was not changed.
- The pre-existing modified plan doc `docs/superpowers/plans/2026-08-09-bc-sni-repair-ablation.md` was left untouched and excluded from this task commit.

## Concerns

- Focused tests covered the changed behavior; no live 10-pair ablation was run in this task.
- Existing suite warning remains: `LangGraphDeprecatedSinceV10: config_schema is deprecated`; unrelated to this change.
