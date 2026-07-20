from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_html_context_can_disable_legacy_hypothesis_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.drug_target.tools.drug_report_html import build_drug_html_context

    (tmp_path / "drug.md").write_text("# Drug Report\n", encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    hypothesis_path = evidence_dir / "hypothesis_report.json"
    hypothesis_path.write_text(
        json.dumps(
            {
                "hypotheses": [
                    {
                        "title": "Legacy-only hypothesis",
                        "category": "mechanistic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    forbidden_reads: list[Path] = []
    original_read_text = Path.read_text

    def tracking_read_text(path: Path, *args, **kwargs) -> str:
        if path == hypothesis_path:
            forbidden_reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    context = build_drug_html_context(
        str(tmp_path),
        allow_legacy_hypothesis_fallback=False,
    )

    assert context.get("hypothesis", []) == []
    assert forbidden_reads == []
