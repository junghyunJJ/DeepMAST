# Manual Test Notes

## Validation Loop

| Step | Command | Exit Code | Notes |
|------|---------|-----------|-------|
| strict-validate-1 | `python -m scripts.validate_strict /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/skills/biomedical-literature-search --strict` | 0 | `error=0 soft_error=0 warning=0 strict=True passed=True` |
| autofix-dry-run | `python -m scripts.autofix /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/skills/biomedical-literature-search` | 0 | `applied=0 skipped=0 manual_required=0` |
| autofix-apply | `python -m scripts.autofix /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/skills/biomedical-literature-search --fix-all-safe --yes` | 0 | No-op apply; nothing safe to change |
| strict-validate-2 | `python -m scripts.validate_strict /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/skills/biomedical-literature-search --strict` | 0 | Baseline remained clean after Rev6 edits |

## Manual Trigger Checks

### Prompt 1: Clear Trigger
- Prompt: `Find PubMed literature for ligand-receptor, pathway, and celltype evidence in a breast cancer ST/CCI analysis and save the grounded result set to /papers.json.`
- Expected trigger: trigger
- Observed trigger: partial / wrong-skill routing
- Notes: `codex exec` started with `pubmed-database` and broad repo exploration rather than clearly loading `biomedical-literature-search`. This is a useful under-trigger signal for later tuning.

### Prompt 2: Paraphrased Trigger
- Prompt: `I need a literature pass for pathway and celltype gaps from an ST/CCI result, and the follow-up should be bundled instead of stopping early on coverage_sufficient.`
- Expected trigger: trigger
- Observed trigger: partial / mis-routed
- Notes: `codex exec` interpreted the prompt as a repo behavior-change task and read global process skills rather than cleanly entering the literature-search workflow.

### Prompt 3: Strong-Retention Trigger
- Prompt: `Run the SEARCHER literature workflow for a high-context breast cancer interaction case and keep the paper set grounded for downstream interpretation.`
- Expected trigger: trigger
- Observed trigger: trigger
- Notes: `codex exec` explicitly said it was using `biomedical-literature-search` and opened `skills/biomedical-literature-search/SKILL.md`. This is the strongest positive routing signal in the manual checks.

### Prompt 4: Non-Trigger
- Prompt: `Write a general overview of breast cancer biology without using a structured literature-search workflow.`
- Expected trigger: non-trigger or explicit refusal to over-apply the skill
- Observed trigger: non-trigger
- Notes: `codex exec` treated the request as a writing task, explicitly said it would avoid a structured literature-search workflow, and did not route into the target skill behavior.

## Repo Verification

### Structural proxy
- Command: `pytest tests/benchmarks/test_harness_x_model.py -v`
- Exit code: `0`
- Result: `44 passed, 5 warnings in 2.10s`
- Notes: This verifies harness prompt composition and guard logic only. It is not a relevance oracle.

## Manual Relevance Audit Template

### Audit Entry
- `case_id`: TODO
- `comparison`: `weak_off` vs `weak_on`
- `weak_off_papers_path`: TODO
- `weak_on_papers_path`: TODO
- `weak_off_only_pmids`: TODO
- `weak_on_added_pmids`: TODO
- `anchor_types_per_added_pmid`: TODO
  - `disease`
  - `pathway`
  - `celltype`
  - `generic`
  - `off-target`
- `verdict`: TODO (`supports Rev6` / `neutral` / `regresses Rev6`)
- `notes`: TODO

## Pending Heavy Checks

- The full `run_pilot.py --mode B/B_prime/C` Rev6 pilot has not been run in this session.
- `docs/benchmarks/harness_x_model/_rev6_summary.py` has been added, but it still needs populated Rev6 pilot outputs and `pooled_postupdate_v3.json`.

## Bounded Debug Set

- Environment:
  - `OLLAMA_HOST=http://localhost:7000`
  - `OLLAMA_BASE_URL=http://localhost:7000`
- Mode: `C`
- Fresh dirs:
  - `docs/benchmarks/harness_x_model/results/rev6_debug`
  - `docs/benchmarks/harness_x_model/workspaces/rev6_debug`
- Note: `trial_0007 strong_off` hung after writing `papers.json`; the result row was recovered from the saved artifact using the same coverage logic as `common.py`.

### Proxy Results

| Trial | Case | Condition | Pathway | Celltype | Latency (s) |
|------|------|-----------|--------:|---------:|------------:|
| 1 | `cci_full_02_ANOS1_FGFR1` | `weak_off` | 100.0 | 75.0 | 167.29 |
| 2 | `cci_full_02_ANOS1_FGFR1` | `weak_on` | 100.0 | 75.0 | 90.255 |
| 3 | `cci_full_02_ANOS1_FGFR1` | `strong_off` | 100.0 | 50.0 | 90.041 |
| 4 | `cci_full_02_ANOS1_FGFR1` | `strong_on` | 100.0 | 75.0 | 143.88 |
| 5 | `cci_full_12_COL1A2_ITGA1` | `weak_off` | 0.0 | 37.5 | 124.012 |
| 6 | `cci_full_12_COL1A2_ITGA1` | `weak_on` | 100.0 | 62.5 | 118.827 |
| 7 | `cci_full_12_COL1A2_ITGA1` | `strong_off` | 0.0 | 37.5 | 89.859 |
| 8 | `cci_full_12_COL1A2_ITGA1` | `strong_on` | 100.0 | 62.5 | 146.594 |

## Manual Relevance Audit

### Audit Entry
- `case_id`: `cci_full_02_ANOS1_FGFR1`
- `comparison`: `weak_off` vs `weak_on`
- `weak_off_papers_path`: `docs/benchmarks/harness_x_model/workspaces/rev6_debug/trial_0001_cci_full_02_ANOS1_FGFR1_weak_off/papers.json`
- `weak_on_papers_path`: `docs/benchmarks/harness_x_model/workspaces/rev6_debug/trial_0002_cci_full_02_ANOS1_FGFR1_weak_on/papers.json`
- `weak_off_only_pmids`: 10 PMIDs
- `weak_on_added_pmids`: 10 PMIDs
- `anchor_types_per_added_pmid`:
  - `34830821`: `pathway`, `disease`
  - `35008634`: `pathway`, `disease`
  - `36003773`: `pathway`, `disease`
  - `28789687`: `pathway`, `generic`
  - `35267567`: `pathway`, `generic`
  - `24037094`: `off-target`
  - `33521378`: `off-target`
  - `37065626`: `off-target`
- `verdict`: `supports Rev6`
- `notes`: Proxy pathway/celltype coverage stayed flat because `weak_off` was already saturated, but `weak_on` added more HIF/hypoxia breast-cancer papers. The delta is useful but noisy, with several off-target additions.

### Audit Entry
- `case_id`: `cci_full_12_COL1A2_ITGA1`
- `comparison`: `weak_off` vs `weak_on`
- `weak_off_papers_path`: `docs/benchmarks/harness_x_model/workspaces/rev6_debug/trial_0005_cci_full_12_COL1A2_ITGA1_weak_off/papers.json`
- `weak_on_papers_path`: `docs/benchmarks/harness_x_model/workspaces/rev6_debug/trial_0006_cci_full_12_COL1A2_ITGA1_weak_on/papers.json`
- `weak_off_only_pmids`: 12 PMIDs
- `weak_on_added_pmids`: 12 PMIDs
- `anchor_types_per_added_pmid`:
  - `10360672`: `pathway`, `celltype`, `disease`
  - `10604730`: `pathway`, `disease`
  - `12783674`: `pathway`, `disease`
  - `17550303`: `pathway`, `disease`
  - `22690749`: `pathway`, `disease`
  - `22547351`: `pathway`, `generic`
  - `15766573`: `off-target`
- `verdict`: `supports Rev6`
- `notes`: This is the clearest Rev6 win in the bounded debug set. `weak_on` moved from generic collagen/integrin papers to VEGF/angiogenesis and epithelial-stromal context, raising both pathway and celltype proxy coverage.

### Audit Entry
- `case_id`: `cci_full_02_ANOS1_FGFR1`
- `comparison`: `strong_off` vs `strong_on`
- `weak_off_papers_path`: `docs/benchmarks/harness_x_model/workspaces/rev6_debug/trial_0003_cci_full_02_ANOS1_FGFR1_strong_off/papers.json`
- `weak_on_papers_path`: `docs/benchmarks/harness_x_model/workspaces/rev6_debug/trial_0004_cci_full_02_ANOS1_FGFR1_strong_on/papers.json`
- `weak_off_only_pmids`: 11 PMIDs
- `weak_on_added_pmids`: 11 PMIDs
- `anchor_types_per_added_pmid`: mixed `pathway` / `generic` / `off-target`
- `verdict`: `neutral`
- `notes`: Strong did not regress on the pathway-present case and improved celltype proxy coverage from `50 -> 75`. Added papers are mixed, so this is a non-regression signal rather than a clear quality win.

### Audit Entry
- `case_id`: `cci_full_12_COL1A2_ITGA1`
- `comparison`: `strong_off` vs `strong_on`
- `weak_off_papers_path`: `docs/benchmarks/harness_x_model/workspaces/rev6_debug/trial_0007_cci_full_12_COL1A2_ITGA1_strong_off/papers.json`
- `weak_on_papers_path`: `docs/benchmarks/harness_x_model/workspaces/rev6_debug/trial_0008_cci_full_12_COL1A2_ITGA1_strong_on/papers.json`
- `weak_off_only_pmids`: 12 PMIDs
- `weak_on_added_pmids`: 12 PMIDs
- `anchor_types_per_added_pmid`: mostly `pathway` / `celltype` / `disease`, with one `off-target`
- `verdict`: `supports Rev6`
- `notes`: Strong also gains the same VEGF/angiogenesis set here, raising `pathway 0 -> 100` and `celltype 37.5 -> 62.5` without a negative signal.
