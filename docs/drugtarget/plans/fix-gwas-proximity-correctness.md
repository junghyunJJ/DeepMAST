# PR Plan — `fix/gwas-proximity-correctness`

**Status**: ready-to-implement (drafted 2026-04-20)
**Author context**: follow-up to PR #4 + #5 (already merged to `main`). Post-run review uncovered two latent silent bugs in the GWAS proximity-matching code. They do NOT change the IPF run result (verified: CCI panel has zero proximity overlap with IPF GWAS loci at the 500 kb window), but they prevent any other disease/panel combination from correctly earning GWAS proximity points.

**Estimated effort**: 1 day (code + tests + one smoke re-run)
**Risk**: low — localized to two files, no schema changes, no re-ranking expected for the IPF data dir

---

## Prior work — read first

This session is a continuation. The prior context:

1. **PR #4** (merged as `62fa68b..268a4ad`): closed 12 CRITICAL/HIGH defects from the first deepwork review.
2. **PR #5** (`fix/followup-pipeline-defects`, merged): closed 7 follow-up defects including novelty bracket rescale, Stage-1-aware promotion, schema null-types + persist, grounding regex tightening, HYPOTHESIS_WRITER prompt rewrite.
3. **This PR (#6)**: residual GWAS proximity-matching correctness. Surfaced by a 3rd-pass code-reviewer + architect review on the fresh `res_ipf_qwen2/` artifacts.

Key files to orient yourself (read in this order):
- `docs/drugtarget/plans/fix-gwas-proximity-correctness.md` ← this file
- `scripts/validate_pipeline_output.py` — the 5-invariant gate, must still exit 0 after changes
- `tests/test_drug_target_fixes.py` and `tests/test_drug_target_followup.py` — must still pass (26 tests)

---

## Problem statement

The drug-target pipeline scores each gene on `gwas_support ∈ {0, 1, 2, 3}` using `src/agents/drug_target/tools/stage_logic.py:1040-1077::_score_gwas_support`. The score depends on three counts inside `disease_specific_hits`:

- `n_gene_in_trait` — exact gene-name match in trait_associations[*].genes
- `n_gene_snps_in_disease` — exact rsId intersection of gene cis-SNPs and trait SNPs
- `n_proximity_hits` — genomic proximity (±500 kb window) between gene loci and trait SNPs

**The proximity dimension is dead code**. Two compounding bugs guarantee `n_proximity_hits = 0` for every gene, every disease.

### Bug A (HIGH): `_proximity_match` format gate

Location: `src/agents/drug_target/tools/stage2_service.py:519-555`

```python
def _proximity_match(gene_assocs, trait_assocs, window=500_000):
    gene_regions = [...]                       # (chrom, pos) tuples from gene_assocs[*].locations
    nearby = []
    for ta in trait_assocs:
        rsid = ta.get("rsId", "")
        if ":" in rsid:                          # ← guards entry to the actual matching
            raw = rsid.replace("chr", "")
            parts = raw.split(":")
            t_chrom, t_pos = parts[0], int(parts[1])
            for g_chrom, g_pos in gene_regions:
                if ... abs(t_pos - g_pos) <= window ...
```

Trait rsIds from OpenTargets Genetics / GWAS Catalog come in dbSNP form (`rs35705950`) — **none contain `:`**. The matching loop is therefore never entered. Confirmed empirically: every gene in `res_ipf_qwen2/evidence/stage2_evidence.json` has `n_proximity_hits = 0` despite the call path running.

### Bug B (MEDIUM): parquet strips chr/pos from trait associations

Location: `skills/gwas-database/scripts/gwas_parquet.py:114-154::get_trait_associations`

```python
results.append({
    "rsId": row.get("rsId", ""),
    "pvalue": ...,
    ...
    "genes": genes,
    "studyId": ...,
    "trait": ...,
})
```

The parquet file stores `chromosome` and `position` columns (confirmed — see `skills/gwas-database/scripts/download_gwas_bulk.py:181-188` which writes them). `get_trait_associations` never propagates those two columns into its return dict. Even when Bug A is fixed, there is no `(chrom, pos)` on trait entries to compare against gene regions.

### Why the bugs compound

- Bug A says "can't parse a chr:pos from rsId form" — a format problem.
- Bug B says "no chr:pos is available anyway" — a data-surfacing problem.
- Together: proximity has neither parseable keys nor structured coordinate fields. Dead code.

### What's NOT broken

- `get_gene_associations` at `gwas_parquet.py:196-199` correctly propagates `locations` (chromosome/position list) for each gene SNP. That's why `gene_regions` builds successfully — the asymmetry is only on the trait side.
- `_score_gwas_support` scoring brackets work. `_proximity_match` is called (confirmed by `n_proximity_hits` key appearing in every output). Just always returns `[]`.

---

## Fix plan

### 1. Surface chromosome/position in trait associations

**File**: `skills/gwas-database/scripts/gwas_parquet.py`
**Function**: `get_trait_associations` (lines 114-154)

Add two fields to the appended dict:

```python
results.append({
    "rsId": row.get("rsId", ""),
    "pvalue": float(row["pvalue"]) if pd.notna(row.get("pvalue")) else None,
    "pvalueMantissa": None,
    "pvalueExponent": None,
    "riskAllele": row.get("riskAllele", ""),
    "orPerCopyNum": float(row["orBeta"]) if pd.notna(row.get("orBeta")) else None,
    "betaNum": None,
    "betaUnit": "",
    "genes": genes,
    "studyId": row.get("studyAccession", ""),
    "trait": row.get("trait", ""),
    # NEW: coordinate fields for _proximity_match downstream.
    "chromosome": str(row.get("chromosome", "") or "") or None,
    "position": int(row["position"]) if pd.notna(row.get("position")) else None,
})
```

Edge cases: when `chromosome` / `position` are missing in the parquet row (rare but possible for older entries), emit `None` so downstream consumers can skip those trait entries cleanly.

### 2. Rewrite `_proximity_match` to use coordinates, not rsId format

**File**: `src/agents/drug_target/tools/stage2_service.py`
**Function**: `_proximity_match` (lines 519-555)

Replace body with coordinate-based comparison. Accept either `(chromosome, position)` direct fields or legacy `chr:pos` format for backward compatibility.

```python
def _proximity_match(
    gene_assocs: list[dict],
    trait_assocs: list[dict],
    window: int = 500_000,
) -> list[dict]:
    """Find trait SNPs within ±window bp of any gene-associated locus.

    Accepts trait_assocs entries in either shape:
      - structured: {"chromosome": "11", "position": 1219991, ...}
      - legacy:     {"rsId": "chr11:1219991", ...}

    Requires gene_assocs[*].locations entries with `chromosome` + `position`.
    Returns the subset of trait_assocs whose (chrom, pos) lies within
    `window` of at least one gene region.
    """
    # Build gene regions from gene_assocs (unchanged).
    gene_regions: list[tuple[str, int]] = []
    for ga in gene_assocs:
        for loc in ga.get("locations", []):
            chrom = loc.get("chromosome") or loc.get("chromosomeName")
            pos = loc.get("position") or loc.get("chromosomePosition")
            if chrom and pos is not None:
                try:
                    gene_regions.append((str(chrom), int(pos)))
                except (ValueError, TypeError):
                    continue
    if not gene_regions:
        return []

    def _trait_coords(ta: dict) -> tuple[str, int] | None:
        """Extract (chrom, pos) from a trait association in either shape."""
        # Preferred: structured fields (added by gwas_parquet.py fix).
        chrom = ta.get("chromosome")
        pos = ta.get("position")
        if chrom and pos is not None:
            try:
                return (str(chrom), int(pos))
            except (ValueError, TypeError):
                pass
        # Legacy: parse chr:pos out of rsId string.
        rsid = str(ta.get("rsId", "") or "")
        if ":" in rsid:
            raw = rsid.replace("chr", "")
            parts = raw.split(":")
            if len(parts) == 2:
                try:
                    return (parts[0], int(parts[1]))
                except (ValueError, TypeError):
                    return None
        return None

    nearby: list[dict] = []
    seen: set[str] = set()
    for ta in trait_assocs:
        key = str(ta.get("rsId", "") or "")
        if key in seen:
            continue
        coords = _trait_coords(ta)
        if coords is None:
            continue
        t_chrom, t_pos = coords
        for g_chrom, g_pos in gene_regions:
            if str(t_chrom) == str(g_chrom) and abs(t_pos - g_pos) <= window:
                nearby.append(ta)
                seen.add(key)
                break
    return nearby
```

Key invariants the rewrite must preserve:
- Returns `list[dict]`, never mutates inputs.
- Dedupes on rsId.
- Returns `[]` when no gene regions (legacy behaviour).
- Legacy `chr:pos` rsId parsing still works (keeps backward compat with any caller that still emits that form).

### 3. Documentation

Update the inline docstring on `_score_gwas_support` (`stage_logic.py:1040-1050`) to reflect that proximity scoring is now functional, not just a placeholder. One-liner in the commit message suffices.

No schema change. No validator invariant change.

---

## Tests

**New file**: `tests/test_drug_target_gwas_proximity.py`

One hermetic test covering the three code paths:

```python
"""Regression tests for fix/gwas-proximity-correctness.

Covers Bug A (format gate) + Bug B (chr/pos surfacing) fixes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_parquet_mod():
    spec = importlib.util.spec_from_file_location(
        "gpq",
        REPO_ROOT / "skills/gwas-database/scripts/gwas_parquet.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_get_trait_associations_surfaces_chromosome_position(monkeypatch):
    """Bug B fix: get_trait_associations must propagate chr/pos from parquet."""
    pd = pytest.importorskip("pandas")
    gpq = _load_parquet_mod()

    df = pd.DataFrame([
        {
            "efoId": "EFO_IPF",
            "rsId": "rs35705950",
            "pvalue": 1e-40,
            "chromosome": "11",
            "position": 1219991,
            "genes_list": [],
            "studyAccession": "GCST001",
            "trait": "pulmonary fibrosis",
            "riskAllele": "T",
            "orBeta": 4.51,
        },
    ])
    monkeypatch.setattr(gpq, "_load_associations", lambda: df)
    out = gpq.get_trait_associations("EFO_IPF")
    assert len(out) == 1
    assert out[0]["chromosome"] == "11"
    assert out[0]["position"] == 1219991
    assert out[0]["rsId"] == "rs35705950"


def test_proximity_match_uses_structured_coords():
    """Bug A fix: _proximity_match works on (chr, pos) fields, not only chr:pos rsIds."""
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    gene_assocs = [
        {"rsId": "rs2855535", "locations": [{"chromosome": "12", "position": 6800000}]},
    ]
    trait_assocs_structured = [
        {"rsId": "rs35705950", "chromosome": "12", "position": 6850000},  # 50 kb away -> hit
        {"rsId": "rs99999999", "chromosome": "1", "position": 1},           # different chrom
        {"rsId": "rs88888888", "chromosome": "12", "position": 8_000_000},  # 1.2 Mb -> miss
    ]
    hits = _proximity_match(gene_assocs, trait_assocs_structured)
    assert [h["rsId"] for h in hits] == ["rs35705950"]


def test_proximity_match_legacy_chr_pos_rsid_still_supported():
    """Backward compat: chr:pos rsId form still works."""
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    gene_assocs = [
        {"locations": [{"chromosome": "11", "position": 1220000}]},
    ]
    trait_assocs_legacy = [
        {"rsId": "chr11:1219991"},       # 9 bp away -> hit
        {"rsId": "chr11:5000000"},       # 3.78 Mb -> miss
    ]
    hits = _proximity_match(gene_assocs, trait_assocs_legacy)
    assert [h["rsId"] for h in hits] == ["chr11:1219991"]


def test_proximity_match_empty_inputs():
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    assert _proximity_match([], []) == []
    # Gene assocs missing locations → empty result.
    assert _proximity_match([{"rsId": "rs1"}], [{"chromosome": "1", "position": 1}]) == []


def test_proximity_match_dedupes_on_rsid():
    from src.agents.drug_target.tools.stage2_service import _proximity_match

    gene_assocs = [{"locations": [{"chromosome": "1", "position": 100}]}]
    trait_assocs = [
        {"rsId": "rs1", "chromosome": "1", "position": 150},
        {"rsId": "rs1", "chromosome": "1", "position": 200},  # same rsId
        {"rsId": "rs2", "chromosome": "1", "position": 200},
    ]
    hits = _proximity_match(gene_assocs, trait_assocs)
    assert sorted(h["rsId"] for h in hits) == ["rs1", "rs2"]
```

Target: 5 tests, all pass.

---

## Verification (post-implementation)

```bash
# Unit tests
pytest tests/test_drug_target_gwas_proximity.py -v
# 5/5 pass

# Regression check — follow-up suite must stay green
pytest tests/test_drug_target_fixes.py tests/test_drug_target_followup.py -q
# 26/26 pass

# Main suite — must match main baseline (17 failed / 221 passed — pre-existing)
pytest tests/test_drug_target.py -q -m "not api"
# 17 failed / 221 passed (identical to main)

# Ruff B023 still clean
ruff check --select B023 src/agents/drug_target/

# Invariant validator on existing res_ipf_qwen2/ artifacts — PASS (no artifact change needed)
python scripts/validate_pipeline_output.py res_ipf_qwen2/
```

### Smoke integration (optional but recommended)

Re-run the pipeline on `res_ipf_qwen2` and confirm `gwas_support` is still 0 for all 41 genes (expected: the proximity fix surfaces no new hits for IPF because the CCI panel is >4 Mb from every IPF GWAS locus):

```bash
python scripts/run_drug_target_traced.py \
  --data-dir res_ipf_qwen2/ \
  --disease "idiopathic pulmonary fibrosis" \
  --no-debug \
  --census

# After completion:
python3 -c "
import json
rows = json.load(open('res_ipf_qwen2/evidence/assessment_results.json'))['rubric_assessment']
print('gwas_support still 0?:', all(r['gwas_support'] == 0 for r in rows))
"
```

Expected: `True` — IPF data truly has no proximity overlap, so the fix is structural (not behavioral for this specific run).

### Forward-looking smoke (how to prove the fix actually helps)

Pick a disease where CCI panels and GWAS loci are known to overlap. A good fixture is **Rheumatoid arthritis (EFO_0000685)** with any CCI panel that includes HLA-DRB1. The HLA region on chr6 has dense GWAS signal; HLA-DRB1 cis-SNPs will now register as proximity hits.

Document this forward-looking test in the PR description so reviewers see the value proposition beyond the IPF no-op.

---

## Commit structure

Single PR, two commits (bisectable):

### Commit 1: `fix(gwas): surface chromosome + position in trait associations`
- File: `skills/gwas-database/scripts/gwas_parquet.py` (~+3 LOC)
- Closes Bug B on its own: even without touching `_proximity_match`, downstream consumers can now do their own coordinate lookups.

### Commit 2: `fix(drug_target): proximity match on coordinates, not rsId format`
- File: `src/agents/drug_target/tools/stage2_service.py` (~+30 / −10 LOC)
- File: `tests/test_drug_target_gwas_proximity.py` (new, ~120 LOC)
- Closes Bug A. Requires Commit 1.

---

## PR description template

```
## Summary

Closes two latent silent bugs in the GWAS proximity-matching code surfaced
by the 3rd-pass deepwork review of `res_ipf_qwen2/` post PR #4 + #5.

Both bugs cause `n_proximity_hits = 0` for every (gene, disease) combination
regardless of actual genomic overlap. They do NOT change the IPF run result
(verified: CCI panel is >4 Mb from every IPF GWAS locus), but they prevent
any disease/panel where genomic proximity exists (e.g., autoimmune panels
with HLA genes) from correctly earning `gwas_support = 1`.

## Fixes

- **Bug A** (`stage2_service.py:519-555`): `_proximity_match` only parsed
  rsIds containing `":"`. Trait rsIds from OT Genetics are always dbSNP
  form (`rs35705950`). The matching loop never entered — dead code.
  Fix: compare `(chromosome, position)` directly; keep legacy `chr:pos`
  rsId parsing as a fallback.
- **Bug B** (`gwas_parquet.py:114-154`): `get_trait_associations` stripped
  `chromosome` and `position` columns from the parquet on return. Even
  with Bug A fixed, there was no structured coordinate data to compare.
  Fix: propagate both fields to the output dict.

## Tests

- `tests/test_drug_target_gwas_proximity.py` (new, 5 tests, all pass):
  structured coordinate match, legacy `chr:pos` rsId match, empty inputs,
  dedup-by-rsId, chr/pos propagation.
- 26/26 existing follow-up tests still pass (test_drug_target_fixes.py
  + test_drug_target_followup.py).
- 17/221 main-suite baseline unchanged.

## Impact on IPF run

Zero. `gwas_support = 0` for all 41 genes remains (correct behaviour —
verified by coordinate lookup: nearest CCI gene to any IPF GWAS SNP is
CD81 at 4 Mb, way outside the 500 kb window).

## Why this matters

The fix is structural. When DeepMAST is applied to any disease where
CCI panels and GWAS peaks overlap (autoimmune, cancer, inflammatory
bowel disease), genes within 500 kb of a genome-wide-significant SNP
will now correctly receive `gwas_support = 1`. Before this PR, that
score was unreachable.

## Out of scope / next steps

- **Not** adding OT Genetics L2G scoring (Option 3 from the planning
  discussion). The L2G dimension would add functional eQTL-driven
  signal beyond proximity; ~3-5 days of work. Deferred until a
  research question actually requires it.
- **Not** changing novelty brackets, the hypothesis grounding regex,
  or any PR #4 / #5 contract.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## Rollback

If anything regresses:
1. `git revert <commit-sha-of-commit-2> <commit-sha-of-commit-1>`
2. `gh pr close <pr-number>`
3. Re-run `pytest tests/test_drug_target_fixes.py tests/test_drug_target_followup.py` to confirm green.

Since the fix does not alter the artifact format, there is no data-migration concern. The `gwas_parquet.py` change is additive (new fields, no removals), so any code that ignores the new fields is unaffected.

---

## Handoff notes for the next session

- Start a fresh session at `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST`, on `main`.
- You do NOT need context from the prior conversation — this file is self-contained.
- Do all changes on a new branch: `git checkout -b fix/gwas-proximity-correctness`.
- The user has already aligned on Option 2 only (not Option 3). Do not expand scope.
- When complete: push branch, `gh pr create --base main --head fix/gwas-proximity-correctness --title "fix(drug_target): correct GWAS proximity matching (bugs A+B)"`, paste the PR description above.
- User asked for this plan to be written so they could pick it up in a different session. They're OK with you working autonomously when they start the next session — expect `"계속 진행"` or similar go-ahead signal.
