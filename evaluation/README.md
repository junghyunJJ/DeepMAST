# DeepMAST Evaluation Assets

This directory contains fixed benchmark specifications for Core Suite v1.1
(Deep Interpreter part-aligned).

## Layout

- `datasets/catalog.yaml`: dataset registry (3 fixed datasets)
- `evidence/*.yaml`: per-dataset evidence checklists (8 claims each)
  with `deep_interpreter_part` tags (`part1`, `part2`, `part3`)
- `core_suite/tasks_v1.yaml`: 24-task benchmark suite (`core_suite_v1_1`)
- `schema.py`: schema contracts and validators
- `build_core_suite.py`: regenerate `tasks_v1.yaml` from evidence
- `check_pmids.py`: PMID existence checker
- `validate_specs.py`: end-to-end cross-file validation
- `schema_post_hitl.json`: JSON schema for post-HITL run records
- `validate_post_hitl.py`: validator for post-HITL run records
- `scorers.py`: scoring interface contracts

## Commands

```bash
python -m evaluation.build_core_suite \
  --catalog evaluation/datasets/catalog.yaml \
  --evidence evaluation/evidence \
  --output evaluation/core_suite/tasks_v1.yaml
```

```bash
python -m evaluation.validate_specs \
  --catalog evaluation/datasets/catalog.yaml \
  --evidence evaluation/evidence \
  --suite evaluation/core_suite/tasks_v1.yaml
```

```bash
python -m evaluation.check_pmids --evidence evaluation/evidence --strict
```

```bash
pytest tests/evaluation -v
```

```bash
python -m evaluation.validate_post_hitl --input evaluation/examples/post_hitl_sample.json
```

## CI Gate

GitHub Actions workflow: `.github/workflows/evaluation-gate.yml`

- Job name: `evaluation-gate`
- Runs on PRs and pushes to `main`/`master`
- Enforces:
  - core suite regeneration
  - spec consistency validation
  - strict PMID verification (with retries)
  - evaluation test suite

To make it a required merge gate, set branch protection to require
the `evaluation-gate` check.

## Freeze Policy

Core Suite v1 is immutable for reproducibility.

- Do not modify `tasks_v1.yaml` directly.
- Update evidence/catalog and regenerate tasks using `build_core_suite.py`.
- Any task expansion must be published as `v2`.
