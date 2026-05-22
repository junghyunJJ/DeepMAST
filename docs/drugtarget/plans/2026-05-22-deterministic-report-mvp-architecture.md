# Deterministic Drug Target Report MVP Architecture

Date: 2026-05-22

Purpose: preserve the recommended `drug_target` report-finalization architecture so a new session, worktree, or branch can resume the MVP without re-litigating the design.

Related handoff:

- `docs/drugtarget/plans/2026-05-22-deterministic-report-mvp-handoff.md`

## Current Situation

The current `drug_target` agent is already useful for evidence collection and hypothesis generation:

```text
run_drug_target_assessment
  -> drug_target_graph
  -> START
  -> run_deep_agent
       -> DeepAgents orchestrator
       -> evidence_assessor
       -> hypothesis_writer
       -> writes evidence/*.json and hypothesis_report.json
  -> finalize_report
       -> current LLM-driven report expansion path
  -> END
```

The weak point is report finalization. The current `finalize_report` path asks one LLM structured-output call to:

- read a large evidence/reference/spec prompt;
- fill all report expansion slots;
- emit valid structured JSON;
- choose exact provenance keys;
- preserve cited-only provenance;
- enable final markdown and HTML rendering.

Live runs showed that model changes did not remove the failure mode. This is a harness/design problem, not primarily a model-quality problem.

## Final Recommendation

Keep DeepAgents for the parts that benefit from agentic reasoning, but make final artifact generation deterministic.

Recommended topology:

```text
run_drug_target_assessment
  -> LangGraph super-graph

START
  -> run_deep_agent
       -> DeepAgents orchestrator
       -> evidence_assessor
       -> hypothesis_writer
       -> writes evidence/*.json + hypothesis_report.json

  -> finalize_report
       -> build_report_data        # no LLM
       -> validate_report_data     # no LLM
       -> optional_interpretations # LLM optional, small cards only
       -> validate_interpretations # no LLM
       -> render_drug_md           # no LLM
       -> render_drug_html         # no LLM
       -> validate_artifacts       # no LLM

END
```

Ownership boundaries:

```text
DeepAgents:
  - evidence collection
  - target and candidate evaluation
  - hypothesis generation
  - optional short interpretation candidates
  - failure-trace diagnosis and harness-improvement suggestions

Deterministic code:
  - report_data.json construction
  - gene/drug/score/table/provenance selection
  - markdown rendering
  - HTML rendering
  - artifact validation
  - final success/failure decision
```

The central rule:

```text
LLM output may enrich the report, but LLM output must not be required for report completion.
```

## DeepAgents Role

DeepAgents should remain in the system. The recommendation is not to remove it.

Good DeepAgents responsibilities:

- run `evidence_assessor`;
- run `hypothesis_writer`;
- optionally run `report_interpreter` later for short section/candidate interpretation snippets;
- use subagent isolation for small narrative cards such as one candidate card per gene;
- use Better Harness style eval loops to inspect traces and improve harness surfaces.

Bad DeepAgents responsibilities:

- directly write final `drug.md`;
- directly write `report_data.json`;
- choose exact provenance keys;
- decide whether final artifacts are complete;
- remove `EXPAND` markers by prompt discipline;
- preserve numeric consistency by prompt discipline.

If a `report_finalizer` subagent is added later, it should only coordinate deterministic tools. It should not be the author of final factual artifacts.

## Deterministic Report Contract

New deterministic report path should produce:

Required artifacts:

- `report_data.json`
- `drug.md`
- `drug_report.html`
- `report_validation.json`

Optional artifacts:

- `report_interpretations.json`

Legacy-compatible artifacts, if needed:

- `target_assessment.json`
- `drug_report_render.json`

`report_data.json` is the source of truth. It should contain, at minimum:

- disease metadata;
- input L-R pairs;
- selected candidate genes;
- stage pass/fail and evidence availability;
- rubric scores and classifications;
- OpenTargets/GWAS/STRING/ChEMBL summaries already present in evidence files;
- drug names, indications, phases, mechanisms when deterministically available;
- hypothesis summaries from `hypothesis_report.json`;
- section-level evidence sources;
- source file hashes or source metadata sufficient for audit.

`drug.md` and `drug_report.html` must be rendered from `report_data.json` plus any accepted optional interpretation snippets.

## Optional LLM Interpretation Layer

LLM use is allowed only after deterministic report generation works without it.

Allowed LLM input shape:

```text
section_card:
  section_id
  allowed_genes
  allowed_drugs
  allowed_numbers
  allowed_sources
  deterministic_facts
```

Allowed LLM output:

```text
1-3 short interpretation sentences
```

Validation rule:

```text
If a snippet introduces unsupported genes, drugs, numbers, trials, indications,
mechanisms, sources, or speculative claims, drop it or replace it with deterministic fallback text.
Do not fail report generation because an optional snippet is invalid.
```

Required invariant:

```text
No provider credentials, no LLM availability, or invalid LLM prose must still result in:
  - report_data.json
  - drug.md
  - drug_report.html
  - successful deterministic finalization
```

## Proposed Module Shape

Suggested module:

```text
src/agents/drug_target/deterministic_report.py
```

Suggested functions:

```python
def build_report_data(data_dir: str, disease: str) -> dict:
    """Read evidence files and produce deterministic report_data.json payload."""

def validate_report_data(report_data: dict) -> list[dict]:
    """Validate required fields and source consistency before rendering."""

def build_interpretation_cards(report_data: dict) -> list[dict]:
    """Build small section/candidate cards for optional LLM interpretation."""

def validate_interpretation(card: dict, text: str) -> list[dict]:
    """Reject unsupported genes, drugs, numbers, sources, or claims."""

def render_report_markdown(report_data: dict, interpretations: dict | None = None) -> str:
    """Render deterministic drug.md from report_data and accepted snippets."""

def render_report_html(report_data: dict, markdown: str) -> str:
    """Render deterministic drug_report.html from markdown/report_data."""

async def finalize_report_mvp(state: dict, config: RunnableConfig) -> dict:
    """Write deterministic artifacts; optionally enrich with validated prose."""
```

The existing `src/agents/drug_target/finalize_report.py` can call this MVP path once the first slice is proven by tests.

## PR Breakdown

Do not put MVP0 through MVP4 in one PR. The changes have different risk profiles and should be reviewed independently.

### PR 1: Deterministic Report MVP

Goal: prove no-LLM artifact generation from fixture/tmp workspace evidence.

Scope:

- add deterministic report module;
- build `report_data.json`;
- render no-LLM `drug.md`;
- render no-LLM `drug_report.html`;
- write `report_validation.json`;
- add focused fixture tests;
- keep legacy `finalize_report` unchanged unless a minimal feature-flagged hook is necessary.

Acceptance criteria:

- `report_data.json` exists;
- `drug.md` exists;
- `drug_report.html` exists;
- `drug.md` contains no `EXPAND` markers;
- test path requires no provider credentials;
- tests use fixture or copied tmp workspace data;
- original result directories such as `res_ipf_ollama_tmp` and `res_ipf_openai_tmp` are not mutated.

### PR 2: Integrate Deterministic Finalizer

Goal: route production finalization through deterministic artifact generation.

Scope:

- update `finalize_report` to call deterministic MVP path;
- keep legacy `report_expansions.json` path as fallback or isolated legacy path during transition;
- preserve existing integration envelope fields such as `report_finalization_error` and `evidence_truncated`;
- add targeted integration tests.

### PR 3: Optional Interpretation Layer

Goal: allow LLM prose without making LLM output required.

Scope:

- generate section/candidate cards;
- call optional LLM interpreter only when enabled;
- validate and accept/drop snippets;
- write `report_interpretations.json`;
- prove invalid snippets do not fail final report generation.

### PR 4: Better Harness / Eval Loop

Goal: evaluate and improve the report harness with fixtures and holdout traces.

Scope:

- add deterministic fixture evals;
- add holdout trace checks when available;
- categorize finalization failures;
- track artifact validity, no-LLM success, source consistency, and optional snippet acceptance/rejection.

### PR 5: Legacy Cleanup

Goal: remove or isolate the old report-expansion path after deterministic finalization is proven.

Scope:

- remove stale report-writer/summarizer references where safe;
- decide whether `report_expansions.json` remains as legacy/debug artifact;
- update docs and stage guides;
- avoid changing evidence collection behavior.

## First Implementation Prompt

Use this prompt in a fresh session or worktree:

```text
We are working on the DeepMAST drug_target deterministic report MVP.

Read:
- docs/drugtarget/plans/2026-05-22-deterministic-report-mvp-handoff.md
- docs/drugtarget/plans/2026-05-22-deterministic-report-mvp-architecture.md

Implement PR 1 only:
- add a no-LLM deterministic report path;
- build report_data.json from fixture/tmp workspace evidence;
- render drug.md from report_data.json without EXPAND markers;
- render drug_report.html;
- write report_validation.json;
- add focused tests that require no provider credentials;
- keep legacy finalize_report behavior unchanged unless a minimal feature-flagged hook is necessary.

Do not implement optional LLM interpretation, Better Harness evals, or legacy cleanup in PR 1.
```

## Non-Goals For PR 1

- Do not ask an LLM to write final markdown.
- Do not ask an LLM to build `report_data.json`.
- Do not ask an LLM to choose exact provenance keys.
- Do not require `report_expansions.json`.
- Do not add repair loops before deterministic rendering passes.
- Do not mutate original live result directories.
- Do not merge the archived compaction E2E branch by default.

## Stop Condition

Stop PR 1 when the no-LLM deterministic path passes focused tests and creates the required artifacts from a copied fixture workspace. Do not continue into optional LLM interpretation or legacy cleanup in the same PR.
