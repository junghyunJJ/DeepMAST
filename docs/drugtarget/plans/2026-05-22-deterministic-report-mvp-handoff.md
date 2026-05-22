# Deterministic Report MVP Handoff

Date: 2026-05-22

Workspace:

- Worktree: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/deterministic-report-mvp`
- Branch: `feat/deterministic-report-mvp`
- Base: `origin/main` at `6e00ba6 Reduce finalizer evidence-budget failures for large target panels (#33)`

## MVP1 PR Scope Freeze

Status: frozen for MVP1 review as of 2026-05-22.

Include these repo-local files in the MVP1 PR:

- `src/agents/drug_target/deterministic_report.py`
- `src/agents/drug_target/templates/drug_report.md.j2`
- `skills/drug-target-reporting/templates/drug_report.md.j2`
- `tests/agents/drug_target/test_deterministic_report_mvp.py`
- `docs/drugtarget/plans/2026-05-22-deterministic-report-mvp-architecture.md`
- `docs/drugtarget/plans/2026-05-22-deterministic-report-mvp-handoff.md`
- `docs/drugtarget/plans/2026-05-22-drug-profile-enrichment-mvp.md`

Explicitly exclude from the MVP1 PR:

- unrelated `skills/*` deletions and unrelated `skills/omb-*` / LangChain skill additions in this worktree;
- generated runtime artifacts under `res_ipf_*`;
- `.omx/state/*` runtime state.

Scope note:

- `skills/drug-target-reporting/templates/drug_report.md.j2` must be included because `_markdown_template_path()` prefers the repo-local skills template before the package fallback. If this tracked template keeps `replace('|', '\|')`, a clean checkout can still emit the Jinja `invalid escape sequence '\|'` warning even though the package fallback is fixed.
- `src/agents/drug_target/templates/drug_report.md.j2` is the package-local fallback and should remain byte-identical to the repo-local skills markdown template for MVP1.

Archived reference branch:

- Worktree: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/finalizer-e2e-compaction`
- Branch: `feat/finalizer-e2e-compaction`
- Commit: `9073b01 Preserve deterministic finalizer compaction evidence`
- Purpose: preserve the compaction-path E2E test as reference only. Do not merge by default.

## Problem Summary

The current `finalize_report` path asks the LLM to do too much in one structured call:

1. Read a large evidence/reference/spec prompt.
2. Fill all report expansion slots.
3. Produce valid structured JSON.
4. Pick exact `source_file::source_field` provenance keys.
5. Preserve cited-only provenance.
6. Enable deterministic markdown/HTML rendering.

Live runs showed that changing models did not solve the core reliability problem:

- `qwen3.5:122b` on port 6000: actual loaded context was about 98k, so the prompt likely exceeded context.
- `qwen3.5:35b` on port 5000: context was sufficient at 262k, but the model supplied invalid schema/hash data.
- `gpt-4.1`: failed cited-only provenance by inventing plausible but invalid provenance keys.
- `gpt-5.4-mini`: failed cited-only provenance with many invalid provenance keys.
- `gpt-5.4`: got farther, but finalization still failed because `drug.md` retained all 33 `EXPAND` markers and render metadata was missing.

Conclusion: this is mainly a harness/design problem, not just a model-quality problem.

## MVP Direction

Build the report as a deterministic scientific artifact first. Treat LLM output as optional narrative enrichment.

Target architecture:

```text
evidence files
  -> deterministic report_data.json
  -> deterministic drug.md
  -> deterministic drug_report.html
  -> optional section-level LLM interpretation snippets
  -> validators
```

Core principle:

```text
DeepMAST report = deterministic factual report
LLM = optional interpretation layer
```

This intentionally inverts the current pattern:

```text
Current: LLM generates final report; deterministic code watches for failures.
MVP: deterministic code generates final report; LLM only improves readability.
```

## Design Rules

Facts are deterministic:

- Gene lists
- L-R pair tables
- Stage pass/fail
- Scores
- p-values
- STRING scores
- drug names
- drug indications
- target classifications
- final markdown/HTML artifact creation

LLM may only write short interpretation prose:

- 1-3 sentences per section or candidate card.
- Input should be a small prebuilt section card, not full raw evidence.
- LLM must not invent genes, drugs, numbers, trials, indications, or provenance.
- If the snippet fails validation, omit it or replace it with deterministic fallback text.

Provenance should be section-level for MVP:

- Do not require sentence-level `source_file/source_field/source_value` from the LLM.
- Deterministically attach evidence sources to each section/card.
- Keep deeper machine-readable provenance in `report_data.json` if needed.

Failure behavior:

- Report generation should not fail because an LLM paragraph is invalid.
- Invalid narrative snippets are dropped.
- Missing optional narrative is acceptable.
- Missing deterministic artifacts is not acceptable.

## Suggested Artifacts

Minimum useful MVP artifacts:

- `report_data.json`: deterministic structured source of truth for rendering.
- `drug.md`: deterministic markdown report.
- `drug_report.html`: deterministic HTML report.
- optional `report_interpretations.json`: validated LLM prose snippets by section.
- optional `report_validation.json`: final validation summary.

Avoid for the first MVP:

- Requiring `report_expansions.json`.
- Requiring sentence-level provenance in LLM output.
- Asking the LLM to produce final markdown.
- Asking the LLM to produce exact JSON paths.
- One giant LLM call over all evidence.
- Repair loops before deterministic rendering is proven.

## Candidate Implementation Shape

Introduce a new path rather than deeply modifying legacy `finalize_report` first.

Possible module names:

- `src/agents/drug_target/deterministic_report.py`
- `src/agents/drug_target/report_mvp.py`
- `src/agents/drug_target/tools/report_data_builder.py`

Suggested functions:

```python
def build_report_data(data_dir: str, disease: str) -> dict:
    """Read evidence and produce deterministic report_data.json payload."""

def render_report_markdown(report_data: dict) -> str:
    """Render deterministic drug.md from report_data."""

def render_report_html(report_data: dict) -> str:
    """Render deterministic drug_report.html from report_data or markdown."""

def build_interpretation_cards(report_data: dict) -> list[dict]:
    """Build small section cards for optional LLM interpretation."""

def validate_interpretation(card: dict, text: str) -> list[dict]:
    """Reject snippets with unsupported genes/drugs/numbers/speculation."""

def finalize_report_mvp(state: dict, config: RunnableConfig) -> dict:
    """Write deterministic artifacts; optionally enrich with validated prose."""
```

Simplest first iteration:

1. Build `report_data.json` from existing evidence using existing helper logic where practical.
2. Render `drug.md` without any LLM.
3. Render `drug_report.html` from that markdown.
4. Validate required artifacts exist and `drug.md` has no `EXPAND` markers.
5. Add optional LLM interpretation only after the deterministic path passes.

## Validation Criteria

Deterministic MVP should pass without any provider credentials:

- Creates `report_data.json`.
- Creates `drug.md`.
- Creates `drug_report.html`.
- No `EXPAND` markers in `drug.md`.
- Does not write into `res_ipf_ollama_tmp` or `res_ipf_openai_tmp`.
- Uses fixture or copied tmp workspace data in tests.
- Can run with mocked/no LLM.

Optional LLM interpretation validation:

- Snippet only uses allowed genes/drugs/numbers from its section card.
- Snippet does not introduce unsupported claims.
- Invalid snippet is omitted without failing the whole report.
- The final report remains complete without snippets.

## First Test Plan

Start test-first with a small fixture/tmp workspace:

1. `test_report_mvp_renders_without_llm`
   - Build minimal evidence fixture.
   - Run MVP finalizer with LLM disabled.
   - Assert `report_data.json`, `drug.md`, and `drug_report.html` exist.
   - Assert no `EXPAND` markers.

2. `test_report_mvp_rejects_invalid_interpretation`
   - Provide a section card with allowed gene/drug/number lists.
   - Validate a snippet that introduces an unsupported drug or number.
   - Assert it is rejected or omitted.

3. `test_report_mvp_keeps_section_sources_deterministic`
   - Render a section with known evidence source files.
   - Assert section-level evidence sources appear in the output or metadata.

Later live smoke tests:

- Mark live tests separately, for example `@pytest.mark.llm`.
- Compare `gpt-5.4`, `gpt-5.4-mini`, and local Ollama only for narrative quality.
- Do not let live LLM failure block deterministic artifact generation.

## Important Constraints

- Do not mutate original result directories such as `res_ipf_ollama_tmp` or `res_ipf_openai_tmp`.
- Do not merge the archived compaction E2E branch unless the legacy finalizer remains supported.
- Preserve deterministic factual content as the source of truth.
- Keep LLM interpretation optional.
- Prefer small fixture-driven tests before live model tests.
- Avoid broad refactors in the first MVP. Build a parallel path first, then decide whether to replace legacy `finalize_report`.

## Suggested First Prompt For New Session

```text
We are in /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/deterministic-report-mvp on branch feat/deterministic-report-mvp.

Read docs/drugtarget/plans/2026-05-22-deterministic-report-mvp-handoff.md.

Implement the first deterministic report MVP slice:
- build a no-LLM report path that writes report_data.json, drug.md, and drug_report.html from fixture/tmp workspace evidence;
- add focused tests proving it renders without EXPAND markers and does not require provider credentials;
- keep the legacy finalize_report behavior unchanged unless a minimal integration hook is necessary.
```
