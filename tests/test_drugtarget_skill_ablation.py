from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    PROJECT_ROOT
    / "docs"
    / "benchmarks"
    / "drugtarget_skill_ablation"
    / "benchmark_core.py"
)
V3_SWEEP_MODULE_PATH = (
    PROJECT_ROOT
    / "docs"
    / "benchmarks"
    / "drugtarget_skill_ablation"
    / "benchmark_stage2_interpretation_v3_sweep.py"
)
V3_REJUDGE_MODULE_PATH = (
    PROJECT_ROOT
    / "docs"
    / "benchmarks"
    / "drugtarget_skill_ablation"
    / "benchmark_stage2_interpretation_v3_rejudge.py"
)
V4_RUNNER_MODULE_PATH = (
    PROJECT_ROOT
    / "docs"
    / "benchmarks"
    / "drugtarget_skill_ablation"
    / "benchmark_stage2_interpretation_v4.py"
)


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_module():
    return _load_module_from_path("drugtarget_skill_ablation_benchmark_core", MODULE_PATH)


@pytest.mark.asyncio
async def test_render_skill_prompt_exposes_only_selected_stage2_skills():
    mod = load_module()

    prompt = await mod.render_skill_prompt(
        "Base system prompt.",
        skill_registry=mod.MAIN_STAGE2_SKILL_REGISTRY,
    )
    empty_prompt = await mod.render_skill_prompt(
        "Base system prompt.",
        skill_registry={},
    )

    assert "Base system prompt." in prompt
    assert "opentargets-database" in prompt
    assert "gwas-database" in prompt
    assert "chembl-database" not in prompt
    assert "No skills registered" in empty_prompt


@pytest.mark.asyncio
async def test_variant_b_prompt_requires_reading_each_exposed_skill_file():
    mod = load_module()

    base_prompt = await mod.render_skill_prompt(
        mod.build_system_prompt(mod.MAIN_STAGE2_BENCHMARK),
        skill_registry=mod.MAIN_STAGE2_SKILL_REGISTRY,
    )

    enforced_prompt = mod.enforce_skill_read_requirement(
        base_prompt,
        variant=mod.VARIANT_B,
        skill_registry=mod.MAIN_STAGE2_SKILL_REGISTRY,
    )
    control_prompt = mod.enforce_skill_read_requirement(
        base_prompt,
        variant=mod.VARIANT_A,
        skill_registry=mod.MAIN_STAGE2_SKILL_REGISTRY,
    )

    assert "Before you score the case, you MUST call `read_skill_file`" in enforced_prompt
    assert str(mod.PROJECT_ROOT / "skills" / "opentargets-database" / "SKILL.md") in enforced_prompt
    assert str(mod.PROJECT_ROOT / "skills" / "gwas-database" / "SKILL.md") in enforced_prompt
    assert "Before you score the case, you MUST call `read_skill_file`" not in control_prompt


def test_preload_skill_guidance_reads_each_exposed_skill_document(monkeypatch: pytest.MonkeyPatch):
    mod = load_module()
    seen_paths: list[str] = []

    def fake_loader(skill_path: str, *, offset: int = 0, limit: int = 2000):
        seen_paths.append(skill_path)
        return f"loaded::{Path(skill_path).name}::{offset}::{limit}"

    monkeypatch.setattr(mod, "_load_skill_doc", fake_loader)

    rendered = mod.preload_skill_guidance(mod.MAIN_STAGE2_SKILL_REGISTRY)

    assert seen_paths == [
        str(mod.PROJECT_ROOT / "skills" / "opentargets-database" / "SKILL.md"),
        str(mod.PROJECT_ROOT / "skills" / "gwas-database" / "SKILL.md"),
    ]
    assert "loaded::SKILL.md" in rendered
    assert "opentargets-database" in rendered
    assert "gwas-database" in rendered


def test_append_preloaded_skill_guidance_only_changes_b_arm():
    mod = load_module()

    base_prompt = "Base system prompt."
    guidance = "Loaded skill guidance."

    prompt_a = mod.append_preloaded_skill_guidance(
        base_prompt,
        variant=mod.VARIANT_A,
        preloaded_guidance=guidance,
    )
    prompt_b = mod.append_preloaded_skill_guidance(
        base_prompt,
        variant=mod.VARIANT_B,
        preloaded_guidance=guidance,
    )

    assert prompt_a == base_prompt
    assert "Loaded skill guidance." in prompt_b
    assert "Preloaded Skill Guidance" in prompt_b


def test_load_judge_model_configs_rejects_overlap_with_generator(monkeypatch: pytest.MonkeyPatch):
    mod = load_module()
    generator_cfg = {
        "label": "gpt-4.1",
        "provider": "openai",
        "model_kwargs": {"model": "gpt-4.1", "temperature": 0},
    }

    monkeypatch.setenv(
        "DRUGTARGET_BENCHMARK_JUDGE_MODELS",
        "openai:gpt-4.1,ollama:qwen3.5:35b,ollama:qwen3.5:122b",
    )

    with pytest.raises(ValueError, match="must not overlap"):
        mod.load_judge_model_configs(generator_cfg)


def test_judge_winner_prefers_non_major_error_then_score_margin():
    mod = load_module()

    parsed = {
        "output_a": {
            "grounding": 3,
            "rubric_alignment": 3,
            "unsupported_claim_penalty": 0,
            "major_error": False,
            "notes": "strong",
        },
        "output_b": {
            "grounding": 3,
            "rubric_alignment": 3,
            "unsupported_claim_penalty": 0,
            "major_error": True,
            "notes": "major error",
        },
        "confidence": "medium",
        "rationale": "A avoids a major error.",
    }
    assert mod._judge_winner_from_rubric(parsed) == "A"

    parsed["output_b"]["major_error"] = False
    parsed["output_b"]["grounding"] = 1
    parsed["output_b"]["rubric_alignment"] = 1
    assert mod._judge_winner_from_rubric(parsed) == "A"

    parsed["output_b"]["grounding"] = 3
    parsed["output_b"]["rubric_alignment"] = 2
    parsed["output_b"]["unsupported_claim_penalty"] = 0
    assert mod._judge_winner_from_rubric(parsed) == "tie"


def test_blinded_output_order_is_seeded_and_reproducible():
    mod = load_module()
    trial_a = {"variant": mod.VARIANT_A, "raw_output": "A"}
    trial_b = {"variant": mod.VARIANT_B, "raw_output": "B"}

    first = mod._blinded_output_order(
        case_id="case-1",
        repeat_index=0,
        judge_label="judge-x",
        trial_a=trial_a,
        trial_b=trial_b,
    )
    second = mod._blinded_output_order(
        case_id="case-1",
        repeat_index=0,
        judge_label="judge-x",
        trial_a=trial_a,
        trial_b=trial_b,
    )

    assert first[2] == second[2]
    assert first[0]["variant"] == second[0]["variant"]
    assert first[1]["variant"] == second[1]["variant"]


def test_aggregate_panel_verdict_handles_majority_and_unanimity():
    mod = load_module()
    unanimous_rows = [
        {"judge_label": "j1", "winner": mod.VARIANT_B, "validation_errors": [], "rationale": "b", "deltas": {}},
        {"judge_label": "j2", "winner": mod.VARIANT_B, "validation_errors": [], "rationale": "b", "deltas": {}},
        {"judge_label": "j3", "winner": mod.VARIANT_B, "validation_errors": [], "rationale": "b", "deltas": {}},
    ]
    unanimous = mod.aggregate_panel_verdict(
        case_id="case-1",
        repeat_index=0,
        model_label="gpt-4.1",
        judge_rows=unanimous_rows,
    )
    assert unanimous["winner"] == mod.VARIANT_B
    assert unanimous["confidence"] == "high"
    assert unanimous["unanimous"] is True

    split_rows = [
        {"judge_label": "j1", "winner": mod.VARIANT_A, "validation_errors": [], "rationale": "a", "deltas": {}},
        {"judge_label": "j2", "winner": mod.VARIANT_B, "validation_errors": [], "rationale": "b", "deltas": {}},
        {"judge_label": "j3", "winner": mod.VARIANT_B, "validation_errors": [], "rationale": "b", "deltas": {}},
    ]
    split = mod.aggregate_panel_verdict(
        case_id="case-2",
        repeat_index=0,
        model_label="gpt-4.1",
        judge_rows=split_rows,
    )
    assert split["winner"] == mod.VARIANT_B
    assert split["confidence"] == "medium"
    assert split["unanimous"] is False


def test_select_human_audit_cases_includes_conflicts_and_stratified_sample():
    mod = load_module()
    case_map = {
        "c1": {"benchmark_type": mod.MAIN_STAGE2_BENCHMARK, "input_bundle": {}, "judge_focus": []},
        "c2": {"benchmark_type": mod.MAIN_STAGE2_BENCHMARK, "input_bundle": {}, "judge_focus": []},
        "c3": {"benchmark_type": mod.MAIN_STAGE2_BENCHMARK, "input_bundle": {}, "judge_focus": []},
    }
    panel_verdicts = [
        {
            "case_id": "c1",
            "repeat_index": 0,
            "model": "gpt-4.1",
            "winner": mod.VARIANT_A,
            "confidence": "medium",
            "unanimous": False,
            "vote_counts": {mod.VARIANT_A: 2, mod.VARIANT_B: 1, "tie": 0},
        },
        {
            "case_id": "c2",
            "repeat_index": 0,
            "model": "gpt-4.1",
            "winner": mod.VARIANT_B,
            "confidence": "high",
            "unanimous": True,
            "vote_counts": {mod.VARIANT_A: 0, mod.VARIANT_B: 3, "tie": 0},
        },
        {
            "case_id": "c3",
            "repeat_index": 0,
            "model": "gpt-4.1",
            "winner": "tie",
            "confidence": "high",
            "unanimous": True,
            "vote_counts": {mod.VARIANT_A: 0, mod.VARIANT_B: 0, "tie": 3},
        },
    ]
    trial_pairs = {
        ("c1", 0, "gpt-4.1"): {
            mod.VARIANT_A: {"variant": mod.VARIANT_A, "raw_output": "A1", "metrics": {"exact_match_rate": 0.8}},
            mod.VARIANT_B: {"variant": mod.VARIANT_B, "raw_output": "B1", "metrics": {"exact_match_rate": 0.6}},
        },
        ("c2", 0, "gpt-4.1"): {
            mod.VARIANT_A: {"variant": mod.VARIANT_A, "raw_output": "A2", "metrics": {"exact_match_rate": 0.2}},
            mod.VARIANT_B: {"variant": mod.VARIANT_B, "raw_output": "B2", "metrics": {"exact_match_rate": 0.9}},
        },
        ("c3", 0, "gpt-4.1"): {
            mod.VARIANT_A: {"variant": mod.VARIANT_A, "raw_output": "A3", "metrics": {"exact_match_rate": 0.5}},
            mod.VARIANT_B: {"variant": mod.VARIANT_B, "raw_output": "B3", "metrics": {"exact_match_rate": 0.5}},
        },
    }

    queue = mod.select_human_audit_cases(
        panel_verdicts=panel_verdicts,
        trial_pairs=trial_pairs,
        case_map=case_map,
        sample_rate=0.2,
    )

    queue_ids = {item["audit_id"] for item in queue}
    assert "gpt-4.1::c1::0" in queue_ids
    assert len(queue) >= 2


def test_load_case_files_and_validate_expected_counts():
    mod = load_module()

    stage2_cases = mod.load_cases(mod.CASES_DIR / "stage2_synthesis_cases.json")
    stage2_v2_cases = mod.load_cases(mod.CASES_DIR / "stage2_interpretation_v2_cases.json")
    stage2_v3_cases = mod.load_cases(mod.CASES_DIR / "stage2_interpretation_v3_cases.json")
    stage2_v4_cases = mod.load_cases(mod.CASES_DIR / "stage2_interpretation_v4_cases.json")
    chembl_cases = mod.load_cases(mod.CASES_DIR / "chembl_micro_cases.json")
    excerpt_library = mod.load_skill_excerpt_library()
    rule_library = mod.load_skill_rule_library()

    assert len(stage2_cases) == 14
    assert len(stage2_v2_cases) == 14
    assert len(stage2_v3_cases) == 14
    assert len(stage2_v4_cases) >= 6
    assert len(chembl_cases) == 4
    assert excerpt_library
    assert rule_library

    stage2_ids = {case["case_id"] for case in stage2_cases}
    stage2_v2_ids = {case["case_id"] for case in stage2_v2_cases}
    stage2_v3_ids = {case["case_id"] for case in stage2_v3_cases}
    stage2_v4_ids = {case["case_id"] for case in stage2_v4_cases}
    chembl_ids = {case["case_id"] for case in chembl_cases}

    assert "real_flt1_breast" in stage2_ids
    assert "perturbation_approval_scope_mismatch" in stage2_ids
    assert "real_vegfa_breast" in stage2_v2_ids
    assert "perturbation_uncertainty_high_mixed_signal" in stage2_v2_ids
    assert "real_vegfa_breast" in stage2_v3_ids
    assert "perturbation_trait_ambiguity" in stage2_v4_ids
    assert "perturbation_trait_ambiguity" in stage2_ids
    assert "chembl_preclinical_potency_not_clinical_support" in chembl_ids

    required_case_keys = {
        "case_id",
        "benchmark_type",
        "source_type",
        "input_bundle",
        "gold_assessment",
        "expected_classification",
        "expected_priority",
        "judge_focus",
        "notes",
    }
    for case in stage2_cases:
        assert required_case_keys.issubset(case)

    for case in stage2_v2_cases:
        assert case["benchmark_type"] == mod.STAGE2_INTERPRETATION_V2_BENCHMARK
        assert "input_bundle" in case
        assert "interpretation_checks" in case
        assert len(case["interpretation_checks"]) >= 3
        assert case["overall_conclusion"]["gold_label"]
        assert case["expected_uncertainty"]["gold_label"]

    for case in stage2_v3_cases:
        assert case["benchmark_type"] == mod.STAGE2_INTERPRETATION_V3_BENCHMARK
        assert "input_bundle" in case
        assert "evidence_refs" in case
        assert "skill_excerpt_ids" in case
        assert len(case["probes"]) == 3
        assert case["secondary_conclusion"]["gold_label"]

    for case in stage2_v4_cases:
        assert case["benchmark_type"] == mod.STAGE2_INTERPRETATION_V4_BENCHMARK
        assert "input_bundle" in case
        assert "rule_ids" in case
        assert len(case["probes"]) == 3
        assert case["secondary_conclusion"]["gold_label"]
        assert case["source_type"] == "v4_overlay"

    for excerpt_id, excerpt in excerpt_library.items():
        assert excerpt_id
        assert excerpt["skill_name"] in {"opentargets-database", "gwas-database"}
        assert excerpt["text"]
        assert excerpt["source_line_ref"]

    for rule_id, rule in rule_library.items():
        assert rule_id
        assert rule["skill_name"] in {"opentargets-database", "gwas-database"}
        assert rule["directive"]
        assert rule["source_line_ref"]


def test_build_case_rule_guidance_uses_only_requested_rules_and_caps_budget():
    mod = load_module()
    case = {
        "rule_ids": ["r1", "r2", "r3"],
        "probes": [
            {"required_rule_ids": ["r1"]},
            {"required_rule_ids": ["r2"]},
            {"required_rule_ids": ["r3"]},
        ],
    }
    rule_library = {
        "r1": {
            "rule_id": "r1",
            "skill_name": "gwas-database",
            "error_family": "gwas_strength_inflation",
            "title": "GWAS threshold",
            "directive": "Do not upgrade suggestive p-values to genome-wide significance.",
            "source_path": "skills/gwas-database/SKILL.md",
            "source_line_ref": "L1",
        },
        "r2": {
            "rule_id": "r2",
            "skill_name": "opentargets-database",
            "error_family": "safety_underweighting",
            "title": "Safety",
            "directive": "Safety liabilities must reduce optimism.",
            "source_path": "skills/opentargets-database/SKILL.md",
            "source_line_ref": "L2",
        },
        "r3": {
            "rule_id": "r3",
            "skill_name": "gwas-database",
            "error_family": "trait_alignment_inflation",
            "title": "Trait mapping",
            "directive": "Related traits are not automatically disease matched.",
            "source_path": "skills/gwas-database/SKILL.md",
            "source_line_ref": "L3",
        },
    }

    guidance = mod.build_case_rule_guidance(case, rule_library=rule_library, max_tokens=16)

    assert "GWAS threshold" in guidance
    assert "Safety" in guidance
    assert "Trait mapping" not in guidance
    assert "skills/gwas-database/SKILL.md" in guidance


def test_parse_benchmark_output_recovers_json_from_code_fence():
    mod = load_module()
    payload = {
        "gene_symbol": "FLT1",
        "validated_track": {
            "existing_drug_evidence": {"score": 3, "rationale": "approved"},
            "clinical_trial_activity": {"score": 3, "rationale": "advanced"},
            "mechanism_relevance": {"score": 3, "rationale": "direct"},
            "safety_profile": {"score": -1, "rationale": "vascular"},
        },
        "exploratory_track": {
            "gwas_genetic_support": {"score": 2, "rationale": "gws"},
            "tractability": {"score": 3, "rationale": "approved modality"},
            "biological_plausibility": {"score": 3, "rationale": "strong"},
            "novelty_opportunity": {"score": 0, "rationale": "established"},
        },
        "classification": "validated_target",
        "priority": "high",
        "summary": "FLT1 is a validated target.",
    }
    text = f"```json\n{json.dumps(payload, indent=2)}\n```"

    parsed = mod.parse_benchmark_output(text)

    assert parsed["gene_symbol"] == "FLT1"
    assert parsed["validated_track"]["existing_drug_evidence"]["score"] == 3


def test_score_main_case_supports_exact_and_near_matches():
    mod = load_module()
    case = next(
        case
        for case in mod.load_cases(mod.CASES_DIR / "stage2_synthesis_cases.json")
        if case["case_id"] == "real_flt1_breast"
    )

    exact_output = {
        "gene_symbol": "FLT1",
        "validated_track": {
            "existing_drug_evidence": {"score": 3, "rationale": "approved anti-VEGFR"},
            "clinical_trial_activity": {"score": 3, "rationale": "multiple advanced trials"},
            "mechanism_relevance": {"score": 3, "rationale": "angiogenesis"},
            "safety_profile": {"score": -1, "rationale": "vascular toxicity"},
        },
        "exploratory_track": {
            "gwas_genetic_support": {"score": 2, "rationale": "p <= 5e-8"},
            "tractability": {"score": 3, "rationale": "approved modality"},
            "biological_plausibility": {"score": 3, "rationale": "multi-evidence"},
            "novelty_opportunity": {"score": 0, "rationale": "established target"},
        },
        "classification": "validated_target",
        "priority": "high",
        "summary": "Supported by strong OT, GWAS, and clinical evidence.",
    }
    near_output = json.loads(json.dumps(exact_output))
    near_output["exploratory_track"]["gwas_genetic_support"]["score"] = 1

    exact_metrics = mod.score_stage2_output(case, exact_output)
    near_metrics = mod.score_stage2_output(case, near_output)

    assert exact_metrics["exact_match_count"] == 8
    assert exact_metrics["near_match_count"] == 8
    assert exact_metrics["classification_correct"] is True
    assert exact_metrics["priority_correct"] is True

    assert near_metrics["exact_match_count"] == 7
    assert near_metrics["near_match_count"] == 8
    assert near_metrics["classification_correct"] is True


def test_score_chembl_micro_case_uses_validated_track_only():
    mod = load_module()
    case = next(
        case
        for case in mod.load_cases(mod.CASES_DIR / "chembl_micro_cases.json")
        if case["case_id"] == "chembl_preclinical_potency_not_clinical_support"
    )

    parsed_output = {
        "gene_symbol": "SPP1",
        "validated_track": {
            "existing_drug_evidence": {"score": 0, "rationale": "preclinical only"},
            "clinical_trial_activity": {"score": 0, "rationale": "no matching trials"},
            "mechanism_relevance": {"score": 2, "rationale": "plausible target biology"},
            "safety_profile": {"score": 0, "rationale": "limited known safety issues"},
        },
        "summary": "Potent bioactivity alone does not establish clinical evidence.",
    }

    metrics = mod.score_chembl_output(case, parsed_output)

    assert metrics["exact_match_count"] == 4
    assert metrics["near_match_count"] == 4
    assert metrics["malformed_output"] is False


def test_score_stage2_interpretation_v2_output_supports_exact_partial_and_overclaim():
    mod = load_module()
    case = next(
        case
        for case in mod.load_cases(mod.CASES_DIR / "stage2_interpretation_v2_cases.json")
        if case["case_id"] == "perturbation_gwas_significance_boundary"
    )

    parsed_output = {
        "gene_symbol": "PLXNB2",
        "interpretation_checks": [
            {
                "check_id": "genetic_support",
                "answer": "suggestive",
                "justification": "Best association is p = 2e-6 from a single cohort, and there is no independent replication; do not treat as genome-wide significant.",
            },
            {
                "check_id": "clinical_precedence",
                "answer": "none",
                "justification": "No approved or clinical disease-matched therapies are reported, and there are no matched clinical trials.",
            },
            {
                "check_id": "tractability_signal",
                "answer": "clinical_precedent",
                "justification": "Predicted tractability only; no clinical precedent is actually stated.",
            },
        ],
        "overall_conclusion": {
            "answer": "exploratory_target",
            "justification": "Moderate disease association exists, but the genetics remain sub-threshold and unreplicated.",
        },
        "uncertainty": {
            "answer": "high",
            "justification": "The best association is only p = 2e-6 from a single cohort and lacks independent replication.",
        },
        "summary": "Interpret conservatively.",
    }

    metrics = mod.score_stage2_interpretation_v2_output(case, parsed_output)

    assert metrics["exact_check_count"] == 2
    assert metrics["partial_credit_accuracy"] == pytest.approx(2.0 / 3.0)
    assert metrics["interpretation_score"] == pytest.approx((2.0 / 3.0 + 1.0 + 1.0) / 3.0)
    assert metrics["overall_conclusion_correct"] is True
    assert metrics["uncertainty_correct"] is True
    assert metrics["overclaim_rate"] == pytest.approx(1.0 / 3.0)
    assert metrics["rationale_anchor_coverage"] is not None


def test_summarize_trials_v2_uses_case_level_pairing_not_raw_repeat_rows():
    mod = load_module()

    trials = [
        {
            "benchmark_type": mod.STAGE2_INTERPRETATION_V2_BENCHMARK,
            "case_id": "c1",
            "model": "openai:gpt-4.1",
            "repeat_index": 0,
            "variant": mod.VARIANT_A,
            "latency_s": 1.0,
            "tool_history": [],
            "token_usage": {"total_tokens": 100},
            "metrics": {
                "interpretation_score": 0.25,
                "exact_check_accuracy": 0.25,
                "partial_credit_accuracy": 0.25,
                "overall_conclusion_correct": False,
                "uncertainty_correct": False,
                "overclaim_rate": 0.5,
                "malformed_output": False,
                "rationale_anchor_coverage": 0.5,
            },
        },
        {
            "benchmark_type": mod.STAGE2_INTERPRETATION_V2_BENCHMARK,
            "case_id": "c1",
            "model": "openai:gpt-4.1",
            "repeat_index": 1,
            "variant": mod.VARIANT_A,
            "latency_s": 1.0,
            "tool_history": [],
            "token_usage": {"total_tokens": 100},
            "metrics": {
                "interpretation_score": 0.75,
                "exact_check_accuracy": 0.75,
                "partial_credit_accuracy": 0.75,
                "overall_conclusion_correct": True,
                "uncertainty_correct": True,
                "overclaim_rate": 0.0,
                "malformed_output": False,
                "rationale_anchor_coverage": 1.0,
            },
        },
        {
            "benchmark_type": mod.STAGE2_INTERPRETATION_V2_BENCHMARK,
            "case_id": "c1",
            "model": "openai:gpt-4.1",
            "repeat_index": 0,
            "variant": mod.VARIANT_B,
            "latency_s": 1.0,
            "tool_history": [],
            "token_usage": {"total_tokens": 100},
            "metrics": {
                "interpretation_score": 0.75,
                "exact_check_accuracy": 0.75,
                "partial_credit_accuracy": 0.75,
                "overall_conclusion_correct": True,
                "uncertainty_correct": True,
                "overclaim_rate": 0.0,
                "malformed_output": False,
                "rationale_anchor_coverage": 1.0,
            },
        },
        {
            "benchmark_type": mod.STAGE2_INTERPRETATION_V2_BENCHMARK,
            "case_id": "c1",
            "model": "openai:gpt-4.1",
            "repeat_index": 1,
            "variant": mod.VARIANT_B,
            "latency_s": 1.0,
            "tool_history": [],
            "token_usage": {"total_tokens": 100},
            "metrics": {
                "interpretation_score": 1.0,
                "exact_check_accuracy": 1.0,
                "partial_credit_accuracy": 1.0,
                "overall_conclusion_correct": True,
                "uncertainty_correct": True,
                "overclaim_rate": 0.0,
                "malformed_output": False,
                "rationale_anchor_coverage": 1.0,
            },
        },
    ]

    summary = mod.summarize_trials(trials)
    paired = summary["paired_tests"]["interpretation_score_case_level"]

    assert summary["benchmark_type"] == mod.STAGE2_INTERPRETATION_V2_BENCHMARK
    assert paired["pair_unit_count"] == 1
    assert paired["delta_mean"] == pytest.approx(0.375)


def test_build_case_excerpt_guidance_uses_only_requested_excerpts_and_caps_budget():
    mod = load_module()
    case = {
        "skill_excerpt_ids": ["ex1", "ex2", "ex3"],
        "probes": [
            {"required_excerpt_ids": ["ex1"]},
            {"required_excerpt_ids": ["ex2"]},
            {"required_excerpt_ids": ["ex3"]},
        ],
    }
    excerpt_library = {
        "ex1": {
            "skill_name": "gwas-database",
            "title": "Replication",
            "text": "one two three four",
            "source_path": "skills/gwas-database/SKILL.md",
            "source_line_ref": "L1",
        },
        "ex2": {
            "skill_name": "opentargets-database",
            "title": "Safety",
            "text": "five six seven eight",
            "source_path": "skills/opentargets-database/SKILL.md",
            "source_line_ref": "L2",
        },
        "ex3": {
            "skill_name": "gwas-database",
            "title": "Trait mapping",
            "text": "nine ten eleven twelve",
            "source_path": "skills/gwas-database/SKILL.md",
            "source_line_ref": "L3",
        },
    }

    guidance = mod.build_case_excerpt_guidance(case, excerpt_library=excerpt_library, max_tokens=9)

    assert "Replication" in guidance
    assert "Safety" in guidance
    assert "Trait mapping" not in guidance
    assert "skills/gwas-database/SKILL.md" in guidance


def test_score_stage2_interpretation_v3_output_tracks_weighted_probe_error_and_target_errors():
    mod = load_module()
    case = {
        "benchmark_type": mod.STAGE2_INTERPRETATION_V3_BENCHMARK,
        "case_id": "c1",
        "evidence_refs": {"E1": "foo", "E2": "bar", "E3": "baz"},
        "probes": [
            {
                "probe_id": "p1",
                "options": ["a", "b", "c"],
                "gold_label": "a",
                "conservative_labels": ["b"],
                "target_error_labels": ["c"],
                "required_evidence_refs": ["E1"],
            },
            {
                "probe_id": "p2",
                "options": ["a", "b", "c"],
                "gold_label": "a",
                "conservative_labels": ["b"],
                "target_error_labels": ["c"],
                "required_evidence_refs": ["E2"],
            },
            {
                "probe_id": "p3",
                "options": ["a", "b", "c"],
                "gold_label": "a",
                "conservative_labels": ["b"],
                "target_error_labels": ["c"],
                "required_evidence_refs": ["E3"],
            },
        ],
        "secondary_conclusion": {
            "options": ["supported", "unclear"],
            "gold_label": "supported",
            "required_evidence_refs": ["E1", "E2"],
        },
    }
    parsed_output = {
        "gene_symbol": "GENE",
        "probe_answers": [
            {"probe_id": "p1", "answer": "a", "evidence_refs": ["E1"], "justification": "exact"},
            {"probe_id": "p2", "answer": "b", "evidence_refs": ["E2"], "justification": "conservative"},
            {"probe_id": "p3", "answer": "c", "evidence_refs": ["E3"], "justification": "target error"},
        ],
        "secondary_conclusion": {
            "answer": "supported",
            "evidence_refs": ["E1", "E2"],
            "justification": "supported",
        },
    }

    metrics = mod.score_stage2_interpretation_v3_output(case, parsed_output)

    assert metrics["targeted_error_count"] == 1
    assert metrics["primary_probe_target_error"] is False
    assert metrics["all_probe_target_error_rate"] == pytest.approx(1.0 / 3.0)
    assert metrics["weighted_probe_error_score"] == pytest.approx(0.6 * 0.0 + 0.25 * 0.25 + 0.15 * 1.0)
    assert metrics["secondary_conclusion_accuracy"] == pytest.approx(1.0)
    assert metrics["evidence_ref_validity_rate"] == pytest.approx(1.0)


def test_score_stage2_interpretation_v4_output_tracks_rule_validity_and_target_errors():
    mod = load_module()
    case = {
        "benchmark_type": mod.STAGE2_INTERPRETATION_V4_BENCHMARK,
        "case_id": "c1",
        "evidence_refs": {"E1": "foo", "E2": "bar", "E3": "baz"},
        "rule_ids": ["R1", "R2", "R3"],
        "probes": [
            {
                "probe_id": "P1",
                "error_family": "gwas_strength_inflation",
                "options": ["a", "b", "c"],
                "gold_label": "a",
                "conservative_labels": ["b"],
                "target_error_labels": ["c"],
                "required_rule_ids": ["R1"],
                "required_evidence_refs": ["E1"],
            },
            {
                "probe_id": "P2",
                "error_family": "approval_scope_inflation",
                "options": ["a", "b", "c"],
                "gold_label": "a",
                "conservative_labels": ["b"],
                "target_error_labels": ["c"],
                "required_rule_ids": ["R2"],
                "required_evidence_refs": ["E2"],
            },
            {
                "probe_id": "P3",
                "error_family": "uncertainty_underestimation",
                "options": ["a", "b", "c"],
                "gold_label": "a",
                "conservative_labels": ["b"],
                "target_error_labels": ["c"],
                "required_rule_ids": ["R3"],
                "required_evidence_refs": ["E3"],
            },
        ],
        "secondary_conclusion": {
            "options": ["supported", "unclear"],
            "gold_label": "supported",
            "required_evidence_refs": ["E1", "E2"],
            "required_rule_ids": ["R1", "R2"],
        },
    }
    parsed_output = {
        "gene_symbol": "GENE",
        "probe_answers": [
            {
                "probe_id": "P1",
                "answer": "a",
                "applied_rule_ids": ["R1"],
                "evidence_refs": ["E1"],
                "justification": "exact",
            },
            {
                "probe_id": "P2",
                "answer": "b",
                "applied_rule_ids": ["R2"],
                "evidence_refs": ["E2"],
                "justification": "conservative",
            },
            {
                "probe_id": "P3",
                "answer": "c",
                "applied_rule_ids": ["R3"],
                "evidence_refs": ["E3"],
                "justification": "target error",
            },
        ],
        "secondary_conclusion": {
            "answer": "supported",
            "applied_rule_ids": ["R1", "R2"],
            "evidence_refs": ["E1", "E2"],
            "justification": "supported",
        },
    }

    metrics = mod.score_stage2_interpretation_v4_output(case, parsed_output)

    assert metrics["targeted_error_count"] == 1
    assert metrics["primary_probe_target_error"] is False
    assert metrics["all_probe_target_error_rate"] == pytest.approx(1.0 / 3.0)
    assert metrics["weighted_target_error_score"] == pytest.approx(0.6 * 0.0 + 0.25 * 0.25 + 0.15 * 1.0)
    assert metrics["rule_application_validity_rate"] == pytest.approx(1.0)
    assert metrics["secondary_conclusion_accuracy"] == pytest.approx(1.0)
    assert metrics["evidence_ref_validity_rate"] == pytest.approx(1.0)


def test_summarize_trials_v3_uses_a_minus_b_delta_for_weighted_probe_error():
    mod = load_module()
    trials = [
        {
            "benchmark_type": mod.STAGE2_INTERPRETATION_V3_BENCHMARK,
            "case_id": "c1",
            "model": "ollama:qwen3.5:122b",
            "repeat_index": 0,
            "variant": mod.VARIANT_A,
            "latency_s": 1.0,
            "tool_history": [],
            "token_usage": {"total_tokens": 100},
            "metrics": {
                "weighted_probe_error_score": 0.8,
                "primary_probe_target_error_rate": 1.0,
                "all_probe_target_error_rate": 0.5,
                "major_error_rate": 0.0,
                "evidence_ref_validity_rate": 1.0,
                "secondary_conclusion_accuracy": 1.0,
                "malformed_output": False,
            },
        },
        {
            "benchmark_type": mod.STAGE2_INTERPRETATION_V3_BENCHMARK,
            "case_id": "c1",
            "model": "ollama:qwen3.5:122b",
            "repeat_index": 0,
            "variant": mod.VARIANT_B,
            "latency_s": 1.0,
            "tool_history": [],
            "token_usage": {"total_tokens": 100},
            "metrics": {
                "weighted_probe_error_score": 0.2,
                "primary_probe_target_error_rate": 0.0,
                "all_probe_target_error_rate": 0.0,
                "major_error_rate": 0.0,
                "evidence_ref_validity_rate": 1.0,
                "secondary_conclusion_accuracy": 1.0,
                "malformed_output": False,
            },
        },
    ]

    summary = mod.summarize_trials(trials)
    paired = summary["paired_tests"]["weighted_probe_error_score_case_level"]

    assert summary["benchmark_type"] == mod.STAGE2_INTERPRETATION_V3_BENCHMARK
    assert paired["pair_unit_count"] == 1
    assert paired["delta_mean"] == pytest.approx(0.6)


def test_summarize_trials_v4_uses_a_minus_b_delta_for_weighted_target_error():
    mod = load_module()
    trials = [
        {
            "benchmark_type": mod.STAGE2_INTERPRETATION_V4_BENCHMARK,
            "case_id": "c1",
            "model": "ollama:qwen3.5:35b",
            "repeat_index": 0,
            "variant": mod.VARIANT_A,
            "latency_s": 1.0,
            "tool_history": [],
            "token_usage": {"total_tokens": 100},
            "metrics": {
                "weighted_target_error_score": 0.8,
                "primary_probe_target_error_rate": 1.0,
                "all_probe_target_error_rate": 0.5,
                "major_error_rate": 0.0,
                "rule_application_validity_rate": 1.0,
                "evidence_ref_validity_rate": 1.0,
                "secondary_conclusion_accuracy": 1.0,
                "malformed_output": False,
            },
        },
        {
            "benchmark_type": mod.STAGE2_INTERPRETATION_V4_BENCHMARK,
            "case_id": "c1",
            "model": "ollama:qwen3.5:35b",
            "repeat_index": 0,
            "variant": mod.VARIANT_B,
            "latency_s": 1.0,
            "tool_history": [],
            "token_usage": {"total_tokens": 100},
            "metrics": {
                "weighted_target_error_score": 0.2,
                "primary_probe_target_error_rate": 0.0,
                "all_probe_target_error_rate": 0.0,
                "major_error_rate": 0.0,
                "rule_application_validity_rate": 1.0,
                "evidence_ref_validity_rate": 1.0,
                "secondary_conclusion_accuracy": 1.0,
                "malformed_output": False,
            },
        },
    ]

    summary = mod.summarize_trials(trials)
    paired = summary["paired_tests"]["weighted_target_error_score_case_level"]

    assert summary["benchmark_type"] == mod.STAGE2_INTERPRETATION_V4_BENCHMARK
    assert paired["pair_unit_count"] == 1
    assert paired["delta_mean"] == pytest.approx(0.6)


def test_v4_runner_module_loads():
    mod = _load_module_from_path("drugtarget_v4_runner", V4_RUNNER_MODULE_PATH)

    assert hasattr(mod, "main")


def test_select_v3_judge_keys_prefers_nonzero_deltas_and_samples_ties():
    mod = load_module()
    trial_pairs = {
        ("c1", 0, "m"): {
            mod.VARIANT_A: {"metrics": {"weighted_probe_error_score": 0.8}},
            mod.VARIANT_B: {"metrics": {"weighted_probe_error_score": 0.2}},
        },
        ("c2", 0, "m"): {
            mod.VARIANT_A: {"metrics": {"weighted_probe_error_score": 0.5}},
            mod.VARIANT_B: {"metrics": {"weighted_probe_error_score": 0.5}},
        },
        ("c3", 0, "m"): {
            mod.VARIANT_A: {"metrics": {"weighted_probe_error_score": 0.4}},
            mod.VARIANT_B: {"metrics": {"weighted_probe_error_score": 0.4}},
        },
    }

    selected = mod.select_v3_judge_keys(trial_pairs, sample_rate=0.5)

    assert ("c1", 0, "m") in selected
    assert len(selected) >= 2


def test_load_model_configs_from_env_accepts_provider_model_override(monkeypatch: pytest.MonkeyPatch):
    mod = load_module()
    monkeypatch.setenv("DRUGTARGET_BENCHMARK_MODELS", "openai:gpt-4.1")

    cfgs = mod.load_model_configs_from_env()

    assert len(cfgs) == 1
    assert cfgs[0]["label"] == "openai:gpt-4.1"
    assert cfgs[0]["provider"] == "openai"
    assert cfgs[0]["model_kwargs"]["model"] == "gpt-4.1"


def test_v3_sweep_runner_parses_temperatures_and_builds_stems():
    mod = _load_module_from_path("drugtarget_v3_sweep", V3_SWEEP_MODULE_PATH)

    assert mod._parse_temperature_list("0.0, 0.2,0.30,0.4") == [0.0, 0.2, 0.3, 0.4]
    assert mod._temperature_token(0.0) == "t00"
    assert mod._temperature_token(0.3) == "t03"
    assert mod._build_stem("stage2_interpretation_v3_qwen35_122b", 0.3, 5) == (
        "stage2_interpretation_v3_qwen35_122b_t03_r5"
    )


def test_v3_rejudge_runner_parses_judge_models():
    mod = _load_module_from_path("drugtarget_v3_rejudge", V3_REJUDGE_MODULE_PATH)

    judge_cfgs = mod._parse_judge_models(
        "ollama:qwen3.5:35b,ollama:gpt-oss:20b,ollama:qwen3:30b"
    )

    assert [cfg["label"] for cfg in judge_cfgs] == [
        "ollama:qwen3.5:35b",
        "ollama:gpt-oss:20b",
        "ollama:qwen3:30b",
    ]
