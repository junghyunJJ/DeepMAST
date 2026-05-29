import re

from src.agents.drug_target.subagents import prompts


REQUIRED_CATEGORIES = (
    "Mechanism of Action",
    "Therapeutic Strategy",
    "Cross-Target Interaction",
    "Novel Pathway",
)


def test_hypothesis_writer_prompt_names_exact_required_categories() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    table_categories = re.findall(r"^\| \*\*(.*?)\*\* \|", text, flags=re.MULTILINE)

    assert table_categories == list(REQUIRED_CATEGORIES)
    for category in REQUIRED_CATEGORIES:
        assert category in text


def test_hypothesis_writer_prompt_requires_all_categories_in_retained_set() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Retained hypotheses MUST include all 4 mandatory categories" in text
    assert "Before saving, verify each required category appears at least once" in text


def test_hypothesis_writer_prompt_removes_three_of_four_category_contract() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Ensure at least 3 of 4 categories represented" not in text


def test_hypothesis_writer_prompt_requires_four_to_six_retained_hypotheses() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Keep **4-6 retained hypotheses**" in text
    assert "**Number of retained hypotheses MUST be 4-6**" in text
    assert "Default to 5 retained hypotheses" in text
    assert (
        "retain\n   6 only when needed for FEATURED gene coverage or mandatory category balance"
        in text
    )


def test_hypothesis_writer_prompt_requires_category_coverage_before_saving() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert (
        "Before saving, verify each required category appears at least once in the\n"
        "   retained hypotheses."
    ) in text
