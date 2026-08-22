## Task 3 Report

Status: implemented and verified.

Changed files:
- `src/agents/deep_interpreter/report_guardrails.py`
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`

Implementation:
- Added `_snapshot_markdown_files`, `_restore_markdown_files`, and `_strict_phase_progress`.
- Made regular Parts repairs tentative. Candidate markdown mutations are retained and counted only after strict phase-aware progress.
- Made regular synthesis repairs tentative with the same retained-change metric.
- Made Parts and synthesis terminal repairs tentative. Terminal mutations are retained and counted only when hard-error count decreases.
- Preserved existing result dictionary keys.
- Kept phase-specific initial metric behavior for retained deterministic-to-semantic transitions.

RED evidence:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_rolls_back_caveat_only_table_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_restores_all_files_after_no_progress_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_atomic_table_repair_is_idempotent tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_accepts_only_safe_phase_transitions`
- Result before controller change: `3 failed, 1 passed`.
- Failures showed no-progress synthesis and Parts repairs counted as retained changes, plus missing `_strict_phase_progress`.

GREEN evidence:
- Focused rollback/idempotence/helper tests: `4 passed, 1 warning`.
- Middleware suite: `51 passed, 1 warning`.

Final verification:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py tests/agents/deep_interpreter/test_claim_rag_validation.py tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py tests/scripts/test_repair_report.py tests/deep_interpreter/test_comprehensive_template_report` -> `222 passed, 1 warning`.
- `uv run ruff check src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> `All checks passed!`
- `uv run python -m py_compile src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> exit 0.
- `git diff --check` -> exit 0.

Concern:
- Existing LangGraph deprecation warning remains pre-existing: `config_schema` is deprecated in `src/base/base_agent.py:129`.

## Fix round 4

Status: implemented and verified.

Reviewer finding:
- Deterministic `unsupported_synthesis_overclaim` could target an exact H2-H6 Markdown heading, but generic repair correctly rejected every heading-text change and left the hard error unresolved.

Covering tests:
- Added a production-shaped H3 structured replacement test proving deterministic `1 → 0`, retained-change accounting, unchanged heading level/position and surrounding content, and second-run idempotence.
- Added structured delete rejection with byte-exact retention and the hard error preserved.
- Added empty, multiline, Markdown-heading, and new-PMID replacement rejection cases.

RED evidence:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_repairs_targeted_semantic_heading_idempotently tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_rejects_targeted_semantic_heading_delete tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_repair_synthesis_report_rejects_unsafe_semantic_heading_replacement`
- Output before implementation: `2 failed, 4 passed, 1 warning`.
- Failures showed the H3 remained unresolved and the delete decision never received the stripped heading body.

Change:
- Added a trusted pre-generic handler only for exact targeted `unsupported_synthesis_overclaim` H2-H6 headings in `synthesis.md`.
- The handler sends only the stripped heading body through the existing structured `RepairDecision` prompt and semantic safety check, accepts only a safe single-line `replace`, reconstructs the original heading prefix, and exact-splices the unique targeted line.
- Rejected recognized heading decisions are consumed before generic repair, retain original bytes, and contribute no changed metric.
- Updated tracked plan/spec invariants and replay layout checks to allow validator-owned semantic heading text changes while preserving level/position; H1 title promotion remains the sole level change.

Focused verification:
- New heading tests -> `6 passed, 1 warning`.
- H1, HTML, table rollback/idempotence, semantic frontier, and CRLF preservation set -> `14 passed, 1 warning`.
- Middleware suite -> `61 passed, 1 warning`.

Final verification:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py tests/agents/deep_interpreter/test_claim_rag_validation.py tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py tests/scripts/test_repair_report.py tests/deep_interpreter/test_comprehensive_template_report.py` -> `232 passed, 1 warning`.
- `uv run ruff check src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> `All checks passed!`
- `uv run python -m py_compile src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> exit 0.
- `git diff --check` -> exit 0.

Concern:
- Existing LangGraph deprecation warning remains pre-existing: `config_schema` is deprecated in `src/base/base_agent.py:129`.

## Fix round 3

Status: implemented and verified.

Reviewer finding:
- `synthesis.md` could pass report repair while starting with an H2 heading. The reporter contract requires the first non-empty line to be a Markdown H1 title.

Covering tests:
- Added `test_synthesis_requires_first_non_empty_line_h1_title`.
- Added `test_synthesis_guardrail_promotes_first_heading_to_h1_idempotently`.

RED evidence:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_requires_first_non_empty_line_h1_title tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_promotes_first_heading_to_h1_idempotently tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_rejects_html_fragment_synthesis tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_accepts_only_safe_phase_transitions tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_report_guardrail_retains_equal_count_disjoint_semantic_frontier tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_rolls_back_caveat_only_table_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_atomic_table_repair_is_idempotent`
- Output before implementation: `2 failed, 5 passed, 1 warning`.
- Failures: no `synthesis_title_not_h1` issue existed, and the guardrail reported zero initial title errors.

Change:
- `validate_synthesis_report` emits deterministic hard error `synthesis_title_not_h1` when non-HTML synthesis does not start with an H1.
- H2-H6 first headings carry exact `target_text` and H1 `replacement_text`; no-heading cases fail closed with no replacement.
- `repair_synthesis_report` has a trusted structural handler that changes only the first heading marker.
- Existing generic repair heading protection remains unchanged; test fixtures now include an H1 document title before H2 repair sections.
- Updated tracked spec/plan heading-preservation wording with the single validator-owned first-heading H1 promotion exception.

Focused verification:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_requires_first_non_empty_line_h1_title tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_promotes_first_heading_to_h1_idempotently tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_rejects_html_fragment_synthesis tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_accepts_only_safe_phase_transitions tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_report_guardrail_retains_equal_count_disjoint_semantic_frontier tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_rolls_back_caveat_only_table_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_atomic_table_repair_is_idempotent` -> `7 passed, 1 warning`.

Final verification:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py tests/agents/deep_interpreter/test_claim_rag_validation.py tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py tests/scripts/test_repair_report.py tests/deep_interpreter/test_comprehensive_template_report` -> `226 passed, 1 warning`.
- `uv run ruff check src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> `All checks passed!`
- `uv run python -m py_compile src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> exit 0.
- `git diff --check` -> exit 0.

Concern:
- Existing LangGraph deprecation warning remains pre-existing: `config_schema` is deprecated in `src/base/base_agent.py:129`.

## Fix round 2

Status: implemented and verified.

Reviewer finding:
- Count-only semantic progress rolled back valid frontier movement when all exact old semantic targets disappeared but new semantic targets surfaced at the same hard-error count.

Covering tests:
- Extended `test_strict_phase_progress_accepts_only_safe_phase_transitions` with equal-count disjoint semantic acceptance and equal-count persistent-key rejection.
- Added `test_report_guardrail_retains_equal_count_disjoint_semantic_frontier` to prove the accepted disjoint candidate is retained and becomes the next repair frontier.

RED evidence:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_accepts_only_safe_phase_transitions tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_report_guardrail_retains_equal_count_disjoint_semantic_frontier tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_rolls_back_caveat_only_table_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_restores_all_files_after_no_progress_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_rolls_back_no_progress_repair_byte_exact tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_atomic_table_repair_is_idempotent`
- Output before implementation: `2 failed, 4 passed, 1 warning`.
- Failures: equal-count disjoint semantic progress returned false, and controller retained only one changed section because the first semantic frontier was restored.

Change:
- Deterministic same-phase still requires strict hard-error decrease.
- `semantic -> deterministic` still rejects.
- Semantic same-phase accepts strict decrease or equal count when prior error-key set is non-empty and disjoint from candidate error-key set.
- Count increases still reject.
- Updated the tracked design spec and implementation plan atomic-progress wording to match the target-aware semantic frontier rule.

Focused verification:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_accepts_only_safe_phase_transitions tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_report_guardrail_retains_equal_count_disjoint_semantic_frontier tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_rolls_back_caveat_only_table_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_restores_all_files_after_no_progress_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_rolls_back_no_progress_repair_byte_exact tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_atomic_table_repair_is_idempotent` -> `6 passed, 1 warning`.

Final verification:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py tests/agents/deep_interpreter/test_claim_rag_validation.py tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py tests/scripts/test_repair_report.py tests/deep_interpreter/test_comprehensive_template_report` -> `224 passed, 1 warning`.
- `uv run ruff check src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> `All checks passed!`
- `uv run python -m py_compile src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> exit 0.
- `git diff --check` -> exit 0.

Concern:
- Existing LangGraph deprecation warning remains pre-existing: `config_schema` is deprecated in `src/base/base_agent.py:129`.

## Fix round 1

Status: implemented and verified.

Reviewer finding:
- Rollback snapshots used `read_text`/`write_text`, which normalized CRLF and prevented byte-exact restore.

Covering test:
- Added `test_parts_guardrail_rolls_back_no_progress_repair_byte_exact`.
- The test writes `part1_final.md` with explicit CRLF bytes, forces a changed-but-no-progress repair, and asserts final `read_bytes()` equals the original byte string.

RED evidence:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_rolls_back_no_progress_repair_byte_exact`
- Output: `1 failed, 1 warning`.
- Failure: final bytes contained LF-normalized content instead of original CRLF bytes.

Change:
- `_snapshot_markdown_files` now returns `dict[str, bytes]` and uses `read_bytes()`.
- `_restore_markdown_files` now accepts `dict[str, bytes]` and uses `write_bytes()`.

Focused verification:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_rolls_back_no_progress_repair_byte_exact tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_rolls_back_caveat_only_table_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_restores_all_files_after_no_progress_repair tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_atomic_table_repair_is_idempotent tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_accepts_only_safe_phase_transitions` -> `5 passed, 1 warning`.

Final verification:
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py tests/agents/deep_interpreter/test_claim_rag_validation.py tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py tests/scripts/test_repair_report.py tests/deep_interpreter/test_comprehensive_template_report` -> `223 passed, 1 warning`.
- `uv run ruff check src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> `All checks passed!`
- `uv run python -m py_compile src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> exit 0.
- `git diff --check` -> exit 0.

Concern:
- Existing LangGraph deprecation warning remains pre-existing: `config_schema` is deprecated in `src/base/base_agent.py:129`.
