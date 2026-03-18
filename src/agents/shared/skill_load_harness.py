"""Thin re-export for SkillLoadHarness from skills/skill-load-harness/."""

from pathlib import Path
import importlib.util

_harness_path = (
    Path(__file__).resolve().parents[3] / "skills" / "skill-load-harness" / "harness.py"
)
_spec = importlib.util.spec_from_file_location("skill_load_harness", _harness_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SkillLoadHarness = _mod.SkillLoadHarness
