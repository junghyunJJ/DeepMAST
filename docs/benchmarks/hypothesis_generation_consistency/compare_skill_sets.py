from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.hypothesis_generation_consistency.analysis import (
    jaccard,
    summarize_report,
    text_similarity,
)

IGNORED_EVIDENCE_FINGERPRINT_FILES = {
    "hypothesis_report.json",
    "hypothesis_draft.json",
    "hypothesis_report_last_rejection.json",
}


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def evidence_fingerprint(workspace: Path) -> dict[str, Any]:
    evidence_dir = workspace / "evidence"
    digest = hashlib.sha256()
    included: list[str] = []
    if not evidence_dir.exists():
        return {"sha256": "", "file_count": 0, "files": []}
    for path in sorted(evidence_dir.glob("*.json")):
        if path.name in IGNORED_EVIDENCE_FINGERPRINT_FILES:
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        included.append(path.name)
    return {"sha256": digest.hexdigest(), "file_count": len(included), "files": included}


def load_report_summary(workspace: Path) -> dict[str, Any]:
    report_path = workspace / "evidence" / "hypothesis_report.json"
    report = read_json(report_path)
    if not isinstance(report, dict):
        raise TypeError(f"{report_path} must contain a JSON object")
    return summarize_report(report)


def _round_or_none(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def compare_pair(pair: dict[str, Any]) -> dict[str, Any]:
    case_id = str(pair["case_id"])
    current4 = resolve_path(str(pair["current4"]))
    expanded6 = resolve_path(str(pair["expanded6"]))
    current_summary = load_report_summary(current4)
    expanded_summary = load_report_summary(expanded6)
    current_fingerprint = evidence_fingerprint(current4)
    expanded_fingerprint = evidence_fingerprint(expanded6)

    return {
        "case_id": case_id,
        "current4": str(current4),
        "expanded6": str(expanded6),
        "current4_hypothesis_count": current_summary["hypothesis_count"],
        "expanded6_hypothesis_count": expanded_summary["hypothesis_count"],
        "current4_topn_missing": current_summary["topn_missing"],
        "expanded6_topn_missing": expanded_summary["topn_missing"],
        "current4_category_counts": current_summary["category_counts"],
        "expanded6_category_counts": expanded_summary["category_counts"],
        "gene_jaccard": _round_or_none(
            jaccard(
                set(current_summary["covered_genes"]),
                set(expanded_summary["covered_genes"]),
            )
        ),
        "evidence_ref_jaccard": _round_or_none(
            jaccard(
                set(current_summary["evidence_refs"]),
                set(expanded_summary["evidence_refs"]),
            )
        ),
        "title_similarity": _round_or_none(
            text_similarity(
                current_summary["titles_joined"],
                expanded_summary["titles_joined"],
            )
        ),
        "core_claim_similarity": _round_or_none(
            text_similarity(
                current_summary["core_claims_joined"],
                expanded_summary["core_claims_joined"],
            )
        ),
        "current4_evidence_fingerprint": current_fingerprint,
        "expanded6_evidence_fingerprint": expanded_fingerprint,
        "evidence_fingerprint_match": (
            current_fingerprint["sha256"] == expanded_fingerprint["sha256"]
        ),
    }


def _fmt_list(values: Any) -> str:
    if not values:
        return "-"
    if isinstance(values, list):
        return ", ".join(str(value) for value in values) or "-"
    return str(values)


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Current4 vs Expanded6 Hypothesis Comparison",
        "",
        "| Case | Current4 n | Expanded6 n | Current4 TOP-N missing | Expanded6 TOP-N missing | Gene Jaccard | Ref Jaccard | Title sim | Core claim sim | Same evidence |",
        "| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {case_id} | {current4_n} | {expanded6_n} | {current4_missing} | "
            "{expanded6_missing} | {gene_jaccard} | {ref_jaccard} | {title_sim} | "
            "{claim_sim} | {same_evidence} |".format(
                case_id=row["case_id"],
                current4_n=row["current4_hypothesis_count"],
                expanded6_n=row["expanded6_hypothesis_count"],
                current4_missing=_fmt_list(row["current4_topn_missing"]),
                expanded6_missing=_fmt_list(row["expanded6_topn_missing"]),
                gene_jaccard=row["gene_jaccard"],
                ref_jaccard=row["evidence_ref_jaccard"],
                title_sim=row["title_similarity"],
                claim_sim=row["core_claim_similarity"],
                same_evidence=row["evidence_fingerprint_match"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare current4 and expanded6 hypothesis_report.json outputs."
    )
    parser.add_argument("--pairs-json", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = read_json(resolve_path(args.pairs_json))
    if not isinstance(payload, dict):
        raise SystemExit(
            "--pairs-json must contain a JSON object with a non-empty 'pairs' list"
        )
    pairs = payload.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise SystemExit("--pairs-json must contain a non-empty 'pairs' list")
    rows = [compare_pair(pair) for pair in pairs]
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "comparison_results.json", {"pairs": rows})
    (output_dir / "comparison_summary.md").write_text(
        render_markdown(rows),
        encoding="utf-8",
    )
    print(f"wrote {output_dir / 'comparison_results.json'}")
    print(f"wrote {output_dir / 'comparison_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
