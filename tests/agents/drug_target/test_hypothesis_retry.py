from __future__ import annotations

from src.agents.drug_target.hypothesis_retry import build_hypothesis_retry_message


def test_retry_message_includes_numeric_prediction_correction() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_ollama",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "UNVERIFIED_NUMERIC_PREDICTION",
                "message": "One or more falsifiable predictions contain unverified numeric values.",
                "details": {"unverified_indices": [1, 3]},
            }
        ],
        attempt=2,
        max_attempts=3,
    )

    assert "Retry attempt 2 of 3" in message
    assert "UNVERIFIED_NUMERIC_PREDICTION" in message
    assert "unsupported percentages" in message
    assert "fold changes" in message
    assert "p-values" in message
    assert "rewrite the prediction qualitatively" in message
    assert "Do not copy failed numeric predictions" in message
    assert "unverified_indices" in message
    assert 'task(subagent_type="hypothesis_writer"' in message


def test_retry_message_keeps_validation_feedback_inside_task_instruction() -> None:
    message = build_hypothesis_retry_message(
        "res_ipf_ollama",
        "idiopathic pulmonary fibrosis",
        quality_errors=[
            {
                "code": "MISSING_REQUIRED_CATEGORIES",
                "message": "Hypothesis report is missing required thematic categories.",
                "details": {"missing": ["Novel Pathway"]},
            }
        ],
        attempt=1,
        max_attempts=3,
    )

    assert message.index("MISSING_REQUIRED_CATEGORIES") < message.index(
        '")\n\nFor auditability'
    )
    assert "Novel Pathway" in message
