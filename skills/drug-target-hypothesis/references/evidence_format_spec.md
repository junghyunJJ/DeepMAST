# Evidence Data Format Specification

This document defines the schema for all evidence files consumed by the drug-target-hypothesis skill.

## Directory Structure

```text
{data_dir}/evidence/
├── rubric_scores.csv           # Gene-level rubric scores (REQUIRED)
├── assessment_results.json     # Full rubric assessment with metadata (REQUIRED)
├── stage2_evidence.json        # OpenTargets data per gene (REQUIRED)
├── stage1_filter_results.json  # Stage 1 pass/fail sidecar for deterministic gates
├── stage1_{LIGAND}--{RECEPTOR}.json  # Per L-R pair evidence
├── stage3_{GENE}.json          # Per gene deep-dive (FEATURED only)
├── ot_{GENE}.json              # OpenTargets detailed per-gene data
├── known_drugs.json            # Disease-level drug landscape
└── gene_manifest.json          # Gene list with selection flags
```

## Required Files

### rubric_scores.csv

Tabular scoring for assessed genes. One row per gene. This CSV is a supporting artifact for humans and downstream tooling; the hypothesis writer itself operates on hypothesis-scope JSON evidence and should not treat this CSV as a citation source.

| Column | Type | Description |
|--------|------|-------------|
| `gene` | string | Gene symbol (e.g., "TGFB1") |
| `existing_drug_evidence` | int | Existing drug evidence score; may be negative when disease-level evidence outweighs target-level support |
| `clinical_trial_activity` | int | Clinical activity score for the target |
| `safety_profile` | int | Safety and toxicity score; negative values indicate concerns |
| `validated_total` | int | Sum of validated track scores |
| `gwas_support` | int | GWAS and genetic evidence score |
| `tractability` | int | Drug tractability score |
| `biological_plausibility` | int | Biological plausibility score |
| `novelty_opportunity` | int | Novelty and opportunity score |
| `exploratory_total` | int | Sum of exploratory track scores |
| `combined_total` | int | validated_total + exploratory_total |
| `classification` | string | One of: "validated_target", "exploratory_target", "novel_candidate", "insufficient_evidence" |
| `priority` | string | One of: "high", "medium", "low", "unranked" |
| `stage3_candidate` | bool | Whether the gene remains in the post-filter Stage 3 candidate set |

### assessment_results.json

Full rubric assessment with metadata. Contains `assessment_date`, `disease`, and `rubric_assessment` array with the same fields as rubric_scores.csv plus:

| Field | Type | Description |
|-------|------|-------------|
| `ot_disease_evidence_count` | int | OpenTargets disease evidence count |
| `ot_associations_count` | int | OpenTargets disease associations count |

### stage2_evidence.json

Per-gene OpenTargets data. Top-level keys are gene symbols. Each gene has:

```json
{
  "GENE_SYMBOL": {
    "opentargets": {
      "gene_symbol": "string",
      "disease": "string",
      "executed": true,
      "ensembl_id": "string",
      "target_info": {
        "id": "string",
        "approvedSymbol": "string",
        "approvedName": "string",
        "biotype": "string",
        "functionDescriptions": ["string"],
        "tractability": [
          {"modality": "SM|AB|PR|OC", "id": "string", "value": true|false}
        ]
      },
      "disease_association": {
        "score": 0.0-1.0,
        "evidenceCount": int
      },
      "genetic_association": {...},
      "safety_liabilities": [...]
    }
  }
}
```

**Tractability modalities:**
- `SM` = Small molecule
- `AB` = Antibody
- `PR` = Protein replacement (e.g., recombinant protein)
- `OC` = Other clinical (PROTAC, oligonucleotide, etc.)

### stage1_filter_results.json

Stage 1 deterministic pass/fail sidecar used by the hypothesis writer. This file is written as a JSON array of rows that mirrors the Stage 1 filter CSV.

```json
[
  {
    "ligand": "string",
    "receptor": "string",
    "passed": true,
    "string_combined": 0.0,
    "string_status": "in_db|no_record",
    "census_coexpr_pvalue": 0.0,
    "census_gene_a_pvalue": 0.0,
    "census_gene_b_pvalue": 0.0,
    "gene_a_target_pct": 0.0,
    "gene_a_risk_ratio": 0.0,
    "gene_b_target_pct": 0.0,
    "gene_b_risk_ratio": 0.0,
    "coexpr_target_pct": 0.0,
    "coexpr_risk_ratio": 0.0
  }
]
```

Interpretation:
- `passed = true` means the pair cleared the strict Stage 1 gate
- `passed = false` means the pair may be cited only as contrast evidence with the `_FAILED` suffix

The strict pass rule requires:
- STRING combined score above 0.8
- coexpression p-value below 0.05
- gene A p-value below 0.05
- gene B p-value below 0.05

## Optional Files

### stage1_{LIGAND}--{RECEPTOR}.json

Per L-R pair biological context validation. The exact file may contain additional metadata, but the active Stage 1 filter reads the fields below.

```json
{
  "ligand": "string",
  "receptor": "string",
  "disease": "string",
  "stage1_status": "completed|failed",
  "cellxgene_context": {
    "cell_count": int,
    "disease_matched": true|false,
    "top_cell_types": [
      {"cell_type": "string", "count": int}
    ]
  },
  "census_validation": {
    "target_vs_rest": {
      "coexpression": {
        "p_value": float,
        "risk_ratio": float,
        "target_pct": float
      },
      "gene_a": {
        "p_value": float,
        "risk_ratio": float,
        "target_pct": float
      },
      "gene_b": {
        "p_value": float,
        "risk_ratio": float,
        "target_pct": float
      }
    }
  },
  "stage1_filter": {
    "passed": true|false,
    "string_combined": float,
    "string_status": "in_db|no_record"
  },
  "string_ppi": {
    "interaction_found": true|false,
    "max_combined_score": float (0-1),
    "p_value": float
  },
  "kegg_pathways": {
    "ligand_pathways": [{"name": "string", "pathway_id": "string"}],
    "receptor_pathways": [{"name": "string", "pathway_id": "string"}]
  },
  "reactome_pathways": {
    "ligand_pathways": [{"name": "string", "reactome_id": "string"}],
    "receptor_pathways": [{"name": "string", "reactome_id": "string"}]
  }
}
```

**Key interpretation guidelines:**
- `census_validation.target_vs_rest.coexpression.risk_ratio` above 5.0 indicates strong disease-specific coexpression
- `census_validation.target_vs_rest.coexpression.p_value` below 1e-10 indicates statistically significant coexpression
- `string_ppi.max_combined_score` above 0.9 indicates high-confidence physical interaction
- Shared pathways between ligand and receptor suggest functional coupling

### stage3_{GENE}.json

Per-gene deep-dive for FEATURED candidates.

```json
{
  "gene_symbol": "string",
  "disease": "string",
  "stage3_status": "completed|failed",
  "chembl_drugs": [
    {
      "chembl_id": "string",
      "drug_name": "string",
      "indications": [
        {"efo_term": "string", "max_phase": "string"}
      ],
      "mechanism_of_action": "string|null"
    }
  ],
  "pubmed_papers": [
    {"pmid": "string", "title": "string"}
  ]
}
```

### ot_{GENE}.json

Detailed OpenTargets data per gene. Same structure as stage2_evidence.json entries but as standalone files.

### known_drugs.json

Disease-level drug landscape.

```json
{
  "disease": "string",
  "executed": true,
  "efo_id": "string",
  "drugs": {
    "uniqueDrugs": int,
    "uniqueTargets": int,
    "rows": [
      {
        "drug": {
          "id": "string",
          "name": "string",
          "drugType": "string|null",
          "maximumClinicalTrialPhase": int (1-4)
        },
        "target": {
          "id": "string",
          "approvedSymbol": "string"
        },
        "phase": int,
        "status": "string|null",
        "mechanismOfAction": "string|null"
      }
    ]
  }
}
```

### gene_manifest.json

Array of gene entries with selection flags.

```json
[
  {"symbol": "string", "is_selected_top3": true|false}
]
```

## Excluded From Citations

The following files are not valid hypothesis citations in hypothesis scope:
- `hypothesis_report.json`
- `target_assessment.json`
- `stage1_audit.json`
- `stage1_confidence.json`
- `stage1_evidence.json`

`load_evidence_files(data_dir, scope="hypothesis")` may also stub or exclude:
- stale prior-run `stage3_*.json`
- non-featured `ot_*.json`
- FAILED Stage 1 pair files, which may appear only as slim contrast stubs

## Drug Report Markdown

The drug report (e.g., `drug.md` or `tmp_drug.md`) in the parent directory provides a human-readable synthesis. Key sections to extract:

- **Executive Summary**: FEATURED and NOVEL candidate lists with scores
- **Pan-Disease Target Druggability Matrix**: All L-R pairs ranked with OT scores, clinical phases, genetic flags, tractability
- **[FEATURED] Deep Dives**: Per-gene Stage 3 analysis with clinical/safety profiles, pathway context, rubric scores
- **[NOVEL] Candidate Deep Dives**: Emerging candidates with rationale
