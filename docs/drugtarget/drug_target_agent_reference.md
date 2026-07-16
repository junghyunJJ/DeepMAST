# Drug Target Assessment Agent -- Comprehensive Reference

> **Source of truth**: `src/agents/drug_target/` codebase
> **Last verified**: 2026-07-16 (guarded hybrid report-writer production path)
> **Related**: `drug_target_stage_guide.md` (stage-level detail), `output_schema.json` (JSON contract)

---

> **Current production contract:** `evidence_assessor -> report_writer -> DrugReportGuardrailMiddleware -> guarded publication`. The writer owns only canonical `report_sections.json`; Jinja renders `drug.md` and the other pre-publication artifacts. Success requires valid initial/final audits plus Part 4 and HTML publication artifacts. Tools are forced to the configured directory, DeepAgents `general-purpose` is blocked, and custom tools are rejected. The guarded runners are `run_report_writer_only.py`, `run_drug_target_e2e.py`, and `run_drug_target_agent_bc.py`. `legacy_hypothesis` is the only outer-super-graph/finalizer compatibility path.

**Production entrypoints**: construct `create_drug_target_agent` directly with
`workflow_mode="guarded_report"`, or use `run_report_writer_only.py`, `run_drug_target_e2e.py`, and `run_drug_target_agent_bc.py`.

**Legacy compatibility wrapper integration**: `integration.py` calls
`drug_target_graph.ainvoke(...)`; that graph forces `legacy_hypothesis` and is
not the guarded production entrypoint.

## 1. Overview

The Drug Target Assessment Agent evaluates therapeutic potential of ligand-receptor (L-R) pairs identified from spatial transcriptomics (ST) cell-cell interaction (CCI) analysis. Production uses a **guarded 2-subagent** architecture: the evidence assessor gathers evidence, the report writer authors bounded structured sections, and middleware validates, repairs, publishes, and audits the rendered result.

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
| **Output** | `report_sections.json` | Qwen-authored canonical hypotheses and recommendations |
| **Output** | `target_assessment.json`, `report_data.json`, `drug.md`, `drug_report_render.json` | Renderer-owned pre-publication artifacts |
| **Output** | Part 4 JSON/Markdown and `drug_report.html` | Guarded-publication artifacts after final validation |

---

## 2. Architecture

### 2.1 Component Hierarchy

```
Production entrypoints
  -> create_drug_target_agent(config, workflow_mode="guarded_report") [agent.py]
     -> DrugReportRunCleanupMiddleware
     -> evidence_assessor (configured-run evidence tools)
     -> report_writer (save_report_sections exactly once)
     -> DrugReportGuardrailMiddleware (validate rendered Markdown, repair sections, publish Part 4 + HTML, audit)
  -> run_report_writer_only.py | run_drug_target_e2e.py | run_drug_target_agent_bc.py

Legacy compatibility wrapper integration (not guarded production)
  -> run_drug_target_assessment(data_dir, disease)    [integration.py]
    -> drug_target_graph.ainvoke(...)                 [graph_builder.py]
      -> legacy_hypothesis super-graph
```

### 2.2 Source File Map

| File | Role |
|------|------|
| `super_graph.py` | Explicit `legacy_hypothesis` compatibility super-graph only. |
| `graph_builder.py` | Legacy graph entry surface. |
| `finalize_report.py` | Explicit legacy finalizer compatibility implementation. |
| `finalize_report_prompts.py` | Legacy compatibility prompts for the `finalize_report` LLM call: `FINALIZE_REPORT_SYSTEM_PROMPT`, `FINALIZE_REPORT_USER_TEMPLATE` |
| `validators.py` | `validate_cited_only_provenance(payload, reference_card)` — cited-only provenance check called inside `_persist_and_validate` |
| `middleware.py` | Run cleanup, task allowlist, configured-filesystem, and report guardrail middleware. |
| `agent.py` | Orchestrator factory: `DrugTargetConfig`, `create_drug_target_agent()`, system prompt |
| `subagents/configs.py` | Guarded `WORKFLOW_ORDER = ["evidence_assessor", "report_writer"]` and explicit legacy factory. |
| `subagents/prompts.py` | Evidence assessor, canonical report writer, and retained legacy hypothesis prompts. |
| `tools/__init__.py` | Tool re-exports with lazy imports for circular-dep breaking |
| `tools/stage_domain_tools.py` | Stage 1-3 domain tools: CELLxGENE, KEGG, Reactome, STRING, VEP, OT, GWAS, DrugBank/ChEMBL, PubMed |
| `tools/stage2_service.py` | Stage 2 batch orchestration: `build_stage2_gene_panel()`, parquet/API routing, workspace caching |
| `tools/stage_logic.py` | Rubric scoring, classification, priority, confidence, stage gates |
| `tools/evidence_loader.py` | I/O helpers: `load_lr_candidates`, `load_evidence_files`, `save_evidence` |
| `tools/assessment_output.py` | Output contract: `save_target_assessment()`, `_validate_contract()` |
| `tools/census_lr_validation_tools.py` | Census cross-validation: `run_compare_census_lr_pair()`, fuzzy matching |
| `tools/report_expansion_schema.py` | `ReportExpansionsPayload` Pydantic model, `validate_report_expansions()`, `canonical_json_hash`, `_build_provenance_index` |
| `tools/skill_reader.py` | Progressive disclosure: `read_skill_file()` |
| `tools/common.py` | Cognitive tools: `sequential_thinking`, `think_tool`, `validate_quality` |
| `integration.py` | Legacy compatibility reporter bridge: `run_drug_target_assessment()` async Step 9.5 tool invokes `drug_target_graph.ainvoke(...)`, which forces `legacy_hypothesis`. |

### 2.3 Subagent Configuration

**Workflow order**: `["evidence_assessor", "report_writer"]` (strict sequential, defined in `subagents/configs.py`). `report_writer` is the sole production author; `DrugReportGuardrailMiddleware` owns all post-write work.

| Component | Type | Tools | Role |
|-----------|------|-------|------|
| `evidence_assessor` | flat dict subagent | ~20 tools | 3-stage funnel: biological context -> validation & scoring -> deep dive + inline rubric |
| `report_writer` | flat dict subagent | bound evidence tools + `save_report_sections` | Authors the canonical `report_sections.json` payload; only allow-listed skill content and the configured run directory are available. |

Production middleware boundaries:

| Middleware | Location | What it enforces |
|---|---|---|
| `DrugReportRunCleanupMiddleware` | top-level | Removes stale guarded output before dispatch. |
| `DrugTargetManagedFilesystemGuardMiddleware` | top-level + subagents | Blocks generic filesystem/Docker tools and rewrites all `data_dir` arguments. |
| `DrugTargetTaskAllowlistMiddleware` | top-level | Allows only evidence_assessor/report_writer; blocks automatic `general-purpose`. |
| `DrugReportGuardrailMiddleware` | report_writer | Validates, repairs, publishes, and writes audits. |

**Sentinel**: The orchestrator ends with `REPORT_PIPELINE_COMPLETE` after the guarded writer returns.

### 2.4 Guarded hybrid ownership and recovery

`evidence_assessor -> report_writer -> DrugReportGuardrailMiddleware -> guarded publication`
is the complete guarded production graph. The report writer (Qwen in the local
smoke path) owns only the canonical Section 4 hypotheses and 2–4 Section 5
recommendations in `report_sections.json`. It never writes Markdown, report
data, or target assessment artifacts directly.

| Output | Owner | When written |
|---|---|---|
| `report_sections.json` | report writer / repair agent | One validated structured save per write or repair pass |
| `target_assessment.json`, `report_data.json`, `drug.md`, `drug_report_render.json` | Jinja renderer | Immediately after a valid sections save or repair re-render |
| Markdown layout, factual values, Section 5.1 execution summary, and `[source: …]` placement | Jinja renderer | During deterministic render only |
| `part4_candidate_selection.json`, `part4_therapeutic_synthesis.md`, `drug_report.html` | guarded publication | Only after final Markdown validation succeeds |
| `drug_report_validation_initial.json`, `drug_report_validation_final.json` | guardrail | Before and after validation/publication |

The guardrail repairs the structured sections payload, re-renders the complete
Markdown, and validates it again. After three failed repair attempts it clears
publication artifacts and does not publish Part 4 or HTML. Legacy direct
Markdown repair remains only for runs without `report_sections.json`.

### 2.5 DrugTargetConfig Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | str | `"ollama"` | LLM provider |
| `model` | str\|None | `None` | Optional explicit top-level model; in guarded mode the same constructed model is assigned to `report_writer`. |
| `data_dir` | str | env `DEEP_INTERPRETER_DATA_DIR` | Directory with `lr_candidates.json` |
| `disease` | str | `""` | Disease context injected into system prompt |
| `use_checkpointer` | bool | `False` | Enable LangGraph memory checkpointer |
| `workflow_mode` | `guarded_report\|legacy_hypothesis` | `guarded_report` | Explicit production/compatibility selection |
| `custom_tools` | Sequence | `[]` | Rejected in guarded mode; retained only by explicit legacy mode |
| `docker_image` | str\|None | `None` | Docker image for sandbox backend |
| `enable_progressive_disclosure` | bool | `True` | Expose skills metadata via SkillsMiddleware |
| `agent_skill_names` | tuple | `("opentargets-database", "gwas-database", "chembl-database")` | Skills exposed to agent |
| `skills_dir` | str\|None | `None` | Override project skills directory |
| `subagent_models` | dict\|None | `None` | Per-subagent model overrides (init_chat_model format) |

> **Legacy compatibility note**: `critic_enabled` and `summarizer_skill_names` config fields were removed in the 2026-05-19 migration. The summarizer subagent no longer exists; explicit `legacy_hypothesis` execution uses the deterministic `finalize_report` LangGraph node. Guarded production uses `report_writer` plus `DrugReportGuardrailMiddleware` instead.

### 2.6 Legacy `finalize_report` compatibility node — historical error classes

The retained `finalize_report` node (`src/agents/drug_target/finalize_report.py`) serves only explicit `legacy_hypothesis` super-graph/traced compatibility callers. Production uses the guarded writer flow above.

| Error class | When raised | Disk writes? |
|-------------|-------------|-------------|
| `evidence_budget_exceeded` | Evidence token estimate > 20 000 tokens at node entry (before LLM call) | None — `evidence_truncated=True` |
| `llm_call_failed_after_retries` | `_llm_fill_expansions_once` exhausts 2 attempts (ValidationError, OutputParserException, or provider error) | None |
| `validation_failed` | `validate_report_expansions()` returns non-empty errors | None |
| `cited_only_violation` | `validate_cited_only_provenance()` finds sentences citing keys absent from `reference_card` | None |
| `finalization_validation_failed` | `validate_drug_report_finalization()` returns `valid=false` in `_finalize_workspace` | drug.md + HTML already written |

**Token-budget fail-closed gate** (line 81–84, `finalize_report.py`): at node entry, before any LLM call, the node estimates evidence token count as `len(json.dumps(evidence)) // 4`. If this exceeds `_TOKEN_BUDGET = 20_000`, the node returns immediately with `evidence_truncated=True` and `report_finalization_error="evidence_budget_exceeded: ..."`. No LLM call is made; no disk writes occur.

**Idempotency** (Decision 12, line 77, `finalize_report.py`): if `drug.md` already exists at node entry, `finalize_report` skips all processing and returns success. This allows safe re-invocation without re-running the LLM call.

### 2.7 Legacy compatibility Super-Graph State Schema (`DrugTargetState`)

Defined in `src/agents/drug_target/super_graph.py`:

| Field | Type | Description |
|-------|------|-------------|
| `data_dir` | `str` | Workspace directory (read-only across all nodes) |
| `disease` | `str` | Disease context string |
| `featured_lr_pairs` | `list[str] \| None` | Featured L-R pairs from evidence assessor |
| `messages` | `Annotated[list[BaseMessage], add_messages]` | Accumulated messages; `run_deep_agent` returns only the last `AIMessage` |
| `report_finalization_error` | `str \| None` | Set by legacy `finalize_report` on any failure; `None` means success |
| `evidence_truncated` | `bool` | `True` when the legacy token-budget gate fired; default `False` |

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

### 3.7 Legacy compatibility finalization (finalize_report node)

In explicit `legacy_hypothesis` compatibility runs, `run_deep_agent` routes to the deterministic
`finalize_report` node (`src/agents/drug_target/finalize_report.py`).
This node performs exactly **1 LLM call** and is not a subagent.

**6-step internal sequence:**

1. **Idempotency check** — if `drug.md` already exists, skip all processing
   and return success (Decision 12, `finalize_report.py:77`).
2. **Load inputs** — `_load_expansion_inputs(data_dir, disease)` loads
   evidence dict, expansion schema spec, and reference card from disk.
3. **Token-budget gate** — estimate evidence token count as
   `len(json.dumps(evidence)) // 4`. If `> 20_000`, return
   `evidence_truncated=True` immediately. No LLM call; no disk writes.
4. **LLM call** — `_llm_fill_expansions_once(model, spec, evidence, reference_card, config)`
   calls `model.with_structured_output(ReportExpansionsPayload).with_retry(stop_after_attempt=2)`.
   On failure (ValidationError, OutputParserException, provider error), return
   `report_finalization_error="llm_call_failed_after_retries: ..."`.
5. **Persist + validate** — `_persist_and_validate(data_dir, payload, reference_card)`:
   - **5a.** `validate_report_expansions(data_dir, payload.model_dump())` — schema validation.
   - **5b.** `validate_cited_only_provenance(payload, reference_card)` — cited-only provenance
     check; verifies every `source_provenance.source_file::source_field` key exists in the
     reference card's provenance index. `cited_only` errors win over `schema` errors.
   - On any errors: return `report_finalization_error` and **do not write disk artifacts**.
   - On pass: atomically save `report_expansions.json`.
6. **Render outputs** — `_render_outputs(data_dir, payload)`:
   `render_drug_md_from_expansions()` → `drug.md`;
   `generate_drug_html_report()` → HTML;
   atomic write of `target_assessment.json` (from `payload.model_dump()`).
7. **Finalize workspace** — `_finalize_workspace(data_dir)`:
   `finalize_stage1_artifacts()` then `validate_drug_report_finalization()`.
   On failure: `report_finalization_error="finalization_validation_failed: ..."`.

All writes in steps 6–7 are atomic (`tempfile` + `os.replace`).
The `report_finalization_error` state field is the single observable failure
surface for this node. `integration.run_drug_target_assessment()` reads it
and sets `success=False` with `errors=[finalization_error]` in the return envelope.

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

### 4.2 Legacy compatibility `finalize_report` Node Tools

The legacy compatibility `finalize_report` node calls tool `.func()` directly (not via LLM tool-calling). The following tools from `tools/__init__.py` are used internally:

| Tool | Called by | Purpose |
|------|-----------|---------|
| `load_evidence_files` | `_load_expansion_inputs` | Load all `evidence/*.json` |
| `save_report_expansions` | `_persist_and_validate` | Atomic save of schema-validated expansions |
| `render_drug_md_from_expansions` | `_render_outputs` | Deterministic Markdown assembly of `drug.md` |
| `generate_drug_html_report` | `_render_outputs` | Final HTML render |
| `finalize_stage1_artifacts` | `_finalize_workspace` | Stage 1 artifact normalization |
| `validate_drug_report_finalization` | `_finalize_workspace` | Final validation gate |

Validation functions called directly (not LangChain tools):

| Function | Module | Purpose |
|----------|--------|---------|
| `validate_report_expansions` | `tools/report_expansion_schema.py` | Schema validation of expansion payload |
| `validate_cited_only_provenance` | `validators.py` | Cited-only provenance check against reference card |

> **Legacy compatibility note**: The `summarizer` subagent and its associated tools (`build_evidence_summary`, `validate_drug_md`, `think_tool` in summarizer context) were removed in the 2026-05-19 migration. Explicit `legacy_hypothesis` finalization runs as a deterministic LangGraph node; guarded production uses the writer/guardrail flow.

See [Section 2.5](#25-legacy-finalize_report-compatibility-node--historical-error-classes) for the full error class table and gate description.

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

### 7.4 Supported Ollama guarded smoke invocation (live validation pending)

Production continues to run the full Deep Agent topology:
`evidence_assessor -> report_writer -> DrugReportGuardrailMiddleware`.
`run_report_writer_only.py` is a diagnostic entrypoint instead: it requires
existing evidence-assessor artifacts, then directly compiles the canonical
guarded `report_writer` specification without an outer task-dispatch turn.

The explicit `--model` and `--request-timeout-seconds` selection is preserved
for initial authoring, both guardrail repair paths, and the Part 4 selector.
The provider request timeout must be positive and shorter than the positive
overall `--run-timeout-seconds`; the latter reports a bounded, artifact-derived
failure phase without accepting stale success artifacts.

Ollama 0.20.6's OpenAI-compatible endpoint may ignore
`enable_thinking=false`; do not treat that setting as guaranteed reasoning
suppression.

```bash
export OLLAMA_BASE_URL=http://localhost:6000
uv run python -u scripts/run_report_writer_only.py \
  --data-dir /path/to/copied-evidence-run \
  --disease "breast cancer" \
  --provider ollama-openai \
  --model qwen3.5:122b \
  --request-timeout-seconds 600 \
  --run-timeout-seconds 1800
```

Exit `0` requires all guarded artifacts plus a valid final audit and passed
publication gate. A timeout exits `1` with its best observable phase:
`report_writer`, `guardrail_or_publication`, or `publication`.

**Latest bounded live result (2026-07-16):** with `qwen3.5:122b` through
`http://localhost:6000`, `--request-timeout-seconds 600`, and
`--run-timeout-seconds 1800`, the first writer request produced no
`report_sections.json` or audit artifacts and exited `1` after 1800 seconds
with `phase=report_writer`. This validates the bounded failure contract, not
successful report generation. The configured provider request timeout did not
preempt this Ollama OpenAI-compatible call; investigate model-side first-token
latency before relabeling this invocation as verified.

---

## 8. Legacy compatibility wrapper integration: Step 9.5

The legacy compatibility drug target graph integrates into the DeepMAST wrapper
pipeline as **Step 9.5** via `integration.py`. Guarded production instead uses
the direct agent factory or the three canonical guarded runners listed above:

```python
@tool
async def run_drug_target_assessment(data_dir: str, disease: str) -> str:
    """Run the Drug Target Assessment agent on lr_candidates.json."""
```

**Legacy compatibility integration flow**:
1. Reporter subagent (deep_interpreter) calls `run_drug_target_assessment(data_dir, disease)`
2. Function lazily imports `drug_target_graph` from `graph_builder` (breaks circular dependency)
3. Invokes the super-graph: `drug_target_graph.ainvoke(initial_state, config={"recursion_limit": 10000, "configurable": {"thread_id": uuid4()}})`
4. Reads `report_finalization_error` and `evidence_truncated` from final state
5. On success: reads `drug.md` and `target_assessment.json` from disk and returns `json.dumps({success, drug_md, target_assessment, errors, evidence_truncated})`
6. On failure: returns `json.dumps({success=False, drug_md=None, target_assessment=None, errors=[finalization_error], evidence_truncated})`

**Return envelope** (invariant contract — `wrapper_agent.py` calls `json.loads(result)`):

```json
{
  "success": true,
  "drug_md": "<string content of drug.md>",
  "target_assessment": { ... },
  "errors": [],
  "evidence_truncated": false
}
```

**Legacy compatibility circular dependency handling**: `integration.py` uses a lazy import of `drug_target_graph` inside the tool function body to break the chain: `deep_interpreter.subagents.configs → drug_target.integration → drug_target.graph_builder → drug_target.super_graph`.

**Legacy compatibility wrapper transparency**: The disk-artifact contract (`drug.md`, `drug_report.html`, `target_assessment.json`) is unchanged. `wrapper_agent.run_drug_target_node` continues to read these artifacts from disk without modification.

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
