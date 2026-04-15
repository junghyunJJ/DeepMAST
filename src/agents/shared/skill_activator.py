"""Thin re-export for SkillActivator from skills/skill-activator/."""

from pathlib import Path
import importlib.util

_harness_path = (
    Path(__file__).resolve().parents[3] / "skills" / "skill-activator" / "harness.py"
)
_spec = importlib.util.spec_from_file_location("skill_activator", _harness_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SkillActivator = _mod.SkillActivator
