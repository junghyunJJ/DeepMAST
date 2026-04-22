"""Rev 7 gene-enrichment script for the harness_x_model benchmark.

Adds an ``enriched_genes`` field (exactly 15 genes including the original
ligand+receptor) to every case in ``cci_full_cases.json``. The two enrichment
sources are orthogonal to the LIANA spatial co-expression table that ranked
the original L-R pair, preventing circular provenance (architect concern in
docs/benchmarks/harness_x_model/SESSION_SUMMARY.md lines 142-143):

1. STRING-DB high-confidence interaction partners of ligand + receptor
   (species=9606 Homo sapiens, required_score >= 700, i.e. >= 0.7 confidence).
2. KEGG pathway hub-genes from the case's ``pathway_associations`` via the
   ``PATHWAY_TO_GENES`` table already used by the production SEARCHER
   deterministic fan-out (``src/agents/deep_interpreter/tools/literature.py``).

STRING scores are scaled 0-1000 and win ties against KEGG hub scores (fixed
at 600) — this keeps the ranking empirical and pathway hubs as a fallback.

Ligand and receptor always rank 0 (mandatory inclusion). Output is written
to a NEW file (``cci_full_cases_enriched_v1.json``) beside the original so
the sibling ``cci_skill_ablation`` benchmark — which reads the original file
unchanged — is unaffected (whitelist rendering at ``benchmark_cci_core.py:381``
ignores the new field anyway, but the separate-file design is the cleaner
audit trail for Table 3 provenance).

Provenance (STRING version, script SHA, timestamp) is written to a sidecar
``*.provenance.json`` so the cases file stays a raw list that
``common.load_cases()`` can load without schema changes.

Usage
-----
    python docs/benchmarks/harness_x_model/enrich_cases_string_kegg.py

Optional args:
    --input  default: docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json
    --output default: docs/benchmarks/cci_skill_ablation/cases/cci_full_cases_enriched_v1.json
    --target-n default: 15
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.deep_interpreter.tools.literature import PATHWAY_TO_GENES

DEFAULT_INPUT = PROJECT_ROOT / "docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs/benchmarks/cci_skill_ablation/cases/cci_full_cases_enriched_v1.json"

STRING_PARTNERS_URL = "https://string-db.org/api/json/interaction_partners"
STRING_VERSION_URL = "https://string-db.org/api/json/version"
SPECIES_HUMAN = 9606
MIN_CONFIDENCE = 700  # STRING uses 0-1000; 700 = high confidence (>= 0.7)
RATE_LIMIT_S = 0.3    # Be polite with the public API (~3 req/sec)
KEGG_FALLBACK_SCORE = 600.0  # Below high-conf STRING, above anything else


def fetch_string_partners(gene: str, *, limit: int = 50) -> list[dict]:
    """High-confidence STRING interaction partners for a single gene (human)."""
    params = urllib.parse.urlencode(
        {
            "identifiers": gene,
            "species": SPECIES_HUMAN,
            "required_score": MIN_CONFIDENCE,
            "limit": limit,
            "caller_identity": "DeepMAST-Rev7-enricher",
        }
    )
    url = f"{STRING_PARTNERS_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "DeepMAST-Rev7-enricher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    partners = []
    for row in data or []:
        name = row.get("preferredName_B")
        score = row.get("score")
        if not name or score is None:
            continue
        # STRING JSON API returns score as 0-1 float; scale to 0-1000 for consistency.
        scaled = float(score) * 1000.0 if float(score) <= 1.0 else float(score)
        partners.append({"gene": name, "score": scaled})
    return partners


def fetch_string_version() -> str:
    try:
        req = urllib.request.Request(
            STRING_VERSION_URL, headers={"User-Agent": "DeepMAST-Rev7-enricher/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            return (
                f"string_version={data.get('string_version', '?')},"
                f"stable_address={data.get('stable_address', '?')}"
            )
        return f"raw={data!r}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"error:{type(exc).__name__}:{exc}"


def kegg_hub_genes_for_case(pathway_associations: list[str]) -> dict[str, float]:
    """Return {gene: KEGG_FALLBACK_SCORE} for pathway hubs of this case.

    Match pathway_associations to PATHWAY_TO_GENES keys case-insensitively and
    via substring containment — the same resolution heuristic used by
    ``_build_deterministic_pathway_queries`` at ``literature.py:~1556``.
    """
    out: dict[str, float] = {}
    for pw in pathway_associations or []:
        key = str(pw).strip().lower()
        if not key:
            continue
        genes = PATHWAY_TO_GENES.get(key)
        if not genes:
            for tk, tg in PATHWAY_TO_GENES.items():
                if tk in key or key in tk:
                    genes = tg
                    break
        if genes:
            for g in genes:
                out.setdefault(g, KEGG_FALLBACK_SCORE)
    return out


def enrich_case(case: dict, *, target_n: int = 15, log_prefix: str = "") -> tuple[list[str], dict]:
    """Return (enriched_genes, diagnostics) for a single case."""
    bundle = case.get("input_bundle") or {}
    ligand = str(bundle.get("ligand", "")).strip()
    receptor = str(bundle.get("receptor", "")).strip()
    if not ligand or not receptor:
        raise ValueError(f"{case.get('case_id')}: missing ligand/receptor")

    # tier 0 = mandatory anchors (always included)
    # tier 1 = STRING partners (empirical high-confidence)
    # tier 2 = KEGG hub genes (pathway-curated fallback)
    ranked: dict[str, tuple[int, float]] = {
        ligand: (0, 10_000.0),
        receptor: (0, 10_000.0),
    }

    string_errors: list[str] = []
    for anchor in (ligand, receptor):
        try:
            partners = fetch_string_partners(anchor, limit=50)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            string_errors.append(f"{anchor}:{type(exc).__name__}:{exc}")
            partners = []
        time.sleep(RATE_LIMIT_S)
        for p in partners:
            g = p["gene"]
            s = p["score"]
            existing = ranked.get(g)
            if existing is None or (existing[0] > 1) or (existing[0] == 1 and s > existing[1]):
                # Never downgrade the anchors (tier 0) to tier 1.
                if existing is not None and existing[0] == 0:
                    continue
                ranked[g] = (1, s)

    kegg = kegg_hub_genes_for_case(bundle.get("pathway_associations") or [])
    for g, s in kegg.items():
        if g not in ranked:
            ranked[g] = (2, s)

    # Deterministic sort: tier asc, score desc, gene name asc (alphabetical tiebreak)
    sorted_items = sorted(ranked.items(), key=lambda kv: (kv[1][0], -kv[1][1], kv[0]))
    selected = [g for g, _ in sorted_items[:target_n]]

    # Fallback padding if somehow < target_n (e.g., both STRING fetches failed and
    # no pathways): use the global union of PATHWAY_TO_GENES in deterministic order.
    if len(selected) < target_n:
        pad_pool: list[str] = []
        for _, genes in sorted(PATHWAY_TO_GENES.items()):
            for g in genes:
                if g not in selected and g not in pad_pool:
                    pad_pool.append(g)
        for g in pad_pool:
            selected.append(g)
            if len(selected) >= target_n:
                break

    # Hard invariants — will raise if violated; caller can catch.
    if ligand not in selected:
        raise AssertionError(f"{case.get('case_id')}: ligand {ligand} dropped from enriched list")
    if receptor not in selected:
        raise AssertionError(f"{case.get('case_id')}: receptor {receptor} dropped")
    if len(selected) != target_n:
        raise AssertionError(
            f"{case.get('case_id')}: enriched len={len(selected)} != {target_n}"
        )
    if len(set(selected)) != target_n:
        raise AssertionError(f"{case.get('case_id')}: enriched list has duplicates")

    diagnostics = {
        "string_errors": string_errors,
        "tier_counts": {
            "anchors": 2,
            "string": sum(1 for g in selected if ranked[g][0] == 1),
            "kegg": sum(1 for g in selected if ranked[g][0] == 2),
        },
        "n_string_candidates": sum(1 for v in ranked.values() if v[0] == 1),
        "n_kegg_candidates": sum(1 for v in ranked.values() if v[0] == 2),
    }
    print(
        f"{log_prefix}{case['case_id']}: "
        f"tiers {diagnostics['tier_counts']} "
        f"(pool: {diagnostics['n_string_candidates']} STRING, "
        f"{diagnostics['n_kegg_candidates']} KEGG)"
        + (f" string_errors={string_errors}" if string_errors else ""),
        file=sys.stderr,
    )
    return selected, diagnostics


def compute_script_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target-n", type=int, default=15)
    args = parser.parse_args()

    cases = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise SystemExit(f"{args.input}: expected JSON list")

    print(f"Enriching {len(cases)} cases from {args.input}", file=sys.stderr)
    print(f"Fetching STRING version ...", file=sys.stderr)
    string_version = fetch_string_version()
    print(f"  STRING: {string_version}", file=sys.stderr)

    enriched_cases: list[dict] = []
    per_case_diag: list[dict] = []
    started = time.perf_counter()
    for idx, case in enumerate(cases, start=1):
        try:
            enriched, diag = enrich_case(
                case, target_n=args.target_n, log_prefix=f"[{idx:02d}/{len(cases)}] "
            )
        except Exception as exc:
            print(f"[{idx:02d}] FAILED {case.get('case_id')}: {exc}", file=sys.stderr)
            raise
        new_case = dict(case)
        new_case["enriched_genes"] = enriched
        enriched_cases.append(new_case)
        per_case_diag.append({"case_id": case["case_id"], **diag})

    elapsed = round(time.perf_counter() - started, 1)
    print(f"Done in {elapsed}s. Writing {args.output}", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(enriched_cases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    provenance = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_input": str(args.input.relative_to(PROJECT_ROOT)),
        "output": str(args.output.relative_to(PROJECT_ROOT)),
        "target_n": args.target_n,
        "string_version": string_version,
        "string_params": {
            "species": SPECIES_HUMAN,
            "required_score": MIN_CONFIDENCE,
            "per_anchor_limit": 50,
            "rate_limit_s": RATE_LIMIT_S,
        },
        "kegg_source": {
            "module": "src.agents.deep_interpreter.tools.literature.PATHWAY_TO_GENES",
            "pathways_in_map": sorted(PATHWAY_TO_GENES.keys()),
            "fallback_score": KEGG_FALLBACK_SCORE,
        },
        "orthogonality_note": (
            "Enrichment sources (STRING + KEGG) are orthogonal to the LIANA "
            "spatial co-expression table (interest_sig_liana.csv) that "
            "produced the original L-R ranking. No block-list exclusion is "
            "applied; orthogonality is guaranteed by source selection, not "
            "by filtering."
        ),
        "script_sha256": compute_script_sha(),
        "script_path": str(Path(__file__).relative_to(PROJECT_ROOT)),
        "wall_time_s": elapsed,
        "per_case_diagnostics": per_case_diag,
    }
    provenance_path = args.output.with_suffix(".provenance.json")
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Provenance written to {provenance_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
