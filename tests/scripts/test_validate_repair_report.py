from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


orchestrator = _load_script("validate_repair_report")
validate_report = _load_script("validate_report")
repair_report = _load_script("repair_report")


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("#")]


class StructuredDecisionLLM:
    def __init__(self, *, action: str, replacement_text: str) -> None:
        self.action = action
        self.replacement_text = replacement_text
        self.schema = None

    def with_structured_output(self, schema, **_kwargs):
        self.schema = schema
        return self

    def invoke(self, _prompt: str):
        assert self.schema is not None
        return self.schema(
            action=self.action,
            replacement_text=self.replacement_text,
        )


class DirectionLLM(StructuredDecisionLLM):
    def __init__(self) -> None:
        super().__init__(
            action="replace",
            replacement_text="Factor3 shows EGFR depletion.",
        )


class FailLLM:
    def invoke(self, prompt: str):
        raise AssertionError(f"LLM should not be called: {prompt}")


@pytest.mark.parametrize(
    "code",
    ["claim_rag_unsupported", "inline_citation_unsupported"],
)
def test_unsupported_claim_shapes_delete_only_the_exact_target(
    tmp_path: Path,
    code: str,
) -> None:
    target = "p53 directly drives invasion (PMID: 12345678)."
    original = f"## Biology\nKeep before.\n{target}\nKeep after.\n"
    report = tmp_path / "part1_final.md"
    report.write_text(original, encoding="utf-8")
    issue = {
        "severity": "error",
        "code": code,
        "file": report.name,
        "section": "## Biology",
        "value": target,
        "target_text": target,
        "evidence": "The supplied evidence does not support this assertion.",
        "repair_instruction": "Remove the unsupported assertion.",
    }
    if code == "inline_citation_unsupported":
        issue["inline_pmid"] = "12345678"
        issue["source_claim_index"] = 0
    issues_path = tmp_path / "issues.json"
    _write_json(issues_path, {"issues": [issue]})

    changed = repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=StructuredDecisionLLM(action="delete", replacement_text=""),
        claim_validation=[],
    )

    repaired = report.read_text(encoding="utf-8")
    assert changed == 1
    assert target not in repaired
    assert "Keep before." in repaired
    assert "Keep after." in repaired
    assert _headings(repaired) == _headings(original)
    assert repair_report._pmids(repaired).issubset(repair_report._pmids(original))


def test_real_validate_repair_validate_deletes_unsupported_part3_spillover(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "papers.json", [])
    report = tmp_path / "part3_final.md"
    report.write_text(
        "## Analysis 3-10\n"
        "### Biological Interpretation\n"
        "NECTIN4 is an underexplored therapeutic target.\n"
        "Spatial evidence remains unchanged.\n",
        encoding="utf-8",
    )
    before = _headings(report.read_text(encoding="utf-8"))
    issues = validate_report.validate_report(tmp_path)
    issues_path = tmp_path / "issues.json"
    _write_json(issues_path, {"issues": issues})

    changed = repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=StructuredDecisionLLM(action="delete", replacement_text=""),
    )

    final = validate_report.validate_report(tmp_path)
    assert changed == 1
    assert not [issue for issue in final if issue["severity"] == "error"]
    assert _headings(report.read_text(encoding="utf-8")) == before
    assert "Spatial evidence remains unchanged." in report.read_text(encoding="utf-8")


def test_one_pass_returns_zero_when_repair_clears_errors(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_validate(data_dir: Path, output: Path) -> int:
        calls.append("validate")
        issues = [{"severity": "error", "code": "bad"}] if calls.count("validate") == 1 else []
        output.write_text(json.dumps({"issues": issues}), encoding="utf-8")
        return 1 if issues else 0

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        calls.append("repair")
        assert provider == "ollama"
        return 0

    monkeypatch.setattr(orchestrator, "_run_validate", fake_validate)
    monkeypatch.setattr(orchestrator, "_run_repair", fake_repair)

    rc = orchestrator.validate_repair_once(tmp_path, provider="ollama")

    assert rc == 0
    assert calls == ["validate", "repair", "validate"]


def test_one_pass_returns_one_when_final_errors_remain(tmp_path: Path, monkeypatch) -> None:
    def fake_validate(data_dir: Path, output: Path) -> int:
        output.write_text(json.dumps({"issues": [{"severity": "error", "code": "bad"}]}), encoding="utf-8")
        return 1

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        return 0

    monkeypatch.setattr(orchestrator, "_run_validate", fake_validate)
    monkeypatch.setattr(orchestrator, "_run_repair", fake_repair)

    rc = orchestrator.validate_repair_once(tmp_path, provider=None)

    assert rc == 1


def test_returns_one_when_final_validation_fails_after_clean_initial(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_validate(data_dir: Path, output: Path) -> int:
        calls.append("validate")
        issues = [] if len(calls) == 1 else [{"severity": "error", "code": "late"}]
        output.write_text(json.dumps({"issues": issues}), encoding="utf-8")
        return 1 if issues else 0

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        calls.append("repair")
        return 0

    monkeypatch.setattr(orchestrator, "_run_validate", fake_validate)
    monkeypatch.setattr(orchestrator, "_run_repair", fake_repair)

    rc = orchestrator.validate_repair_once(tmp_path, provider=None)

    assert rc == 1
    assert calls == ["validate", "validate"]


def test_runs_final_validation_even_when_repair_fails(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_validate(data_dir: Path, output: Path) -> int:
        calls.append("validate")
        output.write_text(json.dumps({"issues": [{"severity": "error", "code": "bad"}]}), encoding="utf-8")
        return 1

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        calls.append("repair")
        return 7

    monkeypatch.setattr(orchestrator, "_run_validate", fake_validate)
    monkeypatch.setattr(orchestrator, "_run_repair", fake_repair)

    rc = orchestrator.validate_repair_once(tmp_path, provider=None)

    assert rc == 7
    assert calls == ["validate", "repair", "validate"]
    assert (tmp_path / "report_validation_final.json").exists()


def test_real_validate_repair_validate_clears_lr_and_target_only_direction_issue(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LRIG1^ERBB3",
                "ligand": "LRIG1",
                "receptor": "ERBB3",
                "morans": 0.3629,
                "genept_score": 0.7,
                "combinedscore": 0.8,
            }
        ],
    )
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor3", "pathway": "EGFR", "estimate": -2.897, "pval": 0.004, "adj_pval": 0.028}],
    )
    report = tmp_path / "part2_final.md"
    report.write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "LRIG1-ERBB3 Moran's R = 0.4213.\n"
        "## Analysis 2-8: Pathway-Factor\n"
        "### Biological Interpretation\n"
        "Factor3 shows EGFR enrichment and activation.\n",
        encoding="utf-8",
    )
    before_headings = _headings(report.read_text(encoding="utf-8"))
    issues = validate_report.validate_report(tmp_path)
    issues_path = tmp_path / "issues.json"
    _write_json(issues_path, {"issues": issues})

    changed = repair_report.repair_report(tmp_path, issues_path, llm=DirectionLLM())

    final_issues = validate_report.validate_report(tmp_path)
    assert changed == 2
    assert not [i for i in final_issues if i["severity"] == "error"]
    assert _headings(report.read_text(encoding="utf-8")) == before_headings


def test_real_validate_repair_validate_clears_two_lr_mismatches_in_one_sentence(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana.csv",
        [
            {
                "interaction": "LRIG1^ERBB3",
                "ligand": "LRIG1",
                "receptor": "ERBB3",
                "morans": 0.3629,
                "genept_score": 0.7,
                "combinedscore": 0.8,
            },
            {
                "interaction": "LAMA5^ITGB4",
                "ligand": "LAMA5",
                "receptor": "ITGB4",
                "morans": 0.3265,
                "genept_score": 0.8,
                "combinedscore": 0.7,
            },
        ],
    )
    report = tmp_path / "part2_final.md"
    report.write_text(
        "## Analysis 2-6: LIANA Moran's R\n"
        "### Biological Interpretation\n"
        "Before text stays. "
        "LRIG1-ERBB3 Moran's R = 0.4213, while LAMA5-ITGB4 Moran's R = 0.7171. "
        "After text stays.\n",
        encoding="utf-8",
    )
    before_headings = _headings(report.read_text(encoding="utf-8"))
    issues = validate_report.validate_report(tmp_path)
    issues_path = tmp_path / "issues.json"
    _write_json(issues_path, {"issues": issues})

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    text = report.read_text(encoding="utf-8")
    final_lr_issues = [i for i in validate_report.validate_report(tmp_path) if i["code"] == "lr_metric_value_mismatch"]
    assert changed == 2
    assert final_lr_issues == []
    assert (
        "Before text stays. "
        "LRIG1-ERBB3 Moran's R = 0.3629, while LAMA5-ITGB4 Moran's R = 0.3265. "
        "After text stays."
    ) in text
    assert _headings(text) == before_headings
