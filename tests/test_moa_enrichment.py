"""Unit tests for local-first mechanism-of-action enrichment.

All tests mock both the chembl-database skill module and the drug_moa_cache
so they run offline and do not write to the real parquet cache.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.agents.drug_target.tools import moa_enrichment


@pytest.fixture(autouse=True)
def _clear_index_cache():
    moa_enrichment.reset_index_cache()
    yield
    moa_enrichment.reset_index_cache()


def _mock_chembl_module(mechanisms_df: pd.DataFrame) -> MagicMock:
    mod = MagicMock()
    mod.is_available.return_value = True
    mod._load_mechanisms.return_value = mechanisms_df
    return mod


def test_resolve_local_parquet_hit_and_miss():
    """Local parquet lookup populates known ChEMBL IDs, leaves misses as None."""
    mechanisms = pd.DataFrame(
        [
            {"molecule_chembl_id": "CHEMBL25", "mechanism_of_action": "Cyclooxygenase inhibitor"},
            {"molecule_chembl_id": "CHEMBL1201583", "mechanism_of_action": "VEGF-A inhibitor"},
        ]
    )
    mod = _mock_chembl_module(mechanisms)

    with patch.object(moa_enrichment, "_load_skill_module", return_value=mod), \
         patch.object(moa_enrichment.drug_moa_cache, "get_cached_moa", return_value=None), \
         patch.object(moa_enrichment.drug_moa_cache, "write_entries", return_value=None):
        result = moa_enrichment.resolve_moa_for_chembl_ids(
            ["CHEMBL25", "chembl1201583", "CHEMBL_MISSING"]
        )

    assert result["CHEMBL25"] == "Cyclooxygenase inhibitor"
    assert result["CHEMBL1201583"] == "VEGF-A inhibitor"
    assert result["CHEMBL_MISSING"] is None


def test_resolve_collapses_multiple_mechanisms_per_drug():
    """Multiple MoA rows for the same molecule get joined with ` | ` in order."""
    mechanisms = pd.DataFrame(
        [
            {"molecule_chembl_id": "CHEMBL1", "mechanism_of_action": "Primary action"},
            {"molecule_chembl_id": "CHEMBL1", "mechanism_of_action": "Secondary action"},
            {"molecule_chembl_id": "CHEMBL1", "mechanism_of_action": "Primary action"},
        ]
    )
    mod = _mock_chembl_module(mechanisms)

    with patch.object(moa_enrichment, "_load_skill_module", return_value=mod), \
         patch.object(moa_enrichment.drug_moa_cache, "get_cached_moa", return_value=None), \
         patch.object(moa_enrichment.drug_moa_cache, "write_entries", return_value=None):
        result = moa_enrichment.resolve_moa_for_chembl_ids(["CHEMBL1"])

    assert result["CHEMBL1"] == "Primary action | Secondary action"


def test_enrich_drugs_in_place_preserves_existing_moa():
    """A drug with pre-existing non-empty mechanism_of_action is not overwritten."""
    mechanisms = pd.DataFrame(
        [
            {"molecule_chembl_id": "CHEMBL25", "mechanism_of_action": "From parquet"},
            {"molecule_chembl_id": "CHEMBL999", "mechanism_of_action": "From parquet 2"},
        ]
    )
    mod = _mock_chembl_module(mechanisms)

    clinical = [
        {"chembl_id": "CHEMBL25", "drug_name": "aspirin"},
        {"chembl_id": "CHEMBL999", "drug_name": "brand-x", "mechanism_of_action": "Manual override"},
    ]
    preclinical = [
        {"chembl_id": "CHEMBL_MISSING", "drug_name": "compound-y"},
    ]

    with patch.object(moa_enrichment, "_load_skill_module", return_value=mod), \
         patch.object(moa_enrichment.drug_moa_cache, "get_cached_moa", return_value=None), \
         patch.object(moa_enrichment.drug_moa_cache, "write_entries", return_value=None):
        filled = moa_enrichment.enrich_drugs_in_place(clinical, preclinical)

    assert filled == 1
    assert clinical[0]["mechanism_of_action"] == "From parquet"
    assert clinical[1]["mechanism_of_action"] == "Manual override"  # preserved
    assert "mechanism_of_action" not in preclinical[0] or preclinical[0].get("mechanism_of_action") is None


def test_enrich_drugs_handles_unavailable_chembl_module_gracefully():
    """When chembl_parquet is unavailable the function returns None values without raising."""
    with patch.object(moa_enrichment, "_load_skill_module", side_effect=ImportError("no skill")), \
         patch.object(moa_enrichment.drug_moa_cache, "get_cached_moa", return_value=None), \
         patch.object(moa_enrichment.drug_moa_cache, "write_entries", return_value=None):
        result = moa_enrichment.resolve_moa_for_chembl_ids(["CHEMBL25"])
        drugs = [{"chembl_id": "CHEMBL25"}]
        filled = moa_enrichment.enrich_drugs_in_place(drugs)

    assert result == {"CHEMBL25": None}
    assert filled == 0
    assert drugs[0].get("mechanism_of_action") in (None, "")


def test_enrich_drugs_uses_cached_moa_before_parquet():
    """drug_moa_cache hits short-circuit the parquet lookup for that ID."""
    mechanisms = pd.DataFrame(
        [
            {"molecule_chembl_id": "CHEMBL25", "mechanism_of_action": "From parquet"},
        ]
    )
    mod = _mock_chembl_module(mechanisms)

    cache_responses = {"CHEMBL25": "From cache"}

    def _fake_cached(cid, gene):
        return cache_responses.get(cid.upper())

    with patch.object(moa_enrichment, "_load_skill_module", return_value=mod), \
         patch.object(moa_enrichment.drug_moa_cache, "get_cached_moa", side_effect=_fake_cached), \
         patch.object(moa_enrichment.drug_moa_cache, "write_entries", return_value=None):
        result = moa_enrichment.resolve_moa_for_chembl_ids(["CHEMBL25"])

    assert result["CHEMBL25"] == "From cache"


def test_enrich_drugs_in_place_noop_on_empty_input():
    """Empty lists / non-list input return 0 with no exceptions."""
    assert moa_enrichment.enrich_drugs_in_place() == 0
    assert moa_enrichment.enrich_drugs_in_place([], []) == 0
    # non-list, non-dict inputs are tolerated
    assert moa_enrichment.enrich_drugs_in_place([{"no_chembl_id": True}]) == 0  # type: ignore[list-item]
