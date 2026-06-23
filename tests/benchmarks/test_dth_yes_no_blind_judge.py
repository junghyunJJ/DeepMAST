from __future__ import annotations

import json
from pathlib import Path


def _write_report(workspace: Path, marker: str) -> None:
    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "hypothesis_report.json").write_text(
        json.dumps(
            {
                "schema_version": "hypothesis_report.v2",
                "disease": "breast cancer",
                "hypotheses_generated": 1,
                "hypotheses_retained": 1,
                "evidence_coverage_pct": 80.0,
                "topn_coverage": {"covered": ["ERBB2"], "missing": []},
                "prediction_grounding_summary": {"qualitative": 1},
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": f"{marker} ERBB2 prioritization",
                        "category": "Mechanism of Action",
                        "core_claim": (
                            "drug-target-hypothesis operational_contract says "
                            "ERBB2 has breast cancer support."
                        ),
                        "biological_entities": {
                            "genes": ["ERBB2"],
                            "cell_types": ["malignant cell"],
                            "pathways": ["ERBB signaling"],
                        },
                        "evidence_references": ["ot_ERBB2.json", "stage3_ERBB2.json"],
                        "falsifiable_prediction": "Perturb ERBB2 and measure signaling.",
                        "validation_approach": "Use breast cancer malignant cell assays.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _fake_summary(tmp_path: Path, pair_count: int = 2) -> Path:
    rows = []
    for condition in ("DTH_yes", "DTH_no"):
        for repeat in range(1, pair_count + 1):
            workspace = tmp_path / "workspaces" / condition / f"rep{repeat:03d}"
            _write_report(workspace, marker=condition)
            rows.append(
                {
                    "condition": condition,
                    "stamp": "stamp_a",
                    "repeat": repeat,
                    "run_id": f"{condition}_rep{repeat:03d}",
                    "valid": True,
                    "dth_activated": condition == "DTH_yes",
                    "coverage": 80.0,
                    "hypothesis_count": 1,
                    "retry_attempts": 0,
                    "elapsed_s": 1.0,
                    "workspace": str(workspace),
                }
            )
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "model": "qwen3.5:397b-cloud",
                "included_stamps": ["stamp_a"],
                "valid_run_table": rows,
            }
        ),
        encoding="utf-8",
    )
    return summary_path


def test_pair_jobs_are_deterministic_and_keep_hidden_labels(tmp_path: Path) -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        build_pair_jobs,
        load_json,
    )

    summary = load_json(_fake_summary(tmp_path, pair_count=3))

    first = build_pair_jobs(summary, seed=17, limit_pairs=None)
    second = build_pair_jobs(summary, seed=17, limit_pairs=None)

    assert first == second
    assert len(first) == 3
    assert set(first[0]["label_map"]) == {"A", "B"}
    assert set(first[0]["label_map"].values()) == {"DTH_yes", "DTH_no"}
    assert first[0]["runs_by_condition"]["DTH_yes"]["condition"] == "DTH_yes"


def test_rendered_prompt_redacts_dth_labels_and_contract_names(tmp_path: Path) -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        build_judge_prompt,
        build_pair_jobs,
        load_json,
        load_reports_for_job,
    )

    summary = load_json(_fake_summary(tmp_path, pair_count=1))
    job = build_pair_jobs(summary, seed=3, limit_pairs=1)[0]
    reports = load_reports_for_job(job)

    prompt = build_judge_prompt(job=job, reports_by_condition=reports)
    lowered = prompt.lower()

    assert "dth_yes" not in lowered
    assert "dth_no" not in lowered
    assert "drug-target-hypothesis" not in lowered
    assert "operational_contract" not in lowered
    assert "output a report" in lowered
    assert "output b report" in lowered
    assert "erbb2" in lowered


def test_aggregate_maps_blinded_winners_back_to_conditions() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        aggregate_judge_rows,
    )

    rows = [
        {
            "pair_id": "pair001",
            "validation_errors": [],
            "label_map": {"A": "DTH_yes", "B": "DTH_no"},
            "winner_blinded": "A",
            "winner": "DTH_yes",
            "condition_scores": {"DTH_yes": 21.0, "DTH_no": 17.0},
            "condition_payloads": {},
            "cost": {"estimated_cost_usd": 0.01},
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
        {
            "pair_id": "pair002",
            "validation_errors": [],
            "label_map": {"A": "DTH_no", "B": "DTH_yes"},
            "winner_blinded": "A",
            "winner": "DTH_no",
            "condition_scores": {"DTH_yes": 16.0, "DTH_no": 20.0},
            "condition_payloads": {},
            "cost": {"estimated_cost_usd": 0.02},
            "usage": {"input_tokens": 110, "output_tokens": 30},
        },
        {
            "pair_id": "pair003",
            "validation_errors": [],
            "label_map": {"A": "DTH_yes", "B": "DTH_no"},
            "winner_blinded": "tie",
            "winner": "tie",
            "condition_scores": {"DTH_yes": 18.0, "DTH_no": 18.0},
            "condition_payloads": {},
            "cost": {"estimated_cost_usd": 0.03},
            "usage": {"input_tokens": 90, "output_tokens": 10},
        },
    ]

    summary = aggregate_judge_rows(rows)

    assert summary["wins"] == {"DTH_yes": 1, "DTH_no": 1, "tie": 1}
    assert summary["non_tie_n"] == 2
    assert summary["token_usage"]["input_tokens"] == 300
    assert summary["token_usage"]["output_tokens"] == 60
    assert summary["estimated_total_cost_usd"] == 0.06


def test_prepare_only_cli_writes_panel_and_summary(tmp_path: Path) -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        main,
    )

    summary_path = _fake_summary(tmp_path, pair_count=2)
    output_dir = tmp_path / "out"

    assert (
        main(
            [
                "--summary-json",
                str(summary_path),
                "--output-dir",
                str(output_dir),
                "--prepare-only",
                "--limit-pairs",
                "1",
                "--seed",
                "11",
            ]
        )
        == 0
    )

    panel_path = output_dir / "dth_yes_no_gpt4o_mini_blind_pair_panel.jsonl"
    summary_out = output_dir / "dth_yes_no_gpt4o_mini_blind_summary.json"
    markdown_out = output_dir / "dth_yes_no_gpt4o_mini_blind_results.md"
    prompt_preview = output_dir / "dth_yes_no_gpt4o_mini_blind_prompt_previews" / "pair001.txt"

    assert panel_path.exists()
    assert summary_out.exists()
    assert markdown_out.exists()
    assert prompt_preview.exists()
    assert "DTH_yes" not in prompt_preview.read_text(encoding="utf-8")
    payload = json.loads(summary_out.read_text(encoding="utf-8"))
    assert payload["metadata"]["status"] == "prepared_only"
    assert payload["metadata"]["pair_count"] == 1


def test_cli_accepts_ollama_cloud_judge_provider() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        parse_args,
    )

    args = parse_args(
        [
            "--judge-provider",
            "ollama",
            "--judge-model",
            "glm-5.2:cloud",
            "--base-url",
            "http://localhost:11434",
        ]
    )

    assert args.judge_provider == "ollama"
    assert args.judge_model == "glm-5.2:cloud"
    assert args.base_url == "http://localhost:11434"


def test_ollama_chat_payload_requests_json_response() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        build_ollama_chat_payload,
    )

    payload = build_ollama_chat_payload(
        model="glm-5.2:cloud",
        prompt="Return JSON only.",
        temperature=0.0,
        max_output_tokens=1200,
        think=True,
    )

    assert payload["model"] == "glm-5.2:cloud"
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["think"] is True
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"] == "Return JSON only."


def test_parse_json_object_prefers_outer_fenced_object() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        parse_json_object,
    )

    parsed = parse_json_object(
        """```json
        {
          "output_a": {"evidence_grounding": 4, "notes": "nested"},
          "output_b": {"evidence_grounding": 3, "notes": "nested"},
          "judge_preference": "B",
          "confidence": "medium",
          "rationale": "outer object should be parsed",
          "key_differences": ["restraint"]
        }
        ```"""
    )

    assert parsed["output_a"]["notes"] == "nested"
    assert parsed["judge_preference"] == "B"


def test_normalize_judge_preference_accepts_output_labels() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        normalize_judge_preference,
    )

    assert normalize_judge_preference("output_a") == "A"
    assert normalize_judge_preference("Output B") == "B"
    assert normalize_judge_preference("tie") == "tie"


def test_select_active_rows_keeps_latest_row_per_pair_and_judge() -> None:
    from docs.benchmarks.hypothesis_generation_consistency.judge_dth_yes_no_blind import (
        select_active_rows,
    )

    rows = [
        {
            "pair_id": "pair001",
            "judge_provider": "ollama",
            "judge_model": "glm-5.2:cloud",
            "validation_errors": ["truncated"],
            "winner": "tie",
        },
        {
            "pair_id": "pair001",
            "judge_provider": "ollama",
            "judge_model": "glm-5.2:cloud",
            "validation_errors": [],
            "winner": "DTH_yes",
        },
        {
            "pair_id": "pair001",
            "judge_provider": "openai",
            "judge_model": "gpt-4o-mini",
            "validation_errors": [],
            "winner": "DTH_no",
        },
    ]

    selected = select_active_rows(
        rows,
        active_pair_ids={"pair001"},
        judge_provider="ollama",
        judge_model="glm-5.2:cloud",
    )

    assert len(selected) == 1
    assert selected[0]["winner"] == "DTH_yes"
