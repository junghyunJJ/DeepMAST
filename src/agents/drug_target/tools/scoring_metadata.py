"""Shared scoring metadata used by drug-target scoring and report rendering."""

from __future__ import annotations


NOVELTY_OPPORTUNITY_BUCKETS = (
    {
        "score": 0,
        "min_count": 1000,
        "label": "1000+ associations",
        "description": "well-studied target",
    },
    {
        "score": 1,
        "min_count": 300,
        "label": "300-999 associations",
        "description": "moderately studied target",
    },
    {
        "score": 2,
        "min_count": 100,
        "label": "100-299 associations",
        "description": "emerging target",
    },
    {
        "score": 3,
        "min_count": 30,
        "label": "30-99 associations",
        "description": "less explored target",
    },
    {
        "score": 4,
        "min_count": 10,
        "label": "10-29 associations",
        "description": "sparsely explored target",
    },
    {
        "score": 5,
        "min_count": 0,
        "label": "0-9 associations",
        "description": "ST-only discovery or brand-new target",
    },
)

NOVELTY_OPPORTUNITY_LEGEND = (
    "Inverse of number of disease associations: "
    + "; ".join(
        f"{bucket['score']} = {bucket['label']} ({bucket['description']})"
        for bucket in NOVELTY_OPPORTUNITY_BUCKETS
    )
)
