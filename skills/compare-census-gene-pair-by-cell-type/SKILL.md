---
name: compare-census-gene-pair-by-cell-type
description: Run and interpret scripts/compare_census_gene_pair_by_cell_type.py for disease-focused CELLxGENE Census analysis. Use when you need cell-type-level expression and co-expression rates for two genes, target-vs-rest two-proportion z-tests, or reproducible CSV outputs by cell type.
---

# Compare Census Gene Pair By Cell Type

## Overview

Run the script `scripts/compare_census_gene_pair_by_cell_type.py` from this skill directory to compare two genes across cell types for a disease subset in CELLxGENE Census. Compute `gene_a+`, `gene_b+`, and co-expression rates, then test enrichment/depletion for one target cell type versus all remaining cells.

Use [command-examples.md](references/command-examples.md) when you need ready-to-run command patterns.

## Prerequisites

- Ensure Python can import required packages:
  - `cellxgene_census`
  - `tiledbsoma`
- Run a quick dependency check before analysis:

```bash
python -c "import cellxgene_census, tiledbsoma; print('ok')"
```

## Workflow

1. Confirm required inputs: `--disease`, `--gene-a`, `--gene-b`, `--target-cell-type`.
2. Build a command from the template below; pin `--census-version` for reproducibility.
3. Run the script and review:
   - `Overall summary`
   - `Target vs rest`
   - `Cell-type summary`
4. If needed, rerun with `--obs-extra-filter`, `--min-cells`, `--top-n`, or `--include-non-primary`.
5. Use `--output-csv` to persist full cell-type metrics and summarize downstream.

## Command Template

Run from the skill directory:

```bash
python scripts/compare_census_gene_pair_by_cell_type.py \
  --disease "<disease>" \
  --gene-a <GENE_A> \
  --gene-b <GENE_B> \
  --target-cell-type "<cell_type>" \
  --organism homo_sapiens \
  --census-version <YYYY-MM-DD> \
  --min-cells 50 \
  --top-n 20
```

## Optional Flags

Use these only when required:

- `--include-non-primary`: Include non-primary cells. Default is primary-only (`is_primary_data == True`).
- `--obs-extra-filter "<expr>"`: Add extra obs filter with `and`.
- `--output-csv <path>`: Save full per-cell-type table.
- `--organism mus_musculus`: Switch organism.

## Output Interpretation

Use `Target vs rest` lines for inferential comparison:

- `target` and `rest`: Positive rates in each group.
- `diff`: Absolute difference (`target - rest`).
- `RR`: Risk ratio (`target/rest`).
- `z`, `p`: Two-proportion z-test statistics.

Treat very small cell counts cautiously, even with small p-values. Increase `--min-cells` when needed.

## Troubleshooting

- `No cells matched the provided obs filter`:
  - Check disease label spelling.
  - Remove or relax `--obs-extra-filter`.
- `Gene(s) not found in Census var metadata`:
  - Validate gene symbols and organism.
- `Target cell type '<name>' not found`:
  - Use the error's suggested available cell types, then rerun.
- `--gene-a and --gene-b must be different genes`:
  - Choose two distinct genes.

## Execution Notes

- Enter this skill directory before running commands:
  - Repository copy: `cd skills/compare-census-gene-pair-by-cell-type`
  - Global skill copy: `cd ~/.codex/skills/compare-census-gene-pair-by-cell-type`
- Confirm CLI options quickly with:
  - `python scripts/compare_census_gene_pair_by_cell_type.py --help`
- Prefer pinned `--census-version` for reproducible analysis.
- Use UTF-8 safe quoting for disease/cell type strings with spaces.

## References

- [command-examples.md](references/command-examples.md)
