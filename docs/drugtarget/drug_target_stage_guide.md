# Drug Target Assessment Agent -- Stage-by-Stage Guide

> **Version**: Current independent agent (`src/agents/drug_target/`) — updated 2026-07-15 for guarded direct report writing
> **Supersedes**: `docs/phase47_drug_target_assessment_step_by_step.md` (legacy deep_interpreter Phase 4.7)

---

> **Current production contract:**
> ```text
> prepare -> validate_evidence -> hypothesis_writer
>         -> validate_hypothesis -> report_writer -> final audit/publication
> ```
> The root LLM does not schedule guarded production phases. The root LLM does not schedule guarded production retries. The report_writer is never invoked without a fresh valid hypothesis handoff. Production Section 4 is in `drug.md`; success needs two audits and seven artifacts including `drug_report_validation_final.json`. Configured-directory tools are forced safe, `general-purpose` is blocked, and custom tools are rejected. `legacy_hypothesis` is the explicit outer-super-graph/finalizer compatibility path. Full-agent, E2E, and BC paths are production entrypoints; `run_report_writer_only.py` is diagnostic-only and requires a valid existing handoff.

**Production entrypoints**: construct `create_drug_target_agent` directly with
`workflow_mode="guarded_report"`, or run `run_drug_target_e2e.py` and
`run_drug_target_agent_bc.py`. `run_report_writer_only.py` only diagnoses the
canonical writer against existing evidence.

**Production Reporter integration**: `integration.py` exposes
`run_drug_target_assessment(data_dir, disease)` for the Deep Interpreter
Reporter. It lazily imports `create_drug_target_agent`, builds it with
`workflow_mode="guarded_report"`, and invokes the returned `agent.ainvoke(...)`.
`super_graph.py` remains the Legacy compatibility super-graph for explicit
`legacy_hypothesis` callers; the integration tool does not use it.

## 1. Overview

### Architecture: Guarded 3-Subagent + 3-Stage Funnel

The Drug Target Assessment Agent evaluates therapeutic potential of ligand-receptor (L-R) pairs
identified from spatial transcriptomics cell-cell interaction (CCI) analysis.

```
create_drug_target_agent (guarded_report)
  guarded_pipeline
    └── prepare
    └── evidence_assessor (unless resuming) → validate_evidence
    └── hypothesis_writer → validate_hypothesis
    └── report_writer → final audit/publication
```

`evidence_assessor` runs the staged funnel. `hypothesis_writer` creates the
validated handoff. `report_writer` authors only
`report_sections.json`; deterministic Jinja rendering owns
`target_assessment.json` and `drug.md`. The guardrail owns post-write output
rather than an outer graph node. `request_timeout_seconds` is forwarded to
supported provider clients when supplied; omitted values retain provider defaults.

### Input / Output

| Direction | File | Description |
|-----------|------|-------------|
| Input | `lr_candidates.json` | Top-30 L-R pairs from CCI analysis |
| Input | `targets.json` (optional) | User-selected interest cell types |
| Input | `selected_top3_lr.json` (optional/legacy) | Legacy top-3 selection |
| Output | `evidence/*.json` | Per-stage, per-pair/gene evidence files |
| Output | `report_sections.json` | Report-writer-authored structured sections |
| Output | `target_assessment.json` | Deterministic Jinja structured JSON contract |
| Output | `drug.md` | Deterministically rendered publication-quality markdown report |

### Workflow Order

```
prepare -> validate_evidence -> hypothesis_writer
        -> validate_hypothesis -> report_writer -> final audit/publication
```

The graph, not the root LLM, enforces this phase order. Evidence validation
fails closed before `hypothesis_writer`; hypothesis validation fails closed
before `report_writer`. The deterministic coordinator invokes the role nodes
directly; guarded production has no root task allowlist or completion
sentinel. When evidence is generated, the role order is
`evidence_assessor -> hypothesis_writer -> report_writer`, with validation
gates between roles. The retained outer graph/finalizer is
`legacy_hypothesis` compatibility only.

To resume existing evidence, the coordinator takes `prepare -> validate_evidence`
and then regenerates the fresh hypothesis handoff before report writing:

```bash
export OLLAMA_HOST=http://localhost:6000
export OLLAMA_BASE_URL=http://localhost:6000
export OLLAMA_REASONING=false
export OLLAMA_NUM_PREDICT=4096
python scripts/run_drug_target_agent_bc.py --data-dir /tmp/deepmast-bc-handoff-qwen --disease "breast cancer" --provider ollama-openai --model qwen3.5:122b --skip-evidence-assessor
```

A successful publication run requires a fresh valid
`evidence/hypothesis_report.json`, `report_sections.json`, `drug.md`, and
`drug_report_validation_final.json` with `valid: true` and
`publication.status: "passed"`. A durable hypothesis rejection without a
report audit is fail-closed behavior, not a published report. The coordinator
retries one `HYPOTHESIS_REPORT_MISSING`; rejected saves remain under the
writer's bounded repair path.

For native Ollama/Qwen, Python still selects all evidence, FEATURED genes,
L-R pairs, scores, and layout. Qwen contributes only four labelled hypothesis
cards, optional one-sentence Section 3 follow-ups, and two Section 5
recommendations. Every unit is checked locally; an initial response may receive
three repairs, then falls back to deterministic text or is omitted. The run
writes `evidence/llm_enrichment_audit.json`; `DrugReportGuardrailMiddleware`
remains the final whole-report audit and publication boundary.

`hypothesis_writer` receives the selected evidence and returns four labelled
hypothesis cards (the bounded `gene-card` units), not a full JSON report.
Python reads FEATURED genes from `assessment_results.json`, selects the
validator-required `ot_<GENE>.json` and `stage3_<GENE>.json` evidence, and
builds 4 final hypotheses before persisting
`evidence/hypothesis_report.json`. Only interest-cell-intrinsic Stage 1 pairs
with strict-PASS status may accompany the malignant-cell anchor. The report
writer returns optional one-sentence Section 3 follow-ups and two bounded
recommendation sentences for Section 5. Python selects supporting sources from
the validated handoff, validates those units, and calls
`production_save_report_sections_tool` before saving `report_sections.json`.
Non-Ollama providers keep the existing tool-call save path.

`run_report_writer_only.py` is diagnostic-only: it tests a valid existing
handoff's reporter phase and fails before model invocation without one.

---

## 2. Phase 0: Disease / Cell Type Mapping

**Purpose**: Map user-provided disease and cell type names to Census MONDO ontology vocabulary
before any database queries.

### 2.1 Disease Name Matching

1. Call `list_census_diseases(organism)` to retrieve all disease labels from CELLxGENE Census
   `summary_cell_counts` table (MONDO vocabulary).
2. Compare the raw `disease` field from `lr_candidates.json` against Census labels:
   - Exact match (case-insensitive)
   - Substring/fuzzy match (e.g., "breast cancer" -> "breast carcinoma")
3. Store the matched label as `census_disease` for all subsequent Census queries.

> **Why?** Census uses MONDO ontology labels that often differ from common names
> (e.g., "non-small cell lung cancer" vs "non-small cell lung carcinoma").

### 2.2 Cell Type Fuzzy Matching

When `run_compare_census_lr_pair` fails due to unrecognized cell type:

1. Parse `Examples of available cell types:` from stderr output
2. Attempt exact match against requested cell type
3. Fall back to substring/partial match, selecting the candidate with highest cell count
4. If disease name also fails, `_resolve_disease_name()` retries with fuzzy-matched Census label

**Resolution modes**: `exact` | `fuzzy` | `none`

### Source Files

| File | Key Functions |
|------|---------------|
| `stage_domain_tools.py` | `list_census_diseases()` |
| `census_lr_validation_tools.py` | `_resolve_disease_name()`, `_resolve_interest_cell_type()`, `_parse_available_celltypes()` |

---

## 3. Stage 1: Biological Context (ALL L-R pairs)

**Scope**: Every L-R pair from `lr_candidates.json` (up to 30 pairs).

### 3.1 Tools (5 per pair)

| # | Tool | Database | Purpose |
|---|------|----------|---------|
| a | `query_cellxgene_lr_context` | CELLxGENE Census | Disease/cell-type context, gene availability |
| b | `query_kegg_pathways` | KEGG | Pathway mapping (ligand AND receptor separately) |
| b | `query_reactome_pathways` | Reactome | Pathway mapping (ligand AND receptor separately) |
| c | `query_string_ppi_pair` | STRING | Protein-protein interaction evidence |
| d | `run_compare_census_lr_pair` | CELLxGENE Census | Z-test cross-validation (target vs rest cell types) |

### 3.2 Key Details

- **CELLxGENE**: Uses `census_disease` (Phase 0 mapped), checks `disease_matched` flag.
  If `false`, disease was not found and results fell back to ALL cells.
- **KEGG/Reactome**: Called **separately** for ligand and receptor genes.
  Results stored as `{ligand_pathways: [...], receptor_pathways: [...]}` to enable
  shared-pathway detection.
- **STRING**: `query_string_ppi_pair(gene_a, gene_b)` with `required_score=400`.
  Returns `interaction_found` boolean and `max_combined_score` (0-1 range).
- **Census cross-validation**: Uses Census-matched cell type name (not raw `interest_celltypes`).
  Runs `compare_census_gene_pair_by_cell_type.py` as subprocess with fail-soft retry logic.

### 3.3 Stage 1 Confidence Scoring

After completing Stage 1 for ALL pairs, `compute_stage1_confidence()` calculates a
biological confidence score:

| Signal | Weight | Source | Normalization |
|--------|--------|--------|---------------|
| STRING PPI | 35% | `max_combined_score` | Clamped to [0, 1] |
| Census coexpression | 30% | `target_vs_rest.coexpression` | p < 0.05 gate, then risk_ratio / 3.0 |
| Pathway count | 20% | KEGG + Reactome | 1.0 if shared pathway exists, else 0.0 |
| Gene expression | 15% | Census `target_pct` | genes_expressed / 2.0 |

**Formula**:
```
confidence = 0.35 * string + 0.30 * census + 0.20 * pathway + 0.15 * expression
```

- Pairs with confidence < 0.4 are tagged `stage1_low_confidence = True`
- **All pairs proceed to Stage 2** regardless of confidence score (tagging only, no filtering)

### 3.4 Output Files

| File | Content |
|------|---------|
| `stage1_{LIGAND}_{RECEPTOR}.json` | Per-pair evidence (CELLxGENE + KEGG + Reactome + STRING + Census) |
| `stage1_confidence.json` | Confidence scores for all pairs |
| `census_{gene_a}_{gene_b}_{celltype}.csv` | Census comparison raw output |

### Source Files

| File | Key Functions |
|------|---------------|
| `stage_domain_tools.py` | `query_cellxgene_lr_context`, `query_kegg_pathways`, `query_reactome_pathways`, `query_string_ppi_pair` |
| `census_lr_validation_tools.py` | `run_compare_census_lr_pair` |
| `stage_logic.py` | `compute_stage1_confidence`, `filter_by_stage1_confidence` |

---

## 4. Stage 2: Target Validation & Scoring (ALL unique genes)

**Scope**: Every unique gene symbol extracted from all L-R pairs.

### 4.1 Tools (up to 4 per gene)

| # | Tool | Database | Purpose |
|---|------|----------|---------|
| a | `query_opentargets_target` | OpenTargets | Ensembl ID, tractability, safety, disease evidence, associations |
| c | `query_gwas_gene_trait` | GWAS Catalog | EFO traits, trait associations, gene variants, disease-specific hits |
| d | `query_ensembl_vep_consequence` | Ensembl VEP | Variant functional consequence (gated) |
| -- | `query_opentargets_known_drugs` | OpenTargets | Known drugs for the disease (called once, not per-gene) |

### 4.2 OpenTargets Query Flow

1. `search_entities(gene_symbol)` -> Ensembl ID
2. `get_target_info(ensembl_id)` -> tractability, safety, top diseases
3. `search_entities(disease)` -> EFO ID
4. `get_target_disease_evidence(ensembl_id, efo_id)` -> disease-specific evidence
5. `get_target_associations(ensembl_id)` -> all disease associations (min_score=0.1)

Supports **Parquet-first, API fallback** strategy via `_try_load_parquet_module()`.

### 4.3 GWAS Query Flow

1. `search_efo_traits(disease)` -> EFO/MONDO trait IDs (with synonym expansion: cancer <-> carcinoma)
2. `get_trait_associations(efo_id)` -> all SNPs for each trait (up to 500 per ID)
3. `get_gene_associations(gene_symbol)` -> gene-specific variants
4. **Cross-filtering**: Intersect trait SNPs with gene SNPs to find disease-specific hits

### 4.4 VEP Gate

VEP runs **only when**:
```python
should_run_vep(oncology_flag=True, has_gwas_variants=True)
# Gate: oncology OR GWAS variants available
```

VEP consequence classification:
- **high_impact**: transcript_ablation, splice_acceptor/donor_variant, stop_gained, frameshift_variant, stop_lost, start_lost
- **moderate_impact**: missense_variant, inframe_insertion/deletion, protein_altering_variant
- **low_impact**: everything else

### 4.5 Inline Rubric Assessment

After Stage 2 completes for all genes, the LLM scores each gene against the
`DRUG_TARGET_RUBRIC` (see [Section 8](#8-rubric-scoring-detail) for full detail).

### 4.6 Featured vs Novel Selection

After rubric scoring, `rank_featured_candidates()` separates targets into two tracks:

| Track | Criterion | Ranking Key | Slots |
|-------|-----------|-------------|-------|
| **Featured** | `existing_drug_evidence >= 1` | `combined_total` descending | 2-5 |
| **Novel** | `existing_drug_evidence == 0` | `exploratory_total` descending | 1-3 |
| Combined max | -- | -- | **5-7 total** |

**Novel Tier Assignment**:
- **Tier 1**: Has GWAS support (`gwas >= 1`) OR known tractability (`tractability >= 1`)
- **Tier 2**: No GWAS/tractability, supported only by ST + PPI evidence

**Dynamic Slot Allocation**:
- If few validated targets exist, allocate more Novel slots
- If many validated targets exist, still include at least 1 Novel
- Total Featured + Novel combined: max 7

### 4.7 Output Files

| File | Content |
|------|---------|
| `ot_{GENE}.json` | OpenTargets data per gene |
| `gene_manifest.json` | Gene list with processing flags |
| `known_drugs.json` | OpenTargets known drugs for the disease |
| `assessment_results.json` | Rubric scores per gene |
| `gwas_interpretation.json` | GWAS biological interpretation |
| `clinical_landscape.json` | Clinical trial landscape analysis |

### Source Files

| File | Key Functions |
|------|---------------|
| `stage_domain_tools.py` | `query_opentargets_target`, `query_opentargets_known_drugs`, `query_gwas_gene_trait`, `query_ensembl_vep_consequence` |
| `stage_logic.py` | `rank_featured_candidates`, `should_run_vep`, `classify_vep_consequence`, `compute_drug_evidence_scores` |

---

## 5. Stage 3: Deep Dive (Featured + Novel only)

**Scope**: Only targets selected as Featured or Novel in Stage 2.

### 5.1 Tools (up to 2 per target)

| # | Tool | Database | Condition |
|---|------|----------|-----------|
| a | `query_drugbank_target_profile` | DrugBank (primary) / ChEMBL (fallback) | Always |
| b | `query_pubmed_clinical_limitations` | PubMed | **Gated**: max clinical phase >= 2 |

### 5.2 DrugBank / ChEMBL Details

- **DrugBank primary**: Parses XML to find drugs targeting the gene by polypeptide gene-name match
- **ChEMBL fallback**: If DrugBank unavailable, queries ChEMBL via:
  1. `search_targets_by_name(gene_symbol)` -> target ChEMBL IDs
  2. `get_bioactivity_data(target_id, activity_type="IC50", max_value=10000)` -> active compounds
  3. `get_drug_info(molecule_chembl_id)` -> indications + mechanism of action
- Response includes `source` field: `"drugbank"` or `"chembl"`

### 5.3 PubMed Gate

```python
should_run_pubmed(max_clinical_phase) -> bool
# Gate: max_clinical_phase >= 2
```

Query template: `"{target_name}"[tiab] AND "Clinical Trial"[pt] AND "adverse event"[tiab]`

### 5.4 Output Files

| File | Content |
|------|---------|
| `stage3_{GENE}.json` | Deep dive data (DrugBank/ChEMBL + PubMed) per featured/novel gene |

### Source Files

| File | Key Functions |
|------|---------------|
| `stage_domain_tools.py` | `query_drugbank_target_profile`, `_chembl_fallback`, `query_pubmed_clinical_limitations` |
| `stage_logic.py` | `should_run_pubmed` |

---

## 6. Legacy Finalize Report Node (post-2026-05-19, compatibility only)

The retained `finalize_report` node (`src/agents/drug_target/finalize_report.py`) is a
**deterministic LangGraph node**, not a subagent. It runs after `run_deep_agent`
completes, connected by a static edge. It makes exactly **1 LLM call** (structured
output, `ReportExpansionsPayload`). All other steps are plain Python.

### 6.1 6-Step Internal Sequence

1. **Idempotency check** — if `drug.md` exists at node entry, skip all
   processing and return success. Resume protocol: delete the 4 artifacts
   (`drug.md`, `drug_report.html`, `target_assessment.json`, `report_expansions.json`)
   and re-invoke the graph to force a fresh finalization run.

2. **Load inputs** — `_load_expansion_inputs(data_dir, disease)` loads:
   - Evidence dict via `load_evidence_files(data_dir)` tool
   - Expansion schema spec from `expansion_schema_spec.json`
   - Reference card from `drug_report_reference_card.json`

3. **Token-budget fail-closed gate** — estimate evidence size as
   `len(json.dumps(evidence)) // 4` tokens. If `> 20_000`, return immediately:
   ```python
   {"report_finalization_error": "evidence_budget_exceeded: {n} > 20000",
    "evidence_truncated": True}
   ```
   No LLM call is made. No disk artifacts are written.

4. **LLM call** — `_llm_fill_expansions_once(model, spec, evidence, reference_card, config)`:
   - Uses `model.with_structured_output(ReportExpansionsPayload).with_retry(stop_after_attempt=2)`
   - Model: `create_llm(LLM_PROVIDER)` with `temperature=0`
   - On exhausted retries: `report_finalization_error="llm_call_failed_after_retries: ..."`

5. **Persist + validate** — `_persist_and_validate(data_dir, payload, reference_card)`:
   - **5a. Schema validation**: `validate_report_expansions(data_dir, payload.model_dump())`
     (`tools/report_expansion_schema.py`)
   - **5b. Cited-only provenance check**: `validate_cited_only_provenance(payload, reference_card)`
     (`validators.py`) — verifies every sentence's `source_file::source_field` key exists
     in the reference card's provenance index. `cited_only` errors take precedence over
     `schema` errors in error classification.
   - On any errors: set `report_finalization_error` and **return without disk writes**.
   - On pass: atomic save of `report_expansions.json`.

6. **Render outputs** — `_render_outputs(data_dir, payload)`:
   - `render_drug_md_from_expansions()` → `drug.md`
   - `generate_drug_html_report()` → `drug_report.html`
   - Atomic write of `target_assessment.json` from `payload.model_dump()`

7. **Finalize workspace** — `_finalize_workspace(data_dir)`:
   - `finalize_stage1_artifacts()` — stage 1 artifact normalization
   - `validate_drug_report_finalization()` — final validation gate
   - On failure: `report_finalization_error="finalization_validation_failed: ..."`

All writes in steps 6–7 use `tempfile` + `os.replace` for atomicity.

### 6.2 Error Classes

All failures surface via the `report_finalization_error` state field. See
[`drug_target_agent_reference.md` Section 2.5](drug_target_agent_reference.md#25-legacy-finalize_report-compatibility-node--historical-error-classes)
for the complete error class table.

### 6.3 `target_assessment.json` Contract

The schema contract written upstream by `save_target_assessment()`:

```json
{
  "project_meta": {
    "disease_focus": "...",
    "total_input_pairs": 30
  },
  "druggability_matrix": [
    {
      "ligand": "...",
      "receptor": "...",
      "is_featured": true/false,
      "is_novel": true/false,
      "open_targets_score": 0.0,
      "validated_track": { ... },
      "exploratory_track": { ... },
      "classification": "validated_target|exploratory_target|novel_candidate|insufficient_evidence",
      "priority": "high|medium|low|unranked",
      "combined_total": 0,
      "validated_total": 0,
      "exploratory_total": 0,
      "rank": 1,
      "novel_tier": 1
    }
  ],
  "featured_candidates_deep_dive": [
    {
      "gene": "...",
      "track": "featured|novel",
      ...
    }
  ]
}
```

`save_target_assessment()` internally calls `rank_featured_candidates()` to re-rank
the druggability_matrix before writing, and validates the schema contract.

### 6.2 `drug.md` 4-Section Structure

| Section | Content |
|---------|---------|
| **1. Executive Summary** | Scope, [FEATURED] candidates first, [NOVEL] candidates, key opportunities |
| **2. Pan-Disease Target Druggability Matrix** | Markdown table with ALL pairs; [FEATURED]/[NOVEL] rows bolded and listed first |
| **3. [FEATURED] Candidate Deep Dives** | Per-candidate: Clinical & Safety (Stage 3), Biological Context (Stage 1), Rubric Summary |
| **4. [NOVEL] Candidate Deep Dives** | Per-candidate: Why Novel, Biological Evidence, Exploratory Evidence, Drug Dev Potential |
| **5. Pipeline Execution Summary** | Counts, API summary, 4 recommendation categories |

### Source Files

| File | Key Functions |
|------|---------------|
| `finalize_report.py` | Legacy compatibility `finalize_report()`, `_load_expansion_inputs()`, `_llm_fill_expansions_once()`, `_persist_and_validate()`, `_render_outputs()`, `_finalize_workspace()` |
| `validators.py` | `validate_cited_only_provenance()` |
| `tools/report_expansion_schema.py` | `ReportExpansionsPayload`, `validate_report_expansions()`, `_build_provenance_index()` |
| `super_graph.py` | `DrugTargetState`, `run_deep_agent()`, `build_drug_target_super_graph()` |
| `graph_builder.py` | Guarded direct-agent deployment entrypoint: `drug_target_graph` builds `workflow_mode="guarded_report"` |

---

## 7. Stage Gate Summary

| Gate | Stage | Condition | Effect |
|------|-------|-----------|--------|
| **VEP gate** | Stage 2 | `oncology_flag == True` OR `has_gwas_variants == True` | Run Ensembl VEP; skip otherwise |
| **PubMed gate** | Stage 3 | `max_clinical_phase >= 2` | Run PubMed clinical search; skip otherwise |
| **Stage 1 confidence** | Stage 1 -> 2 | confidence < 0.4 | Tag only (`stage1_low_confidence`); all pairs proceed |
| **Featured selection** | Stage 2 -> 3 | `existing_drug_evidence >= 1` | Only Featured + Novel candidates proceed to Stage 3 |

---

## 8. Rubric Scoring Detail

### 8.1 Validated Track (Clinical Evidence)

| Criterion | Range | Scale |
|-----------|-------|-------|
| `existing_drug_evidence` | 0-3 | none(0) \| indirect_evidence(1) \| Phase 1-2(2) \| Phase 3+/approved(3) |
| `clinical_trial_activity` | 0-3 | no_trials(0) \| few_early_phase(1) \| multiple_or_advanced(2) \| extensive(3) |
| `mechanism_relevance` | 0-3 | unclear(0) \| plausible(1) \| well_supported(2) \| direct_mechanism(3) |
| `safety_profile` | -2 to 0 | major_concerns(-2) \| moderate_concerns(-1) \| minimal_or_none(0) |

**Pass logic**:
```
existing_drug_evidence >= 2
OR (existing_drug_evidence >= 1 AND clinical_trial_activity >= 1)
```

### 8.2 Exploratory Track (Genetic/Biological Evidence)

| Criterion | Range | Scale |
|-----------|-------|-------|
| `gwas_genetic_support` | 0-3 | no_signal(0) \| suggestive(1) \| genome_wide_significant(2) \| replicated(3) |
| `tractability` | 0-3 | unknown(0) \| predicted(1) \| clinical_precedent(2) \| approved_modality(3) |
| `biological_plausibility` | 0-3 | weak(0) \| moderate(1) \| strong(2) \| compelling_multi_evidence(3) |
| `novelty_opportunity` | 0-3 | well_established(0) \| moderately_explored(1) \| emerging(2) \| novel(3) |

**Pass logic**:
```
gwas_genetic_support >= 1
AND (tractability >= 1 OR biological_plausibility >= 2)
```

### 8.3 Classification

| Classification | Condition |
|----------------|-----------|
| `validated_target` | Passes validated track |
| `exploratory_target` | Fails validated, passes exploratory track |
| `novel_candidate` | Fails both, but `biological_plausibility >= 2` OR `novelty_opportunity >= 2` |
| `insufficient_evidence` | Does not meet any criteria |

### 8.4 Priority

| Priority | Condition |
|----------|-----------|
| `high` | validated_target with validated_total >= 6, OR exploratory_target with exploratory_total >= 8 |
| `medium` | validated_target with validated_total >= 3, OR exploratory_target with exploratory_total >= 5 |
| `low` | Passes either track but below medium threshold; or novel_candidate |
| `unranked` | insufficient_evidence |

### 8.5 Drug Evidence Programmatic Scoring (`compute_drug_evidence_scores`)

For ChEMBL-sourced drug data, scores are computed programmatically:

**`existing_drug_evidence`**:
| Score | Condition |
|-------|-----------|
| 3 | Target disease has Phase 3+ or approved drug |
| 2 | Target disease has Phase 1-2 drug |
| 1 | Other indication has approved drug (repurposing) OR OpenTargets tractability "Approved Drug" |
| 0 | No drugs |

**`clinical_trial_activity`**:
| Score | Condition |
|-------|-----------|
| 3 | Target disease has Phase 3+ with multiple indications |
| 2 | Target disease has Phase 2+ OR other indication Phase 3+ |
| 1 | Other indication has clinical trials |
| 0 | None |

Disease matching uses keyword variants (e.g., for breast cancer:
"breast carcinoma", "breast neoplasm", "TNBC", "HER2-positive breast", etc.).

---

## 9. Legacy compatibility Data Flow Diagram (`legacy_hypothesis` only)

```
lr_candidates.json ─────────────────────────────────────────────────────┐
targets.json (optional) ────────────────────────────────────────────────┤
                                                                        │
         ┌──────────────────────────────────────────────────────────────▼──┐
         │ LEGACY COMPATIBILITY run_deep_agent NODE (super_graph.py)        │
         │                                                                  │
         │  ┌──────────────────────────────────────────────────────────┐   │
         │  │        LEGACY ORCHESTRATOR (agent.py)                    │   │
         │  │  load_lr_candidates() → gene_symbols, lr_pairs          │   │
         │  └──────────────────┬───────────────────────────────────────┘   │
         │                     │                                            │
         │  ┌──────────────────▼───────────────────────────────────────┐   │
         │  │         EVIDENCE ASSESSOR (subagent #1)                  │   │
         │  │                                                           │   │
         │  │  Phase 0: Disease/Cell Type Mapping                      │   │
         │  │    list_census_diseases() → census_disease               │   │
         │  │                                                           │   │
         │  │  Stage 1: Biological Context (ALL pairs)                 │   │
         │  │    ┌─ CELLxGENE Census (disease context)                 │   │
         │  │    ├─ KEGG (ligand + receptor pathways)                  │   │
         │  │    ├─ Reactome (ligand + receptor pathways)              │   │
         │  │    ├─ STRING PPI (interaction score)                     │   │
         │  │    └─ Census cross-validation (z-test)                   │   │
         │  │    → stage1_{L}_{R}.json per pair                        │   │
         │  │    → compute_stage1_confidence()                         │   │
         │  │    → stage1_confidence.json                              │   │
         │  │                                                           │   │
         │  │  Stage 2: Validation & Scoring (ALL genes)               │   │
         │  │    ┌─ OpenTargets (target info + disease evidence)       │   │
         │  │    ├─ GWAS Catalog (gene-trait associations)             │   │
         │  │    ├─ Ensembl VEP [gated: oncology/GWAS]                │   │
         │  │    └─ OpenTargets Known Drugs (once per disease)         │   │
         │  │    → ot_{GENE}.json per gene                             │   │
         │  │    → known_drugs.json, gene_manifest.json                │   │
         │  │                                                           │   │
         │  │  Inline Rubric → rank_featured_candidates()              │   │
         │  │    → assessment_results.json                             │   │
         │  │    → gwas_interpretation.json                            │   │
         │  │    → clinical_landscape.json                             │   │
         │  │    → Featured (2-5) + Novel (1-3) selected               │   │
         │  │                                                           │   │
         │  │  Stage 3: Deep Dive (Featured + Novel only)              │   │
         │  │    ┌─ DrugBank / ChEMBL (drug profiles)                  │   │
         │  │    └─ PubMed [gated: phase >= 2]                         │   │
         │  │    → stage3_{GENE}.json per candidate                    │   │
         │  └──────────────────┬───────────────────────────────────────┘   │
         │                     │                                            │
         │  ┌──────────────────▼───────────────────────────────────────┐   │
         │  │ LEGACY COMPATIBILITY HYPOTHESIS WRITER (subagent #2)     │   │
         │  │  UCB-scored mechanistic hypothesis generation             │   │
         │  │  → hypothesis_report.json                                 │   │
         │  └──────────────────┬───────────────────────────────────────┘   │
         │                     │ (EVIDENCE_PIPELINE_COMPLETE sentinel)      │
         └─────────────────────┼──────────────────────────────────────────-┘
                               │  static edge
         ┌─────────────────────▼──────────────────────────────────────────-┐
         │ LEGACY COMPATIBILITY finalize_report NODE (finalize_report.py)  │
         │                                                                  │
         │  1. Idempotency check (drug.md exists? → skip)                  │
         │  2. load_evidence_files() + reference_card + spec               │
         │  3. Token-budget gate [>20K tokens → evidence_truncated=True]   │
         │  4. LLM call → ReportExpansionsPayload (1 call, temperature=0)  │
         │  5. validate_report_expansions() + validate_cited_only_prov()   │
         │  6. render drug.md + HTML + target_assessment.json (atomic)     │
         │  7. finalize_stage1_artifacts() + validate_drug_report_final()  │
         │                                                                  │
         │  Error surface: report_finalization_error state field           │
         └─────────────────────┬──────────────────────────────────────────-┘
                               │
                               ▼
         ┌──────────────────────────────────────────────────────────────────┐
         │                        OUTPUTS                                   │
         │  target_assessment.json  (structured contract)                   │
         │  drug.md                 (markdown report)                       │
         │  drug_report.html        (rendered HTML)                         │
         │  evidence/*.json         (intermediate data)                     │
         └──────────────────────────────────────────────────────────────────┘
```

---

## 10. Source File Reference

| File | Role | Key Contents |
|------|------|-------------|
| `src/agents/drug_target/super_graph.py` | Legacy compatibility super-graph | `DrugTargetState`, `run_deep_agent()`, `build_drug_target_super_graph()` |
| `src/agents/drug_target/graph_builder.py` | Guarded direct-agent deployment entrypoint | `drug_target_graph` builds `workflow_mode="guarded_report"` |
| `src/agents/drug_target/finalize_report.py` | Legacy finalizer | Retained explicit compatibility implementation |
| `src/agents/drug_target/finalize_report_prompts.py` | Legacy finalizer LLM prompts | `FINALIZE_REPORT_SYSTEM_PROMPT`, `FINALIZE_REPORT_USER_TEMPLATE` |
| `src/agents/drug_target/validators.py` | Cited-only validation | `validate_cited_only_provenance()` |
| `src/agents/drug_target/middleware.py` | Guarded production middleware | Cleanup, task allowlist, filesystem, and report guardrails (plus legacy retry) |
| `src/agents/drug_target/agent.py` | Orchestrator | `DrugTargetConfig`, `create_drug_target_agent()`, `ORCHESTRATOR_SYSTEM_PROMPT` |
| `src/agents/drug_target/subagents/prompts.py` | Subagent prompts | `EVIDENCE_ASSESSOR_PROMPT`, `HYPOTHESIS_WRITER_PROMPT`, `REPORT_WRITER_PROMPT`, legacy prompts |
| `src/agents/drug_target/subagents/configs.py` | Subagent tool configs | Guarded `get_subagents()`, explicit `get_legacy_subagents()`, `WORKFLOW_ORDER = ["evidence_assessor", "hypothesis_writer", "report_writer"]` |
| `src/agents/drug_target/tools/__init__.py` | Tool registry | Tool re-exports with lazy imports |
| `src/agents/drug_target/tools/stage_domain_tools.py` | Domain tools | CELLxGENE, KEGG, Reactome, STRING, VEP, OpenTargets, GWAS, DrugBank/ChEMBL, PubMed |
| `src/agents/drug_target/tools/census_lr_validation_tools.py` | Census cross-validation | `run_compare_census_lr_pair()`, fuzzy matching logic |
| `src/agents/drug_target/tools/stage_logic.py` | Rubric & gates | `compute_stage1_confidence`, `rank_featured_candidates`, `classify_target`, `compute_priority`, `should_run_vep`, `should_run_pubmed`, `compute_drug_evidence_scores` |
| `src/agents/drug_target/tools/evidence_loader.py` | I/O helpers | `load_lr_candidates`, `load_evidence_files`, `save_evidence` |
| `src/agents/drug_target/tools/report_expansion_schema.py` | Expansion schema | `ReportExpansionsPayload`, `validate_report_expansions()`, `_build_provenance_index()` |
| `src/agents/drug_target/tools/common.py` | Cognitive tools | `sequential_thinking`, `think_tool`, `validate_quality` |
| `src/agents/drug_target/integration.py` | Production Reporter bridge | `run_drug_target_assessment()` lazily builds a guarded direct agent with `workflow_mode="guarded_report"` and invokes it |
| `docs/drugtarget/output_schema.json` | JSON schema | Contract schema for `target_assessment.json` |
