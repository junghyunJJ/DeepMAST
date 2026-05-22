# Deterministic Report MVP2 Harness Plan

Date: 2026-05-22

Branch: `feat/deterministic-report-mvp2-harness`

## Context

PR #34 merged the MVP1 deterministic no-LLM report renderer into `main`.
The current `deterministic_report.py` path can build:

- `report_data.json`
- `drug.md`
- `drug_report.html`
- `report_validation.json`

The next PR must prepare deterministic finalization for later DeepAgents
integration without changing the production super-graph routing yet.

## MVP2 Goal

Add a provider-free harness/eval/diagnostics layer around deterministic report
generation so future integration PRs can route production finalization through
deterministic code with explicit evidence.

## Scope

Included:

- `src/agents/drug_target/report_harness.py`
- `tests/agents/drug_target/test_report_harness_mvp2.py`
- `report_harness_diagnostics.json` generated in copied fixture/tmp workspaces
- failure taxonomy for deterministic report artifacts
- DeepAgents responsibility boundary contract

Excluded:

- production routing changes in `src/agents/drug_target/super_graph.py`
- production finalizer changes in `src/agents/drug_target/finalize_report.py`
- DeepAgents prompt rewrites
- optional LLM interpretation snippets
- live LLM evaluation
- legacy `report_expansions.json` cleanup
- mutation of `res_ipf_*` run directories

## Ownership Boundary

DeepAgents may:

- collect evidence;
- write `hypothesis_report.json`;
- orchestrate tool calls;
- provide optional interpretation snippets in a later PR;
- critique report quality;
- inspect harness diagnostics and suggest harness improvements.

DeepAgents must not:

- write `report_data.json`;
- write final `drug.md`;
- write final `drug_report.html`;
- choose exact provenance keys;
- decide final report success or failure.

Deterministic code owns:

- `report_data.json`;
- `drug.md`;
- `drug_report.html`;
- `report_validation.json`;
- `report_harness_diagnostics.json`;
- final success or failure.

## Harness Diagnostics Contract

File:

```text
report_harness_diagnostics.json
```

Schema version:

```text
drug_target.report_harness_diagnostics.v1
```

Required base diagnostics top-level fields:

```json
{
  "schema_version": "drug_target.report_harness_diagnostics.v1",
  "valid": true,
  "created_at": "2026-05-22T00:00:00+00:00",
  "data_dir": "/absolute/tmp/workspace",
  "artifacts": {},
  "evidence": {},
  "issues": [],
  "deepagents_boundary": {}
}
```

harness-run diagnostics add required `finalizer_result`:

```json
{
  "finalizer_result": {}
}
```

Failure codes:

- `MISSING_REQUIRED_EVIDENCE`
- `MALFORMED_REQUIRED_EVIDENCE_JSON`
- `MISSING_REQUIRED_ARTIFACT`
- `MALFORMED_ARTIFACT_JSON`
- `REPORT_VALIDATION_FAILED`
- `UNEXPANDED_PLACEHOLDER`

## Acceptance Criteria

- Harness tests pass without provider credentials.
- Harness writes `report_harness_diagnostics.json` in tmp/copied workspaces.
- Successful deterministic runs report `valid: true`.
- Missing required evidence is classified as `MISSING_REQUIRED_EVIDENCE`.
- Malformed required evidence JSON is classified as `MALFORMED_REQUIRED_EVIDENCE_JSON`.
- `EXPAND` marker leakage is classified as `UNEXPANDED_PLACEHOLDER`.
- DeepAgents boundary contract lists allowed and forbidden responsibilities.
- `src/agents/drug_target/finalize_report.py` remains unchanged.
- `src/agents/drug_target/super_graph.py` remains unchanged.
- `src/agents/drug_target/agent.py` remains unchanged.

## Test Plan

Run:

```bash
pytest tests/agents/drug_target/test_report_harness_mvp2.py -q
pytest tests/agents/drug_target/test_deterministic_report_mvp.py -q
pytest tests/agents/drug_target/test_super_graph_topology.py -q
pytest tests/agents/drug_target/test_report_renderer.py tests/agents/drug_target/test_finalization_validator.py -q
```

Then confirm the PR did not edit production routing files:

```bash
git diff --exit-code origin/main...HEAD -- src/agents/drug_target/finalize_report.py src/agents/drug_target/super_graph.py src/agents/drug_target/agent.py
```

Expected:

```text
no output
```

## Stop Condition

Stop MVP2 when the harness diagnostics module, tests, and plan document are
merged. Do not continue into production finalizer routing, optional LLM
interpretation, or legacy cleanup in the same PR.
