"""Unit tests for CCI Skill Ablation Benchmark V2 (LLM Judge).

Tests prompt rendering, judge rubric validation, composite scoring,
Cohen's kappa calculation, and statistics.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "docs" / "benchmarks" / "cci_skill_ablation"
sys.path.insert(0, str(BENCHMARK_DIR))

from benchmark_cci_core import (
    ALL_VARIANTS,
    CCI_BENCHMARK_TYPE,
    CCI_ERROR_FAMILIES,
    JUDGE_DIMENSIONS,
    VARIANT_A,
    VARIANT_B,
    VARIANT_C,
    _build_judge_prompt,
    build_system_prompt,
    build_user_prompt,
    compute_cohens_kappa,
    compute_composite_score,
    load_cases,
    parse_json_output,
    render_markdown_summary,
    summarize_trials,
    validate_judge_output,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CASES_PATH = BENCHMARK_DIR / "cases" / "pilot_cci_cases.json"


@pytest.fixture
def cases():
    return load_cases(CASES_PATH)


@pytest.fixture
def sample_case(cases):
    return cases[0]


def _perfect_judge_output() -> dict:
    return {
        "faithfulness": 5,
        "fabrication_count": 0,
        "uncertainty_handling": 5,
        "spatial_calibration": 5,
        "overclaiming": 5,
        "fabricated_claims": [],
        "rationale": "Perfectly grounded interpretation.",
    }


def _bad_judge_output() -> dict:
    return {
        "faithfulness": 1,
        "fabrication_count": 4,
        "uncertainty_handling": 1,
        "spatial_calibration": 1,
        "overclaiming": 1,
        "fabricated_claims": ["claimed Wnt activation", "invented therapeutic target",
                              "wrong receptor function", "fabricated downstream cascade"],
        "rationale": "Extensively fabricated.",
    }


def _make_trial(variant: str, consensus: float, raw_output: str = "test",
                judge_outputs: list | None = None) -> dict:
    jrs = []
    if judge_outputs:
        for i, jo in enumerate(judge_outputs):
            jrs.append({
                "judge_label": f"judge_{i}",
                "parsed_output": jo,
                "composite_score": compute_composite_score(jo),
                "validation_errors": [],
            })
    return {
        "case_id": "test",
        "benchmark_type": CCI_BENCHMARK_TYPE,
        "variant": variant,
        "latency_s": 5.0,
        "raw_output": raw_output,
        "judge_results": jrs,
        "consensus_score": consensus,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Case loading
# ---------------------------------------------------------------------------


class TestCaseLoading:
    def test_load_cases_returns_list(self, cases):
        assert isinstance(cases, list)
        assert len(cases) == 5

    def test_each_case_has_input_bundle(self, cases):
        for case in cases:
            assert "input_bundle" in case
            assert "ligand" in case["input_bundle"]
            assert "receptor" in case["input_bundle"]
            assert "morans_r" in case["input_bundle"]

    def test_each_case_has_case_id(self, cases):
        ids = [c["case_id"] for c in cases]
        assert len(ids) == len(set(ids)), "Duplicate case IDs"

    def test_invalid_cases_raise(self, tmp_path):
        bad = [{"case_id": "bad"}]
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="missing keys"):
            load_cases(p)


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


class TestPromptRendering:
    def test_three_variants_exist(self):
        assert len(ALL_VARIANTS) == 3

    def test_variant_a_is_shortest(self):
        a = build_system_prompt(VARIANT_A)
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        assert len(a) < len(b)
        assert len(a) < len(c)

    def test_variant_a_requests_free_text(self):
        a = build_system_prompt(VARIANT_A)
        assert "2-3 paragraphs" in a
        assert "JSON" not in a
        assert "probe" not in a.lower()

    def test_variant_b_contains_prose_not_markdown(self):
        b = build_system_prompt(VARIANT_B)
        assert "## CCI" not in b
        assert "calibrate" in b.lower()

    def test_variant_c_contains_structured_markdown(self):
        c = build_system_prompt(VARIANT_C)
        assert "## CCI Biological Interpretation Skill" in c
        assert "### Spatial Evidence Calibration" in c
        assert "| Moran's R |" in c

    def test_all_variants_share_base_prompt(self):
        a = build_system_prompt(VARIANT_A)
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        assert b.startswith(a[:100])
        assert c.startswith(a[:100])

    def test_user_prompt_contains_evidence_no_probes(self, sample_case):
        up = build_user_prompt(sample_case)
        assert "EFNB2" in up
        assert "Moran's R" in up
        assert "Write your biological interpretation" in up
        assert "probe" not in up.lower()
        assert "Options:" not in up

    def test_unknown_variant_raises(self):
        with pytest.raises(ValueError):
            build_system_prompt("D_nonexistent")


# ---------------------------------------------------------------------------
# Content equivalence (B vs C)
# ---------------------------------------------------------------------------


class TestContentEquivalence:
    """Verify B and C contain identical information content (format only differs)."""

    # Every specific term that must appear in BOTH B and C
    REQUIRED_TERMS = [
        # Receptor gene names (previously C-only)
        ("TNFRSF10C", "specific decoy receptor gene name"),
        ("DcR1", "decoy receptor alias"),
        ("ACKR3", "specific atypical chemokine receptor gene name"),
        ("CXCR7", "atypical chemokine receptor alias"),
        # Evidence hierarchy keywords
        ("GenePT", "functional evidence tier"),
        ("progeny", "pathway evidence tier"),
        # Receptor subtype check
        ("receptor subtype", "subtype classification check"),
        # NEVER rules
        ("fabricate signaling", "NEVER fabricate rule"),
        ("tissue-specific", "NEVER tissue claim rule"),
        ("extrapolate", "NEVER extrapolate rule"),
        # Precise directionality threshold
        ("two or fewer", "precise directionality threshold in B"),
        # Spatial calibration thresholds
        ("0.3", "strong spatial threshold"),
        ("0.1", "moderate spatial threshold"),
        # Confidence levels
        ("high", "confidence level"),
        ("moderate", "confidence level"),
        ("insufficient", "confidence level"),
    ]

    def test_b_contains_all_required_terms(self):
        b = build_system_prompt(VARIANT_B)
        for term, desc in self.REQUIRED_TERMS:
            assert term.lower() in b.lower(), f"B missing '{term}' ({desc})"

    def test_c_contains_all_required_terms(self):
        c = build_system_prompt(VARIANT_C)
        for term, desc in self.REQUIRED_TERMS:
            # C uses "≤2" instead of "two or fewer" — both express same threshold
            if term == "two or fewer":
                assert "≤2" in c or "two or fewer" in c.lower(), f"C missing directionality threshold"
            else:
                assert term.lower() in c.lower(), f"C missing '{term}' ({desc})"

    def test_a_does_not_contain_skill_content(self):
        a = build_system_prompt(VARIANT_A)
        assert "TNFRSF10C" not in a
        assert "ACKR3" not in a
        assert "decoy" not in a.lower()
        assert "fabricate signaling" not in a.lower()
        assert "0.3" not in a.split("paragraphs")[0]

    def test_b_has_no_markdown_structure(self):
        b = build_system_prompt(VARIANT_B)
        # B should NOT have structured markdown (that's the format difference)
        assert "## CCI" not in b
        assert "### " not in b.split("guidance")[1] if "guidance" in b else True
        assert "| Moran" not in b  # no tables

    def test_c_has_markdown_structure(self):
        c = build_system_prompt(VARIANT_C)
        assert "## CCI Biological Interpretation Skill" in c
        assert "### Spatial Evidence Calibration" in c
        assert "| Moran's R |" in c


# ---------------------------------------------------------------------------
# Judge output validation
# ---------------------------------------------------------------------------


class TestJudgeValidation:
    def test_perfect_output_validates(self):
        errors = validate_judge_output(_perfect_judge_output())
        assert errors == []

    def test_bad_output_validates(self):
        errors = validate_judge_output(_bad_judge_output())
        assert errors == []

    def test_none_fails(self):
        errors = validate_judge_output(None)
        assert len(errors) > 0

    def test_out_of_range_fails(self):
        bad = _perfect_judge_output()
        bad["faithfulness"] = 6
        errors = validate_judge_output(bad)
        assert any("faithfulness" in e for e in errors)

    def test_negative_fabrication_fails(self):
        bad = _perfect_judge_output()
        bad["fabrication_count"] = -1
        errors = validate_judge_output(bad)
        assert any("fabrication_count" in e for e in errors)

    def test_missing_rationale_fails(self):
        bad = _perfect_judge_output()
        del bad["rationale"]
        errors = validate_judge_output(bad)
        assert any("rationale" in e for e in errors)

    def test_fabricated_claims_must_be_list(self):
        bad = _perfect_judge_output()
        bad["fabricated_claims"] = "not a list"
        errors = validate_judge_output(bad)
        assert any("fabricated_claims" in e for e in errors)


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------


class TestCompositeScore:
    def test_perfect_score_is_5(self):
        score = compute_composite_score(_perfect_judge_output())
        assert abs(score - 5.0) < 0.001

    def test_bad_score_is_low(self):
        score = compute_composite_score(_bad_judge_output())
        assert score < 2.0

    def test_score_range(self):
        for f in (1, 3, 5):
            for oc in (1, 3, 5):
                for uh in (1, 3, 5):
                    score = compute_composite_score({
                        "faithfulness": f, "overclaiming": oc,
                        "uncertainty_handling": uh, "spatial_calibration": 3,
                        "fabrication_count": 0,
                    })
                    assert 0.0 <= score <= 5.5  # slight margin for rounding

    def test_weights_sum_to_1(self):
        total = sum(d["weight"] for d in JUDGE_DIMENSIONS.values())
        assert abs(total - 1.0) < 0.001

    def test_fabrication_count_capped_at_5(self):
        s1 = compute_composite_score({
            "faithfulness": 3, "overclaiming": 3, "uncertainty_handling": 3,
            "spatial_calibration": 3, "fabrication_count": 5,
        })
        s2 = compute_composite_score({
            "faithfulness": 3, "overclaiming": 3, "uncertainty_handling": 3,
            "spatial_calibration": 3, "fabrication_count": 100,
        })
        assert s1 == s2  # Both capped at 5


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------


class TestCohensKappa:
    def test_perfect_agreement(self):
        a = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
        b = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
        assert compute_cohens_kappa(a, b) == 1.0

    def test_no_agreement(self):
        a = [1, 1, 1, 1, 1]
        b = [5, 5, 5, 5, 5]
        k = compute_cohens_kappa(a, b)
        assert k <= 0.0  # At or worse than chance

    def test_moderate_agreement(self):
        a = [1, 2, 3, 4, 5, 3, 4, 2, 1, 5]
        b = [1, 2, 3, 4, 5, 4, 3, 2, 1, 4]
        k = compute_cohens_kappa(a, b)
        assert 0.3 < k < 1.0

    def test_empty_lists(self):
        assert compute_cohens_kappa([], []) == 0.0

    def test_mismatched_lengths(self):
        assert compute_cohens_kappa([1, 2], [1]) == 0.0


# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------


class TestJudgePrompt:
    def test_judge_prompt_contains_evidence(self, sample_case):
        prompt = _build_judge_prompt(sample_case, "Test interpretation")
        assert "EFNB2" in prompt
        assert "Moran's R" in prompt
        assert "Test interpretation" in prompt

    def test_judge_prompt_contains_rubric(self, sample_case):
        prompt = _build_judge_prompt(sample_case, "Test")
        assert "Faithfulness" in prompt
        assert "Fabrication Count" in prompt
        assert "Overclaiming" in prompt
        assert "fabricated_claims" in prompt

    def test_judge_prompt_requests_json(self, sample_case):
        prompt = _build_judge_prompt(sample_case, "Test")
        assert "JSON" in prompt


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


class TestStatistics:
    def _make_trials(self, a_score=2.0, b_score=3.5, c_score=4.5, n=10):
        trials = []
        jo_template = _perfect_judge_output()
        for variant, base_score in [(VARIANT_A, a_score), (VARIANT_B, b_score), (VARIANT_C, c_score)]:
            for i in range(n):
                jo = dict(jo_template)
                jo["faithfulness"] = max(1, min(5, int(base_score)))
                jo["overclaiming"] = max(1, min(5, int(base_score)))
                composite = compute_composite_score(jo)
                trials.append(_make_trial(variant, composite, judge_outputs=[jo, jo]))
        return trials

    def test_summary_has_all_variants(self):
        trials = self._make_trials()
        summary = summarize_trials(trials)
        for v in ALL_VARIANTS:
            assert v in summary["variants"]

    def test_summary_trial_count(self):
        trials = self._make_trials(n=5)
        summary = summarize_trials(trials)
        assert summary["trial_count"] == 15

    def test_kruskal_wallis_significant_for_large_effect(self):
        trials = self._make_trials(a_score=1.5, b_score=3.0, c_score=4.8, n=15)
        summary = summarize_trials(trials)
        kw = summary["kruskal_wallis"]
        assert kw["pvalue"] is not None
        assert kw["pvalue"] < 0.05

    def test_pairwise_deltas(self):
        trials = self._make_trials(a_score=2.0, c_score=5.0)
        summary = summarize_trials(trials)
        delta_ac = summary["pairwise_deltas"]["A_no_skill_vs_C_structured_skill"]
        assert delta_ac["delta_mean"] < 0  # A < C (C better)
        assert delta_ac["effect_direction"] == "C_structured_skill_better"

    def test_cohens_kappa_in_summary(self):
        trials = self._make_trials()
        summary = summarize_trials(trials)
        assert "cohens_kappa" in summary
        # With identical judges, kappa should be 1.0
        for dim, k in summary["cohens_kappa"].items():
            assert k == 1.0

    def test_markdown_renders(self):
        trials = self._make_trials()
        summary = summarize_trials(trials)
        md = render_markdown_summary(summary)
        assert "V2" in md
        assert "Composite" in md
        assert "Kappa" in md


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class TestJsonParsing:
    def test_plain_json(self):
        assert parse_json_output('{"key": "val"}') == {"key": "val"}

    def test_fenced_json(self):
        assert parse_json_output('```json\n{"key": "val"}\n```') == {"key": "val"}

    def test_invalid_json(self):
        assert parse_json_output("not json") is None

    def test_empty_string(self):
        assert parse_json_output("") is None
