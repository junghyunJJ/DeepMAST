"""Tests for Post-HITL evaluation schema and validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


SCHEMA_PATH = Path("evaluation/schema_post_hitl.json")


def _valid_payload() -> dict:
    return {
        "schema_version": "post_hitl_eval_v1",
        "run_meta": {
            "run_id": "run-001",
            "dataset_id": "dlpfc_visium",
            "agent_git_sha": "abc123",
            "llm_provider": "openrouter",
            "llm_model": "kimi-k2",
            "started_at": "2026-02-22T00:00:00Z",
            "finished_at": "2026-02-22T00:10:00Z",
        },
        "hitl_context": {
            "hitl_completed": True,
            "interpretation_approved": True,
            "interest_clusters": ["3", "7"],
            "interest_celltypes": ["Fibroblast"],
            "sel_factor": "factor_2",
            "hitl_packet_hash": "sha256:abcdef",
        },
        "artifacts": {
            "part1_final": "/part1_final.md",
            "part2_final": "/part2_final.md",
            "part3_final": "/part3_final.md",
            "part1_papers": "/part1_papers.json",
            "part23_papers": "/liana_papers.json",
            "final_report": "CCI_Analysis_Report.html",
        },
        "gold_binding": {
            "gold_version": "v1.1",
            "alignment_profile": "deep_interpreter_part_aligned",
            "evidence_file": "evaluation/evidence/dlpfc_visium.yaml",
        },
        "predicted_claims": [
            {
                "pred_id": "P001",
                "part": "part1",
                "claim_text": "Layer structure recovered.",
                "claim_type": "spatial",
                "entities": ["L1", "L2"],
                "direction": "present_in",
                "cited_pmids": ["33558695"],
                "novelty_flag": False,
            }
        ],
        "matching": [
            {
                "pred_id": "P001",
                "gold_claim_id": "DLPFC_001",
                "status": "TP",
                "entity_overlap": 1.0,
                "direction_match": True,
                "pmid_alignment": "strong",
            }
        ],
        "scores": {
            "part1": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
            "part2": {"precision": 0.8, "recall": 0.8, "f1": 0.8},
            "part3": {"precision": 0.7, "recall": 0.7, "f1": 0.7},
            "overall": {
                "precision": 0.83,
                "recall": 0.83,
                "f1": 0.83,
                "grounding_validity": 1.0,
                "strong_alignment_rate": 0.9,
                "hallucination_rate": 0.0,
            },
        },
        "eval_status": "ok",
    }


def test_post_hitl_schema_file_exists_and_is_valid_json():
    assert SCHEMA_PATH.exists()
    payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert payload["$id"] == "post_hitl_eval_v1"
    assert "required" in payload


def test_validate_post_hitl_payload_accepts_valid_payload():
    from evaluation.validate_post_hitl import validate_post_hitl_payload

    errors = validate_post_hitl_payload(_valid_payload())
    assert errors == []


def test_validate_post_hitl_payload_rejects_ok_without_hitl_complete():
    from evaluation.validate_post_hitl import validate_post_hitl_payload

    payload = _valid_payload()
    payload["hitl_context"]["hitl_completed"] = False
    payload["eval_status"] = "ok"

    errors = validate_post_hitl_payload(payload)
    assert errors
    assert any("post-hitl precondition" in e.lower() for e in errors)


def test_cli_returns_nonzero_for_invalid_file(tmp_path: Path):
    from evaluation.validate_post_hitl import main

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{\"schema_version\": \"post_hitl_eval_v1\"}", encoding="utf-8")
    exit_code = main(["--input", str(invalid)])
    assert exit_code == 1
