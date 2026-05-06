# Plan: 2×2 Harness × Model-Strength Ablation Benchmark (Rev 4)

## Rev 4 Delta (2026-04-13) — SEARCHER infrastructure update

Incorporates the SEARCHER + `search_literature_dynamic` overhaul from commits `65b93e0`..`81ffee0` and later keyword-only pathway search revisions (dynamic literature search + deterministic gene/pathway fan-out + retrieval tags + SkillLoadHarness). Production retrieval is no longer LLM-compliance-bottlenecked: the tool now pre-seeds gene-singleton queries, controlled keyword-only pathway queries, and BioMCP gene-alias-aware coverage matching. This changes what the harness effect actually measures and introduces a real ceiling-effect risk that the pilot MUST screen for.

### Upstream changes (Rev 3 → Rev 4)

1. **SEARCHER-mode sentinel** (`literature.py:2535-2567`). Passing `enable_lr_pair_queries=True` auto-enables `coverage_weighted_sort=True`, flips `_use_retrieval_tags=True` on both `_calculate_coverage` call sites, and bumps the internal candidate pool to `max(max_results*5, 300)` — final cap is kept at the caller's `max_results`. SEARCHER sets it at `subagents/prompts.py:261`; PLANNER/REPORTER never set it and retain byte-equivalent legacy behavior.
2. **Deterministic gene singleton fan-out** (`literature.py:_build_deterministic_gene_queries`, ~L1319). Iter-0, **LLM-generation path only** — skipped when `query_cache` is passed. `chunk_size=1`: every input gene gets its own focused BioMCP query, closing the prior 36.7% input-gene ceiling (root cause: `genes[:5]` x 2 LLM gene queries = 10 slots for 30 genes).
3. **Keyword-only per-pathway fan-out** (`literature.py:_build_deterministic_pathway_queries`). Iter-0, **runs unconditionally in both cache-replay and LLM paths** — meaning `query_cache` trials DO receive pathway fan-out. One query per pathway uses `genes=[]` plus 2-3 controlled vocabulary pathway terms; pathway evidence is accepted only when disease and pathway text appear in title/abstract.
4. **Controlled pathway vocabulary** (`literature.py:PATHWAY_KEYWORDS`). Pathway query terms are canonical-first controlled labels with explicit source metadata (`canonical_label`, `query_terms`, `match_aliases`, `source_refs`). Production SEARCHER no longer carries pathway-to-gene search anchors.
5. **BioMCP gene alias pre-warm** (`literature.py:2580-2629`). Parallel `_fetch_gene_aliases_from_biomcp` over top-30 input genes (10s/gene wait_for timeout) populates module-level `_GENE_ALIAS_CACHE`; `_generate_gene_patterns` is now alias-aware end-to-end. Diagnostic recovery: +EFNA1, +ITGB1, +RET on `res_bc_ollama`. Degrades gracefully on outage (empty cache entries).
6. **Retrieval tag stamp** (`literature.py:509-525, 1793-1862`). Every BioMCP article now carries `matched_via_query = {genes, diseases, keywords}`. `_calculate_coverage(use_retrieval_tags=True)` does two-tier provenance for genes. For pathways, stamps are provenance only; title/abstract pathway text is required before coverage is credited.
7. **SkillLoadHarness in Deep Interpreter** (commit `3e2fe8d`; `agent.py:258-275`, `subagents/configs.py`). Skills are injected per-subagent via `SkillLoadHarness` middleware — no more orchestrator-level `SkillsMiddleware`. This benchmark's ON arm is **unaffected**: the single-shot flow still has no tool loop, so both Rev 3 (inline SKILL.md text) and Rev 4 require the same workaround (inline the skill content into the system prompt). The code-path change does not invalidate §3.2 — the strip list (steps 3-6) remains correct because SKILL.md itself was not modified in this work.

### How Rev 4 re-interprets existing sections

| Section | Rev 3 assumption | Rev 4 reality |
|---------|-----------------|---------------|
| §2 Experimental Design | `enable_lr_pair_queries` defaulted off | **MUST set `enable_lr_pair_queries=True` in all 4 conditions** — matches production SEARCHER. Hard mandatory setting, not optional. |
| §3.2 Inlined skill | Strip list (steps 3-6) | Unchanged. SKILL.md was not modified upstream. Add a note that deterministic fan-out is tool-internal and the inlined skill does not describe it (no action needed). |
| §3.4 Trial runner | `query_cache` bypasses internal LLM | Still true. **New**: pathway fan-out runs regardless of `query_cache`; gene fan-out stays LLM-path-only → `query_cache` skips gene singletons. Intentional and correct — the harness effect we want to measure is "LLM query enrichment under skill guidance", localized to `query_cache` quality. Pathway fan-out acts as a uniform baseline across arms, not a confound. |
| §3.4 `SearchTrialResult` | Regex-only coverage metrics | **Add** eight fields tracking tag-aware vs tag-unaware provenance, query composition, candidate-pool sizes, and alias pre-warm latency (see patch below). |
| §4.1 GLMM primary | Coverage vs binary threshold | **Run both** a tag-aware (`use_retrieval_tags=True`, primary — matches production) and a tag-unaware (`False`, sensitivity — isolates pure prompt-quality signal without retrieval-stamp credit) analysis. If both agree in direction, the interaction claim is robust; if they diverge, report both in the paper and flag the tag credit as a mechanism. |
| §4.6 Pilot checks | 7 mandatory checks | **Add 8th check (ceiling-effect gate)**: if both `strong_on` AND `strong_off` pilot cells hit ≥95% gene coverage OR ≥95% pathway coverage, the deterministic fan-out alone is saturating the primary endpoint → **abort full run** and either (a) switch primary endpoint to diversity/novelty (unique PMIDs, paper-count ≥ 25, tag-confirmed-only coverage) or (b) degrade to `enable_lr_pair_queries=False` to isolate LLM-driven coverage at the cost of ecological validity. Load-bearing gate — decide before 360 trials. |
| §8 Reusable code | Pattern table | **New rows**: `_build_deterministic_gene_queries`, `_build_deterministic_pathway_queries`, controlled `PATHWAY_KEYWORDS`, `_calculate_coverage(use_retrieval_tags=...)`, SEARCHER sentinel block, alias pre-warm, plus three test files (`tests/deep_interpreter/test_deterministic_gene_queries.py`, `test_deterministic_pathway_queries.py`, `test_evidence_manifest.py`) and two diagnostic scripts (`scripts/diagnose_searcher_coverage.py`, `scripts/rerun_searcher_only.py`). |
| §10 Risks | 16 rows | **Add four Rev 4 risks**: ceiling effect from deterministic fan-out, query_cache/gene-fan-out asymmetry vs Option A, alias pre-warm latency (~10-30s/trial), and 300-paper candidate pool ballooning wall-clock. |

### Key measurement implication

The harness effect shifts from "did the LLM generate enough gene-centric queries to retrieve the right papers" to "did the LLM enrich its query_cache with pathway+disease+keyword context beyond what deterministic pathway fan-out already supplies". This is still a meaningful signal — the skill teaches disease anchoring, gene-synonym expansion, and multi-slot keyword combinations the deterministic baseline lacks — but the effect size will likely be smaller than Rev 3 predicted. Pilot power analysis (§4.6 step 3) MUST re-estimate `N_required` from observed effect sizes, not Rev 3's prior.

---

## Context

The existing benchmark (`docs/benchmarks/skills/`) proved SkillLoadHarness improves skill activation F1 from 81.7% → 93.9% (p=0.000003) for the Drug Target Agent with qwen3.5:122b. Two gaps remain: (1) does the harness also help a different agent (Deep Interpreter SEARCHER)? (2) does the improvement translate to better downstream search quality? (3) does model strength moderate the effect?

This benchmark fills those gaps as **Table 4** in the paper, complementing the existing **Table 3**.

## RALPLAN-DR Summary

### Principles
1. **Outcome over process**: Measure search quality (coverage), not just skill activation
2. **Cross-agent generalization**: Test the same harness on a different agent
3. **Interaction is the story**: The 2×2 interaction effect is the novel finding
4. **Reuse existing infrastructure**: Cases, models, statistical patterns
5. **Pilot before full**: Validate pipeline on 24 trials before committing to 360
6. **Operational equivalence**: ON arm must actually receive the skill content (not just instructions to read it)
7. **No silent fallbacks**: Any deviation from the protocol must be a hard failure or excluded from analysis

### Decision Drivers
1. PubMed API cost/time (each trial ~3 min, 360 trials ~18h)
2. Need a medium-fidelity SEARCHER prompt (production prompt references skill loading, confounds harness OFF)
3. Double-LLM confound: `search_literature_dynamic` internally creates its own LLM for query generation — must use `query_cache` to bypass
4. Gene input must be enriched beyond [ligand, receptor] to avoid ordinal floor effect
5. **NEW**: Single-shot JSON flow has no tool loop, so `SkillLoadHarness` cannot trigger `read_skill_file`. ON arm must inline skill text directly.
6. **NEW**: Live PubMed/BioMCP traffic across 18h cannot be confounded with model identity → block randomization required

### Viable Options

**Option A: Full tool-calling loop** — LLM calls read_skill_file + search_literature_dynamic + think_tool in multi-turn session. Highest ecological validity but complex, expensive, slow.

**Option B+: Parameter extraction with query_cache + inlined skill (Recommended)** — LLM generates search parameters AND PubMed query objects from case context. Harness ON arm receives the SKILL.md Phase 1-4 content INLINED into the system prompt (not as a `read_skill_file` instruction). Pass query objects as `query_cache` to `search_literature_dynamic`, bypassing the internal LLM entirely. Cleaner, faster, isolates the harness effect on search planning quality. Still measures real downstream coverage via PubMed.

**Why Option B+ with inlined skill**: Eliminates the double-LLM confound (Codex finding #2), the empty-ON-arm confound (Codex finding #1), and is implementable in a single-shot flow. A small Option A validation arm (24 trials) provides ecological validity for reviewers.

### ADR (Architectural Decision Record)

**Decision**: Option B+ with `query_cache` bypass + inlined SKILL.md text + Option A validation arm
**Drivers**: Measurement validity (no inner-LLM confound, no empty ON arm), statistical power (continuous DV), ecological validity (Option A arm), operational integrity (block randomization)
**Alternatives**:
- Option A only — too expensive for 360 trials
- Option B without query_cache — confounded by inner LLM
- Option B+ with `read_skill_file` instruction — empty ON arm because no tool loop exists
**Why chosen**: Best balance of purity and validity; resolves all Codex/Architect/Critic findings
**Consequences**: System prompt for ON arm becomes longer (~2-3K extra tokens). LLM must generate query objects (extra ~500 tokens output). Adds randomization scheduling complexity.
**Follow-ups**: If pilot shows Option A results diverge from Option B+, expand Option A arm

---

## Implementation Plan

### 1. Directory Structure

```
docs/benchmarks/harness_x_model/
├── PLAN.md                        # This document (committed for review)
├── benchmark_harness_x_model.py   # Main benchmark runner
├── generate_enriched_cases.py     # Precompute enriched gene lists for cases
├── analyze_results.py             # Statistical analysis (GLMM + bootstrap)
├── figure_table4_results.R        # R visualization
├── prompts/
│   ├── searcher_base.txt          # Medium-fidelity SEARCHER prompt (OFF arm)
│   ├── skill_inlined.txt          # SKILL.md Phase 1-4 content for ON arm
│   └── render_prompts.py          # Build OFF/ON prompts from templates
├── cases/
│   ├── cci_full_cases.json        # symlink → ../cci_skill_ablation/cases/
│   ├── interest_sig_liana.csv     # symlink → ../cci_skill_ablation/cases/
│   └── enriched_cases.json        # Cases with augmented gene lists (generated)
└── results/
    ├── pilot/
    ├── full/
    └── option_a_validation/
```

### 2. Experimental Design

**Main Experiment: Option B+ (360 trials)**

| Cell | Label | Model | Harness | System Prompt |
|------|-------|-------|---------|---------------|
| A | `strong_off` | qwen3.5:122b | OFF | Medium-fidelity SEARCHER (no skill content) |
| B | `strong_on` | qwen3.5:122b | ON | Medium-fidelity SEARCHER + INLINED SKILL.md Phase 1-4 |
| C | `weak_off` | qwen3.5:35b | OFF | Medium-fidelity SEARCHER (no skill content) |
| D | `weak_on` | qwen3.5:35b | ON | Medium-fidelity SEARCHER + INLINED SKILL.md Phase 1-4 |

**Cases**: 30 L-R pairs from `cci_full_cases.json` (6 strata × 5 pairs), enriched with augmented gene lists
**Repeats**: 3 per cell (temperature=0.3 for LLM variance)
**Trials**: 30 × 4 × 3 = 360 (pilot: 6 × 4 × 1 = 24)
**Schedule**: Block-randomized (NOT serialized by model — see Section 3.5)

**Validation Arm: Option A (24 trials)**
6 cases × 4 conditions × 1 repeat = 24 trials with full tool-calling loop using DeepAgent runtime.
Reported as Supplementary figure for ecological validity.

### 3. Core Components

#### 3.1 Medium-Fidelity SEARCHER System Prompt (OFF arm)

Critical: cannot use the production SEARCHER prompt (`subagents/prompts.py:182`) because it explicitly says "Load Complete Workflow Guide" → confounds harness OFF. Write a medium-fidelity version that describes the role and tools without referencing skill files.

`prompts/searcher_base.txt`:
```
You are a biomedical literature search expert for spatial transcriptomics.

Given an L-R pair evidence bundle with enriched gene context, generate:
1. A search plan: select the most relevant genes, pathways, cell types, and disease terms
2. PubMed query objects for executing the search

Output format (JSON, no other text):
{
  "search_params": {
    "genes": ["gene1", "gene2", ...],
    "pathways": ["pathway1", ...],
    "celltypes": ["celltype1", ...],
    "disease": "disease context"
  },
  "query_objects": [
    {"genes": ["gene1"], "diseases": ["disease"], "keywords": ["keyword"]},
    ...
  ]
}

Goal: Achieve ≥60% gene coverage and ≥50% pathway coverage with ≥25 papers.
Select genes strategically — prioritize genes with known literature presence.
```

#### 3.2 Inlined Skill Text for Harness ON arm (P0 fix from Codex #1)

**Critical change**: `SkillLoadHarness` middleware injects "evaluate skills then call `read_skill_file`" instructions, but our single-shot JSON flow has no tool loop. The LLM cannot actually call `read_skill_file`. Therefore the ON arm must receive the **content** of `biomedical-literature-search/SKILL.md` directly inlined.

**Procedure to build `prompts/skill_inlined.txt`**:
1. Read `skills/biomedical-literature-search/SKILL.md`
2. Strip YAML frontmatter
3. **Strip any references to `search_pubmed_advanced` / E-utilities** (the benchmark only uses `search_literature_dynamic` via BioMCP — we cannot evaluate the LLM against guidance it cannot act on)
4. Strip references to `read_file`, `load_analysis_data`, `write_file` (those are tool-loop-only operations)
5. **Strip `think_success` references** (Phase 2.2) — the benchmark uses `query_cache`, which bypasses `_think_search_strategy` at `literature.py:2280-2291`, so `think_success` is always False. Instructing the LLM to interpret it is a dead instruction.
6. **Strip `rerank_mode="llm"` troubleshooting** (§249-251 of SKILL.md) — the benchmark hardcodes `rerank_mode="off"` because `rerank_mode="llm"` invokes `_llm_disease_relevance_filter` at `literature.py:608-618`, creating a second internal-LLM confound. Instructing the LLM to fix coverage via rerank is a dead instruction.
7. Keep: Phase 2 search strategy (sans 2.2 and 2.3), coverage thresholds, Phase 3 reflection criteria, common mistakes (excluding tool-loop-only ones), troubleshooting (excluding rerank and E-utilities hints)
8. Convert into a "## Workflow Guidance (loaded from biomedical-literature-search skill)" section appended to `searcher_base.txt`

**Build helper** (`prompts/render_prompts.py`):
```python
def build_inlined_skill(skill_md_path: str) -> str:
    """Extract Phase 2-4 content from SKILL.md, strip E-utilities and tool-loop refs."""
    raw = Path(skill_md_path).read_text()
    body = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.DOTALL)
    # Remove E-utilities section
    body = re.sub(r"### Step 2\.3: Advanced E-utilities.*?(?=\n##|\Z)", "", body, flags=re.DOTALL)
    # Remove tool-loop-only refs (load_analysis_data, write_file, read_file)
    body = re.sub(r"^.*(load_analysis_data|write_file|read_file).*$\n?", "", body, flags=re.MULTILINE)
    return body.strip()

def build_system_prompt(arm: str) -> str:
    base = (Path(__file__).parent / "searcher_base.txt").read_text()
    if arm == "off":
        return base
    if arm == "on":
        skill_text = build_inlined_skill(SKILL_MD_PATH)
        return f"{base}\n\n## Workflow Guidance (loaded from biomedical-literature-search skill)\n\n{skill_text}"
    raise ValueError(f"Unknown arm: {arm}")
```

**Equivalence verification**: Save both prompts to disk on first run; manually inspect that ON arm contains the Phase 2-4 workflow text and OFF arm does not. Pilot must confirm token counts: OFF ~500 tokens, ON ~2.5-3K tokens.

**Note on Codex finding #1, second part**: The original SKILL.md says "if gaps remain, use `search_pubmed_advanced` (E-utilities)" but our benchmark only executes BioMCP. Inlining that instruction would evaluate the LLM against guidance it cannot act on. Step 3 above explicitly strips this section. The inlined version describes only BioMCP-compatible workflow.

#### 3.3 Enriched Gene Lists (Fix for Floor Effect + Codex #3 bug fixes)

**Problem 1 (floor effect)**: Raw cases have only [ligand, receptor] = 2 genes. Production SEARCHER uses ~30 genes from `load_analysis_data`. With 2 genes, `genes_coverage_pct` ∈ {0%, 50%, 100%} — ordinal, not continuous.

**Problem 2 (Codex #3, bug A)**: Original Rev 2 used `sorted(set(genes))[:20]` which picks **alphabetically first** genes, destroying the `mean_interest` ranking signal.

**Problem 3 (Codex #3, bug B)**: Original Rev 2 used `str.contains(...)` on cell type labels containing `+` characters (e.g., `"Myoepi ACTA2+"`), which are regex metacharacters → broadens matching unintentionally.

**Solution** (`generate_enriched_cases.py`):

```python
import re
import pandas as pd

def enrich_case_genes(case: dict, liana_df: pd.DataFrame, target_n: int = 20) -> dict:
    """Augment case with production-equivalent gene context.

    Preserves mean_interest ranking and uses literal (non-regex) matching.
    """
    bundle = case["input_bundle"]
    ligand, receptor = bundle["ligand"], bundle["receptor"]

    # Build a single ranked candidate list
    candidates = []  # [(score, gene), ...] preserves order

    # 1. Core L-R pair (highest priority)
    candidates.append((float("inf"), ligand))
    candidates.append((float("inf"), receptor))

    # 2. Co-expressed genes from same cell types (literal matching, not regex)
    ligand_cts = bundle.get("ligand_cell_types", [])
    if ligand_cts:
        # Use literal containment via apply, not regex
        ct_mask = liana_df["ligand_ctSVG"].fillna("").apply(
            lambda s: any(ct in s for ct in ligand_cts)
        )
        ct_rows = liana_df[ct_mask].nlargest(8, "mean_interest")
        for _, row in ct_rows.iterrows():
            score = float(row["mean_interest"])
            candidates.append((score, str(row["ligand"])))
            candidates.append((score, str(row["receptor"])))

    # 3. Pathway-associated genes (literal matching)
    pathways = bundle.get("pathway_associations", [])
    if pathways:
        pw_mask = liana_df["progeny"].fillna("").apply(
            lambda s: any(pw in s for pw in pathways)
        )
        pw_rows = liana_df[pw_mask].nlargest(5, "mean_interest")
        for _, row in pw_rows.iterrows():
            score = float(row["mean_interest"])
            candidates.append((score, str(row["ligand"])))
            candidates.append((score, str(row["receptor"])))

    # Deduplicate while preserving order, take top-N by score
    candidates.sort(key=lambda x: -x[0])  # descending by score
    seen = set()
    enriched = []
    for _, gene in candidates:
        if gene and gene not in seen:
            enriched.append(gene)
            seen.add(gene)
        if len(enriched) >= target_n:
            break

    case["enriched_genes"] = enriched
    case["enriched_gene_count"] = len(enriched)
    return case
```

**Critical changes from Rev 2**:
1. **Score-ranked deduplication** (not alphabetical) — `candidates.sort(key=lambda x: -x[0])` then iterate in order
2. **Literal containment matching** — `apply(lambda s: any(ct in s for ct in ...))` instead of regex `str.contains`
3. **Score preservation** — `(float("inf"), ligand)` ensures core pair always included

**Verification step** (added to Section 9):
- After generation, sample 5 random cases and verify that:
  - `ligand` and `receptor` are in `enriched_genes`
  - The remaining genes are sourced from cell-type or pathway matches with non-empty `mean_interest`
  - No enriched gene came from a `+`-containing label false-positive

Target: **10-20 genes per case** → `genes_coverage_pct` becomes quasi-continuous (5% increments).

#### 3.4 Trial Runner (Option B+: query_cache bypass, hard JSON failure)

Per trial:
1. Build system prompt (OFF or ON via `build_system_prompt(arm)`)
2. Build user prompt with enriched case evidence bundle
3. LLM generates search plan + query objects (JSON)
4. **Strict JSON parse** — if invalid, retry up to 2 times, then mark trial as `parse_failure` and EXCLUDE from main analysis (Codex finding #2 fix)
5. Execute `search_literature_dynamic(**params, query_cache=query_objects, max_iterations=1, enable_lr_pair_queries=True)` — bypasses inner LLM (`literature.py:2143-2147`) AND matches production SEARCHER's sentinel (`subagents/prompts.py:261`). `max_iterations=1` prevents gap-filling iterations (1+) which would re-invoke the inner LLM via `GAP_FILLING_QUERY_PROMPT`. **Rev 4 side effects of `enable_lr_pair_queries=True`** (`literature.py:2535-2567`): (a) auto-enables `coverage_weighted_sort=True` and `_use_retrieval_tags=True` inside `_calculate_coverage`, (b) bumps internal candidate pool to `max(max_results*5, 300)` before `_greedy_coverage_sort` truncates back to `max_results`, (c) triggers iter-0 keyword-only deterministic pathway fan-out unconditionally. Gene singleton fan-out is still skipped because `query_cache` short-circuits the LLM branch — pathway fan-out is applied uniformly across all 4 conditions so it acts as a baseline, not a confound. **Capture `genes_matched_by` / `pathways_matched_by` dicts from the coverage return** to populate the Rev 4 tag-provenance fields on `SearchTrialResult`. If analyzing paper-level telemetry, treat `query_type="pathway"` as deterministic pathway fan-out and `query_type="keyword"` as generic no-gene retrieval.
6. Record coverage metrics + dependency health metadata

```python
@dataclass
class SearchTrialResult:
    case_id: str
    lr_pair: str
    category: str
    condition: str          # "strong_off", "strong_on", "weak_off", "weak_on"
    model: str              # "qwen3.5:122b" or "qwen3.5:35b"
    harness: str            # "off" or "on"
    repeat: int
    trial_index: int        # global trial index for randomization audit
    timestamp_utc: str      # ISO-8601 timestamp at start of trial
    # Primary endpoint
    coverage_pass: bool = False   # gene ≥ 60% (pathway criterion only when pathways non-empty)
    # Continuous secondary
    genes_coverage_pct: float = 0.0
    pathways_coverage_pct: float | None = None  # None when case has no pathways
    total_papers: int = 0
    iterations: int = 0
    # Process metrics
    llm_gene_list: list = field(default_factory=list)
    llm_query_count: int = 0
    query_objects: list = field(default_factory=list)
    json_parse_attempts: int = 0
    parse_failure: bool = False  # True if all retries failed → excluded from main analysis
    latency_s: float = 0.0
    # Dependency health (Codex finding #4)
    biomcp_latency_ms: float = 0.0
    biomcp_error: str | None = None       # None on success; error code/string on failure
    biomcp_paper_count_raw: int = 0       # Before deduplication, for outage detection
    # Rev 4: retrieval-tag provenance (from _calculate_coverage(use_retrieval_tags=True))
    genes_tag_text_confirmed_pct: float = 0.0   # % of covered genes with biomcp_tag+text_confirmed
    genes_tag_only_pct: float = 0.0             # % of covered genes with biomcp_tag_only (no regex)
    pathways_tag_text_confirmed_pct: float = 0.0
    pathways_tag_only_pct: float = 0.0
    # Rev 4: query composition + candidate pool telemetry
    deterministic_pathway_query_count: int = 0  # Keyword-only deterministic pathway fan-out count (uniform baseline)
    llm_query_count_post_dedup: int = 0         # LLM queries retained after deterministic dedup
    candidate_pool_size: int = 0                # all_papers length pre-truncation (≤300 after sentinel)
    alias_prewarm_latency_ms: float = 0.0       # Gene alias pre-warm wall-clock (Rev 4)
    error: str | None = None
```

**JSON failure policy (P0 fix from Codex #2)**:
```python
async def parse_with_retry(llm, system_prompt, user_prompt, max_attempts=3):
    for attempt in range(max_attempts):
        response = await llm.ainvoke([SystemMessage(system_prompt), HumanMessage(user_prompt)])
        try:
            parsed = json.loads(extract_json_block(response.content))
            assert "search_params" in parsed and "query_objects" in parsed
            assert isinstance(parsed["query_objects"], list) and len(parsed["query_objects"]) > 0
            return parsed, attempt + 1
        except (json.JSONDecodeError, AssertionError, KeyError):
            continue
    return None, max_attempts  # Hard failure
```

If `parse_with_retry` returns `None`:
- Set `parse_failure=True`
- Do NOT call `search_literature_dynamic`
- Do NOT fall back to `search_params`-only mode (this would silently re-enable inner LLM)
- Exclude from main analysis; report parse failure rate per condition as a separate diagnostic

**Why hard failure**: Codex #2 correctly identified that JSON validity may correlate with model strength and harness state. If weak+OFF fails JSON ~30% of the time and we silently fall back to inner LLM, the "harness OFF" measurement becomes contaminated. Hard failure preserves measurement integrity.

#### 3.5 Trial Scheduling: Block Randomization (P1 fix from Codex #4)

**Problem**: Rev 2 ran all 122b trials first (180 trials, ~9h), then all 35b trials (180 trials, ~9h). If BioMCP/PubMed has a transient outage during one of those 9h blocks, model_strength becomes confounded with infrastructure health.

**Solution**: Block-randomized scheduling with model+harness as inner factor and case as outer factor.

```python
import random

def build_trial_schedule(cases, conditions, repeats, seed=42) -> list:
    """Block-randomized schedule: each case sees all conditions in random order before next case."""
    rng = random.Random(seed)
    schedule = []
    for rep in range(repeats):
        for case in cases:
            block = [(case, cond, rep) for cond in conditions]
            rng.shuffle(block)  # randomize within case
            schedule.extend(block)
    return schedule  # Length = cases × conditions × repeats
```

**Ollama VRAM management with block randomization**: Switching between qwen3.5:122b and qwen3.5:35b within a randomized schedule means the model is reloaded frequently. To mitigate:
- **Option α**: Set `keep_alive="24h"` on both models so Ollama keeps them resident in VRAM (`model.py:122`). Requires VRAM for both: ~80GB (122b) + ~24GB (35b) ≈ ~110GB → A100 80GB insufficient, **needs H100 80GB or A100 80GB×2 split**
- **Option β**: Block by case (each case sees all 4 conditions adjacently), with model order randomized per case. Reduces switching from 360 to 30 events.
- **Option γ**: Block by half-day (rotate 122b/35b every 30 trials). Compromise.

**Recommended**: Option β. Per-case randomization preserves the property that "any infrastructure issue affects all 4 conditions equally for that case", which is what we need for valid interaction inference.

**Dependency health logging**: Each trial records:
- `biomcp_latency_ms`: wall-clock time of `search_literature_dynamic` call
- `biomcp_error`: any exception or empty-results flag
- `biomcp_paper_count_raw`: paper count before dedup (zero when BioMCP is degraded)

**Outage detection rule**: If a trial returns `biomcp_paper_count_raw == 0` AND `biomcp_latency_ms > 30s`, flag as `dependency_error` and **exclude from main analysis**. Report dependency error rate per time window in supplementary.

#### 3.6 Checkpoint/Resume

Save JSONL after each trial. On restart, skip completed `(trial_index)` tuples (since trial_index is deterministic from the seeded schedule). Pattern from `benchmark_cci_core.py:986-999`.

#### 3.7 Model Configuration

```python
MODEL_CONFIGS = [
    {"label": "qwen3.5:122b", "provider": "ollama", "model_kwargs": {"model": "qwen3.5:122b", "temperature": 0.3}},
    {"label": "qwen3.5:35b", "provider": "ollama", "model_kwargs": {"model": "qwen3.5:35b", "temperature": 0.3}},
]
```

**Note on `keep_alive`**: `create_ollama_llm` hardcodes `keep_alive="24h"` at `model.py:127` (NOT read from kwargs). We rely on this hardcoded value — do NOT pass `keep_alive` as a kwarg. If VRAM is insufficient to hold both models resident (e.g., single 80GB GPU cannot hold 122b ≈80GB + 35b ≈24GB = 110GB total), we accept ~30s reload latency per model swap; with Option β scheduling, swaps happen at most once per case (30 swaps total, ~15min additional overhead across the full run).

LLM instances are cached at script init; the trial runner picks the right one per trial.

#### 3.8 Option A Validation Arm

Reuse `_run_tool_loop` pattern from `benchmark_skill_harness.py:739-800`, extended to bind `read_skill_file` AND drive a separate runner that calls `search_literature_dynamic` after the LLM signals it's ready.

6 cases (1 per stratum) × 4 conditions × 1 repeat = 24 trials.
Measure same endpoints. Report as Supplementary figure with directional agreement test (sign test on harness effect per case).

**Implementation note**: The existing `_run_tool_loop` only binds `read_skill_file`. Extending it to also bind `search_literature_dynamic` (an async tool with PubMed dependencies) requires either: (a) a separate async tool wrapper, or (b) a two-phase approach where the LLM finishes its planning loop and then we extract its final search plan and execute it. Implement as **separate script** that wraps the full DeepAgent SEARCHER runtime rather than extending the minimal tool loop. Defer to follow-up phase if main B+ is on schedule.

### 4. Statistical Analysis

#### 4.1 Primary: GLMM (Generalized Linear Mixed Model)

Replaces Two-Way ANOVA to handle: (a) clustered repeats within cases, (b) binary primary endpoint.

```r
library(lme4)

# Filter to valid trials (exclude parse_failure and dependency_error)
df_valid <- df[df$parse_failure == FALSE & is.na(df$biomcp_error), ]

# Primary model: coverage_pass as binary outcome
fit_primary <- glmer(
  coverage_pass ~ harness * model_strength + (1|case_id),
  data = df_valid,
  family = binomial
)
summary(fit_primary)

# Interaction test
fit_no_interaction <- glmer(
  coverage_pass ~ harness + model_strength + (1|case_id),
  data = df_valid,
  family = binomial
)
anova(fit_no_interaction, fit_primary)  # LRT
```

Key hypothesis: the `harness:model_strength` interaction coefficient — does harness improve pass rate MORE for weak models?

**MNAR Sensitivity Analysis (parse failures are not necessarily random)**:

Parse failure rates may correlate with both harness state and model strength (e.g., weak+OFF may fail JSON ~25% of the time while strong+ON fails ~2%). Simply excluding `parse_failure=True` trials produces MNAR (Missing Not At Random) bias that attenuates the observed interaction toward null, because the weak+OFF cell's remaining trials are the "easiest" subset where even a weak model with no harness could succeed.

Run a **worst-case imputation sensitivity analysis** alongside the primary model:

```r
# Create imputed dataset: parse failures → worst case
df_all <- df  # All 360 trials, including parse_failure
df_all$coverage_pass_imputed <- ifelse(
  df_all$parse_failure, FALSE, df_all$coverage_pass
)
df_all$genes_coverage_imputed <- ifelse(
  df_all$parse_failure, 0.0, df_all$genes_coverage_pct
)

# Conservative estimate: treat failures as worst-case coverage
fit_conservative <- glmer(
  coverage_pass_imputed ~ harness * model_strength + (1|case_id),
  data = df_all,
  family = binomial
)

# Report both fit_primary (df_valid) and fit_conservative (df_all with imputation)
# If the interaction direction agrees between the two, the MNAR confound is bounded
# and reviewers can trust the interaction claim.
# If they diverge, flag as a sensitivity issue and investigate parse failure patterns.
```

This is standard practice for ablation studies with non-random missing data and pre-empts reviewer concerns about exclusion bias.

#### 4.2 Sensitivity: Linear Mixed Model on genes_coverage_pct

```r
# Only if pilot confirms quasi-continuous distribution (with enriched genes)
fit_lmm <- lmer(
  genes_coverage_pct ~ harness * model_strength + (1|case_id),
  data = df_valid
)
```

#### 4.3 Simple Effects (if interaction significant)
- Harness effect within strong model: estimated marginal mean difference + CI
- Harness effect within weak model: estimated marginal mean difference + CI
- Report Cohen's d for each (using `emmeans::emmeans`)

#### 4.4 Secondary Analyses
- Pathway coverage: Subset analysis on 11 cases with non-empty pathway_associations only
- Bootstrap CI: Case-level resampling (10K iterations), pattern from `compare_expanded.py:365-540`
- Mann-Whitney U: For non-normal distributions as robustness check

#### 4.5 Diagnostic Reports (Codex finding #4)

Report as separate diagnostic tables in supplementary:
- **Parse failure rate per condition**: 2×2 grid showing JSON parse failure rate by harness × model
- **Dependency error rate over time**: Time-series of biomcp_error by trial_index
- **Latency drift**: Mean biomcp_latency_ms per 30-trial window

If parse failure rate exceeds 10% in any condition, flag the experiment for re-evaluation.

**Chi-square parse-failure differential gate**: Even a 5% differential rate across 2×2 cells can bias the interaction estimate. Run a chi-square test on the 2×2 contingency table of parse_failure × condition; if p<0.05, the parse failure pattern is non-uniform and the interaction estimate may be MNAR-biased. In that case, rely on the MNAR sensitivity analysis (Section 4.1) as the primary interpretation.

If dependency error rate is non-uniform across conditions (chi-square test p<0.05), flag potential confounding.

#### 4.6 Pilot Distributional Check (MANDATORY before full run)
After pilot (24 trials):
1. Plot histogram of genes_coverage_pct — verify NOT purely ordinal
2. If clustered at discrete values → switch primary endpoint to coverage_pass
3. Run power analysis for interaction effect based on pilot effect sizes
4. Verify ON arm prompt actually contains inlined skill text
5. Verify parse failure rate < 10% in all conditions (otherwise the JSON output format is too hard)
6. Verify dependency error rate < 5%
7. Report pilot results before committing to 360 trials

### 5. R Visualization

**Figure 4A**: Interaction plot (x=Model Strength, y=Coverage Pass Rate, lines=Harness ON/OFF, error bars=SE)
**Figure 4B**: Continuous coverage (gene_coverage_pct) violin+jitter per condition
**Figure 4C**: Forest plot of simple effects (harness within strong, harness within weak)
**Figure 4D** (Supplementary): Option A vs Option B+ directional agreement
**Figure 4E** (Supplementary): Parse failure + dependency error diagnostics

Style matches `s_figure_table3_results.R`: firebrick3 for ON, gray60 for OFF, theme_bw(), patchwork layout.

### 6. Implementation Sequence

1. Create `docs/benchmarks/harness_x_model/` directory structure
2. Create `prompts/searcher_base.txt` (medium-fidelity OFF prompt)
3. Write `prompts/render_prompts.py` with `build_inlined_skill()` and `build_system_prompt()`
4. Run `render_prompts.py` once → save `prompts/skill_inlined.txt` for inspection; manually verify content
5. Write `generate_enriched_cases.py` with score-preserving + literal-matching logic
6. Run `generate_enriched_cases.py` → `cases/enriched_cases.json`; verify random sample
7. Write `benchmark_harness_x_model.py`: imports, dataclass, constants, MODEL_CONFIGS
8. Implement `parse_with_retry()` with strict JSON validation
9. Implement `build_trial_schedule()` with block randomization (Option β)
10. Implement `run_single_trial()` with `search_literature_dynamic(..., query_cache=qo, max_iterations=1)` and dependency health logging
11. Implement checkpoint/resume + JSONL save
12. Implement CLI (`BENCHMARK_MODE=pilot|full`, `BENCHMARK_MODELS`, `BENCHMARK_REPEATS`)
13. **Run pilot (24 trials) → mandatory checks** (distributional, parse failure rate, dependency health, ON arm prompt verification)
14. Write `analyze_results.py` with GLMM + simple effects + bootstrap CI + diagnostic reports
15. Write `figure_table4_results.R`
16. Implement Option A validation arm (separate script)
17. Run full (360 trials, block-randomized) → generate Table 4 + Figure 4
18. Run Option A arm (24 trials) → Supplementary figure

### 7. Critical Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `docs/benchmarks/harness_x_model/PLAN.md` | **CREATED** | This document (committed for review) |
| `docs/benchmarks/harness_x_model/benchmark_harness_x_model.py` | **CREATE** | Main benchmark script |
| `docs/benchmarks/harness_x_model/generate_enriched_cases.py` | **CREATE** | Precompute enriched gene lists |
| `docs/benchmarks/harness_x_model/analyze_results.py` | **CREATE** | GLMM + bootstrap + diagnostics |
| `docs/benchmarks/harness_x_model/figure_table4_results.R` | **CREATE** | R visualization |
| `docs/benchmarks/harness_x_model/prompts/searcher_base.txt` | **CREATE** | Medium-fidelity OFF prompt |
| `docs/benchmarks/harness_x_model/prompts/render_prompts.py` | **CREATE** | Build OFF/ON prompts |
| `docs/benchmarks/harness_x_model/prompts/skill_inlined.txt` | **GENERATE** | Output of render_prompts.py |
| `docs/benchmarks/harness_x_model/cases/enriched_cases.json` | **GENERATE** | Enriched cases with 10-20 genes |
| `docs/benchmarks/harness_x_model/results/` | **CREATE** | Output directory |

### 8. Reusable Code from Existing Benchmarks

| Component | Source | Lines |
|-----------|--------|-------|
| Tool-calling loop (Option A arm reference) | `benchmark_skill_harness.py` | 739-800 |
| save_json / save_jsonl | `benchmark_cci_core.py` | 986-999 |
| Bootstrap CI | `compare_expanded.py` | 365-540 |
| Case loading | `benchmark_cci_core.py` | 971-983 |
| create_llm("ollama") | `model.py` | 106-142 |
| SkillLoadHarness class (reference for ON arm content) | `skills/skill-load-harness/harness.py` | full file |
| query_cache bypass path | `literature.py` | 2143-2147 |
| _calculate_coverage (legacy path) | `literature.py` | 1557-1636 |
| _build_deterministic_gene_queries (Rev 4) | `literature.py` | ~1319 |
| _build_deterministic_pathway_queries (Rev 4) | `literature.py` | ~1365 |
| Controlled pathway vocabulary | `literature.py` | `PATHWAY_KEYWORDS` |
| _calculate_coverage(use_retrieval_tags=True) tier gate (Rev 4) | `literature.py` | 1793-1862 |
| matched_via_query stamping (Rev 4) | `literature.py` | 509-598 |
| SEARCHER-mode sentinel auto-enable block (Rev 4) | `literature.py` | 2535-2567 |
| Gene alias pre-warm (parallel top-30 + 10s timeout) (Rev 4) | `literature.py` | 2580-2629 |
| Iter-0 gene singleton fan-out (LLM-path only) (Rev 4) | `literature.py` | 2748-2780 |
| Iter-0 keyword-only pathway fan-out (unconditional) | `literature.py` | `_build_deterministic_pathway_queries` call site |
| Deterministic gene query unit tests (Rev 4) | `tests/deep_interpreter/test_deterministic_gene_queries.py` | full file |
| Deterministic pathway query unit tests (Rev 4) | `tests/deep_interpreter/test_deterministic_pathway_queries.py` | full file |
| Evidence manifest / retrieval tag tests (Rev 4) | `tests/deep_interpreter/test_evidence_manifest.py` | full file |
| Post-hoc searcher coverage diagnostics (Rev 4) | `scripts/diagnose_searcher_coverage.py` | full file |
| Searcher-only re-run harness (Rev 4) | `scripts/rerun_searcher_only.py` | full file |

### 9. Verification

1. **Prompt build**: Run `render_prompts.py`; manually inspect `skill_inlined.txt` contains Phase 2-4 content with NO E-utilities references. Token count: OFF ~500, ON ~2.5-3K.
2. **Gene enrichment**: Run `generate_enriched_cases.py`, verify 10-20 genes per case. Sample 5 cases:
   - Confirm ligand+receptor present
   - Confirm remaining genes ranked by `mean_interest` (not alphabetical)
   - Confirm no false positives from `+` chars in cell type labels
   - Confirm pathway-sourced genes are distributed across multiple pathways (no single pathway contributes >80% of enriched genes), catching substring-collision edge cases (e.g., if pathway token "EGFR" accidentally matches "EGFR_signaling" as a substring)
3. **Pilot run**: `BENCHMARK_MODE=pilot python docs/benchmarks/harness_x_model/benchmark_harness_x_model.py`
4. **Distributional check**: Plot genes_coverage_pct histogram — must NOT be purely ordinal {0, 50, 100}
5. **Parse failure check**: Verify JSON parse failure rate < 10% in all 4 conditions
6. **Dependency health check**: Verify biomcp_error rate < 5% across pilot
7. **ON arm content check**: Print system prompt for one ON trial; manually verify Phase 2-4 text is present
8. **query_cache verification**: Confirm `iterations` == 0 in output (single-iteration mode). Note: `think_success` is initialized False at `literature.py:2270` and only set True inside the `if query_cache is None` branch at `:2290`. Because our runner always passes `query_cache`, `think_success` will always be False in our data — it is NOT a reliable bypass indicator. Use `iterations == 0` as the only verification signal.
9. **Coverage sanity**: At least 1 condition shows genes_coverage ≥ 60%
10. **Power analysis**: Based on pilot effect sizes, compute required N for interaction detection
11. **Full run**: `BENCHMARK_MODE=full python docs/benchmarks/harness_x_model/benchmark_harness_x_model.py`
12. **Block randomization audit**: After full run, verify trial_index ordering shows model+harness conditions are interleaved (not blocked by model)
13. **Option A arm**: Validate directional agreement with Option B+ results
14. **Figure**: `Rscript docs/benchmarks/harness_x_model/figure_table4_results.R`
15. **Statistical**: GLMM interaction p-value + bootstrap CI exclude 0

### 10. Risks

| Risk | Mitigation |
|------|-----------|
| PubMed/BioMCP API downtime during run | Checkpoint/resume + dependency health logging + outage detection rule (exclude `biomcp_paper_count_raw==0` AND `biomcp_latency_ms>30s` from analysis) |
| Ollama OOM with both models keep-alive | Option β (per-case randomization) reduces reloads to 30; if OOM, fall back to Option γ (half-day rotation) |
| 19/30 cases have empty pathway_associations | pathway_coverage_pct=None for those cases; coverage_pass uses gene-only criterion |
| LLM generates unparseable JSON query objects | **Hard failure** (no inner-LLM fallback). Retry up to 3 times then mark `parse_failure=True` and exclude. Report parse failure rate per condition as diagnostic. |
| Temperature=0.3 variance too low for repeats | Can increase to 0.5 if pilot shows no variance |
| Double-LLM confound on iteration 0 | query_cache bypass eliminates inner LLM (literature.py:2143-2147) |
| Double-LLM confound on iterations 1+ | `max_iterations=1` prevents gap-filling iterations entirely |
| Floor effect from too few genes | Enriched gene lists (10-20 per case) via generate_enriched_cases.py with score preservation |
| Non-independence of repeats | GLMM with (1\|case_id) random intercept handles clustering |
| Ordinal DV if enrichment insufficient | Primary endpoint is coverage_pass (binary); GLMM with family=binomial |
| Option B+ lacks ecological validity | Option A validation arm (24 trials) as Supplementary |
| **NEW**: ON arm doesn't actually receive skill content | Inlined SKILL.md Phase 2-4 text directly into system prompt; verified via prompt content check (verification step 7) |
| **NEW**: model_strength confounded with infrastructure | Block-randomized scheduling (Option β); per-trial dependency health metadata; outage detection rule |
| **NEW**: Enrichment alphabetical-sort bug | Score-ranked dedup via sorted candidates list (Section 3.3) |
| **NEW**: Enrichment regex-metachar bug | Literal containment via `apply(lambda s: any(...))` instead of `str.contains(...)` |
| **NEW**: Inlined skill points to E-utilities | Strip E-utilities section from inlined content (Section 3.2 step 3) |
| **NEW**: Inlined skill references `think_success` / `rerank_mode="llm"` (dead instructions) | Strip those sections from inlined content (Section 3.2 steps 5-6); hardcode `rerank_mode="off"` in Section 3.4 |
| **NEW**: VRAM < 110GB single-GPU — keep_alive OOM on both models | Option β scheduling reduces swaps to 30 per case; accept ~30s reload latency per swap (~15min total overhead); `keep_alive` is hardcoded at `model.py:127` and cannot be overridden via kwargs |
| **NEW**: MNAR bias from parse_failure exclusion | Worst-case imputation sensitivity analysis (Section 4.1) + chi-square parse-failure differential gate (Section 4.5) |
| **Rev 4**: Ceiling effect from deterministic pathway fan-out saturates primary endpoint | Pilot ceiling-effect gate (§4.6 step 8 per Rev 4 Delta): abort full run if `strong_on` AND `strong_off` both ≥95% coverage. Fallbacks: (a) switch primary endpoint to tag-confirmed-only coverage / unique-PMID diversity, or (b) degrade to `enable_lr_pair_queries=False` at cost of ecological validity |
| **Rev 4**: `query_cache` skips gene singleton fan-out while Option A arm receives it → asymmetric retrieval baselines | Accept asymmetry as intentional — Option B+ measures LLM query-enrichment quality, Option A measures full production SEARCHER. Use sign-test on directional agreement (not magnitude) across the two arms. Report both `genes_tag_text_confirmed_pct` and `genes_tag_only_pct` so readers can see the tag-credit contribution separately |
| **Rev 4**: BioMCP gene alias pre-warm adds ~10-30s per trial | 360 trials × 20s ≈ 2h extra wall-clock — acceptable within 18h budget. Log `alias_prewarm_latency_ms` per trial. On BioMCP outage the cache degrades to empty (no-op) rather than blocking. Use `_bounded_fetch` per-gene 10s timeout from `literature.py:2599` |
| **Rev 4**: 300-paper internal candidate pool balloons `search_literature_dynamic` wall-clock | Expected: ~2-4× per-trial latency vs Rev 3 baseline due to larger candidate pool + unconditional pathway fan-out + alias pre-warm. Reuse checkpoint/resume from §3.6 to survive interruptions. If pilot shows >5min/trial, lower the final `max_results` cap (the internal 300-floor still protects coverage quality) |
