# Manual Test Notes

Active validation log for `biomedical-literature-search`. Lightweight, append-only;
record one entry per manual test pass.

Earlier pre-production validation history is archived under
[`archive/manual-test-notes-pre-production.md`](archive/manual-test-notes-pre-production.md).
That archive is read-only and excluded from the active hygiene scan.

---

## Validation Loop Template

Run after any non-trivial change to `SKILL.md`, `references/`, or `evals/`.

| Step | Command | Expected | Notes |
|------|---------|----------|-------|
| strict-validate | `python -m scripts.validate_strict <skill-dir> --strict` | exit 0, `error=0` | record `soft_error` and `warning` counts |
| autofix-dry-run | `python -m scripts.autofix <skill-dir>` | exit 0 | preview structural fixes; should be `applied=0` after a stable rewrite |
| autofix-apply | `python -m scripts.autofix <skill-dir> --fix-all-safe --yes` | exit 0 | optional; only when dry-run reports safe fixes |
| strict-validate (re-run) | same as above | exit 0, `error=0` | confirm re-validation is clean after edits |

---

## Manual Trigger Check Template

Run 2-3 prompts per change. Record one entry per prompt.

### Prompt N: <one-line label>
- Prompt: `<full prompt as issued>`
- Expected trigger: `trigger` or `non-trigger`
- Observed trigger: `trigger` / `partial` / `non-trigger` / `wrong-skill`
- Notes: how the agent routed, which files it opened, any over- or under-trigger
  observation.

Recommended prompt mix:
1. Clear in-scope literature retrieval request for an LR pair plus disease.
2. Paraphrased in-scope request that does not use the skill name.
3. Out-of-scope writing or summarization request that should not over-trigger.

---

## Evidence Retrieval Spot-Check Template

Use after a routing-positive run to confirm the retrieved set is grounded.

### Entry
- `date`: YYYY-MM-DD
- `prompt`: <one-line summary>
- `lr_pair`: `<LIGAND>` x `<RECEPTOR>`
- `disease`: `<normalized disease term>`
- `pathway_modifiers`: `[...]` (optional)
- `celltype_modifiers`: `[...]` (optional)
- `papers_returned`: integer
- `unique_after_dedup`: integer (PMID > DOI > normalized title)
- `direct_lr_evidence`: integer
- `receptor_pathway_context_evidence`: integer
- `disease_only_background`: integer
- `rejected_weak_evidence`: integer
- `papers_raw_path`: path to `papers_raw.json`
- `citation_candidates_path`: path to `citation_candidates.json`
- `filtered_papers_path`: path to filtered `papers.json`
- `notes`: short qualitative pass/fail; flag short-symbol cases and any
  abstract-missing rows.

---

## Known Limitations

- Trigger reliability depends on host agent behavior; record under- and over-trigger
  observations rather than inferring from a single prompt.
- The evidence retrieval spot-check is a manual sanity gate. The deterministic
  scorer owns bucket counts and citation candidate artifacts.
