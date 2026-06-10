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


def test_hypothesis_writer_prompt_separates_opentargets_from_stage3_chembl() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert (
        "OpenTargets known-drug evidence and Stage 3 ChEMBL matched-drug "
        "evidence are distinct"
    ) in text
    assert (
        "If `stage3_<GENE>.json` has empty `matched_drugs`, do not describe "
        "that file as ChEMBL drug, ChEMBL compound, or matched-drug support"
    ) in text


def test_hypothesis_writer_prompt_requires_context_only_partner_wording() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert (
        "Do not list a partner gene in `biological_entities.genes` unless the "
        "same hypothesis cites `ot_<GENE>.json`, `stage3_<GENE>.json`, or a "
        "Stage 1 pair file containing that gene"
    ) in text
    assert (
        "If an uncited partner is biologically useful, mention it only as "
        "context in prose and label it `context only, not independently "
        "supported by cited evidence`"
    ) in text


def test_hypothesis_writer_prompt_softens_fibrosis_resolution_wording() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Avoid `fibrosis resolution` in hypothesis titles" in text
    assert (
        "Prefer `fibrosis-relevant readouts`, `matrix deposition readouts`, or "
        "`macrophage-fibroblast interaction readouts`"
    ) in text
