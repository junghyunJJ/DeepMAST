# Drug Profile Enrichment MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich deterministic `drug.md` Drug Profile sections with OpenTargets clinical compound tables, matching the `res_ipf_ollama/drug.md` shape, without using an LLM.

**Architecture:** Keep the MVP finalizer no-LLM and template-driven. Extend `report_data` candidate drug records with a deterministic union of OpenTargets target drugs and ChEMBL Stage 3 records; render OpenTargets records into `**Clinical Compounds (OpenTargets):**` and ChEMBL-only records into `**Preclinical Compounds (ChEMBL Bioactivity):**` through the existing `drug_report.md.j2` template.

**Tech Stack:** Python, pytest, pyright, Jinja2, existing `src.agents.drug_target.deterministic_report`, evidence JSON files under `data_dir/evidence`.

---

## Source Evidence Contract

Use these local files only:

- `evidence/ot_<GENE>.json`
  - Primary source for OpenTargets clinical compounds.
  - Read `target_drugs.rows`.
  - Each row has `drug.id`, `maxClinicalStage`, and `diseases[*].disease.name`.
- `evidence/resolved_drugs.json`
  - Optional enrichment source for resolved drug name, molecule type, first approval, mechanism of action.
  - Match rows by `gene` and `chembl_id`.
- `evidence/stage3_<GENE>.json`
  - Existing ChEMBL bioactivity/preclinical source.
  - Continue reading `chembl.matched_drugs` and related ChEMBL containers.

Do not use `known_drugs.json` for target-specific Drug Profile enrichment in this MVP. It is disease-level and can contain drugs for targets outside the featured gene set.

## File Structure

- Modify `src/agents/drug_target/deterministic_report.py`
  - Add deterministic OpenTargets clinical drug extraction.
  - Preserve current ChEMBL extraction as preclinical/Stage 3 evidence.
  - Add source metadata for `ot_<GENE>.json` and `resolved_drugs.json`.
  - Keep `render_report_markdown()` template-driven.

- Modify `tests/agents/drug_target/test_deterministic_report_mvp.py`
  - Add fixture-injection tests because the baseline fixture lacks `ot_*.json` and `resolved_drugs.json`.
  - Prove OpenTargets clinical compounds render as a markdown table.
  - Prove genes with OpenTargets drugs no longer say `No known drugs targeting this gene`.

## Behavioral Contract

For a featured gene with OpenTargets `target_drugs.rows`, generated `drug.md` must contain:

```markdown
**Clinical Compounds (OpenTargets):**

| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |
|------|-----------|---------------------|------:|-------------|
| **OCRIPLASMIN** | CHEMBL2095222 | Collagen hydrolytic enzyme \| Fibronectin proteolytic enzyme \| Laminin hydrolytic enzyme | 4 | macular degeneration, eye disease |
```

For a featured gene with no OpenTargets rows and no ChEMBL records, generated `drug.md` may still contain:

```markdown
- No known drugs targeting this gene
```

For a featured gene with both sources, generated `drug.md` should include both:

```markdown
**Clinical Compounds (OpenTargets):**
...
**Preclinical Compounds (ChEMBL Bioactivity):**
...
```

## Task 1: Add Failing Test For OpenTargets Clinical Table Rendering

**Files:**

- Modify: `tests/agents/drug_target/test_deterministic_report_mvp.py`

- [ ] **Step 1: Add a helper that injects minimal OpenTargets drug evidence**

Add this helper below `_copy_baseline_workspace`:

```python
def _write_opentargets_drug_evidence(workspace: Path, gene: str = "FN1") -> None:
    evidence = workspace / "evidence"
    (evidence / f"ot_{gene}.json").write_text(
        json.dumps(
            {
                "gene_symbol": gene,
                "target_drugs": {
                    "count": 2,
                    "rows": [
                        {
                            "maxClinicalStage": 4,
                            "drug": {
                                "id": "CHEMBL2095222",
                                "name": "CHEMBL2095222",
                                "maximumClinicalStage": 4,
                            },
                            "diseases": [
                                {"disease": {"name": "macular degeneration"}},
                                {"disease": {"name": "eye disease"}},
                            ],
                        },
                        {
                            "maxClinicalStage": 1,
                            "drug": {
                                "id": "CHEMBL2109412",
                                "name": "CHEMBL2109412",
                                "maximumClinicalStage": 1,
                            },
                            "diseases": [
                                {"disease": {"name": "cancer"}},
                            ],
                        },
                    ],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (evidence / "resolved_drugs.json").write_text(
        json.dumps(
            [
                {
                    "gene": gene,
                    "chembl_id": "CHEMBL2095222",
                    "resolved_name": "OCRIPLASMIN",
                    "molecule_type": "Enzyme",
                    "max_phase": 4,
                    "first_approval": 2012,
                    "mechanism_of_action": (
                        "Collagen hydrolytic enzyme | Fibronectin proteolytic enzyme"
                    ),
                    "source": "opentargets",
                },
                {
                    "gene": gene,
                    "chembl_id": "CHEMBL2109412",
                    "resolved_name": "L19SIP 131I",
                    "molecule_type": "Protein",
                    "max_phase": 1,
                    "first_approval": None,
                    "mechanism_of_action": "Fibronectin other",
                    "source": "opentargets",
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
```

- [ ] **Step 2: Add the failing markdown-rendering test**

Add this test after `test_report_mvp_markdown_uses_drug_target_reporting_template`:

```python
def test_report_mvp_drug_profile_renders_opentargets_clinical_table(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    _write_opentargets_drug_evidence(workspace, "FN1")

    markdown = render_report_markdown(
        build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    )
    fn1_section = markdown.split("### FN1", 1)[1].split("---", 1)[0]

    assert "**Clinical Compounds (OpenTargets):**" in fn1_section
    assert "| Drug | ChEMBL ID | Mechanism of Action | Phase | Indications |" in fn1_section
    assert "| **OCRIPLASMIN** | CHEMBL2095222 | Collagen hydrolytic enzyme \\| Fibronectin proteolytic enzyme | 4 | macular degeneration, eye disease |" in fn1_section
    assert "| **L19SIP 131I** | CHEMBL2109412 | Fibronectin other | 1 | cancer |" in fn1_section
    assert "- No known drugs targeting this gene" not in fn1_section
```

- [ ] **Step 3: Run the new test and verify RED**

Run:

```bash
pytest tests/agents/drug_target/test_deterministic_report_mvp.py::test_report_mvp_drug_profile_renders_opentargets_clinical_table -q
```

Expected:

```text
FAILED ... assert '**Clinical Compounds (OpenTargets):**' in fn1_section
```

## Task 2: Add Report Data Test For Clinical/Preclinical Split

**Files:**

- Modify: `tests/agents/drug_target/test_deterministic_report_mvp.py`

- [ ] **Step 1: Add a failing report-data structure test**

Add this test after the markdown clinical table test:

```python
def test_report_mvp_report_data_splits_clinical_and_preclinical_drugs(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data

    workspace = _copy_baseline_workspace(tmp_path)
    _write_opentargets_drug_evidence(workspace, "FN1")

    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )
    fn1 = next(c for c in report_data["candidates"] if c["gene"] == "FN1")

    assert fn1["clinical_drug_count"] == 2
    assert fn1["preclinical_drug_count"] == 0
    assert fn1["drug_count"] == 2
    assert fn1["clinical_drugs"][0] == {
        "name": "OCRIPLASMIN",
        "chembl_id": "CHEMBL2095222",
        "phase": 4,
        "first_approval": 2012,
        "mechanism_of_action": (
            "Collagen hydrolytic enzyme | Fibronectin proteolytic enzyme"
        ),
        "indications": ["macular degeneration", "eye disease"],
        "source": "opentargets",
    }
    assert "evidence/ot_FN1.json" in fn1["sources"]
    assert "evidence/resolved_drugs.json" in fn1["sources"]
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
pytest tests/agents/drug_target/test_deterministic_report_mvp.py::test_report_mvp_report_data_splits_clinical_and_preclinical_drugs -q
```

Expected:

```text
FAILED ... KeyError: 'clinical_drug_count'
```

## Task 3: Implement OpenTargets Clinical Drug Extraction

**Files:**

- Modify: `src/agents/drug_target/deterministic_report.py`

- [ ] **Step 1: Add resolved-drug lookup helpers**

Add these helpers near existing drug helpers:

```python
def _resolved_drug_lookup(base: Path) -> dict[tuple[str, str], dict[str, Any]]:
    path = base / "evidence" / "resolved_drugs.json"
    if not path.exists():
        return {}
    payload = _load_json(path)
    rows = payload if isinstance(payload, list) else []
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        gene = _normalize_gene(row.get("gene"))
        chembl_id = _safe_text(row.get("chembl_id"), "").upper()
        if gene and chembl_id:
            lookup[(gene, chembl_id)] = row
    return lookup
```

```python
def _disease_names(row: dict[str, Any]) -> list[str]:
    diseases = row.get("diseases", [])
    names: list[object | None] = []
    if isinstance(diseases, list):
        for item in diseases:
            if not isinstance(item, dict):
                continue
            disease = item.get("disease")
            if isinstance(disease, dict):
                names.append(disease.get("name"))
            names.append(item.get("diseaseFromSource"))
    return _dedupe_strings(names)
```

- [ ] **Step 2: Add OpenTargets row extraction**

Add:

```python
def _clinical_drugs_from_opentargets(
    base: Path,
    gene: str,
    resolved_lookup: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    path = base / "evidence" / f"ot_{gene}.json"
    if not path.exists():
        return [], []
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return [], [f"evidence/ot_{gene}.json"]
    target_drugs = payload.get("target_drugs")
    rows = target_drugs.get("rows") if isinstance(target_drugs, dict) else []
    if not isinstance(rows, list):
        return [], [f"evidence/ot_{gene}.json"]

    drugs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        drug = row.get("drug")
        if not isinstance(drug, dict):
            continue
        chembl_id = _safe_text(drug.get("id"), "").upper()
        if not chembl_id or chembl_id in seen:
            continue
        seen.add(chembl_id)
        resolved = resolved_lookup.get((gene, chembl_id), {})
        phase = row.get("maxClinicalStage") or drug.get("maximumClinicalStage")
        drugs.append(
            {
                "name": _safe_text(
                    resolved.get("resolved_name") or drug.get("name"),
                    chembl_id,
                ),
                "chembl_id": chembl_id,
                "phase": phase,
                "first_approval": resolved.get("first_approval"),
                "mechanism_of_action": resolved.get("mechanism_of_action"),
                "indications": _disease_names(row),
                "source": "opentargets",
            }
        )
    return drugs, [f"evidence/ot_{gene}.json"]
```

- [ ] **Step 3: Split ChEMBL records as preclinical**

Rename or wrap the existing `_drug_records_from_stage3()` result as preclinical records. Keep the existing record shape, but add `"source": "chembl"` to each ChEMBL record:

```python
drugs.append(
    {
        "name": name,
        "chembl_id": str(
            record.get("chembl_id")
            or record.get("molecule_chembl_id")
            or ""
        ).strip(),
        "phase": record.get("max_phase"),
        "first_approval": record.get("first_approval"),
        "mechanism_of_action": record.get("mechanism_of_action"),
        "indications": _dedupe_strings(indications),
        "source": "chembl",
    }
)
```

- [ ] **Step 4: Use the union in `build_report_data()`**

At the start of `build_report_data()` after `selected_genes`:

```python
resolved_lookup = _resolved_drug_lookup(base)
resolved_path = base / "evidence" / "resolved_drugs.json"
```

Inside the candidate loop, replace the current single `drugs` list with:

```python
clinical_drugs, clinical_sources = _clinical_drugs_from_opentargets(
    base,
    gene,
    resolved_lookup,
)
preclinical_drugs: list[dict[str, Any]] = []
if stage3_path.exists():
    sources.append(f"evidence/stage3_{gene}.json")
    preclinical_drugs = _drug_records_from_stage3(_load_json(stage3_path))
sources.extend(source for source in clinical_sources if source not in sources)
if clinical_drugs and resolved_path.exists():
    sources.append("evidence/resolved_drugs.json")
drugs = clinical_drugs + preclinical_drugs
```

Update the candidate dict:

```python
"clinical_drug_count": len(clinical_drugs),
"preclinical_drug_count": len(preclinical_drugs),
"drug_count": len(drugs),
"clinical_drugs": clinical_drugs,
"preclinical_drugs": preclinical_drugs,
"drugs": drugs,
```

- [ ] **Step 5: Run Task 2 test and verify GREEN**

Run:

```bash
pytest tests/agents/drug_target/test_deterministic_report_mvp.py::test_report_mvp_report_data_splits_clinical_and_preclinical_drugs -q
```

Expected:

```text
1 passed
```

## Task 4: Feed Clinical/Preclinical Split Into The Markdown Template

**Files:**

- Modify: `src/agents/drug_target/deterministic_report.py`

- [ ] **Step 1: Update `_markdown_template_context()`**

In the featured-card loop, stop deriving clinical/preclinical solely from `candidate["drugs"]`. Use explicit split fields:

```python
clinical = [
    _template_drug(drug)
    for drug in _dict_list(candidate.get("clinical_drugs", []))
]
preclinical = [
    _template_drug(drug)
    for drug in _dict_list(candidate.get("preclinical_drugs", []))
]
if not clinical and not preclinical:
    clinical, preclinical = _split_template_drugs(_dict_list(candidate.get("drugs", [])))
```

- [ ] **Step 2: Preserve pipe escaping behavior**

No template change is required. `drug_report.md.j2` already renders clinical MoA as:

```jinja2
{{ d.moa | replace('|', '\|') }}
```

- [ ] **Step 3: Run Task 1 test and verify GREEN**

Run:

```bash
pytest tests/agents/drug_target/test_deterministic_report_mvp.py::test_report_mvp_drug_profile_renders_opentargets_clinical_table -q
```

Expected:

```text
1 passed
```

## Task 5: Validate Against Real OpenAI Run Data

**Files:**

- No code files if previous tasks pass.
- Writes runtime artifacts under `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_ipf_openai_tmp`.

- [ ] **Step 1: Regenerate actual report artifacts**

Run:

```bash
python - <<'PY'
import asyncio
import json
import os
from pathlib import Path

from src.agents.drug_target.deterministic_report import finalize_report_mvp

for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "LLM_PROVIDER"):
    os.environ.pop(name, None)

base = Path("/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_ipf_openai_tmp")
result = asyncio.run(finalize_report_mvp({"data_dir": str(base), "disease": "idiopathic pulmonary fibrosis"}, {}))
markdown = (base / "drug.md").read_text(encoding="utf-8")
report_data = json.loads((base / "report_data.json").read_text(encoding="utf-8"))
validation = json.loads((base / "report_validation.json").read_text(encoding="utf-8"))
print("result", result)
print("validation_valid", validation["valid"])
for gene in ("MUC1", "FN1", "CD4", "ITGB2", "CD47", "ICAM1"):
    section = markdown.split(f"### {gene}", 1)[1].split("---", 1)[0]
    candidate = next(c for c in report_data["candidates"] if c["gene"] == gene)
    print(gene, candidate["clinical_drug_count"], candidate["preclinical_drug_count"], "**Clinical Compounds (OpenTargets):**" in section)
PY
```

Expected output includes:

```text
result {'report_finalization_error': None, 'evidence_truncated': False}
validation_valid True
MUC1 5 0 True
FN1 5 0 True
CD4 5 10 True
ITGB2 1 10 True
CD47 2 0 True
ICAM1 2 10 True
```

- [ ] **Step 2: Inspect representative markdown sections**

Run:

```bash
rg -n "\*\*Clinical Compounds \(OpenTargets\):\*\*|OCRIPLASMIN|CANTUZUMAB|IBALIZUMAB|LIFITEGRAST|MAGROLIMAB|ALICAFORSEN" /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_ipf_openai_tmp/drug.md -C 2
```

Expected:

```text
Clinical Compounds (OpenTargets) tables appear for all six featured candidates, with resolved names rather than bare ChEMBL IDs.
```

## Task 6: Full Verification

**Files:**

- No new files.

- [ ] **Step 1: Run MVP tests**

Run:

```bash
pytest tests/agents/drug_target/test_deterministic_report_mvp.py -q
```

Expected:

```text
9 passed
```

- [ ] **Step 2: Run type checking**

Run:

```bash
pyright src/agents/drug_target/deterministic_report.py tests/agents/drug_target/test_deterministic_report_mvp.py
```

Expected:

```text
0 errors, 0 warnings, 0 informations
```

- [ ] **Step 3: Run existing renderer/validator regression tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_renderer.py tests/agents/drug_target/test_finalization_validator.py -q
```

Expected:

```text
40 passed
```

- [ ] **Step 4: Confirm legacy finalizer files remain untouched**

Run:

```bash
git diff -- src/agents/drug_target/finalize_report.py src/agents/drug_target/agent.py src/agents/drug_target/subagents/configs.py
```

Expected:

```text
<no output>
```

## Self-Review

- Spec coverage: The plan covers deterministic OpenTargets clinical table rendering, report-data source split, real-data validation, no-LLM execution, and legacy finalizer isolation.
- Placeholder scan: No TBD/TODO/fill-later placeholders remain.
- Type consistency: The plan uses `clinical_drugs`, `preclinical_drugs`, `clinical_drug_count`, and `preclinical_drug_count` consistently from `report_data` through template context.
