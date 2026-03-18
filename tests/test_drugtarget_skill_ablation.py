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


def load_module():
    spec = importlib.util.spec_from_file_location(
        "drugtarget_skill_ablation_benchmark_core",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
    chembl_cases = mod.load_cases(mod.CASES_DIR / "chembl_micro_cases.json")

    assert len(stage2_cases) == 10
    assert len(chembl_cases) == 4

    stage2_ids = {case["case_id"] for case in stage2_cases}
    chembl_ids = {case["case_id"] for case in chembl_cases}

    assert "real_flt1_breast" in stage2_ids
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
