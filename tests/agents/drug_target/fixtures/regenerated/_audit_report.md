# Manual Audit — Regenerated drug.md vs. Baseline Hallucinations

**Auditor:** core-critique
**Date:** 2026-04-29
**Subject file:** `tests/agents/drug_target/fixtures/regenerated/drug.md` (42 KB, 0 EXPAND markers)
**Baseline:** `tests/agents/drug_target/fixtures/baseline_hallucinated/drug.md`
**Evidence corpus:** `tests/agents/drug_target/fixtures/baseline_hallucinated/evidence/` (33 files)
**Audit scope:** Phase 6 / Task T21 of `2026-04-29-drug-target-closed-book-e2e-stabilization.md`

---

## Verdict: REJECT

One of the six known P0 hallucinations persists in the regenerated report (the fabricated `known_drugs.json` evidence-file reference at line 352). The remaining five are confirmed resolved. No new fabrications were introduced by the regenerated writer beyond what is faithfully copied from the upstream `hypothesis_report.json`.

---

## Resolution Status — 6 Known Hallucinations

| # | Hallucination | Status | Evidence in regenerated drug.md |
|---|---------------|--------|----------------------------------|
| 1 | `ocriplasmin (approved 2010)` — fabricated FDA approval year | **RESOLVED (absent)** | `grep -i "ocriplasmin\|2010"` returns 0 hits. The OCRIPLASMIN entity exists in `resolved_drugs.json` for FN1 (max_phase=4) but is not surfaced in the regenerated report at all. FN1 drug-profile section (line 179) states only "No known drugs targeting this gene", which is consistent with the chembl-only `stage3_FN1.json` (`matched_drugs: []`) it cites as source. No approval-year claim. |
| 2 | `[from known_drugs.json]` — fabricated file reference | **NOT RESOLVED** | Line 352 (Hypothesis 4.2 / Lovastatin): `- known_drugs.json` listed under **Evidence References**. `known_drugs.json` does NOT exist in the evidence directory (`ls evidence/` confirms 33 files, none named `known_drugs.json`). The reference is inherited from the upstream `hypothesis_report.json` (itself a hallucinated upstream artifact) — so the writer is faithfully copying a hallucinated upstream string rather than re-fabricating it. Either way, the user-visible drug.md still contains a citation to a nonexistent file, which is the original P0 symptom. |
| 3 | `*_FAILED`-suffix file references (e.g. `stage1_*.json_FAILED`) | **RESOLVED (absent)** | `grep -i "_FAILED"` returns 0 hits across the regenerated drug.md. |
| 4 | `ibalizumab 2018 approval` — ungrounded approval year | **RESOLVED (absent)** | `grep -i "ibalizumab\|2018"` returns 0 hits. CD4 drug profile (line 126) states only "No known drugs targeting this gene". IBALIZUMAB exists in `resolved_drugs.json` (CD4, max_phase=4) but is not surfaced; the writer correctly elided the unverifiable approval-year claim entirely. |
| 5 | `ocriplasmin mechanism (degrades fibronectin)` — ungrounded MoA | **RESOLVED (absent)** | The word "fibronectin" appears once at line 181 only as the gene-name expansion `FN1 (fibronectin)`, which is a bona-fide synonym. There is no "degrades", no mechanism description for OCRIPLASMIN, and no OCRIPLASMIN entity at all in the prose. |
| 6 | `AS-1409 (aptamer) classification` — ungrounded classification | **RESOLVED (absent)** | `grep -i "AS-1409\|aptamer"` returns 0 hits. AS-1409 exists in `resolved_drugs.json` for FN1 (`molecule_type: "Unknown"`) but the writer correctly elides it rather than guessing a classification. |

**Score:** 5 / 6 resolved.

---

## New-Fabrication Sweep

A line-by-line skim of the regenerated drug.md against the evidence directory yields the following observations:

**Drug entities mentioned in prose:** Lifitegrast, Lovastatin, GO-203 (MUC1-C inhibitor).
- **Lifitegrast** — grounded. Present in `resolved_drugs.json` for ITGB2 (chembl_id CHEMBL2048028, Small molecule, max_phase=4). The regenerated report calls it an "ICAM1 antagonist" (line 339) which is a slight semantic drift (Lifitegrast clinically blocks the ICAM1–LFA-1 interaction; LFA-1 = αLβ2 = ITGB2). Not a hard fabrication, but worth noting as a borderline mechanism statement.
- **Lovastatin** — grounded. Listed in `stage3_ITGB2.json` (`drug_name: "LOVASTATIN"`) and the upstream `hypothesis_report.json` Hypothesis 4.2. Faithful copy.
- **GO-203 (MUC1-C inhibitor)** — grounded in upstream `hypothesis_report.json` validation_approach text. Faithful copy. Not present in `resolved_drugs.json`, but it is present in the upstream evidence the writer was given.

**FDA-approval claims, mechanism descriptions, classification claims:** None found in prose. The writer consistently states "No known drugs targeting this gene" for all 7 candidates, which is grounded in the chembl-only `stage3_*.json` files (`matched_drugs: []`). This is a substantive *under-claim* relative to `resolved_drugs.json` (which lists ≥1 drug per featured candidate from OpenTargets), but it errs in the safe direction (no fabrication) and is internally consistent with the cited source.

**File references:** All `stage1_*.json`, `stage3_*.json`, and `ot_*.json` references match real files in the evidence directory. The single exception is `known_drugs.json` at line 352 (Hallucination #2 above).

**Risk-ratio / STRING / p-value numerics:** Spot-checked five citations (HLA-DQB1–CD4 RR=0.0523, ICAM1–MUC1 RR=17.863, ICAM1–EZR RR=4.4977, FN1–SDC2 RR=0.2258, ICAM1–PECAM1 p=3.45e-07). All match the corresponding `stage1_*.json` files. No fabricated numbers detected.

**Conclusion:** No NEW fabrications introduced by the closed-book writer. The lone surviving fabrication (`known_drugs.json`) is inherited verbatim from upstream `hypothesis_report.json`.

---

## Remediation Pointer

Hallucination #2 cannot be fixed by tightening the report-writer prompt alone, because the writer is faithfully echoing upstream JSON. Two options:

1. **Upstream fix:** strip non-existent file references from `hypothesis_report.json` before passing it to the report writer (filter `evidence_files` against the actual evidence directory listing).
2. **Writer-side guard:** add a post-generation check in the closed-book writer that filters Evidence References to only include files present on disk, and replaces a missing file with `"not available in source data"` per the project's literal-string convention.

Recommend option 1 (single source of truth) but option 2 is acceptable as defense-in-depth.

---

## Summary

| Metric | Value |
|--------|-------|
| Known hallucinations resolved | 5 / 6 |
| Known hallucinations persisting | 1 / 6 (`known_drugs.json` at line 352) |
| New fabrications introduced | 0 |
| EXPAND markers in regenerated | 0 (per task brief) |
| Final verdict | **REJECT** |
