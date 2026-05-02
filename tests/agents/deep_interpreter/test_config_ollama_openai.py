"""Unit tests for DeepInterpreterConfig provider Literal — Phase 2 T2.3/T2.4 (CP-P0-002).

DeepInterpreterConfig is a @dataclass whose full import chain is broken by a missing
'GlobResult' symbol in the installed deepagents version.  We therefore inspect
the Literal annotation using the AST directly from source — no module import
needed.  The check is semantically equivalent to typing.get_args() on the
resolved hint and exercises the same source-of-truth (the .py file).

Note: the plan references this as 'DeepDrugtargetConfig / deep_drugtaget' but
the actual module is 'DeepInterpreterConfig / deep_interpreter'.
"""

import ast
from pathlib import Path


_AGENT_SRC = (
    Path(__file__).parents[3]
    / "src" / "agents" / "deep_interpreter" / "agent.py"
)


def _get_provider_literal_values(filepath: Path) -> list[str]:
    """Return the string members of the 'provider' Literal annotation in DeepInterpreterConfig."""
    source = filepath.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DeepInterpreterConfig":
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


def test_deep_interpreter_config_provider_literal_includes_ollama_openai():
    """T2.3 #3: DeepInterpreterConfig.provider Literal must include 'ollama-openai'."""
    provider_args = _get_provider_literal_values(_AGENT_SRC)
    assert provider_args, "Could not parse DeepInterpreterConfig.provider Literal from source"
    assert "ollama-openai" in provider_args, (
        f"DeepInterpreterConfig.provider Literal missing 'ollama-openai'; got {provider_args}"
    )


def test_deep_interpreter_config_provider_literal_still_includes_existing_providers():
    """T2.3 #4: regression — pre-existing provider values must remain in the Literal."""
    provider_args = _get_provider_literal_values(_AGENT_SRC)
    assert provider_args, "Could not parse DeepInterpreterConfig.provider Literal from source"
    for expected in ("openai", "google", "ollama", "claude", "openrouter"):
        assert expected in provider_args, (
            f"DeepInterpreterConfig.provider Literal is missing pre-existing value "
            f"'{expected}'; got {provider_args}"
        )
