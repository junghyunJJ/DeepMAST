"""Shared data models for skill-creator-x scripts.

ADR-008: All scripts import data classes from this module for consistency.
ADR-009: ValidationReport envelope carries tool/pdf version + timestamp for
         traceability of validation results across time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

TOOL_VERSION = "skill-creator-x 0.1.0"
PDF_VERSION = "2026-01"


class Severity(str, Enum):
    """3-tier severity (ADR-007).

    ERROR: hard constraint; upload/load will fail.
    SOFT_ERROR: PDF MUST but automated check is heuristic-based.
                Emitted as WARNING by default, promoted to ERROR with --strict.
    WARNING: PDF SHOULD/RECOMMENDED; never promoted.
    """

    ERROR = "ERROR"
    SOFT_ERROR = "SOFT-ERROR"
    WARNING = "WARNING"


@dataclass
class ValidationResult:
    rule_id: str
    rule_name: str
    severity: Severity
    pdf_verb: str
    passed: bool
    message: str
    pdf_reference: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class ValidationReport:
    """JSON envelope for a validation run (ADR-009)."""

    tool_version: str
    pdf_version: str
    timestamp: str
    skill_path: str
    agent_id: str | None
    results: list[ValidationResult]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_version": self.tool_version,
            "pdf_version": self.pdf_version,
            "timestamp": self.timestamp,
            "skill_path": self.skill_path,
            "agent_id": self.agent_id,
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary,
        }


@dataclass
class Platform:
    name: str
    skill_dir: Path
    config_marker: Path
    activation_method: str
    constraints: list[str] = field(default_factory=list)


@dataclass
class PlatformCheckResult:
    platform: Platform
    compatible: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class InstallResult:
    platform: str
    success: bool
    installed_path: Path | None
    method: Literal["copy", "symlink"]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "success": self.success,
            "installed_path": str(self.installed_path) if self.installed_path else None,
            "method": self.method,
            "error": self.error,
        }


def build_summary(results: list[ValidationResult], strict: bool = False) -> dict[str, Any]:
    """Compute summary counts from a results list.

    With strict=True, SOFT_ERROR failures count toward error_count so that
    callers can decide pass/fail from a single summary number.
    """
    error_count = sum(1 for r in results if not r.passed and r.severity is Severity.ERROR)
    soft_error_count = sum(1 for r in results if not r.passed and r.severity is Severity.SOFT_ERROR)
    warning_count = sum(1 for r in results if not r.passed and r.severity is Severity.WARNING)
    effective_errors = error_count + (soft_error_count if strict else 0)
    return {
        "error_count": error_count,
        "soft_error_count": soft_error_count,
        "warning_count": warning_count,
        "strict": strict,
        "passed": effective_errors == 0,
    }
