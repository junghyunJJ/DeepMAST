# Drug Target Assessment Agent -- Comprehensive Reference

> **Source of truth**: `src/agents/drug_target/` codebase
> **Last verified**: 2026-03-13 (94% doc-code consistency)
> **Related**: `drug_target_stage_guide.md` (stage-level detail), `output_schema.json` (JSON contract)

---

## 1. Overview

The Drug Target Assessment Agent evaluates therapeutic potential of ligand-receptor (L-R) pairs identified from spatial transcriptomics (ST) cell-cell interaction (CCI) analysis. It uses a **2-subagent architecture** with a **3-stage funnel** to systematically gather multi-database evidence, score targets against a structured rubric, and generate a publication-quality report.

### Key Design Principles

- **Evidence-first**: All assessments are grounded in database queries, not LLM speculation
- **Progressive funnel**: Start broad (all pairs), narrow to Featured + Novel candidates
- **Fail-soft**: API failures return error JSON; partial results are preserved
- **File-based persistence**: Every stage saves evidence to `evidence/*.json` immediately
- **Plan-Execute-Reflect**: Each subagent follows this cognitive cycle per stage

### Input / Output Summary

| Direction | File | Description |
|-----------|------|-------------|
| **Input** | `lr_candidates.json` | Top-30 L-R pairs from CCI analysis |
| **Input** | `targets.json` (optional) | User-selected interest cell types |
| **Output** | `evidence/*.json` | Per-stage, per-pair/gene evidence files |
| **Output** | `target_assessment.json` | Structured JSON contract (schema-validated) |
| **Output** | `drug.md` | Publication-quality markdown report |

---

## 2. Architecture

### 2.1 Component Hierarchy

```
Wrapper Pipeline (Step 9.5)
  -> run_drug_target_assessment(data_dir, disease)    [integration.py]
    -> DrugTargetConfig                                [agent.py]
    -> create_drug_target_agent(config)                [agent.py]
      -> DeepAgents framework (LangGraph Runnable)
      -> 2 subagents + 7 orchestrator tools + SkillsMiddleware
```

### 2.2 Source File Map

| File | Role |
|------|------|
| `agent.py` | Orchestrator factory: `DrugTargetConfig`, `create_drug_target_agent()`, system prompt |
| `subagents/configs.py` | Tool registry per subagent: `SUBAGENT_CONFIGS`, `WORKFLOW_ORDER`, `get_subagents()` |
| `subagents/prompts.py` | Subagent system prompts: `EVIDENCE_ASSESSOR_PROMPT`, `REPORT_WRITER_PROMPT` |
| `tools/__init__.py` | Tool re-exports (21 tools in `__all__`) with lazy imports for circular-dep breaking |
| `tools/stage_domain_tools.py` | Stage 1-3 domain tools (12): CELLxGENE, KEGG, Reactome, STRING, VEP, OT, GWAS, DrugBank/ChEMBL, PubMed |
| `tools/stage2_service.py` | Stage 2 batch orchestration: `build_stage2_gene_panel()`, parquet/API routing, workspace caching |
| `tools/stage_logic.py` | Rubric scoring, classification, priority, confidence, stage gates |
| `tools/evidence_loader.py` | I/O helpers: `load_lr_candidates`, `load_evidence_files`, `save_evidence` |
| `tools/assessment_output.py` | Output contract: `save_target_assessment()`, `_validate_contract()` |
| `tools/census_lr_validation_tools.py` | Census cross-validation: `run_compare_census_lr_pair()`, fuzzy matching |
| `tools/skill_reader.py` | Progressive disclosure: `read_skill_file()` |
| `tools/common.py` | Cognitive tools: `sequential_thinking`, `think_tool`, `validate_quality` |
| `integration.py` | Reporter bridge: `run_drug_target_assessment()` async tool for deep_interpreter Step 9.5 |

### 2.3 Subagent Configuration

**Workflow order**: `["evidence_assessor", "hypothesis_writer", "summarizer"]` (strict sequential)

| Subagent | Spec shape | Tools | Role |
|----------|------------|-------|------|
| `evidence_assessor` | flat dict | ~20 tools | 3-stage funnel: biological context -> validation & scoring -> deep dive + inline rubric |
| `hypothesis_writer` | flat dict | 7 tools | UCB-scored mechanistic hypothesis generation from Stage 1-3 evidence |
| `summarizer` | flat dict (post-2026-05-13) | 7 tools + `SummarizerFinalizationGuardMiddleware` | Author drug.md via 6-step tool sequence; finalize HTML report. Fail-closed on `validate_drug_md`. |

Post-2026-05-13 the summarizer is a flat `SubAgent` dict (no inner subagents,
no CompiledSubAgent shell, no Python repair loop). Its seven tools are
`build_evidence_summary`, `load_evidence_files`, `save_report_expansions`,
`render_drug_md_from_expansions`, `validate_drug_md`,
`generate_drug_html_report`, and `think_tool`.
`SummarizerFinalizationGuardMiddleware` blocks
`generate_drug_html_report` unless the most recent `validate_drug_md`
returned `valid=true`.

### 2.4 DrugTargetConfig Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | str | `"openrouter"` | LLM provider |
| `data_dir` | str | env `DEEP_INTERPRETER_DATA_DIR` | Directory with `lr_candidates.json` |
| `disease` | str | `""` | Disease context injected into system prompt |
| `use_checkpointer` | bool | `False` | Enable LangGraph memory checkpointer |
| `custom_tools` | Sequence | `[]` | Additional tools for all subagents |
| `docker_image` | str\|None | `None` | Docker image for sandbox backend |
| `enable_progressive_disclosure` | bool | `True` | Expose skills metadata via SkillsMiddleware |
| `agent_skill_names` | tuple | `("opentargets-database", "gwas-database", "chembl-database")` | Skills exposed to agent |
| `skills_dir` | str\|None | `None` | Override project skills directory |
| `subagent_models` | dict\|None | `None` | Per-subagent model overrides (init_chat_model format) |

---

## 3. Pipeline Flow

### 3.1 Phase 0: Disease / Cell Type Mapping

**Purpose**: Map user-provided names to Census MONDO ontology vocabulary.

1. `list_census_diseases(organism)` -> retrieve all Census disease labels
2. Fuzzy-match raw `disease` from `lr_candidates.json` to Census label -> `census_disease`
3. Map `interest_celltypes` (from `targets.json`) to Census CL ontology labels

### 3.2 Stage 1: Biological Context (ALL L-R pairs)

For **each** of the top-30 L-R pairs, 5 database queries:

| Step | Tool | Database | Purpose |
|------|------|----------|---------|
| a | `query_cellxgene_lr_context` | CELLxGENE Census | Disease/cell-type context, gene availability |
| b | `query_kegg_pathways` | KEGG | Pathway mapping (ligand AND receptor separately) |
| b | `query_reactome_pathways` | Reactome | Pathway mapping (ligand AND receptor separately) |
| c | `query_string_ppi_pair` | STRING | Protein-protein interaction evidence |
| d | `run_compare_census_lr_pair` | CELLxGENE Census | Z-test cross-validation (target vs rest cell types) |

**Save**: `evidence/stage1_{LIGAND}_{RECEPTOR}.json` per pair

### 3.3 Stage 1 Confidence Scoring

After Stage 1 completes for ALL pairs, `compute_stage1_confidence()` calculates biological confidence:

| Signal | Weight | Source | Normalization |
|--------|--------|--------|---------------|
| STRING PPI | 35% | `max_combined_score` | Clamped to [0, 1] |
| Census coexpression | 30% | `target_vs_rest.coexpression` | p < 0.05 gate, then risk_ratio / 3.0 |
| Pathway count | 20% | KEGG + Reactome | 1.0 if shared pathway exists, else 0.0 |
| Gene expression | 15% | Census `target_pct` | genes_expressed / 2.0 |

```
confidence = 0.35 * string + 0.30 * census + 0.20 * pathway + 0.15 * expression
```

- Pairs with confidence < 0.4: tagged `stage1_low_confidence = True` (informational only)
- **All pairs proceed to Stage 2** regardless of confidence

**Save**: `evidence/stage1_confidence.json`

### 3.4 Stage 2: Target Validation & Scoring (ALL unique genes)

Single batch call: `query_stage2_gene_panel(gene_symbols, disease, selected_top3_genes, data_dir)`

Internally queries per gene:

| Tool | Database | Strategy |
|------|----------|----------|
| `query_opentargets_target` | OpenTargets | Parquet-first, API fallback |
| `query_gwas_gene_trait` | GWAS Catalog | Parquet-first, API fallback |
| `query_ensembl_vep_consequence` | Ensembl VEP | **Gated**: oncology OR GWAS variants available |
| `query_opentargets_known_drugs` | OpenTargets | Called once per disease (not per-gene) |

**Workspace caching**: `_load_cached_stage2_bundle()` reuses existing evidence files if gene panel and disease match exactly.

**Save**: `evidence/stage2_evidence.json`, `evidence/ot_{GENE}.json`, `evidence/known_drugs.json`, `evidence/gene_manifest.json`

### 3.5 Inline Rubric Assessment (after Stage 2)

LLM scores each gene against the 8-criterion rubric (see [Section 5](#5-rubric-scoring-system)), then `rank_featured_candidates()` separates into:

- **Featured**: `existing_drug_evidence >= 1`, ranked by `combined_total` (2-5 slots)
- **Novel**: `existing_drug_evidence == 0`, ranked by `exploratory_total` (1-3 slots)
- **Combined max**: 5-7 total candidates for Stage 3

**Save**: `evidence/assessment_results.json`, `evidence/gwas_interpretation.json`, `evidence/clinical_landscape.json`

### 3.6 Stage 3: Deep Dive (Featured + Novel only)

For each selected candidate:

| Tool | Database | Condition |
|------|----------|-----------|
| `query_drugbank_target_profile` | DrugBank (primary) / ChEMBL (fallback) | Always |
| `query_pubmed_clinical_limitations` | PubMed | **Gated**: max clinical phase >= 2 |

**DrugBank/ChEMBL fallback chain**:
1. Try DrugBank XML -> match by polypeptide gene-name
2. If unavailable, fall back to ChEMBL REST API -> `search_targets_by_name` -> `get_bioactivity_data` -> `get_drug_info`
3. Response `source` field: `"drugbank"` or `"chembl"`

**Save**: `evidence/stage3_{GENE}.json` per candidate

### 3.7 Report Generation

The `summarizer` subagent (flat dict spec, 7 tools) executes the fixed 6-step
sequence:

1. `build_evidence_summary(data_dir)` — pre-fills the deterministic evidence
   summary skeleton (call EXACTLY ONCE).
2. `load_evidence_files(data_dir, ...)` — load per-gene evidence JSON.
3. `save_report_expansions(data_dir, expansions)` — author schema-validated
   per-section Markdown expansions.
4. `render_drug_md_from_expansions(data_dir)` — deterministically assemble
   `drug.md` from the saved expansions (the LLM never hand-writes drug.md).
5. `validate_drug_md(data_dir)` — MANDATORY quality gate (semantic).
   - On `valid=false`: re-call `save_report_expansions` to fix the offending
     sections, re-render, re-validate. Max 2 retries (prompt-budgeted).
6. `generate_drug_html_report(data_dir)` — call EXACTLY ONCE after
   `validate_drug_md` returns `valid=true`. This call is mechanically blocked
   by `SummarizerFinalizationGuardMiddleware` until the validator passes.
7. Emit `SUMMARIZER_STATUS: PASS` on its own line (or `SUMMARIZER_STATUS: FAIL`
   on retry budget exhaustion).

The orchestrator parses the literal `SUMMARIZER_STATUS:` line to decide
pipeline completion. `target_assessment.json` is no longer written by the
summarizer surface (it is produced earlier in the funnel).

---

## 4. Tool Reference

### 4.1 Evidence Assessor Tools (20)

#### I/O Tools (3)

| Tool | Signature | Purpose |
|------|-----------|---------|
| `load_lr_candidates` | `(data_dir: str)` | Load lr_candidates.json, extract gene symbols and pairs |
| `save_evidence` | `(data_dir: str, filename: str, data: str)` | Save evidence JSON to `evidence/` directory |
| `load_evidence_files` | `(data_dir: str)` | Load all `evidence/*.json` files |

#### Phase 0 Tools (1)

| Tool | Signature | Purpose |
|------|-----------|---------|
| `list_census_diseases` | `(organism: str = "homo_sapiens")` | List Census MONDO disease labels for vocabulary matching |

#### Stage 1 Tools (5)

| Tool | Signature | Database | Fallback |
|------|-----------|----------|----------|
| `query_cellxgene_lr_context` | `(ligand, receptor, disease, organism)` | CELLxGENE Census | Returns `disease_matched: false` on miss |
| `query_kegg_pathways` | `(gene_symbol, organism, max_results)` | KEGG REST API | Error JSON |
| `query_reactome_pathways` | `(gene_symbol, max_results)` | Reactome REST API | Error JSON |
| `query_string_ppi_pair` | `(gene_a, gene_b, species, required_score)` | STRING API | Error JSON |
| `run_compare_census_lr_pair` | `(gene_a, gene_b, disease, cell_type, ...)` | CELLxGENE Census (subprocess) | Fuzzy cell-type/disease retry |

#### Stage 2 Tools (5)

| Tool | Signature | Database | Strategy |
|------|-----------|----------|----------|
| `query_stage2_gene_panel` | `(gene_symbols, disease, selected_top3_genes, data_dir)` | OT + GWAS (batch) | Parquet-first + workspace cache |
| `query_opentargets_target` | `(gene_symbol, disease)` | OpenTargets | Parquet-first, API fallback |
| `query_opentargets_known_drugs` | `(disease)` | OpenTargets | Parquet-first, API fallback |
| `query_gwas_gene_trait` | `(gene_symbol, disease)` | GWAS Catalog | Parquet-first, API fallback |
| `query_ensembl_vep_consequence` | `(variant_ids, species)` | Ensembl VEP REST | **Gated**: oncology OR GWAS variants |

#### Stage 3 Tools (2)

| Tool | Signature | Database | Fallback |
|------|-----------|----------|----------|
| `query_drugbank_target_profile` | `(gene_symbol, max_drugs)` | DrugBank XML | ChEMBL REST API |
| `query_pubmed_clinical_limitations` | `(target_name, max_results)` | PubMed E-utils | **Gated**: phase >= 2 |

#### Cognitive / Utility Tools (4)

| Tool | Purpose |
|------|---------|
| `read_skill_file` | Load SKILL.md for progressive disclosure guidance |
| `sequential_thinking` | Structured planning (Plan phase) |
| `think_tool` | Reflection and assessment (Reflect phase) |
| `validate_quality` | Quality score check (threshold >= 0.7) |

### 4.2 Summarizer Tools (7) — post-2026-05-13 simplification

| Tool | Purpose |
|------|---------|
| `build_evidence_summary` | Pre-fills the deterministic evidence summary skeleton (called once at start) |
| `load_evidence_files` | Load all `evidence/*.json` |
| `save_report_expansions` | Schema-validated per-section Markdown expansion writes |
| `render_drug_md_from_expansions` | Deterministic Markdown assembly of `drug.md` from saved expansions |
| `validate_drug_md` | MANDATORY semantic quality gate (returns `{valid: bool, errors: [...]}`) |
| `generate_drug_html_report` | Final HTML render (mechanically blocked unless `validate_drug_md` returned `valid=true`) |
| `think_tool` | Reflection / scratchpad |

The summarizer carries one middleware:
`SummarizerFinalizationGuardMiddleware`, which observes `validate_drug_md`
results and blocks `generate_drug_html_report` until `valid=true`.

---

## 5. Rubric Scoring System

### 5.1 Two-Track Assessment

Each gene is scored on 8 criteria across two tracks.

#### Validated Track (Clinical Evidence)

| Criterion | Range | Scale |
|-----------|-------|-------|
| `existing_drug_evidence` | 0-3 | none(0) \| indirect_evidence(1) \| Phase 1-2(2) \| Phase 3+/approved(3) |
| `clinical_trial_activity` | 0-3 | no_trials(0) \| few_early_phase(1) \| multiple_or_advanced(2) \| extensive(3) |
| `mechanism_relevance` | 0-3 | unclear(0) \| plausible(1) \| well_supported(2) \| direct_mechanism(3) |
| `safety_profile` | -2 to 0 | major_concerns(-2) \| moderate_concerns(-1) \| minimal_or_none(0) |

**Pass**: `existing_drug_evidence >= 2 OR (existing_drug_evidence >= 1 AND clinical_trial_activity >= 1)`

#### Exploratory Track (Genetic/Biological Evidence)

| Criterion | Range | Scale |
|-----------|-------|-------|
| `gwas_genetic_support` | 0-3 | no_signal(0) \| suggestive(1) \| genome_wide_significant(2) \| replicated(3) |
| `tractability` | 0-3 | unknown(0) \| predicted(1) \| clinical_precedent(2) \| approved_modality(3) |
| `biological_plausibility` | 0-3 | weak(0) \| moderate(1) \| strong(2) \| compelling_multi_evidence(3) |
| `novelty_opportunity` | 0-3 | well_established(0) \| moderately_explored(1) \| emerging(2) \| novel(3) |

**Pass**: `gwas_genetic_support >= 1 AND (tractability >= 1 OR biological_plausibility >= 2)`

### 5.2 Classification

| Classification | Condition |
|----------------|-----------|
| `validated_target` | Passes validated track |
| `exploratory_target` | Fails validated, passes exploratory track |
| `novel_candidate` | Fails both, but `biological_plausibility >= 2` OR `novelty_opportunity >= 2` |
| `insufficient_evidence` | Does not meet any criteria |

### 5.3 Priority

| Priority | Condition |
|----------|-----------|
| `high` | validated_target with validated_total >= 6, OR exploratory_target with exploratory_total >= 8 |
| `medium` | validated_target with validated_total >= 3, OR exploratory_target with exploratory_total >= 5 |
| `low` | Passes either track but below medium threshold; or novel_candidate |
| `unranked` | insufficient_evidence |

### 5.4 Featured vs Novel Selection

| Track | Criterion | Ranking Key | Slots |
|-------|-----------|-------------|-------|
| **Featured** | `existing_drug_evidence >= 1` | `combined_total` desc | 2-5 |
| **Novel** | `existing_drug_evidence == 0` | `exploratory_total` desc | 1-3 |
| Combined | -- | -- | **max 7** |

**Novel Tier Assignment**:
- **Tier 1**: `gwas_genetic_support >= 1` OR `tractability >= 1` (more promising)
- **Tier 2**: No GWAS/tractability support, ST + PPI evidence only

**Dynamic slot allocation**: If few validated targets exist, more Novel slots are allocated. At least 1 Novel is always included when available.

### 5.5 Programmatic Drug Evidence Scoring

`compute_drug_evidence_scores()` in `stage_logic.py` computes `existing_drug_evidence` and `clinical_trial_activity` from ChEMBL indication data:

**existing_drug_evidence**:
| Score | Condition |
|-------|-----------|
| 3 | Target disease has Phase 3+ or approved drug |
| 2 | Target disease has Phase 1-2 drug |
| 1 | Other indication has approved drug (repurposing) OR OpenTargets "Approved Drug" tractability |
| 0 | No drugs |

**clinical_trial_activity**:
| Score | Condition |
|-------|-----------|
| 3 | Target disease Phase 3+ with multiple indications |
| 2 | Target disease Phase 2+ OR other indication Phase 3+ |
| 1 | Other indication has clinical trials |
| 0 | None |

---

## 6. File I/O Reference

### 6.1 Input Files

| File | Required | Description |
|------|----------|-------------|
| `lr_candidates.json` | Yes | Top-30 L-R pairs with `disease`, `pairs[]` (ligand, receptor, st_colocalization_score) |
| `targets.json` | No | Interest cell types from user selection |
| `selected_top3_lr.json` | No (legacy) | Legacy top-3 pair selection |

### 6.2 Evidence Files (intermediate, saved to `evidence/`)

| File | Stage | Content | Created By |
|------|-------|---------|------------|
| `stage1_{LIGAND}_{RECEPTOR}.json` | 1 | Per-pair biological context (CELLxGENE + KEGG + Reactome + STRING + Census) | evidence_assessor |
| `stage1_confidence.json` | 1 | Confidence scores for all pairs | evidence_assessor |
| `census_{gene_a}_{gene_b}_{celltype}.csv` | 1 | Census comparison raw output | run_compare_census_lr_pair |
| `stage2_evidence.json` | 2 | All gene evidence keyed by symbol | evidence_assessor |
| `ot_{GENE}.json` | 2 | OpenTargets data per gene | evidence_assessor |
| `known_drugs.json` | 2 | OpenTargets known drugs for the disease | evidence_assessor |
| `gene_manifest.json` | 2 | Gene list with processing flags | evidence_assessor |
| `assessment_results.json` | 2 | Rubric scores per gene | evidence_assessor |
| `gwas_interpretation.json` | 2 | GWAS biological interpretation | evidence_assessor |
| `clinical_landscape.json` | 2 | Clinical trial landscape analysis | evidence_assessor |
| `stage3_{GENE}.json` | 3 | Deep dive data (DrugBank/ChEMBL + PubMed) | evidence_assessor |

### 6.3 Output Files

| File | Description | Validated By |
|------|-------------|-------------|
| `target_assessment.json` | Structured JSON contract with `project_meta`, `druggability_matrix`, `featured_candidates_deep_dive` | `_validate_contract()` checks required fields; `rank_featured_candidates()` re-ranks matrix |
| `drug.md` | Publication-quality markdown report (5 sections) | `validate_quality()` threshold >= 0.7 |

### 6.4 Schema Contract (`target_assessment.json`)

```json
{
  "project_meta": {
    "disease_focus": "string",
    "total_input_pairs": "integer"
  },
  "druggability_matrix": [
    {
      "ligand": "string (required)",
      "receptor": "string (required)",
      "is_featured": "boolean (required)",
      "is_novel": "boolean (required)",
      "open_targets_score": "number (required)",
      "validated_track": { ... },
      "exploratory_track": { ... },
      "classification": "validated_target|exploratory_target|novel_candidate|insufficient_evidence",
      "priority": "high|medium|low|unranked",
      "combined_total": "number",
      "rank": "integer|null",
      "novel_tier": "1|2 (novel only)"
    }
  ],
  "featured_candidates_deep_dive": [
    {
      "target_gene": "string (required)",
      "track": "featured|novel",
      "stage3_clinical_safety": { ... },
      "stage1_biological_context": { ... }
    }
  ]
}
```

---

## 7. Usage Guide

### 7.1 Agent-Mode Execution (recommended)

```python
from src.agents.drug_target.agent import create_drug_target_agent, DrugTargetConfig

config = DrugTargetConfig(
    provider="openrouter",       # or "openai", "google", "claude", "ollama"
    data_dir="/path/to/workspace",
    disease="breast cancer",
)

agent, backend = create_drug_target_agent(config)
try:
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "Run the full drug target assessment pipeline for breast cancer."}]},
        config={"configurable": {"thread_id": "unique-id"}},
    )
finally:
    if backend:
        backend.cleanup()
```

### 7.2 Script-Mode Execution

Several scripts are available in `scripts/`:

| Script | Purpose |
|--------|---------|
| `run_drug_target_agent_bc.py` | Run agent for breast cancer |
| `run_drug_target_e2e.py` | End-to-end agent execution |
| `run_stage2_parquet.py` | Stage 2 only (parquet mode) |
| `run_stage2_recompute.py` | Recompute Stage 2 evidence |
| `run_stage12_bc_ollama.py` | Stage 1+2 with Ollama provider |
| `run_all_stages_bc_ollama.py` | All stages with Ollama provider |

### 7.3 Per-Subagent Model Overrides

```python
config = DrugTargetConfig(
    subagent_models={
        "evidence_assessor": "openai:gpt-4.1",
        "report_writer": "openai:gpt-4.1-mini",
    }
)
```

Or via environment variables:
```bash
export SUBAGENT_EVIDENCE_ASSESSOR_PROVIDER="openai:gpt-4.1"
export SUBAGENT_REPORT_WRITER_PROVIDER="openai:gpt-4.1-mini"
```

---

## 8. Integration: Step 9.5 Wrapper

The drug target agent integrates into the DeepMAST wrapper pipeline as **Step 9.5** via `integration.py`:

```python
@tool
async def run_drug_target_assessment(data_dir: str, disease: str) -> str:
    """Run the Drug Target Assessment agent on lr_candidates.json."""
```

**Integration flow**:
1. Reporter subagent (deep_interpreter) calls `run_drug_target_assessment(data_dir, disease)`
2. Function lazily imports `create_drug_target_agent` (breaks circular dependency)
3. Creates `DrugTargetConfig` with provider from `LLM_PROVIDER` env var
4. Runs agent with `ainvoke()` and unique thread_id
5. Returns `drug.md` content + `target_assessment.json` as JSON response

**Circular dependency handling**: `integration.py` uses lazy imports inside the tool function body to break the chain: `deep_interpreter.subagents.configs -> drug_target.integration -> drug_target.agent -> drug_target.subagents.configs`.

---

## 9. Stage Gate Summary

| Gate | Location | Condition | Effect |
|------|----------|-----------|--------|
| Stage 1 confidence | Stage 1 -> 2 | `confidence < 0.4` | Tag `stage1_low_confidence` only; all pairs proceed |
| VEP gate | Stage 2 | `oncology_flag OR has_gwas_variants` | Run Ensembl VEP; skip otherwise |
| Featured selection | Stage 2 -> 3 | `existing_drug_evidence >= 1` | Only Featured (2-5) + Novel (1-3) proceed to Stage 3 |
| PubMed gate | Stage 3 | `max_clinical_phase >= 2` | Run PubMed clinical search; skip otherwise |

---

## 10. Skills & Progressive Disclosure

The agent uses `SkillsMiddleware` to expose selected skill metadata. Skills provide **interpretation guidance only** -- all database access happens through `@tool` wrappers.

### Skills Used by Drug Target Agent

| Skill | Stage | Purpose |
|-------|-------|---------|
| `opentargets-database` | 2 | Evidence weighting, ontology mapping guidance |
| `gwas-database` | 2 | GWAS result interpretation guidance |
| `chembl-database` | 3 | ChEMBL activity values and compound evidence interpretation |

### Skills Used as Tool Backends (via `_load_skill_module()`)

| Skill | Tool(s) |
|-------|---------|
| `kegg-database` | `query_kegg_pathways` |
| `reactome-database` | `query_reactome_pathways` |
| `string-database` | `query_string_ppi_pair` |
| `cellxgene-census` | `query_cellxgene_lr_context`, `list_census_diseases` |
| `compare-census-gene-pair-by-cell-type` | `run_compare_census_lr_pair` |
| `opentargets-database` | `query_opentargets_target`, `query_opentargets_known_drugs`, `query_stage2_gene_panel` |
| `gwas-database` | `query_gwas_gene_trait`, `query_stage2_gene_panel` |
| `drugbank-database` | `query_drugbank_target_profile` (primary) |
| `chembl-database` | `query_drugbank_target_profile` (fallback) |
| `pubmed-eutils-search` | `query_pubmed_clinical_limitations` |

---

## 11. External API Dependencies

| API | Used By | Offline Capable |
|-----|---------|-----------------|
| CELLxGENE Census (TileDB-SOMA) | Stage 1 | No |
| STRING REST API | Stage 1 | No |
| KEGG REST API | Stage 1 | No |
| Reactome REST API | Stage 1 | No |
| OpenTargets GraphQL / Parquet | Stage 2 | Yes (with local parquet) |
| GWAS Catalog REST / Parquet | Stage 2 | Yes (with local parquet) |
| Ensembl VEP REST API | Stage 2 (gated) | No |
| DrugBank XML | Stage 3 | Yes (with local XML) |
| ChEMBL REST API | Stage 3 (fallback) | No |
| PubMed E-utils | Stage 3 (gated) | No |

Local parquet data locations (relative to project root):
- OpenTargets: `data/ot_data/` (target/, disease/, evidence/ partitions)
- GWAS Catalog: `data/gwas_data/` (associations.parquet, traits.parquet)

All tools return structured error JSON on failure (fail-soft pattern). Network failures do not crash the pipeline.
