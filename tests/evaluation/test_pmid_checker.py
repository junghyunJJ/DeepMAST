"""Tests for PMID checker utilities."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

from evaluation.check_pmids import (
    default_fetch_json,
    check_pmids,
    extract_pmids_from_evidence_file,
    is_valid_pmid_format,
    pmid_exists,
)


def test_pmid_format_validator():
    assert is_valid_pmid_format("33558695")
    assert not is_valid_pmid_format("003355")
    assert not is_valid_pmid_format("abc")


def test_extract_pmids_from_evidence_file_returns_primary_and_support():
    pmids = extract_pmids_from_evidence_file("evaluation/evidence/dlpfc_visium.yaml")
    assert "33558695" in pmids


def test_pmid_exists_uses_injected_fetcher():
    def fake_fetcher(url: str):
        assert "id=12345" in url
        return {"result": {"uids": ["12345"]}}

    assert pmid_exists("12345", fetcher=fake_fetcher)


def test_check_pmids_marks_invalid_when_fetcher_returns_empty(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "sample.yaml").write_text(
        """
dataset_id: sample
claims:
  - claim_id: C1
    claim_text: t
    claim_type: spatial
    entities: [a]
    direction: present_in
    pmid_primary: "12345"
    pmid_support: "99999"
    evidence_span_ref: ref
        """.strip(),
        encoding="utf-8",
    )

    def fake_fetcher(_url: str):
        return {"result": {"uids": []}}

    valid, invalid = check_pmids(evidence, fetcher=fake_fetcher)
    assert valid == []
    assert invalid == ["12345", "99999"]


def test_default_fetch_json_retries_on_429(monkeypatch):
    payload = {"result": {"uids": ["12345"]}}
    calls = {"count": 0}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(_req, timeout=10.0):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                url="https://example.org",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(b""),
            )
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = default_fetch_json("https://example.org")
    assert result == payload
    assert calls["count"] == 2
