# DrugTarget Finalization Validator — Test Fixtures

Each subdirectory is a self-contained synthetic run output (or intentionally broken variant)
used to unit-test `validate_drug_report_finalization`. All fixtures are hand-built minimal
cases. Tests MUST NOT depend on `res_ipf_qwen*/drug.md`.

## Fixture Inventory

| Directory                   | Issue Code                  | Defect description                                                      |
|-----------------------------|-----------------------------|-------------------------------------------------------------------------|
| `clean/`                    | _(none — negative control)_ | All checks pass. One EGFR + one TGFB1 candidate. MoA cells match stage3 evidence. Gap Analysis has body text. Stage1 count not mentioned in prose (no-op for count check). |
| `invalid_data_dir/`         | `INVALID_DATA_DIR`          | Empty dir; test constructs invalid paths at runtime (see README inside). |
| `missing_required_artifact/`| `MISSING_REQUIRED_ARTIFACT` | All 4 required files present; test removes one at a time via tmpdir copy. |
| `validate_drug_md_failed/`  | `VALIDATE_DRUG_MD_FAILED`   | `drug.md` classifies BRCA1 as `Validated Target`; `evidence/assessment_results.json` classifies it as `exploratory_target`. |
| `missing_target_assessment/`| `MISSING_TARGET_ASSESSMENT` | `target_assessment.json` is empty (zero bytes / whitespace-only).       |
| `target_assessment_invalid/`| `TARGET_ASSESSMENT_INVALID` | `target_assessment.json` is valid JSON but lacks required `druggability_matrix` key on all entries. |
| `markdown_table_pipe_drift/`| `MARKDOWN_TABLE_PIPE_DRIFT` | Drug Profile table row for TGFB1 contains an unescaped `\|` inside a cell value (`blocks SMAD2/3 \| collagen deposition`), shifting column count by 1. |
| `stage1_count_mismatch/`    | `STAGE1_COUNT_MISMATCH`     | `drug.md` prose says "18 L-R pairs"; `stage1_filter_results.json` has `total: 19`. Comment in drug.md documents the four phrasings the validator must catch. |
| `empty_gap_analysis/`       | `EMPTY_GAP_ANALYSIS`        | `### Gap Analysis` heading is immediately followed by `### Therapeutic Recommendations` with no body text between them. |
| `unsupported_moa_claim/`    | `UNSUPPORTED_MOA_CLAIM`     | Drug Profile MoA cell for TGFB1 says "potent JAK1 selective inhibitor"; neither `evidence/stage3_TGFB1.json` nor `evidence/stage3_EGFR.json` mentions JAK1. |

## Required Artifacts (v1)

Every successful run output must contain:
- `drug.md`
- `target_assessment.json`
- `evidence/assessment_results.json`
- `stage1_filter_results.json`

The `missing_required_artifact/` fixture contains all four. Tests should copy the fixture to
a tmpdir and remove one file at a time to isolate each `MISSING_REQUIRED_ARTIFACT` case.

## MoA Test Notes

`clean/` includes `evidence/stage3_EGFR.json` and `evidence/stage3_TGFB1.json`. The Drug
Profile MoA cells in `clean/drug.md` are taken verbatim from those files, so the
`UNSUPPORTED_MOA_CLAIM` check passes.

`unsupported_moa_claim/` has the same two stage3 files, but `drug.md` claims ruxolitinib is
a "potent JAK1 selective inhibitor" for TGFB1. Neither stage3 file mentions JAK1, so the
check fires.

## Stage1 Count Phrasing Coverage

`stage1_count_mismatch/drug.md` includes the phrase "18 L-R pairs" in section 2 body text
and again in section 4. Tests should also parameterize over these equivalent phrasings
(all claim 18, evidence total is 19):
- `of 18 L-R pairs`
- `of 18 ligand-receptor pairs`
- `across 18 L-R pairs`
- `from 18 pairs`

When `drug.md` contains none of these patterns, the count check must be a no-op. The `clean/`
fixture exercises that no-op case (no count claim in prose).

## `invalid_data_dir` Test Construction

The test for `INVALID_DATA_DIR` should pass the following directly to the validator (not via
this fixture directory):
1. `/tmp/nonexistent_deep_mast_run_xyz_99999` — path does not exist
2. `/` — filesystem root
3. Repository root (the DeepMAST checkout path) — not a run output directory
4. Path to any existing file (e.g. a `.py` source file) — not a directory

The validator must return `INVALID_DATA_DIR` for all four without consulting
`DRUG_TARGET_DATA_DIR`, `DEEP_INTERPRETER_DATA_DIR`, or `/tmp/deep_interpreter_workspace`.
