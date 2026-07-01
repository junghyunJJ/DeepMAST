# Report Validate Repair Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-pass Deep Interpreter report guardrail that validates `part1_final.md`/`part2_final.md`/`part3_final.md`, repairs only flagged sections, then validates once more.

**Architecture:** Add three small scripts under `scripts/`: a deterministic validator, an LLM-backed section repairer, and a one-pass orchestrator. Keep this out of the main LangGraph pipeline at first; the runner can be wired later after the guardrail proves useful.

**Tech Stack:** Python 3.12 stdlib (`argparse`, `csv`, `json`, `re`, `pathlib`), existing `src.agents.model.create_llm`, `pytest`.

---

## Worktree Setup

This work should happen in a new worktree/branch, based on the current feature branch after its current changes are committed or merged. Untracked files from the current worktree will not appear in a new worktree.

Run from the repo root:

```bash
git status --short
git branch --show-current
git worktree add ../report-validate-repair-loop -b feat/report-validate-repair-loop feat/deep-interpreter-agent-update
cd ../report-validate-repair-loop
uv sync
```

Expected:

```text
feat/report-validate-repair-loop
```

If `git worktree add` fails because the branch already exists:

```bash
git worktree add ../report-validate-repair-loop feat/report-validate-repair-loop
cd ../report-validate-repair-loop
```

## File Structure

- Create `scripts/validate_report.py`
  - Reads markdown parts and run artifacts from a data directory.
  - Emits JSON issues to stdout or `--output`.
  - No LLM calls.

- Create `scripts/repair_report.py`
  - Reads a validator issue JSON file.
  - Sends only the affected section plus compact evidence context to an existing LLM.
  - Replaces only the marked section in the markdown file.

- Create `scripts/validate_repair_report.py`
  - Runs `validate_report.py`.
  - If issues exist, runs `repair_report.py`.
  - Runs `validate_report.py` once more.
  - Exits non-zero if final hard issues remain.

- Create `tests/scripts/test_validate_report.py`
  - Deterministic tests for PMID hallucination, unsupported Factor1 pathway significance, and Part3 therapeutic spillover.

- Create `tests/scripts/test_repair_report.py`
  - Mocked LLM repair test that proves only the flagged section is replaced.

- Create `tests/scripts/test_validate_repair_report.py`
  - Mocked subprocess/orchestrator test that proves one-pass flow and final non-zero behavior.

Do not modify `src/agents/deep_interpreter/wrapper_agent.py` in this plan.

---

### Task 1: Add Deterministic Report Validator

**Files:**
- Create: `scripts/validate_report.py`
- Test: `tests/scripts/test_validate_report.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_validate_report.py`:

```python
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_report.py"
SPEC = importlib.util.spec_from_file_location("validate_report", SCRIPT_PATH)
assert SPEC and SPEC.loader
validate_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_report)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_flags_pmid_not_in_papers_json(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [{"pmid": "11111111", "title": "known"}])
    (tmp_path / "part1_final.md").write_text("Supported PMID:11111111\nFake PMID:99999999\n", encoding="utf-8")

    issues = validate_report.validate_report(tmp_path)

    assert any(i["code"] == "pmid_not_in_papers" and i["value"] == "99999999" for i in issues)


def test_flags_factor1_significance_when_pathway_csv_lacks_factor1(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor2", "pathway": "NFkB", "estimate": -3.28, "p": 0.001, "adj_p": 0.025}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor1 showed significant enrichment for TGFb/MAPK/PI3K/Hypoxia.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert any(i["code"] == "unsupported_factor1_pathway_significance" for i in issues)


def test_allows_factor1_hypothesis_language(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [{"factor": "Factor2", "pathway": "NFkB", "estimate": -3.28, "p": 0.001, "adj_p": 0.025}],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor1 may reflect TGFb/MAPK programs inferred from LR annotations, not pathway-factor significance.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(i["code"] == "unsupported_factor1_pathway_significance" for i in issues)


def test_flags_part3_therapeutic_spillover(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    (tmp_path / "part3_final.md").write_text(
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        "MIF-CD74 is a high-confidence therapeutic target and should be prioritized for druggability.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert any(i["code"] == "part3_therapeutic_spillover" for i in issues)


def test_flags_part3_missing_selected_lr_pairs(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_json(
        tmp_path / "part4_candidate_selection.json",
        {
            "selected_genes": ["ICAM1", "MUC1", "CD74"],
            "selected_lr_pairs": [
                {"interaction": "ICAM1^PECAM1"},
                {"interaction": "ICAM1^MUC1"},
                {"interaction": "MIF^CD74"},
            ],
        },
    )
    (tmp_path / "part3_final.md").write_text(
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        "ICAM1 and MUC1 spatial signals were reviewed.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    missing = [i for i in issues if i["code"] == "missing_selected_lr_pair"]
    assert {i["value"] for i in missing} == {"ICAM1^PECAM1", "ICAM1^MUC1", "MIF^CD74"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/scripts/test_validate_report.py -v
```

Expected: FAIL with `FileNotFoundError` or missing module for `scripts/validate_report.py`.

- [ ] **Step 3: Add the minimal validator**

Create `scripts/validate_report.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


PMID_RE = re.compile(r"\bPMID[:\s]*(\d{6,9})\b", re.IGNORECASE)
SECTION_RE = re.compile(r"(^## .+?$)(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
THERAPEUTIC_RE = re.compile(
    r"\b(therapeutic|druggability|drug ranking|clinical prioritization|high-confidence therapeutic target)\b",
    re.IGNORECASE,
)
SIGNIFICANCE_RE = re.compile(r"\b(significant|significantly|enriched|enrichment)\b", re.IGNORECASE)
FACTOR1_RE = re.compile(r"\bFactor\s*1\b|\bFactor1\b", re.IGNORECASE)
PATHWAY_RE = re.compile(r"\b(TGFb|TGF-beta|MAPK|PI3K|Hypoxia)\b", re.IGNORECASE)
HYPOTHESIS_RE = re.compile(r"\b(may|might|could|hypothesis|inferred|suggests?|consistent with|not pathway-factor significance)\b", re.IGNORECASE)


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _papers_pmids(data_dir: Path) -> set[str]:
    data = _load_json(data_dir / "papers.json")
    if not isinstance(data, list):
        return set()
    pmids: set[str] = set()
    for row in data:
        if isinstance(row, dict) and row.get("pmid"):
            pmids.add(str(row["pmid"]))
    return pmids


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _sections(text: str) -> list[dict[str, str | int]]:
    matches = list(SECTION_RE.finditer(text))
    if not matches and text.strip():
        return [{"heading": "", "body": text, "start": 0, "end": len(text)}]
    return [
        {
            "heading": match.group(1).strip(),
            "body": match.group(2),
            "start": match.start(),
            "end": match.end(),
        }
        for match in matches
    ]


def _issue(
    *,
    code: str,
    file: str,
    section: str,
    value: str,
    severity: str = "error",
    evidence: str = "",
    repair_instruction: str = "",
) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "file": file,
        "section": section,
        "value": value,
        "evidence": evidence,
        "repair_instruction": repair_instruction,
    }


def _check_pmids(data_dir: Path, issues: list[dict[str, str]]) -> None:
    known = _papers_pmids(data_dir)
    for md in sorted(data_dir.glob("part*_final.md")):
        text = _read_text(md)
        for pmid in sorted(set(PMID_RE.findall(text))):
            if known and pmid not in known:
                issues.append(_issue(
                    code="pmid_not_in_papers",
                    file=md.name,
                    section="",
                    value=pmid,
                    evidence=f"{pmid} is cited in {md.name} but absent from papers.json.",
                    repair_instruction="Remove the unsupported PMID or replace it with a PMID present in papers.json.",
                ))


def _has_factor1_pathway_row(data_dir: Path) -> bool:
    path = data_dir / "sig_liana_pathway_factor.csv"
    if not path.exists():
        return False
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            factor = str(row.get("factor") or row.get("Factor") or "")
            pathway = str(row.get("pathway") or row.get("Pathway") or "")
            if FACTOR1_RE.search(factor) and PATHWAY_RE.search(pathway):
                return True
    return False


def _check_factor1_pathway_claims(data_dir: Path, issues: list[dict[str, str]]) -> None:
    if _has_factor1_pathway_row(data_dir):
        return
    path = data_dir / "part2_final.md"
    text = _read_text(path)
    if not text:
        return
    for section in _sections(text):
        body = str(section["body"])
        if (
            FACTOR1_RE.search(body)
            and PATHWAY_RE.search(body)
            and SIGNIFICANCE_RE.search(body)
            and not HYPOTHESIS_RE.search(body)
        ):
            issues.append(_issue(
                code="unsupported_factor1_pathway_significance",
                file=path.name,
                section=str(section["heading"]),
                value="Factor1 pathway significance",
                evidence="sig_liana_pathway_factor.csv has no Factor1 row for TGFb/MAPK/PI3K/Hypoxia.",
                repair_instruction="Rephrase as an LR-annotation-based hypothesis, not measured pathway-factor significance.",
            ))


def _selected_lr_pairs(data_dir: Path) -> list[str]:
    data = _load_json(data_dir / "part4_candidate_selection.json")
    if not isinstance(data, dict):
        return []
    pairs = data.get("selected_lr_pairs") or []
    values: list[str] = []
    for row in pairs:
        if not isinstance(row, dict):
            continue
        value = row.get("interaction") or row.get("lr_pair") or row.get("pair")
        if value:
            values.append(str(value))
    return values


def _check_part3_scope_and_pairs(data_dir: Path, issues: list[dict[str, str]]) -> None:
    path = data_dir / "part3_final.md"
    text = _read_text(path)
    if not text:
        return
    for section in _sections(text):
        body = str(section["body"])
        if THERAPEUTIC_RE.search(body):
            issues.append(_issue(
                code="part3_therapeutic_spillover",
                file=path.name,
                section=str(section["heading"]),
                value="therapeutic/druggability language",
                evidence="Part3 should interpret selected L-R spatial evidence only; Part4 owns therapeutic synthesis.",
                repair_instruction="Remove therapeutic prioritization language and keep the section to spatial/statistical LR evidence.",
            ))
    for pair in _selected_lr_pairs(data_dir):
        ligand, _, receptor = pair.partition("^")
        if pair not in text and not (ligand and receptor and ligand in text and receptor in text):
            issues.append(_issue(
                code="missing_selected_lr_pair",
                file=path.name,
                section="",
                value=pair,
                severity="warning",
                evidence=f"{pair} is selected in part4_candidate_selection.json but not discussed in part3_final.md.",
                repair_instruction="Add a concise evidence-grounded sentence for this selected LR pair if Part3 covers Figure 3-10/3-11.",
            ))


def validate_report(data_dir: Path) -> list[dict[str, str]]:
    data_dir = data_dir.resolve()
    issues: list[dict[str, str]] = []
    _check_pmids(data_dir, issues)
    _check_factor1_pathway_claims(data_dir, issues)
    _check_part3_scope_and_pairs(data_dir, issues)
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Deep Interpreter markdown reports.")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    issues = validate_report(args.data_dir)
    payload = {"issue_count": len(issues), "issues": issues}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if any(i["severity"] == "error" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/scripts/test_validate_report.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_report.py tests/scripts/test_validate_report.py
git commit -m "add report validator for grounded interpreter output

Constraint: Keep the guardrail deterministic and outside the main LangGraph pipeline for the first pass.
Rejected: Full report regeneration as repair strategy | too much blast radius for claim-level issues.
Confidence: medium
Scope-risk: narrow
Directive: Only promote this into wrapper_agent.py after fixture and live-run validation agree.
Tested: uv run pytest tests/scripts/test_validate_report.py -v
Not-tested: Live LLM repair calls."
```

---

### Task 2: Add Section-Only Repair Script

**Files:**
- Create: `scripts/repair_report.py`
- Test: `tests/scripts/test_repair_report.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_repair_report.py`:

```python
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_report.py"
SPEC = importlib.util.spec_from_file_location("repair_report", SCRIPT_PATH)
assert SPEC and SPEC.loader
repair_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair_report)


class FakeLLM:
    def invoke(self, prompt: str):
        assert "Factor1 showed significant enrichment" in prompt
        assert "UNCHANGED INTRO" not in prompt
        return type("Msg", (), {"content": "### Biological Interpretation\nFactor1 may reflect TGFb/MAPK activity inferred from LR annotations, not pathway-factor significance."})()


def test_repair_replaces_only_flagged_section(tmp_path: Path) -> None:
    report = tmp_path / "part2_final.md"
    report.write_text(
        "## Analysis 2-7: Keep\n"
        "UNCHANGED INTRO\n"
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor1 showed significant enrichment for TGFb/MAPK.\n"
        "## Part 2 Summary\n"
        "UNCHANGED SUMMARY\n",
        encoding="utf-8",
    )
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps({
            "issues": [{
                "code": "unsupported_factor1_pathway_significance",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Analysis 2-8: Pathway Factor Heatmap",
                "value": "Factor1 pathway significance",
                "evidence": "No Factor1 row in sig_liana_pathway_factor.csv.",
                "repair_instruction": "Rephrase as hypothesis.",
            }]
        }),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FakeLLM())

    text = report.read_text(encoding="utf-8")
    assert changed == 1
    assert "UNCHANGED INTRO" in text
    assert "UNCHANGED SUMMARY" in text
    assert "Factor1 showed significant enrichment" not in text
    assert "not pathway-factor significance" in text


def test_repair_skips_file_level_issue_without_section(tmp_path: Path) -> None:
    report = tmp_path / "part1_final.md"
    report.write_text("Fake PMID:99999999\n", encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps({
            "issues": [{
                "code": "pmid_not_in_papers",
                "severity": "error",
                "file": "part1_final.md",
                "section": "",
                "value": "99999999",
                "evidence": "Absent from papers.json.",
                "repair_instruction": "Remove unsupported PMID.",
            }]
        }),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FakeLLM())

    assert changed == 0
    assert report.read_text(encoding="utf-8") == "Fake PMID:99999999\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/scripts/test_repair_report.py -v
```

Expected: FAIL with missing `scripts/repair_report.py`.

- [ ] **Step 3: Add the minimal repairer**

Create `scripts/repair_report.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agents.model import create_llm


SECTION_RE = re.compile(r"(^## .+?$)(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def _content(message: Any) -> str:
    return str(getattr(message, "content", message))


def _load_issues(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    issues = data.get("issues", data if isinstance(data, list) else [])
    return [i for i in issues if isinstance(i, dict)]


def _find_section(text: str, heading: str) -> tuple[int, int, str] | None:
    for match in SECTION_RE.finditer(text):
        if match.group(1).strip() == heading.strip():
            return match.start(), match.end(), match.group(0)
    return None


def _build_prompt(issue: dict[str, str], section_text: str) -> str:
    return f"""Rewrite only this markdown section to fix the validation issue.

Keep the same section heading. Keep evidence-grounded scientific tone.
Do not invent new PMIDs, p-values, scores, files, or pathway significance.
Do not add therapeutic/druggability conclusions to Part3.

Validation issue:
{json.dumps(issue, indent=2, ensure_ascii=False)}

Section:
{section_text}

Return only the corrected markdown section."""


def repair_report(data_dir: Path, issues_path: Path, *, llm: Any | None = None, provider: str | None = None) -> int:
    data_dir = data_dir.resolve()
    issues = _load_issues(issues_path)
    model = llm or create_llm(provider)
    changed = 0

    for issue in issues:
        if issue.get("severity") != "error":
            continue
        section = issue.get("section") or ""
        filename = issue.get("file") or ""
        if not section or not filename:
            continue
        path = data_dir / filename
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8")
        found = _find_section(text, section)
        if found is None:
            continue
        start, end, section_text = found
        replacement = _content(model.invoke(_build_prompt(issue, section_text))).strip()
        if not replacement.startswith(section.strip()):
            replacement = section.strip() + "\n" + replacement
        path.write_text(text[:start] + replacement.rstrip() + "\n" + text[end:], encoding="utf-8")
        changed += 1

    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair only validator-flagged report sections.")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)

    changed = repair_report(args.data_dir, args.issues, provider=args.provider)
    print(json.dumps({"changed_sections": changed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/scripts/test_repair_report.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/repair_report.py tests/scripts/test_repair_report.py
git commit -m "add section-scoped report repair script

Constraint: Repair must preserve unflagged markdown content.
Rejected: Whole-file rewrite | too likely to introduce unrelated drift.
Confidence: medium
Scope-risk: narrow
Directive: Keep repair prompts source-grounded; do not let Part3 absorb Part4 therapeutic claims.
Tested: uv run pytest tests/scripts/test_repair_report.py -v
Not-tested: Live provider-specific LLM behavior."
```

---

### Task 3: Add One-Pass Validate Repair Orchestrator

**Files:**
- Create: `scripts/validate_repair_report.py`
- Test: `tests/scripts/test_validate_repair_report.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_validate_repair_report.py`:

```python
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_repair_report.py"
SPEC = importlib.util.spec_from_file_location("validate_repair_report", SCRIPT_PATH)
assert SPEC and SPEC.loader
orchestrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orchestrator)


def test_one_pass_returns_zero_when_repair_clears_errors(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_validate(data_dir: Path, output: Path) -> int:
        calls.append("validate")
        issues = [{"severity": "error", "code": "bad"}] if calls.count("validate") == 1 else []
        output.write_text(json.dumps({"issues": issues}), encoding="utf-8")
        return 1 if issues else 0

    def fake_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
        calls.append("repair")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/scripts/test_validate_repair_report.py -v
```

Expected: FAIL with missing `scripts/validate_repair_report.py`.

- [ ] **Step 3: Add orchestrator**

Create `scripts/validate_repair_report.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE = REPO_ROOT / "scripts" / "validate_report.py"
REPAIR = REPO_ROOT / "scripts" / "repair_report.py"


def _has_error_issues(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    return any(i.get("severity") == "error" for i in data.get("issues", []))


def _run_validate(data_dir: Path, output: Path) -> int:
    result = subprocess.run(
        [sys.executable, str(VALIDATE), str(data_dir), "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        check=False,
    )
    return result.returncode


def _run_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
    cmd = [sys.executable, str(REPAIR), str(data_dir), "--issues", str(issues)]
    if provider:
        cmd.extend(["--provider", provider])
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, check=False)
    return result.returncode


def validate_repair_once(data_dir: Path, *, provider: str | None = None) -> int:
    data_dir = data_dir.resolve()
    first = data_dir / "report_validation_initial.json"
    final = data_dir / "report_validation_final.json"

    _run_validate(data_dir, first)
    if not _has_error_issues(first):
        _run_validate(data_dir, final)
        return 0

    repair_rc = _run_repair(data_dir, first, provider)
    if repair_rc != 0:
        return repair_rc

    _run_validate(data_dir, final)
    return 1 if _has_error_issues(final) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run validate -> repair -> validate once.")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)
    return validate_repair_once(args.data_dir, provider=args.provider)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/scripts/test_validate_repair_report.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_repair_report.py tests/scripts/test_validate_repair_report.py
git commit -m "add one-pass report validate repair orchestrator

Constraint: Run exactly one repair pass to avoid hidden infinite loops.
Rejected: In-agent self-repair middleware | too invasive before standalone validation.
Confidence: medium
Scope-risk: narrow
Directive: Treat final validator errors as pipeline failure, not as warnings.
Tested: uv run pytest tests/scripts/test_validate_repair_report.py -v
Not-tested: Live end-to-end report repair on tmp_final_ipf."
```

---

### Task 4: Run Focused Regression Suite

**Files:**
- Validate only; no new files.

- [ ] **Step 1: Run all new tests**

Run:

```bash
uv run pytest \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run adjacent script tests**

Run:

```bash
uv run pytest \
  tests/test_run_deep_interpreter_agent_cli.py \
  tests/deep_interpreter/test_drug_target_spillover_guard.py \
  -v
```

Expected: PASS.

- [ ] **Step 3: Run validator against an existing dataset without repair**

Run:

```bash
uv run python scripts/validate_report.py /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/feat/deep-interpreter-agent-update/tmp_final_ipf --output /tmp/ipf_report_issues.json || true
cat /tmp/ipf_report_issues.json
```

Expected: JSON output with either zero issues or concrete `issues[]`. Do not edit `tmp_final_ipf` from the new worktree during this check.

- [ ] **Step 4: Commit test evidence note if needed**

If the live dataset reveals a deterministic false positive, fix the validator and commit:

```bash
git add scripts/validate_report.py tests/scripts/test_validate_report.py
git commit -m "tighten report validator false positive handling

Constraint: Validator must catch known unsupported claims without blocking acceptable hypothesis language.
Rejected: LLM-as-validator | nondeterministic and slower than matching known failure modes.
Confidence: medium
Scope-risk: narrow
Directive: Add one fixture per new false-positive class before changing regexes.
Tested: uv run pytest tests/scripts/test_validate_report.py -v
Not-tested: Full LangGraph run."
```

---

### Task 5: Optional Live Repair Smoke Test

**Files:**
- Runtime output only; no code changes unless a bug appears.

- [ ] **Step 1: Copy a dataset before live repair**

Run:

```bash
cp -R /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/feat/deep-interpreter-agent-update/tmp_final_ipf /tmp/tmp_final_ipf_repair_smoke
```

Expected: `/tmp/tmp_final_ipf_repair_smoke` exists.

- [ ] **Step 2: Run one-pass repair with Ollama**

Use the model being evaluated:

```bash
export LLM_PROVIDER=ollama
export OLLAMA_MODEL=qwen3.5:397b-cloud
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_REASONING=true
export OLLAMA_NUM_PREDICT=12000
export OLLAMA_REQUEST_TIMEOUT_SECONDS=7200
uv run python scripts/validate_repair_report.py /tmp/tmp_final_ipf_repair_smoke --provider ollama
```

Expected:

```text
exit code 0
```

If exit code is non-zero, inspect:

```bash
cat /tmp/tmp_final_ipf_repair_smoke/report_validation_initial.json
cat /tmp/tmp_final_ipf_repair_smoke/report_validation_final.json
```

- [ ] **Step 3: Verify only targeted files changed**

Run:

```bash
diff -ru \
  /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/feat/deep-interpreter-agent-update/tmp_final_ipf \
  /tmp/tmp_final_ipf_repair_smoke \
  | head -200
```

Expected: only `part*_final.md` and validation JSON files differ.

---

## Self-Review

Spec coverage:
- `validate_report.py`: Task 1.
- `repair_report.py`: Task 2.
- `validate -> repair -> validate` one-pass automation: Task 3.
- New worktree/branch execution: Worktree Setup.
- Minimal/Ponytail scope: no pipeline integration, no new dependencies, no whole-file rewrite.

Placeholder scan:
- No planned code uses placeholder markers or undefined helper names.

Type consistency:
- `validate_report(data_dir: Path) -> list[dict[str, str]]`.
- `repair_report(data_dir: Path, issues_path: Path, *, llm=None, provider=None) -> int`.
- `validate_repair_once(data_dir: Path, *, provider=None) -> int`.

Known limits:
- Validator covers the known failure classes from current Qwen report testing; it is not a general scientific truth checker.
- File-level PMID issues are reported but not auto-repaired in Task 2 because section location is ambiguous. Add section mapping later if this becomes frequent.
- No main pipeline integration in this plan. Add it only after standalone live smoke tests prove the loop is useful.
