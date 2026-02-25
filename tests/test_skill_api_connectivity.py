"""Live API connectivity tests for Drug Target Assessment skills.

Smoke tests hitting real external APIs with minimal queries.
All tests marked @pytest.mark.api — run separately from unit tests:

    pytest tests/test_skill_api_connectivity.py -v -m api
    pytest tests/test_skill_api_connectivity.py -v -k "ot"
    pytest tests/test_skill_api_connectivity.py -v -k "chembl"
    pytest tests/test_skill_api_connectivity.py -v -k "ct"
    pytest tests/test_skill_api_connectivity.py -v -k "fda"
    pytest tests/test_skill_api_connectivity.py -v -k "gwas"

Skip when offline:
    pytest tests/ -v -m "not api"
"""

import importlib.util
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Dynamic loaders for skill scripts (hyphens in directory names)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_skill_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ot_mod = _load_skill_module(
    "query_opentargets",
    _PROJECT_ROOT / "skills" / "opentargets-database" / "scripts" / "query_opentargets.py",
)

_ct_mod = _load_skill_module(
    "query_clinicaltrials",
    _PROJECT_ROOT / "skills" / "clinicaltrials-database" / "scripts" / "query_clinicaltrials.py",
)

_fda_mod = _load_skill_module(
    "fda_query",
    _PROJECT_ROOT / "skills" / "fda-database" / "scripts" / "fda_query.py",
)

# ChEMBL loaded lazily — its skill script imports chembl_webresource_client at module level
_chembl_mod = None
try:
    _chembl_mod = _load_skill_module(
        "example_queries",
        _PROJECT_ROOT / "skills" / "chembl-database" / "scripts" / "example_queries.py",
    )
except ImportError:
    pass

_requires_chembl = pytest.mark.skipif(
    _chembl_mod is None,
    reason="chembl_webresource_client not installed",
)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

@pytest.mark.api
class TestSkillAPIConnectivity:
    """Live API smoke tests — 1-2 API calls per test, no mocks."""

    # === OpenTargets (2 tests) ===

    def test_ot_search_entities(self):
        """search_entities("TGFB1", entity_types=["target"]) returns Ensembl IDs."""
        results = _ot_mod.search_entities("TGFB1", entity_types=["target"])
        assert isinstance(results, list)
        assert len(results) > 0
        # At least one hit should have an Ensembl gene ID
        ids = [r["id"] for r in results]
        assert any(eid.startswith("ENSG") for eid in ids), f"No ENSG* IDs in {ids}"

    def test_ot_get_target_info(self):
        """Resolve TGFB1 → Ensembl ID, then get_target_info → has approvedSymbol."""
        results = _ot_mod.search_entities("TGFB1", entity_types=["target"])
        assert len(results) > 0
        ensembl_id = results[0]["id"]

        info = _ot_mod.get_target_info(ensembl_id)
        assert isinstance(info, dict)
        assert "approvedSymbol" in info
        assert info["approvedSymbol"].upper() == "TGFB1"

    # === ChEMBL (2 tests) ===

    @_requires_chembl
    def test_chembl_search_targets(self):
        """search_targets_by_name("Epidermal growth factor") returns targets."""
        # ChEMBL filters by pref_name__icontains, so use protein name not gene symbol
        results = _chembl_mod.search_targets_by_name("Epidermal growth factor")
        assert isinstance(results, list)
        assert len(results) > 0, "No ChEMBL targets found for 'Epidermal growth factor'"
        assert "target_chembl_id" in results[0]
        assert results[0]["target_chembl_id"].startswith("CHEMBL")

    @_requires_chembl
    def test_chembl_get_drug_info(self):
        """get_drug_info("CHEMBL25") returns tuple with aspirin data."""
        drug_info, mechanisms, indications = _chembl_mod.get_drug_info("CHEMBL25")
        # drug_info may be None if the drug endpoint returns nothing,
        # but mechanisms or indications should have data for aspirin
        assert isinstance(mechanisms, list)
        assert isinstance(indications, list)
        # At least one of these should be non-empty for aspirin
        assert drug_info is not None or len(mechanisms) > 0 or len(indications) > 0

    # === ClinicalTrials.gov (2 tests) ===

    def test_ct_search_studies(self):
        """search_studies(condition="breast cancer", page_size=5) → returns studies."""
        response = _ct_mod.search_studies(condition="breast cancer", page_size=5)
        assert isinstance(response, dict)
        studies = response.get("studies", [])
        assert len(studies) > 0, f"No studies returned. Keys: {list(response.keys())}"
        # totalCount may or may not be present depending on API version
        total = response.get("totalCount")
        if total is not None:
            assert total > 0

    def test_ct_extract_study_summary(self):
        """Parse first study result → has nct_id, title, status."""
        response = _ct_mod.search_studies(condition="breast cancer", page_size=1)
        studies = response.get("studies", [])
        assert len(studies) > 0

        summary = _ct_mod.extract_study_summary(studies[0])
        assert isinstance(summary, dict)
        assert summary.get("nct_id") is not None
        assert summary["nct_id"].startswith("NCT")
        assert summary.get("title") is not None
        assert summary.get("status") is not None

    # === FDA openFDA (2 tests) ===

    def test_fda_drug_label(self):
        """FDAQuery().query_drug_label("aspirin") → results list non-empty."""
        fda = _fda_mod.FDAQuery(use_cache=False)
        data = fda.query_drug_label("aspirin")
        assert isinstance(data, dict)
        results = data.get("results", [])
        assert len(results) > 0, f"No label results for aspirin: {data}"

    def test_fda_adverse_events(self):
        """FDAQuery().query("drug", "event", search="aspirin", limit=5) → has results."""
        fda = _fda_mod.FDAQuery(use_cache=False)
        data = fda.query(
            "drug", "event",
            search="patient.drug.medicinalproduct:aspirin",
            limit=5,
        )
        assert isinstance(data, dict)
        assert "error" not in data, f"FDA returned error: {data.get('error')}"
        assert len(data.get("results", [])) > 0

    # === GWAS Catalog (2 tests) ===

    def test_gwas_resolve_trait(self):
        """_resolve_trait_id("breast cancer") → returns EFO ID string."""
        from src.agents.drug_target.tools.gwas_tools import _resolve_trait_id

        trait_id = _resolve_trait_id("breast cancer")
        assert trait_id is not None, "Could not resolve 'breast cancer' to EFO trait"
        assert isinstance(trait_id, str)
        assert "EFO" in trait_id or "_" in trait_id  # e.g. "EFO_0000305"

    def test_gwas_fetch_associations(self):
        """_fetch_associations_for_trait(trait_id, max_pages=1) → non-empty list."""
        from src.agents.drug_target.tools.gwas_tools import (
            _resolve_trait_id,
            _fetch_associations_for_trait,
        )

        trait_id = _resolve_trait_id("breast cancer")
        assert trait_id is not None

        associations = _fetch_associations_for_trait(trait_id, max_pages=1)
        assert isinstance(associations, list)
        assert len(associations) > 0, f"No associations for trait {trait_id}"

    # === Integrated tool-level tests (2 tests) ===

    def test_tool_query_ot_target_info(self):
        """Call query_ot_target_info tool with real API → ensembl_id non-null."""
        from src.agents.drug_target.tools.opentargets_tools import query_ot_target_info

        raw = query_ot_target_info.invoke({
            "gene_symbol": "TGFB1",
            "disease": "breast cancer",
        })
        result = json.loads(raw)
        assert result["ensembl_id"] is not None, f"errors: {result.get('errors')}"
        assert result["ensembl_id"].startswith("ENSG")
        assert result["target_info"].get("approvedSymbol") == "TGFB1"

    def test_tool_query_gwas_trait_associations(self):
        """Call query_gwas_trait_associations tool with real API → trait_id non-null."""
        from src.agents.drug_target.tools.gwas_tools import query_gwas_trait_associations

        raw = query_gwas_trait_associations.invoke({
            "disease": "breast cancer",
            "gene_symbols": "TGFB1",
        })
        result = json.loads(raw)
        assert result["trait_id"] is not None, f"errors: {result.get('errors')}"
        assert result["total_associations_scanned"] > 0
