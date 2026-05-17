"""Regression tests for `_preformat_cards` Stage 1 PASS/FAIL label injection.

Verifies that `_preformat_cards` injects a per-pair `_passed` boolean into the
output dicts when `stage1_filter_results` is supplied, and that the legacy
single-arg call path remains backward compatible (no `_passed` key emitted).
"""

from __future__ import annotations

from src.agents.drug_target.tools.drug_report_html import _preformat_cards


def _make_card(gene: str, pairs: list[dict]) -> dict:
    """Build a minimal featured_card fixture matching the production shape."""
    return {
        "gene": gene,
        "stage3": {"clinical_drugs": [], "preclinical_compounds": []},
        "stage1_pairs": {
            f"{p['ligand']}--{p['receptor']}": {
                "ligand": p["ligand"],
                "receptor": p["receptor"],
                "string_ppi": {
                    "max_combined_score": p.get("score", 0.5),
                    "interaction_found": p.get("interaction_found", True),
                },
                "kegg_pathways": {},
                "reactome_pathways": {},
                "census": {"risk_ratio": "1.5", "p_value": "0.01"},
            }
            for p in pairs
        },
    }


def test_pass_pair_gets_passed_true() -> None:
    cards = [_make_card("MUC1", [{"ligand": "ICAM1", "receptor": "MUC1"}])]
    filter_results = [{"ligand": "ICAM1", "receptor": "MUC1", "passed": True}]

    result = _preformat_cards(cards, filter_results)

    assert result[0]["_pairs"][0]["_passed"] is True


def test_fail_pair_gets_passed_false() -> None:
    cards = [_make_card("PLAUR", [{"ligand": "FN1", "receptor": "PLAUR"}])]
    filter_results = [{"ligand": "FN1", "receptor": "PLAUR", "passed": False}]

    result = _preformat_cards(cards, filter_results)

    assert result[0]["_pairs"][0]["_passed"] is False


def test_no_filter_results_none() -> None:
    cards = [_make_card("CD4", [{"ligand": "HLA-DPA1", "receptor": "CD4"}])]

    result = _preformat_cards(cards, None)

    assert "_passed" not in result[0]["_pairs"][0]


def test_no_filter_results_empty() -> None:
    cards = [_make_card("CD4", [{"ligand": "HLA-DPA1", "receptor": "CD4"}])]

    result = _preformat_cards(cards, [])

    assert "_passed" not in result[0]["_pairs"][0]


def test_preformat_cards_default_arg_backward_compat() -> None:
    """Calling with the legacy single-arg signature must still work."""
    cards = [_make_card("CD4", [{"ligand": "HLA-DPA1", "receptor": "CD4"}])]

    result = _preformat_cards(cards)

    assert "_passed" not in result[0]["_pairs"][0]


def test_preformat_cards_mixed_pairs_within_single_card() -> None:
    """A single card with 4 mixed PASS/FAIL pairs must be labeled per-pair.

    Regression guard for intra-card discrimination: ensures the lookup is keyed
    by (ligand, receptor) and not broadcast or order-dependent.
    """
    cards = [_make_card("CD4", [
        {"ligand": "HLA-DPA1", "receptor": "CD4"},
        {"ligand": "HLA-DPB1", "receptor": "CD4"},
        {"ligand": "HLA-DQB1", "receptor": "CD4"},
        {"ligand": "HLA-DRB1", "receptor": "CD4"},
    ])]
    filter_results = [
        {"ligand": "HLA-DPA1", "receptor": "CD4", "passed": False},
        {"ligand": "HLA-DPB1", "receptor": "CD4", "passed": False},
        {"ligand": "HLA-DQB1", "receptor": "CD4", "passed": True},
        {"ligand": "HLA-DRB1", "receptor": "CD4", "passed": False},
    ]

    result = _preformat_cards(cards, filter_results)

    pairs_by_ligand = {p["ligand"]: p for p in result[0]["_pairs"]}
    assert pairs_by_ligand["HLA-DPA1"]["_passed"] is False
    assert pairs_by_ligand["HLA-DPB1"]["_passed"] is False
    assert pairs_by_ligand["HLA-DQB1"]["_passed"] is True
    assert pairs_by_ligand["HLA-DRB1"]["_passed"] is False


def test_preformat_cards_case_insensitive_lookup() -> None:
    """Lookup must normalize case so lowercase filter rows match uppercase pair genes."""
    cards = [_make_card("MUC1", [{"ligand": "ICAM1", "receptor": "MUC1"}])]
    filter_results = [{"ligand": "icam1", "receptor": "muc1", "passed": True}]

    result = _preformat_cards(cards, filter_results)

    assert result[0]["_pairs"][0]["_passed"] is True


def test_preformat_cards_handles_csv_string_passed_values() -> None:
    """Production rows come from CSV DictReader (`passed` is the string "true"/"false")."""
    cards = [_make_card("MUC1", [
        {"ligand": "ICAM1", "receptor": "MUC1"},
        {"ligand": "FN1", "receptor": "MUC1"},
    ])]
    filter_results = [
        {"ligand": "ICAM1", "receptor": "MUC1", "passed": "true"},
        {"ligand": "FN1", "receptor": "MUC1", "passed": "false"},
    ]

    result = _preformat_cards(cards, filter_results)

    pairs_by_ligand = {p["ligand"]: p for p in result[0]["_pairs"]}
    assert pairs_by_ligand["ICAM1"]["_passed"] is True
    assert pairs_by_ligand["FN1"]["_passed"] is False
