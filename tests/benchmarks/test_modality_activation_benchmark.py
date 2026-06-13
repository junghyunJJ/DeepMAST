from __future__ import annotations

from docs.benchmarks.hypothesis_generation_consistency.phase_activation import (
    DOMAIN_SKILL_UNIVERSE,
)


def test_modality_cases_cover_each_domain_skill() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.modality_activation import (
        MODALITY_ACTIVATION_CASES,
    )

    covered = {
        skill
        for case in MODALITY_ACTIVATION_CASES
        for skill in case.expected_domain_skills
    }

    assert covered == set(DOMAIN_SKILL_UNIVERSE)


def test_modality_cases_include_negative_controls() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.modality_activation import (
        MODALITY_ACTIVATION_CASES,
    )

    negative_case_ids = {
        case.case_id
        for case in MODALITY_ACTIVATION_CASES
        if not case.expected_domain_skills
    }

    assert negative_case_ids >= {
        "negative_schema_only",
        "negative_general_recommendation_style",
    }


def test_modality_prompt_is_production_like_but_not_oracle() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.modality_activation import (
        MODALITY_AWARE_BASE_PROMPT,
    )

    prompt = MODALITY_AWARE_BASE_PROMPT
    assert "hypothesis_writer" in prompt
    assert "load_evidence_files(data_dir, scope=\"hypothesis\")" in prompt
    assert "evidence modality inventory" in prompt
    assert "hypothesis_report.json" in prompt
    assert "A skill counts as activated only if read_skill_file" in prompt
    assert "Do not call external database tools" in prompt
    assert "Stage1 Census ->" not in prompt
    assert "Stage1 STRING ->" not in prompt
    assert "Stage2 OpenTargets ->" not in prompt
    assert "Stage2 GWAS ->" not in prompt
    assert "Stage3 ChEMBL ->" not in prompt
    assert "compare-census-gene-pair-by-cell-type" not in prompt
    assert "string-database" not in prompt
    assert "opentargets-database" not in prompt
    assert "gwas-database" not in prompt
    assert "chembl-database" not in prompt


def test_modality_trial_plan_is_120_for_full_matrix() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.modality_activation import (
        build_modality_trial_plan,
    )

    trials = build_modality_trial_plan(
        models=("qwen3.5:35b", "qwen3.5:122b"),
        ports=(5000, 6000, 7000),
        conditions=("passive_listing", "skill_activator"),
    )

    assert len(trials) == 120
    assert trials[0]["run_id"] == (
        "qwen35b_passive_listing_port5000_stage1_census_loaded"
    )
    assert trials[-1]["run_id"] == (
        "qwen122b_skill_activator_port7000_negative_general_recommendation_style"
    )


def test_modality_runner_default_conditions_include_governor() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_modality_activation_benchmark import (
        DEFAULT_CONDITIONS,
    )

    assert DEFAULT_CONDITIONS == (
        "passive_listing",
        "skill_activator",
        "skill_activation_governor",
    )


def test_modality_runner_builds_governor_middleware_condition() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_modality_activation_benchmark import (
        build_middleware_for_condition,
    )

    middleware = build_middleware_for_condition("skill_activation_governor")

    assert [type(item).__name__ for item in middleware] == [
        "SkillsMiddleware",
        "SkillActivationGovernorPromptMiddleware",
    ]


def test_modality_runner_render_system_prompt_selects_condition_protocol() -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency.run_modality_activation_benchmark import (
        render_system_prompt,
    )

    passive_prompt = asyncio.run(render_system_prompt("passive_listing"))
    activator_prompt = asyncio.run(render_system_prompt("skill_activator"))
    governor_prompt = asyncio.run(render_system_prompt("skill_activation_governor"))

    assert "## Skills System" in passive_prompt
    assert "## Skills System" in activator_prompt
    assert "## Skills System" in governor_prompt
    assert "evidence modality inventory" in passive_prompt
    assert "hypothesis_report.json" in passive_prompt
    assert "## Phase 1" not in passive_prompt
    assert "## Phase 1" in activator_prompt
    assert "Context-match rule" in activator_prompt
    assert "# Skill Activation Governor" in governor_prompt
    assert "Flexible Discovery" in governor_prompt
    assert "Available Skills for Flexible Discovery" in governor_prompt


def test_modality_runner_parse_args_accepts_parallel_ports() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_modality_activation_benchmark import (
        parse_args,
    )

    args = parse_args(
        [
            "--models",
            "qwen3.5:35b,qwen3.5:122b",
            "--ports",
            "5000,6000,7000",
            "--conditions",
            "passive_listing,skill_activator",
            "--trial-timeout-s",
            "120",
            "--parallel-ports",
        ]
    )

    assert args.models == "qwen3.5:35b,qwen3.5:122b"
    assert args.ports == "5000,6000,7000"
    assert args.conditions == "passive_listing,skill_activator"
    assert args.trial_timeout_s == 120.0
    assert args.parallel_ports is True


def test_modality_runner_records_timeout_rows(monkeypatch, tmp_path) -> None:
    import asyncio
    import json

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_modality_activation_benchmark as runner,
    )

    async def fake_run_one_modality_trial(trial, output_root):
        await asyncio.sleep(1.0)
        raise AssertionError("fake trial should be cancelled by timeout")

    monkeypatch.setattr(
        runner,
        "run_one_modality_trial",
        fake_run_one_modality_trial,
    )
    monkeypatch.setattr(runner, "unload_model_from_ports", lambda *args: [])

    output_root = tmp_path / "timeout"
    args = runner.parse_args(
        [
            "--models",
            "qwen3.5:35b",
            "--ports",
            "5000",
            "--conditions",
            "passive_listing",
            "--case-ids",
            "stage2_gwas_loaded",
            "--trial-timeout-s",
            "0.01",
            "--output-root",
            str(output_root),
        ]
    )

    asyncio.run(runner.run_matrix(args))
    payload = json.loads((output_root / "benchmark_results.json").read_text())
    row = payload["trials"][0]

    assert row["run_id"] == "qwen35b_passive_listing_port5000_stage2_gwas_loaded"
    assert row["activated_skill_names"] == []
    assert row["domain_exact_match"] is False
    assert row["error"] == "TimeoutError: trial exceeded 0.01s"
    assert (output_root / f"{row['run_id']}.json").exists()


def test_modality_runner_parallel_ports_runs_ports_concurrently_without_same_port_overlap(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio
    import json

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_modality_activation_benchmark as runner,
    )

    active_ports: set[int] = set()
    overlap_ports: list[int] = []
    max_active = 0

    async def fake_run_one_modality_trial(trial, output_root):
        nonlocal max_active
        port = int(trial["port"])
        if port in active_ports:
            overlap_ports.append(port)
        active_ports.add(port)
        max_active = max(max_active, len(active_ports))
        await asyncio.sleep(0.01)
        active_ports.remove(port)
        score = runner.score_modality_activation(
            expected_domain_skills=(),
            activated_skill_names=(),
        )
        return {
            **trial,
            "expected_domain_skills": [],
            "activated_skill_names": [],
            "tool_history": [],
            "final_text": "",
            "elapsed_s": 0.0,
            "error": None,
            **score,
        }

    monkeypatch.setattr(
        runner,
        "run_one_modality_trial",
        fake_run_one_modality_trial,
    )
    monkeypatch.setattr(runner, "unload_model_from_ports", lambda *args: [])

    output_root = tmp_path / "parallel"
    args = runner.parse_args(
        [
            "--models",
            "qwen3.5:35b",
            "--ports",
            "5000,6000",
            "--conditions",
            "passive_listing",
            "--case-ids",
            "negative_schema_only,negative_general_recommendation_style",
            "--parallel-ports",
            "--output-root",
            str(output_root),
        ]
    )

    asyncio.run(runner.run_matrix(args))
    payload = json.loads((output_root / "benchmark_results.json").read_text())
    result_run_ids = [row["run_id"] for row in payload["trials"]]
    jsonl_run_ids = [
        json.loads(line)["run_id"]
        for line in (output_root / "trials.jsonl").read_text().splitlines()
    ]

    assert max_active == 2
    assert overlap_ports == []
    assert result_run_ids == [
        "qwen35b_passive_listing_port5000_negative_schema_only",
        "qwen35b_passive_listing_port5000_negative_general_recommendation_style",
        "qwen35b_passive_listing_port6000_negative_schema_only",
        "qwen35b_passive_listing_port6000_negative_general_recommendation_style",
    ]
    assert jsonl_run_ids == result_run_ids


def test_modality_runner_parallel_ports_unloads_between_models_and_at_end(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_modality_activation_benchmark as runner,
    )

    events: list[tuple[str, str]] = []

    async def fake_run_one_modality_trial(trial, output_root):
        events.append(("trial", str(trial["model"])))
        score = runner.score_modality_activation(
            expected_domain_skills=(),
            activated_skill_names=(),
        )
        return {
            **trial,
            "expected_domain_skills": [],
            "activated_skill_names": [],
            "tool_history": [],
            "final_text": "",
            "elapsed_s": 0.0,
            "error": None,
            **score,
        }

    def fake_unload_model_from_ports(model, ports):
        events.append(("unload", str(model)))
        return [
            {"model": str(model), "port": int(port), "ok": True, "error": None}
            for port in ports
        ]

    monkeypatch.setattr(
        runner,
        "run_one_modality_trial",
        fake_run_one_modality_trial,
    )
    monkeypatch.setattr(runner, "unload_model_from_ports", fake_unload_model_from_ports)

    args = runner.parse_args(
        [
            "--models",
            "qwen3.5:35b,qwen3.5:122b",
            "--ports",
            "5000,6000",
            "--conditions",
            "passive_listing",
            "--case-ids",
            "negative_schema_only",
            "--parallel-ports",
            "--output-root",
            str(tmp_path / "parallel-unload"),
        ]
    )

    asyncio.run(runner.run_matrix(args))

    assert events == [
        ("trial", "qwen3.5:35b"),
        ("trial", "qwen3.5:35b"),
        ("unload", "qwen3.5:35b"),
        ("trial", "qwen3.5:122b"),
        ("trial", "qwen3.5:122b"),
        ("unload", "qwen3.5:122b"),
    ]


def test_modality_analysis_report_contains_delta_and_case_failures(tmp_path) -> None:
    import json

    from docs.benchmarks.hypothesis_generation_consistency.analyze_modality_activation_results import (
        write_analysis_report,
    )

    results_path = tmp_path / "benchmark_results.json"
    output_path = tmp_path / "analysis.md"
    payload = {
        "benchmark": "modality_aware_activation",
        "trials": [
            {
                "model": "qwen3.5:35b",
                "condition": "passive_listing",
                "case_id": "stage2_gwas_loaded",
                "expected_domain_skills": ["gwas-database"],
                "activated_skill_names": [],
                "activated_domain_skills": [],
                "domain_exact_match": False,
                "domain_precision": 0.0,
                "domain_recall": 0.0,
                "domain_f1": 0.0,
                "domain_specificity": 1.0,
                "error": None,
            },
            {
                "model": "qwen3.5:35b",
                "condition": "skill_activator",
                "case_id": "stage2_gwas_loaded",
                "expected_domain_skills": ["gwas-database"],
                "activated_skill_names": ["gwas-database"],
                "activated_domain_skills": ["gwas-database"],
                "domain_exact_match": True,
                "domain_precision": 1.0,
                "domain_recall": 1.0,
                "domain_f1": 1.0,
                "domain_specificity": 1.0,
                "error": None,
            },
        ],
        "unload_events": [{"ok": True}],
    }
    results_path.write_text(json.dumps(payload), encoding="utf-8")

    write_analysis_report(results_path, output_path)

    markdown = output_path.read_text(encoding="utf-8")
    assert "# Modality-Aware Activation Analysis" in markdown
    assert "skill_activator - passive_listing" in markdown
    assert "+1.0000" in markdown
    assert "stage2_gwas_loaded" in markdown
    assert "activation only" in markdown
