import json

from src.agents.deep_interpreter.tools.data_loader import load_analysis_data


def test_load_analysis_data_includes_part4_candidate_selection(tmp_path):
    payload = {
        "schema_version": "drug_target.part4_candidate_selection.v1",
        "selected_genes": ["ERBB3", "EPHB4", "ERBB2"],
    }
    (tmp_path / "part4_candidate_selection.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    result = load_analysis_data.invoke({"data_dir": str(tmp_path)})

    assert result["part4_candidate_selection_status"] == "loaded"
    assert result["part4_candidate_selection"]["selected_genes"] == [
        "ERBB3",
        "EPHB4",
        "ERBB2",
    ]


def test_load_analysis_data_marks_part4_candidate_selection_parse_error(tmp_path):
    (tmp_path / "part4_candidate_selection.json").write_text("{", encoding="utf-8")

    result = load_analysis_data.invoke({"data_dir": str(tmp_path)})

    assert result["part4_candidate_selection_status"] == "parse_error"
    assert result["part4_candidate_selection"] is None
