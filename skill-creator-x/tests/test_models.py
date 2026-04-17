"""Unit tests for scripts/models.py (M1 DoD 7)."""

from __future__ import annotations

from pathlib import Path

from scripts.models import (
    PDF_VERSION,
    TOOL_VERSION,
    InstallResult,
    Platform,
    PlatformCheckResult,
    Severity,
    ValidationReport,
    ValidationResult,
    build_summary,
)


def _make_result(passed: bool = True, severity: Severity = Severity.ERROR,
                 rule_id: str = "FM-001") -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        rule_name="test-rule",
        severity=severity,
        pdf_verb='"test"',
        passed=passed,
        message="ok" if passed else "fail",
        pdf_reference="p.1",
    )


def test_severity_enum_values():
    assert Severity.ERROR.value == "ERROR"
    assert Severity.SOFT_ERROR.value == "SOFT-ERROR"
    assert Severity.WARNING.value == "WARNING"
    # Enum is str-based for JSON friendliness
    assert str(Severity.ERROR.value) == "ERROR"


def test_validation_result_to_dict():
    r = _make_result(passed=False, severity=Severity.SOFT_ERROR)
    d = r.to_dict()
    assert d["rule_id"] == "FM-001"
    assert d["severity"] == "SOFT-ERROR"
    assert d["passed"] is False
    assert d["pdf_verb"] == '"test"'


def test_validation_report_envelope():
    results = [_make_result(), _make_result(passed=False, severity=Severity.WARNING)]
    report = ValidationReport(
        tool_version=TOOL_VERSION,
        pdf_version=PDF_VERSION,
        timestamp="2026-04-17T00:00:00+00:00",
        skill_path="/tmp/x",
        agent_id=None,
        results=results,
        summary=build_summary(results),
    )
    d = report.to_dict()
    assert d["tool_version"] == TOOL_VERSION
    assert d["pdf_version"] == PDF_VERSION
    assert d["agent_id"] is None
    assert len(d["results"]) == 2
    assert isinstance(d["results"][0], dict)
    # Summary structure
    for key in ("error_count", "soft_error_count", "warning_count", "strict", "passed"):
        assert key in d["summary"]


def test_platform_dataclass_defaults():
    p = Platform(
        name="claude-code",
        skill_dir=Path("/tmp/.claude/skills"),
        config_marker=Path("/tmp/.claude"),
        activation_method="auto",
    )
    assert p.constraints == []  # field(default_factory=list)
    # Mutating does not leak across instances
    p.constraints.append("example")
    q = Platform(name="codex-cli", skill_dir=Path("/tmp"), config_marker=Path("/tmp"),
                 activation_method="auto")
    assert q.constraints == []


def test_platform_check_result_defaults():
    p = Platform(name="x", skill_dir=Path("/"), config_marker=Path("/"), activation_method="a")
    r = PlatformCheckResult(platform=p, compatible=True)
    assert r.issues == []
    assert r.suggestions == []


def test_install_result_optional_error():
    r = InstallResult(platform="claude-code", success=True,
                      installed_path=Path("/tmp/x"), method="symlink")
    assert r.error is None
    d = r.to_dict()
    assert d["installed_path"] == "/tmp/x"
    assert d["error"] is None


def test_install_result_failure_path_is_none():
    r = InstallResult(platform="codex", success=False, installed_path=None,
                      method="copy", error="permission denied")
    assert r.to_dict()["installed_path"] is None
    assert r.to_dict()["error"] == "permission denied"


def test_build_summary_counts_and_strict_gate():
    results = [
        _make_result(passed=False, severity=Severity.ERROR, rule_id="FM-006"),
        _make_result(passed=False, severity=Severity.SOFT_ERROR, rule_id="FM-012"),
        _make_result(passed=False, severity=Severity.WARNING, rule_id="BD-001"),
        _make_result(passed=True, severity=Severity.ERROR, rule_id="FM-009"),
    ]
    default = build_summary(results, strict=False)
    assert default == {
        "error_count": 1,
        "soft_error_count": 1,
        "warning_count": 1,
        "strict": False,
        "passed": False,  # error present
    }
    strict = build_summary(results, strict=True)
    # SOFT-ERROR promoted: still blocked, strict flag reflected
    assert strict["strict"] is True
    assert strict["passed"] is False


def test_build_summary_clean_skill_passes():
    s = build_summary([_make_result(passed=True)], strict=True)
    assert s["passed"] is True


def test_build_summary_warning_never_promoted():
    # No ERRORs, only a WARNING failure. Even in strict mode we pass:
    # WARNING rules stay non-blocking per ADR-007.
    results = [_make_result(passed=False, severity=Severity.WARNING, rule_id="BD-006")]
    assert build_summary(results, strict=True)["passed"] is True
    assert build_summary(results, strict=False)["passed"] is True
