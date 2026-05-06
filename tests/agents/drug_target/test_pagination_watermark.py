from __future__ import annotations

from src.agents.drug_target.tools.provenance import pagination_watermark


def test_pagination_watermark_flags_equal_limit_as_capped() -> None:
    mark = pagination_watermark(source="opentargets", loaded_count=100, limit=100)
    assert mark == {
        "source": "opentargets",
        "loaded_count": 100,
        "limit": 100,
        "capped": True,
        "warning": "opentargets returned 100 rows, equal to requested limit 100; count may be incomplete.",
    }


def test_pagination_watermark_does_not_flag_below_limit() -> None:
    mark = pagination_watermark(source="chembl", loaded_count=12, limit=100)
    assert mark["capped"] is False
    assert mark["warning"] is None

