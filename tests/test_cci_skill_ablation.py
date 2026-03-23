"""Unit tests for CCI Skill Ablation Benchmark infrastructure.

Tests probe scoring, prompt rendering, case validation, blinding,
and statistics computation for the 3-condition CCI hallucination benchmark.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "docs" / "benchmarks" / "cci_skill_ablation"
sys.path.insert(0, str(BENCHMARK_DIR))

from benchmark_cci_core import (
    ALL_VARIANTS,
    CCI_BENCHMARK_TYPE,
    CCI_ERROR_FAMILIES,
    CCI_EXCERPT_LIBRARY,
    VARIANT_A,
    VARIANT_B,
    VARIANT_C,
    V3_PROBE_WEIGHTS,
    _probe_support_score,
    build_system_prompt,
    build_user_prompt,
    load_cases,
    parse_json_output,
    render_markdown_summary,
    score_cci_output,
    summarize_trials,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CASES_PATH = BENCHMARK_DIR / "cases" / "pilot_cci_cases.json"


@pytest.fixture
def cases():
    """Load pilot CCI cases."""
    return load_cases(CASES_PATH)


@pytest.fixture
def sample_case(cases):
    """First pilot case (EFNB2-EPHB4)."""
    return cases[0]


def _perfect_output(case: dict) -> dict:
    """Build a perfect output for a given case."""
    return {
        "lr_pair": f"{case['input_bundle']['ligand']}-{case['input_bundle']['receptor']}",
        "probe_answers": [
            {
                "probe_id": p["probe_id"],
                "answer": p["gold_label"],
                "evidence_refs": p["required_evidence_refs"],
                "justification": "correct",
            }
            for p in case["probes"]
        ],
        "secondary_conclusion": {
            "answer": case["secondary_conclusion"]["gold_label"],
            "evidence_refs": case["secondary_conclusion"]["required_evidence_refs"],
            "justification": "correct",
        },
    }


def _error_output(case: dict) -> dict:
    """Build a maximally wrong output for a given case."""
    return {
        "lr_pair": f"{case['input_bundle']['ligand']}-{case['input_bundle']['receptor']}",
        "probe_answers": [
            {
                "probe_id": p["probe_id"],
                "answer": p["target_error_labels"][0] if p["target_error_labels"] else p["options"][-1],
                "evidence_refs": [],
                "justification": "fabricated",
            }
            for p in case["probes"]
        ],
        "secondary_conclusion": {
            "answer": [o for o in case["secondary_conclusion"]["options"] if o != case["secondary_conclusion"]["gold_label"]][0],
            "evidence_refs": [],
            "justification": "wrong",
        },
    }


# ---------------------------------------------------------------------------
# Case loading and validation
# ---------------------------------------------------------------------------


class TestCaseLoading:
    def test_load_cases_returns_list(self, cases):
        assert isinstance(cases, list)
        assert len(cases) == 5

    def test_each_case_has_required_keys(self, cases):
        required = {"case_id", "benchmark_type", "input_bundle", "evidence_refs", "probes", "secondary_conclusion"}
        for case in cases:
            missing = required - set(case)
            assert not missing, f"Case {case['case_id']} missing: {missing}"

    def test_each_case_has_3_probes(self, cases):
        for case in cases:
            assert len(case["probes"]) == 3, f"Case {case['case_id']} has {len(case['probes'])} probes"

    def test_probe_ids_are_p1_p2_p3(self, cases):
        for case in cases:
            ids = [p["probe_id"] for p in case["probes"]]
            assert ids == ["P1", "P2", "P3"], f"Case {case['case_id']}: {ids}"

    def test_gold_labels_in_options(self, cases):
        for case in cases:
            for probe in case["probes"]:
                assert probe["gold_label"] in probe["options"], (
                    f"Case {case['case_id']} {probe['probe_id']}: "
                    f"gold '{probe['gold_label']}' not in {probe['options']}"
                )
            sec = case["secondary_conclusion"]
            assert sec["gold_label"] in sec["options"]

    def test_error_families_are_valid(self, cases):
        valid_families = set(CCI_ERROR_FAMILIES.keys())
        for case in cases:
            for probe in case["probes"]:
                assert probe["error_family"] in valid_families, (
                    f"Case {case['case_id']} {probe['probe_id']}: "
                    f"unknown error family '{probe['error_family']}'"
                )

    def test_evidence_refs_use_e_numbering(self, cases):
        import re
        for case in cases:
            for ref_id in case["evidence_refs"]:
                assert re.match(r"^E\d+$", ref_id), f"Case {case['case_id']}: bad ref '{ref_id}'"

    def test_categories_cover_spectrum(self, cases):
        categories = {c["category"] for c in cases}
        assert "well_known" in categories
        assert "less_known" in categories
        assert "data_supported" in categories
        assert "ambiguous" in categories

    def test_invalid_cases_raise(self, tmp_path):
        bad = [{"case_id": "bad", "benchmark_type": "test"}]
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
        assert VARIANT_A in ALL_VARIANTS
        assert VARIANT_B in ALL_VARIANTS
        assert VARIANT_C in ALL_VARIANTS

    def test_variant_a_is_shortest(self):
        a = build_system_prompt(VARIANT_A)
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        assert len(a) < len(b), "A should be shorter than B"
        assert len(a) < len(c), "A should be shorter than C"

    def test_variant_b_contains_prose_not_markdown(self):
        b = build_system_prompt(VARIANT_B)
        assert "##" not in b, "B should NOT have markdown headings"
        assert "|" not in b.split("schema")[0], "B should NOT have markdown tables before schema"
        assert "calibrate" in b.lower(), "B should mention calibration"

    def test_variant_c_contains_structured_markdown(self):
        c = build_system_prompt(VARIANT_C)
        assert "## CCI Biological Interpretation Skill" in c
        assert "### Spatial Evidence Calibration" in c
        assert "### Mechanism Grounding Rules" in c
        assert "### Confidence Calibration" in c
        assert "| Moran's R |" in c, "C should have markdown tables"

    def test_all_variants_share_base_prompt(self):
        a = build_system_prompt(VARIANT_A)
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        assert b.startswith(a[:200])
        assert c.startswith(a[:200])

    def test_all_variants_require_json_output(self):
        for v in ALL_VARIANTS:
            sp = build_system_prompt(v)
            assert "JSON" in sp
            assert "probe_answers" in sp

    def test_user_prompt_contains_evidence(self, sample_case):
        up = build_user_prompt(sample_case)
        assert "EFNB2" in up
        assert "EPHB4" in up
        assert "Moran's R" in up
        assert "E1:" in up
        assert "P1" in up

    def test_unknown_variant_raises(self):
        with pytest.raises(ValueError, match="Unknown variant"):
            build_system_prompt("D_nonexistent")


# ---------------------------------------------------------------------------
# Probe scoring
# ---------------------------------------------------------------------------


class TestProbeScoring:
    def test_gold_label_scores_1(self):
        assert _probe_support_score(
            answer="gold", gold_label="gold",
            conservative_labels=["cons"], target_error_labels=["err"],
            options=["gold", "cons", "err", "other"],
        ) == 1.0

    def test_conservative_scores_075(self):
        assert _probe_support_score(
            answer="cons", gold_label="gold",
            conservative_labels=["cons"], target_error_labels=["err"],
            options=["gold", "cons", "err", "other"],
        ) == 0.75

    def test_target_error_scores_0(self):
        assert _probe_support_score(
            answer="err", gold_label="gold",
            conservative_labels=["cons"], target_error_labels=["err"],
            options=["gold", "cons", "err", "other"],
        ) == 0.0

    def test_other_valid_option_scores_025(self):
        assert _probe_support_score(
            answer="other", gold_label="gold",
            conservative_labels=["cons"], target_error_labels=["err"],
            options=["gold", "cons", "err", "other"],
        ) == 0.25

    def test_invalid_answer_scores_0(self):
        assert _probe_support_score(
            answer="invalid", gold_label="gold",
            conservative_labels=["cons"], target_error_labels=["err"],
            options=["gold", "cons", "err", "other"],
        ) == 0.0

    def test_probe_weights_sum_to_1(self):
        assert abs(sum(V3_PROBE_WEIGHTS.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Output scoring (integration)
# ---------------------------------------------------------------------------


class TestOutputScoring:
    def test_perfect_output_scores_zero_error(self, sample_case):
        output = _perfect_output(sample_case)
        metrics = score_cci_output(sample_case, output)
        assert metrics["weighted_probe_error_score"] == 0.0
        assert metrics["probe_support_score"] == 1.0
        assert metrics["malformed_output"] is False
        assert metrics["targeted_error_count"] == 0
        assert metrics["primary_probe_target_error"] is False
        assert metrics["secondary_conclusion_accuracy"] == 1.0

    def test_error_output_scores_max_error(self, sample_case):
        output = _error_output(sample_case)
        metrics = score_cci_output(sample_case, output)
        assert metrics["weighted_probe_error_score"] == 1.0
        assert metrics["probe_support_score"] == 0.0
        assert metrics["targeted_error_count"] == 3
        assert metrics["primary_probe_target_error"] is True

    def test_none_output_is_malformed(self, sample_case):
        metrics = score_cci_output(sample_case, None)
        assert metrics["malformed_output"] is True
        assert metrics["weighted_probe_error_score"] == 1.0

    def test_wrong_probe_count_is_malformed(self, sample_case):
        bad = {"probe_answers": [{"probe_id": "P1", "answer": "x"}]}
        metrics = score_cci_output(sample_case, bad)
        assert metrics["malformed_output"] is True

    def test_evidence_ref_validity(self, sample_case):
        output = _perfect_output(sample_case)
        metrics = score_cci_output(sample_case, output)
        assert metrics["evidence_ref_validity_rate"] > 0.0

    def test_error_family_breakdown_populated(self, sample_case):
        output = _perfect_output(sample_case)
        metrics = score_cci_output(sample_case, output)
        assert len(metrics["error_family_breakdown"]) > 0

    def test_conservative_answer_scores_075(self, cases):
        """Test conservative answer for case with conservative_labels."""
        case = cases[0]  # EFNB2-EPHB4, P2 has conservative_labels
        output = _perfect_output(case)
        output["probe_answers"][1]["answer"] = "moderate_spatial_evidence"
        metrics = score_cci_output(case, output)
        assert 0.0 < metrics["weighted_probe_error_score"] < 1.0
        assert metrics["probe_details"][1]["score"] == 0.75

    def test_all_cases_scoreable(self, cases):
        """Every pilot case can be scored with perfect and error outputs."""
        for case in cases:
            perfect = score_cci_output(case, _perfect_output(case))
            assert perfect["weighted_probe_error_score"] == 0.0, f"Case {case['case_id']} perfect != 0"

            error = score_cci_output(case, _error_output(case))
            assert error["weighted_probe_error_score"] > 0.5, f"Case {case['case_id']} error too low"


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class TestJsonParsing:
    def test_plain_json(self):
        result = parse_json_output('{"key": "val"}')
        assert result == {"key": "val"}

    def test_fenced_json(self):
        result = parse_json_output('```json\n{"key": "val"}\n```')
        assert result == {"key": "val"}

    def test_invalid_json(self):
        assert parse_json_output("not json") is None

    def test_empty_string(self):
        assert parse_json_output("") is None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


class TestStatistics:
    def _make_trials(self, a_error=0.8, b_error=0.5, c_error=0.1, n=10):
        """Create synthetic trials with specified error levels."""
        trials = []
        for variant, error in [(VARIANT_A, a_error), (VARIANT_B, b_error), (VARIANT_C, c_error)]:
            for i in range(n):
                trials.append({
                    "variant": variant,
                    "latency_s": 10.0,
                    "metrics": {
                        "weighted_probe_error_score": error + (i * 0.01),
                        "probe_support_score": 1.0 - error,
                        "primary_probe_target_error_rate": 0.0,
                        "all_probe_target_error_rate": 0.0,
                        "evidence_ref_validity_rate": 0.8,
                        "secondary_conclusion_accuracy": 1.0 if error < 0.5 else 0.0,
                        "malformed_output": False,
                        "error_family_breakdown": {
                            "mechanism_fabrication": error,
                            "uncertainty_underestimation": error * 0.5,
                        },
                    },
                })
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
        trials = self._make_trials(a_error=0.9, b_error=0.5, c_error=0.1, n=20)
        summary = summarize_trials(trials)
        kw = summary["kruskal_wallis"]
        assert kw["pvalue"] is not None
        assert kw["pvalue"] < 0.05, f"Expected significant p-value, got {kw['pvalue']}"

    def test_pairwise_deltas_computed(self):
        trials = self._make_trials()
        summary = summarize_trials(trials)
        assert "A_no_skill_vs_C_structured_skill" in summary["pairwise_deltas"]
        assert "B_unstructured_prose_vs_C_structured_skill" in summary["pairwise_deltas"]
        delta_ac = summary["pairwise_deltas"]["A_no_skill_vs_C_structured_skill"]["delta_mean"]
        assert delta_ac > 0, "A should have higher error than C"

    def test_error_family_breakdown_in_summary(self):
        trials = self._make_trials()
        summary = summarize_trials(trials)
        efb = summary["error_family_by_variant"]
        assert VARIANT_A in efb
        assert "mechanism_fabrication" in efb[VARIANT_A]

    def test_markdown_report_renders(self):
        trials = self._make_trials()
        summary = summarize_trials(trials)
        md = render_markdown_summary(summary)
        assert "CCI Skill Ablation Benchmark" in md
        assert "Kruskal-Wallis" in md
        assert VARIANT_A in md
        assert VARIANT_C in md


# ---------------------------------------------------------------------------
# Excerpt library
# ---------------------------------------------------------------------------


class TestExcerptLibrary:
    def test_excerpts_have_required_fields(self):
        required = {"excerpt_id", "skill_name", "error_families", "title", "text"}
        for eid, excerpt in CCI_EXCERPT_LIBRARY.items():
            missing = required - set(excerpt)
            assert not missing, f"Excerpt {eid} missing: {missing}"

    def test_excerpts_map_to_valid_error_families(self):
        valid_families = set(CCI_ERROR_FAMILIES.keys())
        for eid, excerpt in CCI_EXCERPT_LIBRARY.items():
            for family in excerpt["error_families"]:
                assert family in valid_families, f"Excerpt {eid}: unknown family '{family}'"

    def test_all_error_families_covered_by_excerpts(self):
        """Every error family should be addressed by at least one excerpt."""
        covered = set()
        for excerpt in CCI_EXCERPT_LIBRARY.values():
            covered.update(excerpt["error_families"])
        for family in CCI_ERROR_FAMILIES:
            assert family in covered, f"Error family '{family}' not covered by any excerpt"


# ---------------------------------------------------------------------------
# Content equivalence (B vs C)
# ---------------------------------------------------------------------------


class TestContentEquivalence:
    """Verify that Condition B (prose) and C (structured) contain equivalent information."""

    def test_both_mention_morans_thresholds(self):
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        assert "0.3" in b and "0.3" in c, "Both should mention Moran's R > 0.3 threshold"
        assert "0.1" in b and "0.1" in c, "Both should mention Moran's R 0.1 threshold"

    def test_both_mention_confidence_levels(self):
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        for level in ["high", "moderate", "low", "insufficient"]:
            # Case-insensitive check
            assert level.lower() in b.lower(), f"B missing confidence level: {level}"
            assert level.lower() in c.lower(), f"C missing confidence level: {level}"

    def test_both_mention_decoy_receptor(self):
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        assert "decoy" in b.lower(), "B should mention decoy receptors"
        assert "decoy" in c.lower(), "C should mention decoy receptors"

    def test_both_mention_atypical_chemokine(self):
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        assert "atypical" in b.lower(), "B should mention atypical receptors"
        assert "atypical" in c.lower(), "C should mention atypical receptors"

    def test_both_mention_data_first_principle(self):
        b = build_system_prompt(VARIANT_B)
        c = build_system_prompt(VARIANT_C)
        assert "general knowledge" in b.lower()
        assert "general knowledge" in c.lower()

    def test_a_does_not_contain_skill_content(self):
        a = build_system_prompt(VARIANT_A)
        assert "Moran's R > 0.3" not in a
        assert "decoy" not in a.lower()
        assert "hallucination" not in a.lower()
