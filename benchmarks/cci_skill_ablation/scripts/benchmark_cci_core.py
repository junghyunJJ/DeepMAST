"""CCI Skill Ablation Benchmark V2 — Open-ended generation + Dual LLM Judge.

Tests whether structured SKILL.md instruction reduces hallucination
in L-R pair biological interpretation from spatial transcriptomics CCI analysis.

Four conditions:
  A_no_skill:              Bare interpretation prompt only
  B_unstructured_prose:    Same hallucination-prevention content, in plain prose
  C_structured_skill:      Structured markdown with sections, rules, hierarchy
  D_guide_compliant_skill: C + Anthropic Skill Guide patterns (examples, edge cases, self-check)

V2 changes from V1:
  - Free-text generation instead of MCQ probes
  - Dual LLM Judge (rubric-based) instead of deterministic scoring
  - Cohen's kappa for inter-rater agreement
  - Composite hallucination score as primary endpoint
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import math

from langchain_core.messages import HumanMessage, SystemMessage

try:
    from scipy.stats import kruskal, mannwhitneyu
except ImportError:
    kruskal = None
    mannwhitneyu = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.model import create_llm

logger = logging.getLogger(__name__)

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
CASES_DIR = BENCHMARK_DIR / "inputs"
RESULTS_DIR = BENCHMARK_DIR / "results"

# ---------------------------------------------------------------------------
# Variant constants — 4 conditions
# ---------------------------------------------------------------------------

VARIANT_A = "A_no_skill"
VARIANT_B = "B_unstructured_prose"
VARIANT_C = "C_structured_skill"
VARIANT_D = "D_guide_compliant_skill"
ALL_VARIANTS = (VARIANT_A, VARIANT_B, VARIANT_C, VARIANT_D)

CCI_BENCHMARK_TYPE = "cci_interpretation_v2"

# ---------------------------------------------------------------------------
# CCI error families (retained from V1 for reference)
# ---------------------------------------------------------------------------

CCI_ERROR_FAMILIES = {
    "mechanism_fabrication": {
        "description": "Fabricates signaling pathways or mechanisms not supported by evidence",
        "severity": "critical",
    },
    "tissue_context_inflation": {
        "description": "Overclaims tissue-specific effects or spatial evidence strength",
        "severity": "major",
    },
    "lr_specificity_overclaim": {
        "description": "Claims exclusive L-R binding when multiple partners exist",
        "severity": "major",
    },
    "uncertainty_underestimation": {
        "description": "Fails to express appropriate uncertainty given weak or ambiguous evidence",
        "severity": "moderate",
    },
}

# ---------------------------------------------------------------------------
# Judge rubric
# ---------------------------------------------------------------------------

JUDGE_DIMENSIONS = {
    "faithfulness": {
        "weight": 0.30,
        "scale": "1-5",
        "description": "Does the interpretation stay within the evidence bundle?",
        "anchors": {
            1: "Mostly fabricated — claims unrelated to evidence",
            2: "Significant unsupported claims mixed with grounded ones",
            3: "Partially grounded — some claims supported, some not",
            4: "Mostly grounded with minor extrapolations",
            5: "Strictly evidence-grounded, every claim traceable to bundle",
        },
    },
    "fabrication_count": {
        "weight": 0.10,
        "scale": "integer",
        "description": "Count of specific biological mechanisms NOT supported by evidence bundle",
    },
    "uncertainty_handling": {
        "weight": 0.20,
        "scale": "1-5",
        "description": "Appropriate uncertainty expression given evidence quality",
        "anchors": {
            1: "No uncertainty expressed despite weak/ambiguous evidence",
            3: "Some uncertainty but miscalibrated to evidence strength",
            5: "Uncertainty perfectly calibrated to evidence quality",
        },
    },
    "spatial_calibration": {
        "weight": 0.15,
        "scale": "1-5",
        "description": "Correct interpretation of Moran's R magnitude",
        "anchors": {
            1: "Claims strong spatial evidence when Moran's R < 0.1",
            3: "Partially correct spatial interpretation",
            5: "Perfectly calibrated spatial evidence claims",
        },
    },
    "overclaiming": {
        "weight": 0.25,
        "scale": "1-5",
        "description": "Does the model extrapolate beyond the evidence?",
        "anchors": {
            1: "Extensive extrapolation (clinical implications, therapeutic targets, downstream pathways)",
            3: "Some extrapolation beyond evidence",
            5: "No extrapolation — stays strictly within provided data",
        },
    },
}

# ---------------------------------------------------------------------------
# Prompt templates — 4 conditions (V2: free-text generation)
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """\
You are a biological interpreter for spatial transcriptomics CCI \
(Cell-Cell Interaction) analysis.

You will receive an evidence bundle containing LIANA+ results for a \
single ligand-receptor (L-R) pair, including spatial co-localization \
metrics (Moran's R), functional similarity scores (GenePT), cell type \
expression patterns, and pathway associations.

Interpret the biological significance of this L-R pair. Write 2-3 \
paragraphs covering:
- Biological mechanism of this L-R interaction
- Relevance to the cell types and spatial context in this dataset
- Confidence level and limitations of the interpretation

Base your interpretation ONLY on the evidence provided in the bundle."""

_CONDITION_B_PROSE = """\

Additional interpretation guidance:

When interpreting L-R pair interactions from spatial transcriptomics CCI \
analysis, you should maintain strict evidence grounding and calibrate \
your confidence appropriately. Prioritize evidence in this order: spatial \
evidence from Moran's R co-localization first, then functional evidence \
from GenePT similarity, then pathway evidence from LIANA progeny \
associations, and finally expression evidence from cell type-specific \
patterns. Only cite signaling pathways and biological mechanisms that are \
directly supported by the provided evidence. Do not infer downstream \
pathways not explicitly present in the evidence. If no pathway association \
is detected in the LIANA analysis, do not fabricate one from general \
knowledge. Calibrate spatial evidence interpretation to Moran's R \
magnitude: values above 0.3 indicate strong spatial co-localization and \
should be highlighted as key findings, values between 0.1 and 0.3 \
indicate moderate evidence that should be reported with caveats, and \
values below 0.1 indicate weak spatial signal that should not be \
highlighted as a key CCI finding. Most receptors bind multiple ligands, \
so do not claim exclusive binding. For source-target cell type \
directionality, only claim specific directionality when ligand expression \
is restricted to two or fewer cell types. Broadly expressed ligands \
across three or more cell types cannot be reliably attributed to a single \
source, and directionality cannot be determined. Pay careful attention to \
receptor subtypes and their specific signaling properties. For example, \
decoy receptors such as TNFRSF10C (DcR1) lack functional death domains \
and inhibit rather than induce apoptosis, while atypical chemokine \
receptors such as ACKR3 (CXCR7) primarily scavenge ligands rather than \
transducing canonical signals. Always verify receptor function and check \
receptor subtype classification before claiming specific signaling \
outcomes. Confidence levels must be calibrated to both evidence quality \
and domain knowledge: high confidence requires Moran's R above 0.3 and a \
well-characterized pair in matching tissue; moderate confidence applies \
when Moran's R is between 0.1 and 0.3 or the pair is well-characterized \
in a different tissue; low confidence is appropriate when Moran's R is \
below 0.1 or the pair is poorly characterized; and insufficient evidence \
applies when there is no spatial co-localization and no tissue-matched \
literature. When evidence is ambiguous, always prefer the more \
conservative confidence level. Interpret L-R pairs based on this \
dataset's evidence, not general knowledge. A well-known pair may have \
weak signal in this specific dataset, and if the spatial evidence is weak \
it should not be highlighted as a key finding regardless of its general \
biological importance. If the pair is not enriched in the interest \
clusters, its relevance should be considered lower regardless of its \
general biological importance. Never fabricate signaling cascades not \
supported by the evidence, never claim tissue-specific effects without \
matching spatial data, and never extrapolate from related but different \
L-R pairs. When multiple valid interpretations exist, present \
alternatives rather than choosing one."""

_CONDITION_C_STRUCTURED = """\

## CCI Biological Interpretation Skill

### Evidence Hierarchy
1. **Spatial evidence**: Moran's R co-localization from LIANA+
2. **Functional evidence**: GenePT similarity score
3. **Pathway evidence**: LIANA progeny pathway associations
4. **Expression evidence**: Cell type-specific expression patterns

### Spatial Evidence Calibration
| Moran's R | Interpretation | Action |
|-----------|---------------|--------|
| > 0.3 | Strong spatial co-localization | Highlight as key finding |
| 0.1 - 0.3 | Moderate, interpret with caution | Report with caveats |
| < 0.1 | Weak spatial signal | Do NOT highlight as key finding |

### Mechanism Grounding Rules
- ONLY cite pathways directly supported by evidence
- Do NOT infer downstream pathways not in the evidence
- If no pathway association detected → do NOT fabricate from general knowledge
- Verify receptor function before claiming signaling outcomes

### Receptor Biology Accuracy
- **Decoy receptors** (e.g., TNFRSF10C/DcR1): Lack death domain → INHIBIT apoptosis
- **Atypical chemokine receptors** (e.g., ACKR3/CXCR7): Scavenge ligands, NOT canonical GPCR
- Always check receptor subtype classification before interpreting

### L-R Specificity Rules
- Most receptors bind multiple ligands → do NOT claim exclusive binding
- Source-target directionality: ONLY claim when ligand restricted to ≤2 cell types
- Broadly expressed ligands (3+ cell types) → "directionality cannot be determined"

### Confidence Calibration
| Level | Criteria |
|-------|----------|
| **High** | Moran's R > 0.3 AND well-characterized in matching tissue |
| **Moderate** | Moran's R 0.1-0.3 OR well-characterized in different tissue |
| **Low** | Moran's R < 0.1 OR poorly characterized pair |
| **Insufficient** | No spatial co-localization AND no tissue-matched literature |

### Data-First Principle
- Interpret based on THIS dataset's evidence, NOT general knowledge
- Well-known pair + weak spatial signal → do NOT highlight as key finding
- Not in interest clusters → lower relevance regardless of general importance

### Hallucination Prevention
- NEVER fabricate signaling cascades not in evidence
- NEVER claim tissue-specific effects without matching spatial data
- NEVER extrapolate from related but different L-R pairs
- When uncertain → prefer conservative interpretation
- When evidence is ambiguous → present alternatives, do not pick one"""

_CONDITION_D_GUIDE_SKILL = """\

## CCI Biological Interpretation Skill

### Why This Guidance Exists

LLMs consistently fabricate biological mechanisms when interpreting CCI data. \
Observed failure modes with gpt-4.1-mini and gpt-5.4-nano:
- Fabricated downstream signaling cascades not present in the evidence bundle \
(e.g., claiming JAK-STAT activation when only ligand-receptor binding data exists)
- Overclaimed tissue-specific effects derived from general knowledge rather than \
spatial transcriptomics data
- Ignored weak Moran's R (< 0.1) and still reported "strong spatial evidence"
- Invented pathway associations when none were detected in LIANA analysis

This guidance prevents these fabrications by constraining interpretation to \
the provided evidence bundle only.

### Evidence Hierarchy
1. **Spatial evidence**: Moran's R co-localization from LIANA+
2. **Functional evidence**: GenePT similarity score
3. **Pathway evidence**: LIANA progeny pathway associations
4. **Expression evidence**: Cell type-specific expression patterns

### Spatial Evidence Calibration
| Moran's R | Interpretation | Action |
|-----------|---------------|--------|
| > 0.3 | Strong spatial co-localization | Highlight as key finding |
| 0.1 - 0.3 | Moderate, interpret with caution | Report with caveats |
| < 0.1 | Weak spatial signal | Do NOT highlight as key finding |

### Mechanism Grounding Rules
- ONLY cite pathways directly supported by evidence
- Do NOT infer downstream pathways not in the evidence
- If no pathway association detected → do NOT fabricate from general knowledge
- Verify receptor function before claiming signaling outcomes

### Receptor Biology Accuracy
- **Decoy receptors** (e.g., TNFRSF10C/DcR1): Lack death domain → INHIBIT apoptosis
- **Atypical chemokine receptors** (e.g., ACKR3/CXCR7): Scavenge ligands, NOT canonical GPCR
- Always check receptor subtype classification before interpreting

### L-R Specificity Rules
- Most receptors bind multiple ligands → do NOT claim exclusive binding
- Source-target directionality: ONLY claim when ligand restricted to ≤2 cell types
- Broadly expressed ligands (3+ cell types) → "directionality cannot be determined"

### Confidence Calibration
| Level | Criteria |
|-------|----------|
| **High** | Moran's R > 0.3 AND well-characterized in matching tissue |
| **Moderate** | Moran's R 0.1-0.3 OR well-characterized in different tissue |
| **Low** | Moran's R < 0.1 OR poorly characterized pair |
| **Insufficient** | No spatial co-localization AND no tissue-matched literature |

### Data-First Principle
- Interpret based on THIS dataset's evidence, NOT general knowledge
- Well-known pair + weak spatial signal → do NOT highlight as key finding
- Not in interest clusters → lower relevance regardless of general importance

### Hallucination Prevention
- NEVER fabricate signaling cascades not in evidence
- NEVER claim tissue-specific effects without matching spatial data
- NEVER extrapolate from related but different L-R pairs
- When uncertain → prefer conservative interpretation
- When evidence is ambiguous → present alternatives, do not pick one

### Common Interpretation Traps
| Trap | Common Error | Correct Handling |
|------|-------------|-----------------|
| Decoy receptors | Claim apoptosis induction for TNFRSF10C | DcR1 INHIBITS apoptosis (lacks death domain) |
| Atypical chemokine R | Claim canonical GPCR signaling for ACKR3 | ACKR3 scavenges ligands, not canonical signaling |
| Broadly expressed ligand | Claim "Cell A → Cell B directionality" | 3+ cell types expressing ligand → "directionality cannot be determined" |
| Weak Moran's R | Report "strong spatial evidence" when R = 0.08 | R < 0.1 → "weak spatial signal, should not be highlighted" |
| No pathway data | Infer pathway from general knowledge | State "No pathway association detected in LIANA analysis" |

### Examples

**Correct interpretation** (Moran's R = 0.25, TGFb pathway detected):
"The THBS2-ITGA4 pair shows moderate spatial co-localization (Moran's R = 0.25, \
p < 0.001), suggesting possible but not definitive co-expression in the tumor \
microenvironment. The detected TGFb pathway association is consistent with \
known integrin-mediated signaling, though further validation is needed to confirm \
functional relevance in this tissue context."

**INCORRECT interpretation** (hallucinated):
"THBS2-ITGA4 drives epithelial-mesenchymal transition through activation of the \
FAK-PI3K-AKT signaling cascade, promoting tumor cell invasion and metastasis."
Why wrong: FAK-PI3K-AKT cascade is NOT in the evidence bundle. EMT claim \
extrapolates far beyond spatial co-localization data. "Drives" implies causation \
from correlational evidence. "Metastasis" is a therapeutic implication not \
supported by spatial transcriptomics data.

### Before Submitting Your Interpretation
Verify each point before finalizing:
- [ ] Every pathway cited appears in the evidence bundle's pathway associations
- [ ] Confidence level matches the Spatial Evidence Calibration table above
- [ ] No signaling cascades beyond what the evidence directly shows
- [ ] Broadly expressed ligands (3+ cell types) lack directionality claims
- [ ] Hedged language ("suggests", "indicates", "consistent with") for interpretations
- [ ] Definitive language ("shows", "has", "is") ONLY for data values"""


def build_system_prompt(variant: str) -> str:
    """Build the system prompt for a given condition variant."""
    if variant == VARIANT_A:
        return _BASE_SYSTEM_PROMPT
    if variant == VARIANT_B:
        return _BASE_SYSTEM_PROMPT + _CONDITION_B_PROSE
    if variant == VARIANT_C:
        return _BASE_SYSTEM_PROMPT + _CONDITION_C_STRUCTURED
    if variant == VARIANT_D:
        return _BASE_SYSTEM_PROMPT + _CONDITION_D_GUIDE_SKILL
    raise ValueError(f"Unknown variant: {variant}")


def build_user_prompt(case: dict[str, Any]) -> str:
    """Build the user prompt from a frozen case (V2: evidence bundle only)."""
    bundle = case["input_bundle"]

    lines = [
        f"## L-R Pair: {bundle['ligand']}-{bundle['receptor']}",
        "",
        "### Evidence Bundle",
        f"- Interaction: {bundle['interaction']}",
        f"- Moran's R: {bundle['morans_r']} (p = {bundle['morans_pval']})",
    ]
    # Optional fields (present in pilot cases but not full cases, or vice versa)
    if "genept_score" in bundle:
        lines.append(f"- GenePT score: {bundle['genept_score']}")
    if "combinedscore" in bundle:
        lines.append(f"- Combined score: {bundle['combinedscore']}")
    if "ligand_means" in bundle:
        lines.append(f"- Ligand expression: mean={bundle['ligand_means']}, proportion={bundle['ligand_props']}")
    if "receptor_means" in bundle:
        lines.append(f"- Receptor expression: mean={bundle['receptor_means']}, proportion={bundle['receptor_props']}")
    if "factor1" in bundle:
        lines.append(f"- NMF factors: F1={bundle['factor1']}, F2={bundle['factor2']}, F3={bundle['factor3']}")
    elif "factor_relevance" in bundle:
        lines.append(f"- Factor relevance: {bundle['factor_relevance']}")
    lines.extend([
        f"- Pathway associations: {', '.join(bundle.get('pathway_associations', [])) or 'None detected'}",
        f"- Disease associations: {', '.join(bundle.get('disease_associations', [])) or 'None detected'}",
        f"- Ligand cell types: {', '.join(bundle.get('ligand_cell_types', [])) or 'Not available'}",
        f"- Receptor cell types: {', '.join(bundle.get('receptor_cell_types', [])) or 'Not available'}",
    ])
    if "interest_clusters" in bundle:
        lines.append(f"- Interest clusters: {', '.join(bundle['interest_clusters'])}")
    if "interest_celltypes" in bundle:
        lines.append(f"- Interest cell types: {', '.join(bundle['interest_celltypes'])}")
    if "mean_interest" in bundle and bundle["mean_interest"] is not None:
        lines.append(f"- Interest cluster enrichment: mean={bundle['mean_interest']}, p_adj={bundle.get('pval_interest_adj', 'N/A')}")
    lines.extend([
        f"- Tissue context: {bundle['tissue_context']}",
        "",
        "Write your biological interpretation below.",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM Judge
# ---------------------------------------------------------------------------

_JUDGE_PROMPT_TEMPLATE = """\
You are evaluating the biological interpretation quality of a ligand-receptor \
(L-R) pair from spatial transcriptomics CCI analysis.

The interpreter was given ONLY the evidence bundle below and asked to write \
a 2-3 paragraph biological interpretation. Your job is to evaluate how well \
the interpretation stays grounded in the provided evidence.

## Evidence Bundle (this is ALL the interpreter had access to)

{evidence_bundle}

## Interpreter's Output

{interpretation}

## Evaluation Rubric

Score the interpretation on these 5 dimensions:

### 1. Faithfulness (1-5)
Does the interpretation stay within the evidence bundle?
  1 = Mostly fabricated — claims unrelated to evidence
  2 = Significant unsupported claims mixed with grounded ones
  3 = Partially grounded — some claims supported, some not
  4 = Mostly grounded with minor extrapolations
  5 = Strictly evidence-grounded, every claim traceable to bundle

### 2. Fabrication Count (integer, 0+)
Count specific biological mechanisms, pathways, or signaling cascades \
mentioned in the interpretation that are NOT supported by the evidence bundle. \
Examples: claiming a specific downstream pathway not in the data, inventing \
therapeutic implications, stating cell-type-specific functions not in the \
expression data.

### 3. Uncertainty Handling (1-5)
Is uncertainty appropriately expressed given evidence quality?
  1 = No uncertainty expressed despite weak/ambiguous evidence
  3 = Some uncertainty but miscalibrated to evidence strength
  5 = Uncertainty perfectly calibrated to evidence quality
Consider: Moran's R magnitude, presence/absence of pathway data, \
breadth of cell type expression.

### 4. Spatial Calibration (1-5)
Does the interpretation correctly reflect the Moran's R magnitude?
  1 = Claims strong spatial evidence when Moran's R < 0.1
  3 = Partially correct spatial interpretation
  5 = Perfectly calibrated spatial evidence claims
Key reference: R > 0.3 = strong, R = 0.1-0.3 = moderate, R < 0.1 = weak.

### 5. Overclaiming (1-5)
Does the model extrapolate beyond what the evidence supports?
  1 = Extensive extrapolation (clinical implications, therapeutic targets, \
downstream cascades not in evidence)
  3 = Some extrapolation beyond evidence
  5 = No extrapolation — stays strictly within provided data

## Output Format

Return ONLY valid JSON with this exact schema:
{{
  "faithfulness": <1-5>,
  "fabrication_count": <integer>,
  "uncertainty_handling": <1-5>,
  "spatial_calibration": <1-5>,
  "overclaiming": <1-5>,
  "fabricated_claims": ["list of specific fabricated claims found"],
  "rationale": "2-3 sentence explanation of your evaluation"
}}"""


def _build_judge_prompt(case: dict[str, Any], interpretation: str) -> str:
    """Build the judge prompt with evidence bundle and interpretation."""
    bundle = case["input_bundle"]
    evidence_lines = [
        f"L-R Pair: {bundle['ligand']}-{bundle['receptor']}",
        f"Interaction: {bundle['interaction']}",
        f"Moran's R: {bundle['morans_r']} (p = {bundle['morans_pval']})",
    ]
    if "genept_score" in bundle:
        evidence_lines.append(f"GenePT score: {bundle['genept_score']}")
    if "combinedscore" in bundle:
        evidence_lines.append(f"Combined score: {bundle['combinedscore']}")
    if "ligand_means" in bundle:
        evidence_lines.append(f"Ligand expression: mean={bundle['ligand_means']}, proportion={bundle['ligand_props']}")
    if "receptor_means" in bundle:
        evidence_lines.append(f"Receptor expression: mean={bundle['receptor_means']}, proportion={bundle['receptor_props']}")
    if "factor1" in bundle:
        evidence_lines.append(f"NMF factors: F1={bundle['factor1']}, F2={bundle['factor2']}, F3={bundle['factor3']}")
    evidence_lines.extend([
        f"Pathway associations: {', '.join(bundle.get('pathway_associations', [])) or 'None detected'}",
        f"Disease associations: {', '.join(bundle.get('disease_associations', [])) or 'None detected'}",
        f"Ligand cell types: {', '.join(bundle.get('ligand_cell_types', [])) or 'Not available'}",
        f"Receptor cell types: {', '.join(bundle.get('receptor_cell_types', [])) or 'Not available'}",
        f"Tissue context: {bundle['tissue_context']}",
    ])
    evidence_text = "\n".join(evidence_lines)
    return _JUDGE_PROMPT_TEMPLATE.format(
        evidence_bundle=evidence_text,
        interpretation=interpretation,
    )


def parse_json_output(raw_output: str) -> dict[str, Any] | None:
    """Parse JSON from model output, handling markdown fences."""
    text = raw_output.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        for i, line in enumerate(lines[1:], 1):
            if line.strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def validate_judge_output(parsed: dict[str, Any] | None) -> list[str]:
    """Validate judge output against expected schema."""
    if parsed is None:
        return ["Judge output is not valid JSON"]
    errors = []
    for dim in ("faithfulness", "uncertainty_handling", "spatial_calibration", "overclaiming"):
        val = parsed.get(dim)
        if not isinstance(val, (int, float)) or val < 1 or val > 5:
            errors.append(f"{dim} must be 1-5, got {val}")
    fc = parsed.get("fabrication_count")
    if not isinstance(fc, (int, float)) or fc < 0:
        errors.append(f"fabrication_count must be >= 0, got {fc}")
    if not isinstance(parsed.get("fabricated_claims"), list):
        errors.append("fabricated_claims must be a list")
    if not isinstance(parsed.get("rationale"), str):
        errors.append("rationale must be a string")
    return errors


def compute_composite_score(judge_output: dict[str, Any]) -> float:
    """Compute composite hallucination score from judge dimensions.

    Returns a score 0-5 where higher = better (less hallucination).
    """
    f = float(judge_output.get("faithfulness", 1))
    oc = float(judge_output.get("overclaiming", 1))
    uh = float(judge_output.get("uncertainty_handling", 1))
    sc = float(judge_output.get("spatial_calibration", 1))
    fc = float(min(judge_output.get("fabrication_count", 5), 5))

    return (
        0.30 * f
        + 0.25 * oc
        + 0.20 * uh
        + 0.15 * sc
        + 0.10 * (5.0 - fc)
    )


async def run_single_judge(
    *,
    judge_llm: Any,
    case: dict[str, Any],
    interpretation: str,
    judge_label: str,
) -> dict[str, Any]:
    """Run a single judge evaluation on an interpretation."""
    prompt = _build_judge_prompt(case, interpretation)
    messages = [HumanMessage(content=prompt)]

    t0 = time.time()
    try:
        response = await judge_llm.ainvoke(messages)
        raw = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        return {
            "judge_label": judge_label,
            "raw_output": "",
            "parsed_output": None,
            "validation_errors": [str(exc)],
            "composite_score": 0.0,
            "latency_s": time.time() - t0,
        }

    parsed = parse_json_output(raw)
    errors = validate_judge_output(parsed)

    composite = compute_composite_score(parsed) if parsed and not errors else 0.0

    return {
        "judge_label": judge_label,
        "raw_output": raw,
        "parsed_output": parsed,
        "validation_errors": errors,
        "composite_score": composite,
        "latency_s": time.time() - t0,
    }


def compute_cohens_kappa(
    scores_a: list[int],
    scores_b: list[int],
    n_categories: int = 5,
    weighted: bool = True,
) -> float:
    """Compute Cohen's kappa for two lists of ordinal ratings (1-5).

    Args:
        weighted: If True, use quadratic weighted kappa (appropriate for
            ordinal scales). If False, use strict (unweighted) kappa.
    """
    if len(scores_a) != len(scores_b) or len(scores_a) == 0:
        return 0.0

    n = len(scores_a)
    min_val, max_val = 1, n_categories
    n_cat = max_val - min_val + 1

    # Build observed coincidence matrix
    O = [[0.0] * n_cat for _ in range(n_cat)]
    for a, b in zip(scores_a, scores_b):
        if min_val <= a <= max_val and min_val <= b <= max_val:
            O[a - min_val][b - min_val] += 1.0

    total = sum(O[i][j] for i in range(n_cat) for j in range(n_cat))
    if total == 0:
        return 0.0

    # Normalize
    for i in range(n_cat):
        for j in range(n_cat):
            O[i][j] /= total

    # Marginals
    row_sum = [sum(O[i][j] for j in range(n_cat)) for i in range(n_cat)]
    col_sum = [sum(O[i][j] for i in range(n_cat)) for j in range(n_cat)]

    # Expected matrix
    E = [[row_sum[i] * col_sum[j] for j in range(n_cat)] for i in range(n_cat)]

    # Weight matrix
    W = [[0.0] * n_cat for _ in range(n_cat)]
    for i in range(n_cat):
        for j in range(n_cat):
            if weighted:
                W[i][j] = (i - j) ** 2 / (n_cat - 1) ** 2  # quadratic
            else:
                W[i][j] = 0.0 if i == j else 1.0  # strict

    num = sum(W[i][j] * O[i][j] for i in range(n_cat) for j in range(n_cat))
    den = sum(W[i][j] * E[i][j] for i in range(n_cat) for j in range(n_cat))

    if den == 0:
        return 1.0
    return 1.0 - num / den


# ---------------------------------------------------------------------------
# Trial runner (V2: generate free text, then judge)
# ---------------------------------------------------------------------------


async def run_single_trial(
    *,
    llm: Any,
    case: dict[str, Any],
    variant: str,
) -> dict[str, Any]:
    """Run one trial: generate free-text interpretation."""
    system_prompt = build_system_prompt(variant)
    user_prompt = build_user_prompt(case)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    t0 = time.time()
    try:
        response = await llm.ainvoke(messages)
        raw_output = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "benchmark_type": CCI_BENCHMARK_TYPE,
            "variant": variant,
            "latency_s": time.time() - t0,
            "raw_output": "",
            "judge_results": [],
            "consensus_score": 0.0,
            "error": str(exc),
        }

    return {
        "case_id": case["case_id"],
        "benchmark_type": CCI_BENCHMARK_TYPE,
        "variant": variant,
        "latency_s": time.time() - t0,
        "raw_output": raw_output,
        "judge_results": [],
        "consensus_score": 0.0,
        "error": None,
    }


async def judge_trial(
    *,
    trial: dict[str, Any],
    case: dict[str, Any],
    judge_configs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run dual judges on a completed trial."""
    if not trial["raw_output"] or trial.get("error"):
        return trial

    judge_results = []
    for jc in judge_configs:
        judge_llm = create_llm(provider=jc["provider"], **jc["model_kwargs"])
        result = await run_single_judge(
            judge_llm=judge_llm,
            case=case,
            interpretation=trial["raw_output"],
            judge_label=jc["label"],
        )
        judge_results.append(result)

    trial["judge_results"] = judge_results

    valid_scores = [
        jr["composite_score"]
        for jr in judge_results
        if jr["parsed_output"] and not jr["validation_errors"]
    ]
    trial["consensus_score"] = mean(valid_scores) if valid_scores else 0.0

    return trial


# ---------------------------------------------------------------------------
# Statistics — 3-way comparison on judge scores
# ---------------------------------------------------------------------------


def summarize_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize V2 trials with judge-based scores and Kruskal-Wallis test."""
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for trial in trials:
        v = trial["variant"]
        by_variant.setdefault(v, []).append(trial)

    variant_stats: dict[str, dict[str, Any]] = {}
    variant_scores: dict[str, list[float]] = {}

    for variant in ALL_VARIANTS:
        vt = by_variant.get(variant, [])
        if not vt:
            continue

        scores = [t["consensus_score"] for t in vt]
        variant_scores[variant] = scores
        n = len(vt)

        dim_means: dict[str, float] = {}
        for dim in ("faithfulness", "fabrication_count", "uncertainty_handling",
                     "spatial_calibration", "overclaiming"):
            vals = []
            for t in vt:
                for jr in t.get("judge_results", []):
                    p = jr.get("parsed_output")
                    if p and dim in p:
                        vals.append(float(p[dim]))
            dim_means[dim] = mean(vals) if vals else 0.0

        error_rate = mean(1.0 if t.get("error") else 0.0 for t in vt)

        variant_stats[variant] = {
            "n": n,
            "composite_score_mean": mean(scores),
            "composite_score_std": stdev(scores) if n > 1 else 0.0,
            "faithfulness_mean": dim_means.get("faithfulness", 0.0),
            "fabrication_count_mean": dim_means.get("fabrication_count", 0.0),
            "uncertainty_handling_mean": dim_means.get("uncertainty_handling", 0.0),
            "spatial_calibration_mean": dim_means.get("spatial_calibration", 0.0),
            "overclaiming_mean": dim_means.get("overclaiming", 0.0),
            "error_rate": error_rate,
            "latency_s_mean": mean(t["latency_s"] for t in vt),
        }

    kw_result: dict[str, Any] = {"statistic": None, "pvalue": None}
    groups = [variant_scores.get(v, []) for v in ALL_VARIANTS if v in variant_scores]
    if kruskal is not None and len(groups) >= 2 and all(len(g) >= 2 for g in groups):
        try:
            stat, pval = kruskal(*groups)
            kw_result = {"statistic": float(stat), "pvalue": float(pval)}
        except Exception:
            pass

    pairwise: dict[str, dict[str, Any]] = {}
    pairs = [
        (VARIANT_A, VARIANT_B),
        (VARIANT_A, VARIANT_C),
        (VARIANT_B, VARIANT_C),
        (VARIANT_A, VARIANT_D),
        (VARIANT_C, VARIANT_D),
        (VARIANT_B, VARIANT_D),
    ]
    n_comparisons = len(pairs)
    for va, vb in pairs:
        sa = variant_scores.get(va, [])
        sb = variant_scores.get(vb, [])
        if sa and sb:
            delta = mean(sa) - mean(sb)
            entry: dict[str, Any] = {
                "delta_mean": delta,
                "effect_direction": f"{vb}_better" if delta < 0 else f"{va}_better" if delta > 0 else "equal",
            }
            if mannwhitneyu is not None and len(sa) >= 2 and len(sb) >= 2:
                try:
                    u_stat, p_raw = mannwhitneyu(sa, sb, alternative="two-sided")
                    p_bonf = min(p_raw * n_comparisons, 1.0)
                    n1, n2 = len(sa), len(sb)
                    mu = n1 * n2 / 2.0
                    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
                    z = (u_stat - mu) / sigma if sigma > 0 else 0.0
                    r = abs(z) / math.sqrt(n1 + n2)
                    entry.update({
                        "u_statistic": float(u_stat),
                        "p_raw": float(p_raw),
                        "p_bonferroni": float(p_bonf),
                        "effect_size_r": float(r),
                        "significant": bool(p_bonf < 0.05),
                    })
                except Exception:
                    pass
            pairwise[f"{va}_vs_{vb}"] = entry

    # Cohen's kappa across all judge pairs
    kappa_results: dict[str, float] = {}
    all_judge_labels = set()
    for t in trials:
        for jr in t.get("judge_results", []):
            all_judge_labels.add(jr["judge_label"])
    judge_labels = sorted(all_judge_labels)
    if len(judge_labels) >= 2:
        for dim in ("faithfulness", "uncertainty_handling", "spatial_calibration", "overclaiming"):
            scores_j1 = []
            scores_j2 = []
            for t in trials:
                jrs = {jr["judge_label"]: jr for jr in t.get("judge_results", [])}
                j1 = jrs.get(judge_labels[0], {}).get("parsed_output")
                j2 = jrs.get(judge_labels[1], {}).get("parsed_output")
                if j1 and j2 and dim in j1 and dim in j2:
                    scores_j1.append(int(j1[dim]))
                    scores_j2.append(int(j2[dim]))
            if scores_j1:
                kappa_results[dim] = compute_cohens_kappa(scores_j1, scores_j2)

    return {
        "benchmark_type": CCI_BENCHMARK_TYPE,
        "primary_metric": "composite_score",
        "trial_count": len(trials),
        "variants": variant_stats,
        "kruskal_wallis": kw_result,
        "pairwise_deltas": pairwise,
        "cohens_kappa": kappa_results,
        "judge_labels": judge_labels,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def render_markdown_summary(summary: dict[str, Any]) -> str:
    """Render a markdown summary from V2 benchmark results."""
    lines = [
        "# CCI Skill Ablation Benchmark V2 — Full Four-Condition Results",
        "",
        "## Composite Score (higher = less hallucination, max 5.0)",
        "",
        "| Variant | N | Composite | Faithfulness | Fabrications | Uncertainty | Spatial | Overclaiming | Latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for variant in ALL_VARIANTS:
        vs = summary["variants"].get(variant)
        if not vs:
            continue
        lines.append(
            f"| {variant} | {vs['n']} "
            f"| {vs['composite_score_mean']:.2f} ± {vs['composite_score_std']:.2f} "
            f"| {vs['faithfulness_mean']:.2f} "
            f"| {vs['fabrication_count_mean']:.1f} "
            f"| {vs['uncertainty_handling_mean']:.2f} "
            f"| {vs['spatial_calibration_mean']:.2f} "
            f"| {vs['overclaiming_mean']:.2f} "
            f"| {vs['latency_s_mean']:.1f}s |"
        )

    kw = summary.get("kruskal_wallis", {})
    lines.extend([
        "",
        "## Primary Endpoint (Kruskal-Wallis on composite_score)",
        "",
        f"- Statistic: `{kw.get('statistic', 'N/A')}`",
        f"- p-value: `{kw.get('pvalue', 'N/A')}`",
        "",
        "## Post-hoc Pairwise Comparisons (Mann-Whitney U, Bonferroni-corrected)",
        "",
        "| Comparison | Delta | U statistic | Bonferroni p | Effect size r | Sig |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for pair_key, pair_data in summary.get("pairwise_deltas", {}).items():
        u = pair_data.get("u_statistic")
        p_bonf = pair_data.get("p_bonferroni")
        r = pair_data.get("effect_size_r")
        if u is not None:
            sig = "***" if p_bonf < 0.001 else "**" if p_bonf < 0.01 else "*" if p_bonf < 0.05 else "ns"
            lines.append(
                f"| {pair_key} | {pair_data['delta_mean']:.3f} "
                f"| {u:,.0f} | {p_bonf:.2e} | {r:.3f} | {sig} |"
            )
        else:
            lines.append(f"| {pair_key} | {pair_data['delta_mean']:.3f} | N/A | N/A | N/A | |")

    kappa = summary.get("cohens_kappa", {})
    if kappa:
        lines.extend(["", "## Inter-rater Agreement (Cohen's Kappa)", ""])
        for dim, k in kappa.items():
            status = "GOOD" if k >= 0.7 else "MODERATE" if k >= 0.4 else "POOR"
            lines.append(f"- {dim}: kappa = `{k:.3f}` ({status})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate CCI benchmark cases (V2: probes optional)."""
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    required_keys = {"case_id", "input_bundle"}
    for case in cases:
        missing = required_keys - set(case)
        if missing:
            raise ValueError(f"Case {case.get('case_id', '?')} missing keys: {sorted(missing)}")
        bundle = case["input_bundle"]
        for field in ("ligand", "receptor", "morans_r"):
            if field not in bundle:
                raise ValueError(f"Case {case['case_id']} input_bundle missing: {field}")
    return cases


def save_jsonl(path: str | Path, records: list[dict[str, Any]]) -> None:
    """Save records as JSONL."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def save_json(path: str | Path, data: Any) -> None:
    """Save data as JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
