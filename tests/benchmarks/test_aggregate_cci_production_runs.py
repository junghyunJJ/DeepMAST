from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks import aggregate_cci_production_runs as aggregate


def test_aggregate_one_row_writes_summary_outputs_and_korean_results(tmp_path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    row = {
        "run_id": "run-1",
        "case_count": 1,
        "raw_papers": 10,
        "handoff_papers": 4,
        "error": "",
    }
    (run_dir / "row.json").write_text(json.dumps(row), encoding="utf-8")

    exit_code = aggregate.main(["--root", str(tmp_path), "--title", "CCI Production 결과"])

    summary_json = tmp_path / "summary.json"
    summary_csv = tmp_path / "summary.csv"
    results_ko = tmp_path / "RESULTS_KO.md"
    assert exit_code == 0
    assert summary_json.exists()
    assert summary_csv.exists()
    assert results_ko.exists()

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["run_count"] == 1
    assert summary["failed_runs"] == 0
    assert summary["rows"] == [row]
    assert "run_id,case_count,error,handoff_papers,raw_papers" in summary_csv.read_text(
        encoding="utf-8"
    )

    markdown = results_ko.read_text(encoding="utf-8")
    assert "# CCI Production 결과" in markdown
    assert "| status | PASS |" in markdown
    assert "## 최종 결론" in markdown
    assert "최종 결론: 모든 production benchmark run이 통과했다." in markdown


def test_aggregate_no_rows_returns_no_data_failure(tmp_path):
    exit_code = aggregate.main(["--root", str(tmp_path), "--title", "빈 실행 결과"])

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "RESULTS_KO.md").read_text(encoding="utf-8")
    assert exit_code == 1
    assert summary["run_count"] == 0
    assert summary["failed_runs"] == 0
    assert summary["status"] == "NO_DATA"
    assert summary["rows"] == []
    assert (tmp_path / "summary.csv").read_text(encoding="utf-8") == ""
    assert "| status | NO_DATA |" in markdown
    assert "집계할 `row.json`이 없어 benchmark 결과를 판정할 수 없다." in markdown


def test_aggregate_error_row_returns_failure_and_korean_fail_status(tmp_path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    row = {"run_id": "run-1", "error": "RuntimeError: failed"}
    (run_dir / "row.json").write_text(json.dumps(row), encoding="utf-8")

    exit_code = aggregate.main(["--root", str(tmp_path), "--title", "실패 결과"])

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "RESULTS_KO.md").read_text(encoding="utf-8")
    assert exit_code == 1
    assert summary["run_count"] == 1
    assert summary["failed_runs"] == 1
    assert summary["failed_run_details"] == [{"run_id": "run-1", "error": "RuntimeError: failed"}]
    assert "| status | FAIL |" in markdown
    assert "| run-1 | RuntimeError: failed |" in markdown
    assert "최종 결론: 일부 production benchmark run에서 오류가 보고되어 실패했다." in markdown


def test_null_error_is_not_counted_as_failure(tmp_path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    row = {"run_id": "run-1", "error": None}
    (run_dir / "row.json").write_text(json.dumps(row), encoding="utf-8")

    exit_code = aggregate.main(["--root", str(tmp_path), "--title", "Null Error 결과"])

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["status"] == "PASS"
    assert summary["failed_runs"] == 0


def test_csv_union_fields_and_nested_values_are_serialized(tmp_path):
    run_a = tmp_path / "run-a"
    run_b = tmp_path / "run-b"
    run_a.mkdir()
    run_b.mkdir()
    (run_a / "row.json").write_text(
        json.dumps({"run_id": "run-a", "error": "", "nested": {"b": 2, "a": 1}}),
        encoding="utf-8",
    )
    (run_b / "row.json").write_text(
        json.dumps({"run_id": "run-b", "error": "", "items": ["x", "y"]}),
        encoding="utf-8",
    )

    exit_code = aggregate.main(["--root", str(tmp_path), "--title", "CSV 결과"])

    assert exit_code == 0
    with (tmp_path / "summary.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert set(rows[0]) == {"run_id", "error", "items", "nested"}
    assert rows[0]["nested"] == '{"a": 1, "b": 2}'
    assert rows[1]["items"] == '["x", "y"]'


def test_failed_run_markdown_table_escapes_cells(tmp_path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    row = {"run_id": "run|1", "error": "RuntimeError: failed\nnext line"}
    (run_dir / "row.json").write_text(json.dumps(row), encoding="utf-8")

    exit_code = aggregate.main(["--root", str(tmp_path), "--title", "Escape 결과"])

    markdown = (tmp_path / "RESULTS_KO.md").read_text(encoding="utf-8")
    assert exit_code == 1
    assert "run\\|1" in markdown
    assert "failed<br>next line" in markdown
