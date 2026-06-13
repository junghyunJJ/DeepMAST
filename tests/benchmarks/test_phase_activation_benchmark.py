from __future__ import annotations

from docs.benchmarks.hypothesis_generation_consistency.phase_activation import (
    CORE_SKILL_NAME,
    DOMAIN_SKILL_UNIVERSE,
    EXPANDED6_SKILL_NAMES,
    PHASE_ACTIVATION_CASES,
    aggregate_phase_activation,
    build_phase_trial_plan,
    render_phase_activation_summary,
    score_phase_activation,
)


def test_phase_cases_cover_each_domain_skill() -> None:
    covered = {
        skill
        for case in PHASE_ACTIVATION_CASES
        for skill in case.expected_domain_skills
    }

    assert covered == set(DOMAIN_SKILL_UNIVERSE)


def test_phase_cases_include_negative_controls() -> None:
    negative_cases = [
        case for case in PHASE_ACTIVATION_CASES if not case.expected_domain_skills
    ]

    assert {case.case_id for case in negative_cases} >= {
        "negative_schema_formatting",
        "negative_general_biology",
    }


def test_score_phase_activation_exact_match() -> None:
    score = score_phase_activation(
        expected_domain_skills=("chembl-database",),
        activated_skill_names=(
            CORE_SKILL_NAME,
            "chembl-database",
        ),
    )

    assert score["domain_tp"] == 1
    assert score["domain_fp"] == 0
    assert score["domain_fn"] == 0
    assert score["domain_exact_match"] is True
    assert score["domain_precision"] == 1.0
    assert score["domain_recall"] == 1.0
    assert score["core_activated"] is True


def test_score_phase_activation_penalizes_activate_all() -> None:
    score = score_phase_activation(
        expected_domain_skills=("chembl-database",),
        activated_skill_names=(
            CORE_SKILL_NAME,
            "opentargets-database",
            "gwas-database",
            "chembl-database",
            "compare-census-gene-pair-by-cell-type",
            "string-database",
        ),
    )

    assert score["domain_tp"] == 1
    assert score["domain_fp"] == 4
    assert score["domain_fn"] == 0
    assert score["domain_exact_match"] is False
    assert score["domain_recall"] == 1.0
    assert score["domain_precision"] == 0.2
    assert score["domain_overactivated"] is True


def test_score_phase_activation_negative_control_specificity() -> None:
    score = score_phase_activation(
        expected_domain_skills=(),
        activated_skill_names=(CORE_SKILL_NAME,),
    )

    assert score["domain_tp"] == 0
    assert score["domain_fp"] == 0
    assert score["domain_tn"] == len(DOMAIN_SKILL_UNIVERSE)
    assert score["domain_exact_match"] is True
    assert score["domain_precision"] == 1.0
    assert score["domain_recall"] == 1.0
    assert score["domain_specificity"] == 1.0


def test_phase_trial_plan_uses_models_ports_conditions_and_cases() -> None:
    trials = build_phase_trial_plan(
        models=("qwen3.5:35b", "qwen3.5:122b"),
        ports=(5000, 6000, 7000),
        conditions=("passive_listing", "skill_activator"),
        case_ids=("stage2_opentargets_target_disease", "stage3_chembl_compounds"),
    )

    assert len(trials) == 24
    assert trials[0]["run_id"] == (
        "qwen35b_passive_listing_port5000_stage2_opentargets_target_disease"
    )
    assert trials[-1]["run_id"] == (
        "qwen122b_skill_activator_port7000_stage3_chembl_compounds"
    )


def test_aggregate_phase_activation_groups_by_model_condition_and_phase() -> None:
    rows = [
        {
            "model": "qwen3.5:35b",
            "condition": "passive_listing",
            "phase": "stage3",
            "case_id": "stage3_chembl_compounds",
            "domain_exact_match": True,
            "domain_precision": 1.0,
            "domain_recall": 1.0,
            "domain_f1": 1.0,
            "domain_specificity": 1.0,
            "domain_fp": 0,
            "domain_fn": 0,
            "error": None,
        },
        {
            "model": "qwen3.5:35b",
            "condition": "passive_listing",
            "phase": "stage3",
            "case_id": "stage3_chembl_compounds",
            "domain_exact_match": False,
            "domain_precision": 0.2,
            "domain_recall": 1.0,
            "domain_f1": 0.3333,
            "domain_specificity": 0.0,
            "domain_fp": 4,
            "domain_fn": 0,
            "error": None,
        },
    ]

    aggregate = aggregate_phase_activation(rows)
    group = aggregate["groups"]["qwen3.5:35b::passive_listing::stage3"]

    assert group["runs"] == 2
    assert group["error_runs"] == 0
    assert group["domain_exact_match_rate"] == 0.5
    assert group["mean_domain_fp"] == 2.0


def test_render_phase_activation_summary_contains_interpretation_columns() -> None:
    rows = [
        {
            "model": "qwen3.5:35b",
            "port": 5000,
            "condition": "skill_activator",
            "phase": "stage1",
            "case_id": "stage1_census_expression",
            "expected_domain_skills": ["compare-census-gene-pair-by-cell-type"],
            "activated_skill_names": [
                CORE_SKILL_NAME,
                "compare-census-gene-pair-by-cell-type",
            ],
            "domain_exact_match": True,
            "domain_precision": 1.0,
            "domain_recall": 1.0,
            "domain_specificity": 1.0,
            "domain_f1": 1.0,
            "error": None,
        }
    ]
    aggregate = aggregate_phase_activation(rows)

    markdown = render_phase_activation_summary(rows, aggregate)

    assert "# Phase-Aware Skill Activation Appropriateness" in markdown
    assert "expected domain skills" in markdown
    assert "exact match" in markdown
    assert "compare-census-gene-pair-by-cell-type" in markdown


def test_phase_runner_render_system_prompt_selects_condition_protocol() -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency.run_phase_activation_benchmark import (
        render_system_prompt,
    )

    passive_prompt = asyncio.run(render_system_prompt("passive_listing"))
    activator_prompt = asyncio.run(render_system_prompt("skill_activator"))

    assert "## Skills System" in passive_prompt
    assert "## Skills System" in activator_prompt
    assert "future skill reads" in passive_prompt
    assert "actually called during this interaction" in passive_prompt
    assert "Database skills may be read" in activator_prompt
    assert "interpretation" in activator_prompt
    assert "## Phase 1" not in passive_prompt
    assert "## Phase 1" in activator_prompt
    assert "Context-match rule" in activator_prompt


def test_phase_runner_parse_args_accepts_smoke_matrix() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_phase_activation_benchmark import (
        parse_args,
    )

    args = parse_args(
        [
            "--models",
            "qwen3.5:35b",
            "--ports",
            "5000",
            "--conditions",
            "passive_listing,skill_activator",
            "--case-ids",
            "stage1_census_expression,stage3_chembl_compounds",
        ]
    )

    assert args.models == "qwen3.5:35b"
    assert args.ports == "5000"
    assert args.conditions == "passive_listing,skill_activator"
    assert args.case_ids == "stage1_census_expression,stage3_chembl_compounds"


def test_phase_runner_parse_args_accepts_parallel_ports() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_phase_activation_benchmark import (
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


def test_phase_runner_extracts_registered_skill_names() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_phase_activation_benchmark import (
        extract_skills_from_tool_history,
    )

    assert extract_skills_from_tool_history(
        [
            {
                "name": "read_skill_file",
                "args": {"skill_path": "skills/string-database/SKILL.md"},
            },
            {
                "name": "read_skill_file",
                "args": {"skill_path": "skills/not-registered/SKILL.md"},
            },
        ]
    ) == ["string-database"]


def test_phase_runner_coerces_json_string_tool_args() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.run_phase_activation_benchmark import (
        coerce_tool_args,
        extract_skills_from_tool_history,
    )

    args = coerce_tool_args('"skills/string-database/SKILL.md"')

    assert args == {"skill_path": "skills/string-database/SKILL.md"}
    assert extract_skills_from_tool_history(
        [{"name": "read_skill_file", "args": args}]
    ) == ["string-database"]


def test_phase_runner_tool_loop_captures_sequential_expanded6_reads() -> None:
    import asyncio

    from langchain_core.messages import AIMessage

    from docs.benchmarks.hypothesis_generation_consistency.run_phase_activation_benchmark import (
        run_tool_loop,
    )

    class SequentialSkillLLM:
        def __init__(self) -> None:
            self.calls = 0
            self.skill_paths = [
                f"skills/{skill_name}/SKILL.md"
                for skill_name in EXPANDED6_SKILL_NAMES
            ]

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            if self.calls < len(self.skill_paths):
                skill_path = self.skill_paths[self.calls]
                self.calls += 1
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "read_skill_file",
                            "args": {"skill_path": skill_path},
                            "id": f"call_{self.calls}",
                        }
                    ],
                )
            self.calls += 1
            return AIMessage(content="done")

    result = asyncio.run(
        run_tool_loop(
            SequentialSkillLLM(),
            system_prompt="system",
            user_prompt="user",
        )
    )

    assert len(result["tool_history"]) == len(EXPANDED6_SKILL_NAMES)
    assert result["tool_budget_exhausted"] is False


def test_phase_runner_trial_marks_tool_budget_exhaustion(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_phase_activation_benchmark as runner,
    )

    async def fake_render_system_prompt(condition):
        return "system"

    async def fake_run_tool_loop(*args, **kwargs):
        return {
            "final_text": "",
            "tool_history": [],
            "tool_budget_exhausted": True,
        }

    monkeypatch.setattr(runner, "create_phase_trial_llm", lambda model, port: object())
    monkeypatch.setattr(runner, "render_system_prompt", fake_render_system_prompt)
    monkeypatch.setattr(runner, "run_tool_loop", fake_run_tool_loop)

    row = asyncio.run(
        runner.run_one_phase_trial(
            {
                "model": "qwen3.5:35b",
                "port": 5000,
                "condition": "passive_listing",
                "case_id": "negative_schema_formatting",
                "phase": "negative",
                "run_id": "budget_exhausted",
            },
            tmp_path,
        )
    )

    assert row["error"] == "tool_call_budget_exhausted"


def test_phase_runner_one_trial_does_not_mutate_ollama_env(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_phase_activation_benchmark as runner,
    )

    class DummyLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            from langchain_core.messages import AIMessage

            return AIMessage(content="done")

    async def fake_render_system_prompt(condition):
        return "system"

    monkeypatch.setenv("LLM_PROVIDER", "keep-provider")
    monkeypatch.setenv("LLM_MODEL", "keep-model")
    monkeypatch.setenv("OLLAMA_MODEL", "keep-ollama-model")
    monkeypatch.setenv("OLLAMA_REASONING", "true")
    monkeypatch.setenv("OLLAMA_HOST", "http://keep-host")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://keep-base")
    monkeypatch.setattr(runner, "create_phase_trial_llm", lambda model, port: DummyLLM())
    monkeypatch.setattr(runner, "render_system_prompt", fake_render_system_prompt)

    row = asyncio.run(
        runner.run_one_phase_trial(
            {
                "model": "qwen3.5:35b",
                "port": 5000,
                "condition": "passive_listing",
                "case_id": "negative_schema_formatting",
                "phase": "negative",
                "run_id": "env_safe",
            },
            tmp_path,
        )
    )

    assert row["error"] is None
    assert row["activated_skill_names"] == []
    assert {
        "LLM_PROVIDER": "keep-provider",
        "LLM_MODEL": "keep-model",
        "OLLAMA_MODEL": "keep-ollama-model",
        "OLLAMA_REASONING": "true",
        "OLLAMA_HOST": "http://keep-host",
        "OLLAMA_BASE_URL": "http://keep-base",
    } == {
        name: __import__("os").environ[name]
        for name in (
            "LLM_PROVIDER",
            "LLM_MODEL",
            "OLLAMA_MODEL",
            "OLLAMA_REASONING",
            "OLLAMA_HOST",
            "OLLAMA_BASE_URL",
        )
    }


def test_phase_runner_truncates_stale_trials_jsonl(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_phase_activation_benchmark as runner,
    )

    async def fake_run_one_phase_trial(trial, output_root):
        score = runner.score_phase_activation(
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

    output_root = tmp_path / "existing-output"
    output_root.mkdir()
    (output_root / "trials.jsonl").write_text("stale-row\n", encoding="utf-8")

    monkeypatch.setattr(runner, "run_one_phase_trial", fake_run_one_phase_trial)
    monkeypatch.setattr(runner, "unload_model_from_ports", lambda *args: [])

    args = runner.parse_args(
        [
            "--models",
            "qwen3.5:35b",
            "--ports",
            "5000",
            "--conditions",
            "passive_listing",
            "--case-ids",
            "negative_schema_formatting",
            "--output-root",
            str(output_root),
        ]
    )

    resolved_output = asyncio.run(runner.run_matrix(args))
    trial_lines = (output_root / "trials.jsonl").read_text(encoding="utf-8").splitlines()

    assert resolved_output == output_root.resolve()
    assert len(trial_lines) == 1
    assert "stale-row" not in trial_lines[0]


def test_phase_runner_default_matrix_runs_sequentially(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_phase_activation_benchmark as runner,
    )

    active_ports: set[int] = set()
    max_active = 0

    async def fake_run_one_phase_trial(trial, output_root):
        nonlocal max_active
        port = int(trial["port"])
        active_ports.add(port)
        max_active = max(max_active, len(active_ports))
        await asyncio.sleep(0.001)
        active_ports.remove(port)
        score = runner.score_phase_activation(
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

    monkeypatch.setattr(runner, "run_one_phase_trial", fake_run_one_phase_trial)
    monkeypatch.setattr(runner, "unload_model_from_ports", lambda *args: [])

    args = runner.parse_args(
        [
            "--models",
            "qwen3.5:35b",
            "--ports",
            "5000,6000",
            "--conditions",
            "passive_listing",
            "--case-ids",
            "negative_schema_formatting",
            "--output-root",
            str(tmp_path / "sequential"),
        ]
    )

    asyncio.run(runner.run_matrix(args))

    assert max_active == 1


def test_phase_runner_parallel_ports_runs_ports_concurrently_without_same_port_overlap(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio
    import json

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_phase_activation_benchmark as runner,
    )

    active_ports: set[int] = set()
    overlap_ports: list[int] = []
    max_active = 0

    async def fake_run_one_phase_trial(trial, output_root):
        nonlocal max_active
        port = int(trial["port"])
        if port in active_ports:
            overlap_ports.append(port)
        active_ports.add(port)
        max_active = max(max_active, len(active_ports))
        await asyncio.sleep(0.01)
        active_ports.remove(port)
        score = runner.score_phase_activation(
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

    monkeypatch.setattr(runner, "run_one_phase_trial", fake_run_one_phase_trial)
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


def test_phase_runner_parallel_ports_unloads_between_models_and_at_end(
    monkeypatch,
    tmp_path,
) -> None:
    import asyncio

    from docs.benchmarks.hypothesis_generation_consistency import (
        run_phase_activation_benchmark as runner,
    )

    events: list[tuple[str, str]] = []

    async def fake_run_one_phase_trial(trial, output_root):
        events.append(("trial", str(trial["model"])))
        score = runner.score_phase_activation(
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

    monkeypatch.setattr(runner, "run_one_phase_trial", fake_run_one_phase_trial)
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
