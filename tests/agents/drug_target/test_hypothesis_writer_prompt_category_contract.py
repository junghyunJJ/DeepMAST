from pathlib import Path

from src.agents.drug_target.subagents import prompts


REQUIRED_CATEGORIES = (
    "Mechanism of Action",
    "Therapeutic Strategy",
    "Cross-Target Interaction",
    "Novel Pathway",
)


def test_hypothesis_writer_prompt_names_exact_required_categories() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    for category in REQUIRED_CATEGORIES:
        assert category in text


def test_hypothesis_writer_prompt_requires_all_categories_in_retained_set() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "include at least one recommendation in each category" in text
    assert "include every FEATURED gene at least once" in text


def test_hypothesis_writer_prompt_removes_three_of_four_category_contract() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Ensure at least 3 of 4 categories represented" not in text


def test_hypothesis_writer_prompt_requires_four_to_six_retained_recommendations() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Prefer exactly four retained recommendations" in text
    assert "expand to five or six only when needed to cover every FEATURED gene" in text


def test_dth_skill_keeps_category_and_evidence_interpretation_details() -> None:
    text = Path("skills/drug-target-hypothesis/SKILL.md").read_text()

    assert "Maintain all four thematic categories" in text
    assert "OpenTargets known-drug evidence and Stage 3 ChEMBL matched-drug evidence are distinct" in text
    assert (
        "Do not list a partner gene in `biological_entities.genes` unless the same hypothesis cites"
        in text
    )
    assert "context only, not independently supported by cited evidence" in text
