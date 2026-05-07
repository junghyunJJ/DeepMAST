"""Canonical evidence filename registry for DrugTarget reports."""

from __future__ import annotations


class EvidenceFiles:
    """Small registry for evidence paths used across report harness code."""

    _STALE_REPLACEMENTS = {
        "target_assessment.json": "evidence/assessment_results.json",
        "assessment_results.json": "evidence/assessment_results.json",
        "hypothesis_report.json": "evidence/hypothesis_report.json",
        "stage2_evidence.json": "evidence/stage2_evidence.json",
        "stage1_filter_results.json": "evidence/stage1_filter_results.json",
    }

    @staticmethod
    def assessment_results() -> str:
        return "evidence/assessment_results.json"

    @staticmethod
    def hypothesis_report() -> str:
        return "evidence/hypothesis_report.json"

    @staticmethod
    def stage2_evidence() -> str:
        return "evidence/stage2_evidence.json"

    @staticmethod
    def stage1_filter_results() -> str:
        return "evidence/stage1_filter_results.json"

    @staticmethod
    def stage3_gene(gene: str) -> str:
        return f"evidence/stage3_{gene.strip().upper()}.json"

    @staticmethod
    def opentargets_gene(gene: str) -> str:
        return f"evidence/ot_{gene.strip().upper()}.json"

    @classmethod
    def diagnose(cls, path: str) -> dict:
        """Return a deterministic diagnostic for known stale filename forms."""
        normalized = str(path).strip()
        if normalized in {
            cls.assessment_results(),
            cls.hypothesis_report(),
            cls.stage2_evidence(),
            cls.stage1_filter_results(),
        } or normalized.startswith(("evidence/stage3_", "evidence/ot_")):
            return {"valid": True, "code": None, "replacement": None}
        replacement = cls._STALE_REPLACEMENTS.get(normalized)
        if replacement is None:
            return {"valid": True, "code": None, "replacement": None}
        return {
            "valid": False,
            "code": "FILENAME_REGISTRY_DRIFT",
            "replacement": replacement,
        }

