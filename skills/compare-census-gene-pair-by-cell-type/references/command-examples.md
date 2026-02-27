# Command Examples

Run examples from the skill directory (`cd skills/compare-census-gene-pair-by-cell-type` in this repository).

## Basic Human Disease Run

```bash
python scripts/compare_census_gene_pair_by_cell_type.py \
  --disease "breast cancer" \
  --gene-a TGFB1 \
  --gene-b TGFBR2 \
  --target-cell-type "malignant cell" \
  --census-version 2025-11-08
```

## Add Extra Filter and Export CSV

```bash
python scripts/compare_census_gene_pair_by_cell_type.py \
  --disease "lung adenocarcinoma" \
  --gene-a CXCL8 \
  --gene-b CXCR1 \
  --target-cell-type "neutrophil" \
  --obs-extra-filter "tissue_general == 'lung'" \
  --min-cells 100 \
  --top-n 30 \
  --output-csv res/census_luad_cxcl8_cxcr1.csv
```

## Mouse Example Including Non-Primary Cells

```bash
python scripts/compare_census_gene_pair_by_cell_type.py \
  --organism mus_musculus \
  --disease "normal" \
  --gene-a Tgfb1 \
  --gene-b Tgfbr2 \
  --target-cell-type "fibroblast" \
  --include-non-primary \
  --census-version 2025-11-08
```

## Quick Validation Command

Use this before a long query to ensure options and environment are ready:

```bash
python scripts/compare_census_gene_pair_by_cell_type.py --help
```
