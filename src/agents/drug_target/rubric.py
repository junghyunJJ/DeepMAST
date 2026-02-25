"""Structured scoring rubric for Drug Target Assessment.

Scoring is delegated to the LLM using a structured rubric. This keeps the
system flexible and interpretable while maintaining reproducibility through
a fixed rubric definition.

How it works:
1. rubric.py defines the rubric as a Python data structure (criteria + rating scales)
2. The Clinical Assessor loads the rubric and evaluates each target against it
3. LLM outputs structured JSON with scores + explicit rationale per criterion
4. The rubric itself is the reproducible artifact (same rubric + same evidence -> consistent assessment)
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Rubric Definition (version-controlled reproducible artifact)
# =============================================================================

DRUG_TARGET_RUBRIC = {
    "version": "1.0",
    "validated_track": {
        "description": "Clinical evidence-centric assessment for targets with existing drug development activity",
        "criteria": [
            {
                "name": "existing_drug_evidence",
                "question": "Are there known drugs targeting this gene for the disease or related diseases?",
                "scale": "none (0) | indirect_evidence (1) | Phase 1-2 (2) | Phase 3+ or approved (3)",
                "weight_hint": "primary",
            },
            {
                "name": "clinical_trial_activity",
                "question": "How active is the clinical trial landscape for this target?",
                "scale": "no_trials (0) | few_early_phase (1) | multiple_or_advanced (2) | extensive (3)",
                "weight_hint": "secondary",
            },
            {
                "name": "mechanism_relevance",
                "question": "How relevant is this target's mechanism to the observed L-R interaction?",
                "scale": "unclear (0) | plausible (1) | well_supported (2) | direct_mechanism (3)",
                "weight_hint": "secondary",
            },
            {
                "name": "safety_profile",
                "question": "Are there known safety concerns for targeting this gene?",
                "scale": "major_concerns (-2) | moderate_concerns (-1) | minimal_or_none (0)",
                "weight_hint": "modifier",
            },
        ],
        "pass_logic": "existing_drug_evidence >= 2 OR (existing_drug_evidence >= 1 AND clinical_trial_activity >= 1)",
        "max_score": 9,  # 3+3+3+0
    },
    "exploratory_track": {
        "description": "Genetic/biological evidence-centric assessment for novel or emerging targets",
        "criteria": [
            {
                "name": "gwas_genetic_support",
                "question": "Is there GWAS evidence linking this gene to the disease?",
                "scale": "no_signal (0) | suggestive (1) | genome_wide_significant (2) | replicated (3)",
                "weight_hint": "primary",
            },
            {
                "name": "tractability",
                "question": "Is this target druggable (small molecule, antibody, or other modality)?",
                "scale": "unknown (0) | predicted (1) | clinical_precedent (2) | approved_modality (3)",
                "weight_hint": "secondary",
            },
            {
                "name": "biological_plausibility",
                "question": "How strong is the biological rationale connecting this gene to the disease pathway?",
                "scale": "weak (0) | moderate (1) | strong (2) | compelling_multi_evidence (3)",
                "weight_hint": "secondary",
            },
            {
                "name": "novelty_opportunity",
                "question": "How novel is this as a therapeutic target (underexplored = higher opportunity)?",
                "scale": "well_established (0) | moderately_explored (1) | emerging (2) | novel (3)",
                "weight_hint": "tertiary",
            },
        ],
        "pass_logic": "gwas_genetic_support >= 1 AND (tractability >= 1 OR biological_plausibility >= 2)",
        "max_score": 12,  # 3+3+3+3
    },
}


# =============================================================================
# Classification Rules
# =============================================================================

CLASSIFICATION_RULES = {
    "validated_target": "Passes validated_track (existing drugs or active clinical trials)",
    "exploratory_target": "Fails validated_track but passes exploratory_track (genetic/biological support)",
    "novel_candidate": "Fails both tracks but has biological_plausibility >= 2 or novelty_opportunity >= 2",
    "insufficient_evidence": "Does not meet criteria for any classification",
}

PRIORITY_RULES = {
    "high": "validated_target with validated_total >= 6, OR exploratory_target with exploratory_total >= 8",
    "medium": "validated_target with validated_total >= 3, OR exploratory_target with exploratory_total >= 5",
    "low": "Any target that passes either track but does not meet medium threshold",
    "unranked": "insufficient_evidence classification",
}


# =============================================================================
# Prompt Formatting
# =============================================================================

def get_rubric() -> dict:
    """Return the full rubric definition."""
    return DRUG_TARGET_RUBRIC


def format_rubric_prompt(evidence: dict) -> str:
    """Format the rubric into an LLM evaluation prompt.

    Args:
        evidence: Dictionary of collected evidence for a target gene
            Expected keys: gene_symbol, is_selected_top3, opentargets, gwas,
                          chembl, clinical_trials, fda, disease

    Returns:
        Formatted prompt string for LLM evaluation
    """
    gene = evidence.get("gene_symbol", "UNKNOWN")
    is_top3 = evidence.get("is_selected_top3", False)

    prompt = f"""## Drug Target Assessment: {gene}
{"**★ FEATURED CANDIDATE (selected_top3_lr)**" if is_top3 else ""}

### Evidence Summary
```json
{json.dumps(evidence, indent=2, default=str)[:8000]}
```

### Evaluation Rubric

Evaluate this target against both tracks using the criteria below.
For each criterion, provide a score AND a rationale explaining your reasoning.

#### VALIDATED TRACK (Clinical Evidence)
{_format_track_criteria(DRUG_TARGET_RUBRIC["validated_track"])}

Pass logic: {DRUG_TARGET_RUBRIC["validated_track"]["pass_logic"]}

#### EXPLORATORY TRACK (Genetic/Biological Evidence)
{_format_track_criteria(DRUG_TARGET_RUBRIC["exploratory_track"])}

Pass logic: {DRUG_TARGET_RUBRIC["exploratory_track"]["pass_logic"]}

### Classification Rules
- **validated_target**: {CLASSIFICATION_RULES["validated_target"]}
- **exploratory_target**: {CLASSIFICATION_RULES["exploratory_target"]}
- **novel_candidate**: {CLASSIFICATION_RULES["novel_candidate"]}
- **insufficient_evidence**: {CLASSIFICATION_RULES["insufficient_evidence"]}

### Priority Rules
- **high**: {PRIORITY_RULES["high"]}
- **medium**: {PRIORITY_RULES["medium"]}
- **low**: {PRIORITY_RULES["low"]}

### Required Output Format
Respond with a JSON object matching this schema exactly:
```json
{{
    "gene_symbol": "{gene}",
    "is_selected_top3": {str(is_top3).lower()},
    "validated_track": {{
        "existing_drug_evidence": {{"score": <int>, "rationale": "<string>"}},
        "clinical_trial_activity": {{"score": <int>, "rationale": "<string>"}},
        "mechanism_relevance": {{"score": <int>, "rationale": "<string>"}},
        "safety_profile": {{"score": <int>, "rationale": "<string>"}},
        "total": <int>,
        "pass": <boolean>
    }},
    "exploratory_track": {{
        "gwas_genetic_support": {{"score": <int>, "rationale": "<string>"}},
        "tractability": {{"score": <int>, "rationale": "<string>"}},
        "biological_plausibility": {{"score": <int>, "rationale": "<string>"}},
        "novelty_opportunity": {{"score": <int>, "rationale": "<string>"}},
        "total": <int>,
        "pass": <boolean>
    }},
    "classification": "<validated_target|exploratory_target|novel_candidate|insufficient_evidence>",
    "priority": "<high|medium|low|unranked>",
    "summary": "<1-2 sentence summary of assessment>"
}}
```
"""
    return prompt


def _format_track_criteria(track: dict) -> str:
    """Format track criteria for prompt display."""
    lines = []
    for c in track["criteria"]:
        lines.append(f"- **{c['name']}**: {c['question']}")
        lines.append(f"  Scale: {c['scale']}")
    return "\n".join(lines)


# =============================================================================
# Response Parsing and Validation
# =============================================================================

def parse_assessment_response(llm_output: str) -> dict | None:
    """Parse LLM assessment response into structured dict.

    Extracts JSON from LLM output, handling markdown code fences.

    Args:
        llm_output: Raw LLM response text

    Returns:
        Parsed assessment dict, or None if parsing fails
    """
    import re

    # Try to extract JSON from markdown code fence
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", llm_output, re.DOTALL)
    text = json_match.group(1).strip() if json_match else llm_output.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON-like structure in the text
        brace_start = text.find("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end])
            except json.JSONDecodeError:
                pass

    logger.warning(f"Failed to parse assessment response: {llm_output[:200]}")
    return None


def validate_assessment(parsed: dict) -> tuple[bool, list[str]]:
    """Validate a parsed assessment against the rubric schema.

    Args:
        parsed: Parsed assessment dictionary

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []

    if not isinstance(parsed, dict):
        return False, ["Response is not a dictionary"]

    # Check required top-level fields
    for field in ("gene_symbol", "validated_track", "exploratory_track", "classification", "priority"):
        if field not in parsed:
            errors.append(f"Missing required field: {field}")

    # Validate tracks
    for track_name in ("validated_track", "exploratory_track"):
        track = parsed.get(track_name, {})
        if not isinstance(track, dict):
            errors.append(f"{track_name} is not a dictionary")
            continue

        rubric_track = DRUG_TARGET_RUBRIC.get(track_name, {})
        for criterion in rubric_track.get("criteria", []):
            cname = criterion["name"]
            if cname not in track:
                errors.append(f"{track_name}.{cname} missing")
                continue
            entry = track[cname]
            if not isinstance(entry, dict) or "score" not in entry:
                errors.append(f"{track_name}.{cname} must have 'score' field")

        if "total" not in track:
            errors.append(f"{track_name}.total missing")
        if "pass" not in track:
            errors.append(f"{track_name}.pass missing")

    # Validate classification
    valid_classifications = set(CLASSIFICATION_RULES.keys())
    if parsed.get("classification") not in valid_classifications:
        errors.append(f"Invalid classification: {parsed.get('classification')}")

    # Validate priority
    valid_priorities = {"high", "medium", "low", "unranked"}
    if parsed.get("priority") not in valid_priorities:
        errors.append(f"Invalid priority: {parsed.get('priority')}")

    return len(errors) == 0, errors


def compute_track_total(track_data: dict, track_name: str) -> int:
    """Recompute track total from individual scores (for verification).

    Args:
        track_data: Track assessment data with criterion scores
        track_name: "validated_track" or "exploratory_track"

    Returns:
        Computed total score
    """
    rubric_track = DRUG_TARGET_RUBRIC.get(track_name, {})
    total = 0
    for criterion in rubric_track.get("criteria", []):
        cname = criterion["name"]
        entry = track_data.get(cname, {})
        if isinstance(entry, dict):
            total += entry.get("score", 0)
    return total


__all__ = [
    "DRUG_TARGET_RUBRIC",
    "CLASSIFICATION_RULES",
    "PRIORITY_RULES",
    "get_rubric",
    "format_rubric_prompt",
    "parse_assessment_response",
    "validate_assessment",
    "compute_track_total",
]
