# Evidence Data Format Specification

This document defines the schema for all evidence files consumed by the drug-target-hypothesis skill.

## Directory Structure

```
{data_dir}/evidence/
├── rubric_scores.csv           # Gene-level rubric scores (REQUIRED)
├── assessment_results.json     # Full rubric assessment with metadata (REQUIRED)
├── stage2_evidence.json        # OpenTargets data per gene (REQUIRED)
├── stage1_{LIGAND}--{RECEPTOR}.json  # Per L-R pair evidence
├── stage3_{GENE}.json          # Per gene deep-dive (FEATURED only)
├── ot_{GENE}.json              # OpenTargets detailed per-gene data
├── known_drugs.json            # Disease-level drug landscape
└── gene_manifest.json          # Gene list with selection flags
```

## Required Files

### rubric_scores.csv

Tabular scoring for all assessed genes. One row per gene.

| Column | Type | Description |
|--------|------|-------------|
| `gene` | string | Gene symbol (e.g., "TGFB1") |
| `existing_drug_evidence` | int | Score for existing drugs targeting this gene (-3 to 3) |
| `clinical_trial_activity` | int | Score for active clinical trials (-3 to 3) |
| `mechanism_relevance` | int | Score for disease mechanism relevance (-3 to 3) |
| `safety_profile` | int | Score for safety/toxicity concerns (-3 to 3, negative = concerns) |
| `validated_total` | int | Sum of validated track scores |
| `gwas_support` | int | GWAS/genetic evidence score (0-3) |
| `tractability` | int | Drug tractability score (0-3) |
| `biological_plausibility` | int | Biological plausibility score (0-3) |
| `novelty_opportunity` | int | Novelty/opportunity score (0-3) |
| `exploratory_total` | int | Sum of exploratory track scores |
| `combined_total` | int | validated_total + exploratory_total |
| `classification` | string | One of: "exploratory_target", "validated_target", "insufficient_evidence" |
| `priority` | string | One of: "high", "medium", "low", "unranked" |
| `stage3_candidate` | bool | Whether gene advanced to Stage 3 deep-dive |

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

## Optional Files

### stage1_{LIGAND}--{RECEPTOR}.json

Per L-R pair biological context validation.

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
  "census_cross_validation": {
    "census_version": "string",
    "coexpression_diff": float,
    "coexpression_p_value": float,
    "coexpression_risk_ratio": float,
    "gene_a_diff": float,
    "gene_a_p_value": float,
    "gene_a_risk_ratio": float,
    "gene_a_target_pct": float,
    "gene_b_diff": float,
    "gene_b_p_value": float,
    "gene_b_risk_ratio": float,
    "resolved_cell_type": "string",
    "target_cell_type": "string"
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
- `coexpression_risk_ratio` > 5.0 indicates strong disease-specific coexpression
- `coexpression_p_value` < 1e-10 indicates statistically significant coexpression
- `string_ppi.max_combined_score` > 0.9 indicates high-confidence physical interaction
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

## Drug Report Markdown

The drug report (e.g., `drug.md` or `tmp_drug.md`) in the parent directory provides a human-readable synthesis. Key sections to extract:

- **Executive Summary**: FEATURED and NOVEL candidate lists with scores
- **Pan-Disease Target Druggability Matrix**: All L-R pairs ranked with OT scores, clinical phases, genetic flags, tractability
- **[FEATURED] Deep Dives**: Per-gene Stage 3 analysis with clinical/safety profiles, pathway context, rubric scores
- **[NOVEL] Candidate Deep Dives**: Emerging candidates with rationale
