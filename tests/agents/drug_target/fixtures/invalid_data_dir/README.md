# Fixture: invalid_data_dir

**Issue Code:** `INVALID_DATA_DIR`

This fixture directory is intentionally empty. The `invalid_data_dir` test case does not use
files from this directory at all — instead, the test constructs invalid path strings directly
and passes them as the `data_dir` argument to `validate_drug_report_finalization`.

## How the test should use this fixture

The test should exercise the following invalid paths (none of which contain a real run output):

1. A path that does not exist on disk, e.g. `/tmp/nonexistent_deep_mast_run_xyz`.
2. The filesystem root `/`.
3. The repository root (e.g. the absolute path of the DeepMAST checkout).
4. A file path rather than a directory (e.g. any `.py` file on disk).

For each of these, `validate_drug_report_finalization(data_dir)` must:
- Return `valid=false`
- Return `issue_count >= 1`
- Include an issue with `code == "INVALID_DATA_DIR"`
- NOT consult `DRUG_TARGET_DATA_DIR`, `DEEP_INTERPRETER_DATA_DIR`, or
  `/tmp/deep_interpreter_workspace` as fallbacks.

## Why this fixture has no files

The validator's `INVALID_DATA_DIR` check fires before any artifact is read, so no supporting
evidence files are needed. Providing files here would be misleading.
