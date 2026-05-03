"""Unit tests for DrugTargetConfig provider Literal — Phase 2 T2.3/T2.4 (CP-P0-002).

DrugTargetConfig is a @dataclass whose full import chain is broken by a missing
'GlobResult' symbol in the installed deepagents version.  We therefore inspect
the Literal annotation using the AST directly from source — no module import
needed.  The check is semantically equivalent to typing.get_args() on the
resolved hint and exercises the same source-of-truth (the .py file).
"""

import ast
from pathlib import Path


_AGENT_SRC = (
    Path(__file__).parents[3]
    / "src" / "agents" / "drug_target" / "agent.py"
)


def _get_provider_literal_values(filepath: Path) -> list[str]:
    """Return the string members of the 'provider' Literal annotation in DrugTargetConfig."""
    source = filepath.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DrugTargetConfig":
            for item in node.body:
                if (
                    isinstance(item, ast.AnnAssign)
                    and isinstance(item.target, ast.Name)
                    and item.target.id == "provider"
                ):
                    ann_src = ast.get_source_segment(source, item.annotation)
                    if ann_src:
                        # Parse strings out of Literal["a", "b", ...]
                        inner = ast.parse(ann_src, mode="eval")
                        if (
                            isinstance(inner.body, ast.Subscript)
                            and isinstance(inner.body.slice, ast.Tuple)
                        ):
                            return [
                                elt.value
                                for elt in inner.body.slice.elts
                                if isinstance(elt, ast.Constant)
                            ]
    return []


def test_drug_target_config_provider_literal_includes_ollama_openai():
    """T2.3 #1: DrugTargetConfig.provider Literal must include 'ollama-openai'."""
    provider_args = _get_provider_literal_values(_AGENT_SRC)
    assert provider_args, "Could not parse DrugTargetConfig.provider Literal from source"
    assert "ollama-openai" in provider_args, (
        f"DrugTargetConfig.provider Literal missing 'ollama-openai'; got {provider_args}"
    )


def test_drug_target_config_provider_literal_still_includes_existing_providers():
    """T2.3 #2: regression — pre-existing provider values must remain in the Literal."""
    provider_args = _get_provider_literal_values(_AGENT_SRC)
    assert provider_args, "Could not parse DrugTargetConfig.provider Literal from source"
    for expected in ("openai", "google", "ollama", "claude", "openrouter"):
        assert expected in provider_args, (
            f"DrugTargetConfig.provider Literal is missing pre-existing value "
            f"'{expected}'; got {provider_args}"
        )


def test_subagent_models_field_annotation_accepts_basechatmodel_via_ast():
    """CP-P1-001 (type annotation correctness): DrugTargetConfig.subagent_models
    annotation must mention BaseChatModel (not just str).

    The field is populated by load_subagent_models_from_env() which returns
    dict[str, BaseChatModel].  The annotation dict[str, str] is a type lie.
    """
    src = _AGENT_SRC.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DrugTargetConfig":
            for item in node.body:
                if (
                    isinstance(item, ast.AnnAssign)
                    and isinstance(item.target, ast.Name)
                    and item.target.id == "subagent_models"
                ):
                    annotation_text = ast.unparse(item.annotation)
                    assert "BaseChatModel" in annotation_text, (
                        f"DrugTargetConfig.subagent_models annotation should mention "
                        f"BaseChatModel; got: {annotation_text}"
                    )
                    return
    raise AssertionError("DrugTargetConfig.subagent_models annotation not found")
