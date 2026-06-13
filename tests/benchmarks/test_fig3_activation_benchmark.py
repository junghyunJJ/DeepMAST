from __future__ import annotations

from docs.benchmarks.hypothesis_generation_consistency.fig3_activation import (
    FIG3_ACTIVATION_CASES,
    FIG3_STYLE_BASE_PROMPT,
    build_fig3_trial_plan,
)
from docs.benchmarks.hypothesis_generation_consistency.phase_activation import (
    DOMAIN_SKILL_UNIVERSE,
)


def test_fig3_cases_cover_each_domain_skill() -> None:
    covered = {
        skill
        for case in FIG3_ACTIVATION_CASES
        for skill in case.expected_domain_skills
    }

    assert covered == set(DOMAIN_SKILL_UNIVERSE)


def test_fig3_cases_include_negative_controls() -> None:
    negative_case_ids = {
        case.case_id
        for case in FIG3_ACTIVATION_CASES
        if not case.expected_domain_skills
    }

    assert negative_case_ids >= {
        "negative_schema_formatting",
        "negative_general_biology",
    }


def test_fig3_prompt_is_activation_mechanism_not_production_proxy() -> None:
    assert "Do not solve the downstream task" in FIG3_STYLE_BASE_PROMPT
    assert "read_skill_file" in FIG3_STYLE_BASE_PROMPT
    assert "A skill counts as activated only if" in FIG3_STYLE_BASE_PROMPT
    assert "loaded evidence" not in FIG3_STYLE_BASE_PROMPT.lower()
    assert "hypothesis_report.json" not in FIG3_STYLE_BASE_PROMPT


def test_fig3_trial_plan_is_120_for_full_matrix() -> None:
    trials = build_fig3_trial_plan(
        models=("qwen3.5:35b", "qwen3.5:122b"),
        ports=(5000, 6000, 7000),
        conditions=("passive_listing", "skill_activator"),
    )

    assert len(trials) == 120
    assert trials[0]["run_id"] == (
        "qwen35b_passive_listing_port5000_stage1_census_expression"
    )
    assert trials[-1]["run_id"] == (
        "qwen122b_skill_activator_port7000_negative_general_biology"
    )


def test_fig3_runner_render_system_prompt_selects_condition_protocol() -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency.run_fig3_activation_benchmark import (
        render_system_prompt,
    )

    passive_prompt = asyncio.run(render_system_prompt("passive_listing"))
    activator_prompt = asyncio.run(render_system_prompt("skill_activator"))

    assert "## Skills System" in passive_prompt
    assert "## Skills System" in activator_prompt
    assert "Do not solve the downstream task" in passive_prompt
    assert "loaded evidence" not in passive_prompt.lower()
    assert "hypothesis_report.json" not in passive_prompt
    assert "## Phase 1" not in passive_prompt
    assert "## Phase 1" in activator_prompt
    assert "Context-match rule" in activator_prompt


def test_fig3_runner_parse_args_accepts_parallel_ports() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_fig3_activation_benchmark import (
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
            "--parallel-ports",
        ]
    )

    assert args.models == "qwen3.5:35b,qwen3.5:122b"
    assert args.ports == "5000,6000,7000"
    assert args.conditions == "passive_listing,skill_activator"
    assert args.parallel_ports is True


def test_fig3_runner_parallel_ports_runs_ports_concurrently_without_same_port_overlap(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio
    import json

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_fig3_activation_benchmark as runner,
    )

    active_ports: set[int] = set()
    overlap_ports: list[int] = []
    max_active = 0

    async def fake_run_one_fig3_trial(trial, output_root):
        nonlocal max_active
        port = int(trial["port"])
        if port in active_ports:
            overlap_ports.append(port)
        active_ports.add(port)
        max_active = max(max_active, len(active_ports))
        await asyncio.sleep(0.01)
        active_ports.remove(port)
        score = runner.score_fig3_activation(
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

    monkeypatch.setattr(runner, "run_one_fig3_trial", fake_run_one_fig3_trial)
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
            "negative_schema_formatting,negative_general_biology",
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
        "qwen35b_passive_listing_port5000_negative_schema_formatting",
        "qwen35b_passive_listing_port5000_negative_general_biology",
        "qwen35b_passive_listing_port6000_negative_schema_formatting",
        "qwen35b_passive_listing_port6000_negative_general_biology",
    ]
    assert jsonl_run_ids == result_run_ids


def test_fig3_runner_parallel_ports_unloads_between_models_and_at_end(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_fig3_activation_benchmark as runner,
    )

    events: list[tuple[str, str]] = []

    async def fake_run_one_fig3_trial(trial, output_root):
        events.append(("trial", str(trial["model"])))
        score = runner.score_fig3_activation(
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

    monkeypatch.setattr(runner, "run_one_fig3_trial", fake_run_one_fig3_trial)
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
            "negative_schema_formatting",
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


def test_fig3_analysis_report_contains_delta_and_case_failures(tmp_path) -> None:
    import json

    from docs.benchmarks.hypothesis_generation_consistency.analyze_fig3_activation_results import (
        write_analysis_report,
    )

    payload = {
        "benchmark": "fig3_style_activation",
        "trials": [
            {
                "model": "qwen3.5:35b",
                "condition": "passive_listing",
                "phase": "stage2",
                "case_id": "stage2_gwas_genetic_association",
                "domain_exact_match": False,
                "domain_precision": 0.0,
                "domain_recall": 0.0,
                "domain_f1": 0.0,
                "domain_specificity": 1.0,
                "domain_fp": 0,
                "domain_fn": 1,
                "error": None,
                "activated_skill_names": [],
                "expected_domain_skills": ["gwas-database"],
            },
            {
                "model": "qwen3.5:35b",
                "condition": "skill_activator",
                "phase": "stage2",
                "case_id": "stage2_gwas_genetic_association",
                "domain_exact_match": True,
                "domain_precision": 1.0,
                "domain_recall": 1.0,
                "domain_f1": 1.0,
                "domain_specificity": 1.0,
                "domain_fp": 0,
                "domain_fn": 0,
                "error": None,
                "activated_skill_names": ["gwas-database"],
                "expected_domain_skills": ["gwas-database"],
            },
        ],
        "unload_events": [
            {"model": "qwen3.5:35b", "port": 5000, "ok": True, "error": None}
        ],
    }
    results_path = tmp_path / "benchmark_results.json"
    output_path = tmp_path / "fig3_activation_analysis.md"
    results_path.write_text(json.dumps(payload), encoding="utf-8")

    write_analysis_report(results_path, output_path)

    markdown = output_path.read_text(encoding="utf-8")
    assert "# Fig3-Style Activation Analysis" in markdown
    assert "skill_activator - passive_listing" in markdown
    assert "+1.0000" in markdown
    assert "stage2_gwas_genetic_association" in markdown
