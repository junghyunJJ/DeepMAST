#!/usr/bin/env python3
"""Write deterministic QC for the RAG-ready production literature handoff.

This script starts from already-created ``citation_candidates.json`` files. It
does not rerun literature search and does not call LLM judges.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks.run_handoff_ranking_policy_benchmark import (
    _as_list,
    _candidate_papers,
    _concentration_metrics,
    _coverage_for_selection,
    _journal_quality,
    _lr_pairs,
    _mean,
    _median,
    _pair_key,
    _pair_label,
    _paper_supported_pair_keys,
    _safe_id,
    _selected_pmids,
)
from src.agents.deep_interpreter.tools.literature_handoff import (
    BACKGROUND_BUCKET,
    CONTEXT_BUCKET,
    DEFAULT_HANDOFF_CAP,
    DIRECT_BUCKET,
    HANDOFF_POLICY_NAME,
    REJECTED_BUCKET,
    build_literature_handoff,
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = {key for row in rows for key in row.keys()}
    preferred = [
        "candidate_id",
        "policy",
        "cap",
        "eligible_count",
        "selected_count",
        "eligible_all_selected",
        "unused_capacity_count",
        "available_direct_count",
        "selected_direct_count",
        "available_context_count",
        "selected_context_count",
        "available_disease_only_count",
        "available_rejected_count",
        "leakage_count",
        "lr_pairs_covered_count",
        "lr_pair_coverage_pct",
        "genes_covered_count",
        "gene_coverage_pct",
        "pathways_covered_count",
        "pathway_coverage_pct",
        "celltypes_covered_count",
        "celltype_coverage_pct",
        "top_pair_share",
        "pair_hhi",
        "journal_quality_mean",
        "journal_quality_median",
        "candidate_path",
    ]
    fieldnames = [field for field in preferred if field in fields]
    fieldnames.extend(sorted(fields - set(fieldnames)))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _load_candidate_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    for value in args.candidate_path or []:
        paths.append(Path(value).expanduser().resolve())
    for pattern in args.candidate_glob or []:
        paths.extend(
            Path(match).resolve()
            for match in sorted(glob.glob(str(Path(pattern).expanduser()), recursive=True))
        )

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _candidate_ids(paths: list[Path]) -> dict[Path, str]:
    counts: Counter[str] = Counter()
    ids: dict[Path, str] = {}
    for path in paths:
        base = _safe_id(path.parent.name if path.name == "citation_candidates.json" else path.stem)
        counts[base] += 1
        ids[path] = base if counts[base] == 1 else f"{base}_{counts[base]}"
    return ids


def _clean_candidate_papers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    for paper in _candidate_papers(payload):
        clean = dict(paper)
        clean.pop("_candidate_original_index", None)
        papers.append(clean)
    return papers


def _hhi(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return round(sum((count / total) ** 2 for count in counter.values()), 4)


def _top_share(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return round(max(counter.values()) / total, 4)


def _pair_counts(
    *,
    candidate_id: str,
    payload: dict[str, Any],
    selected: list[dict[str, Any]],
    all_papers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pair_rows: list[dict[str, Any]] = []
    pair_counter: Counter[str] = Counter()
    selected_by_key = {
        _pair_key(pair): pair
        for pair in _lr_pairs(payload)
        if _pair_key(pair)
    }

    for paper in selected:
        for key in _paper_supported_pair_keys(paper, payload, infer_text=False):
            if key in selected_by_key:
                pair_counter[key] += 1

    for key, pair in selected_by_key.items():
        pair_selected = [
            paper
            for paper in selected
            if key in _paper_supported_pair_keys(paper, payload, infer_text=False)
        ]
        pair_available = [
            paper
            for paper in all_papers
            if key in _paper_supported_pair_keys(paper, payload, infer_text=False)
        ]
        pair_rows.append(
            {
                "candidate_id": candidate_id,
                "lr_pair": _pair_label(pair),
                "ligand": pair.get("ligand", ""),
                "receptor": pair.get("receptor", ""),
                "available_direct_count": sum(
                    1
                    for paper in pair_available
                    if paper.get("evidence_bucket") == DIRECT_BUCKET
                ),
                "available_context_count": sum(
                    1
                    for paper in pair_available
                    if paper.get("evidence_bucket") == CONTEXT_BUCKET
                ),
                "selected_direct_count": sum(
                    1
                    for paper in pair_selected
                    if paper.get("evidence_bucket") == DIRECT_BUCKET
                ),
                "selected_context_count": sum(
                    1
                    for paper in pair_selected
                    if paper.get("evidence_bucket") == CONTEXT_BUCKET
                ),
                "selected_count": len(pair_selected),
            }
        )

    return pair_rows, {
        "top_pair_share": _top_share(pair_counter),
        "pair_hhi": _hhi(pair_counter),
        "top_pair": selected_by_key[pair_counter.most_common(1)[0][0]].get(
            "lr_pair",
            "",
        )
        if pair_counter
        else "",
    }


def _summary_row(
    *,
    candidate_id: str,
    candidate_path: Path,
    payload: dict[str, Any],
    handoff: dict[str, Any],
    all_papers: list[dict[str, Any]],
    pair_metrics: dict[str, Any],
) -> dict[str, Any]:
    selected = handoff.get("papers", [])
    policy = handoff.get("policy", {})
    counts = handoff.get("counts", {})
    pmids = _selected_pmids(selected)
    journal_values = [_journal_quality(paper) for paper in selected if "journal_quality" in paper]
    leakage_count = sum(
        1
        for paper in selected
        if paper.get("evidence_bucket") not in {DIRECT_BUCKET, CONTEXT_BUCKET}
    )
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "candidate_path": str(candidate_path),
        "policy": policy.get("name", HANDOFF_POLICY_NAME),
        "cap": policy.get("cap", DEFAULT_HANDOFF_CAP),
        "candidate_unique_papers": int(
            (payload.get("source") or {}).get("unique_papers") or len(all_papers)
        ),
        "eligible_count": policy.get("eligible_count", 0),
        "eligible_all_selected": policy.get("eligible_all_selected", False),
        "unused_capacity_count": policy.get("unused_capacity_count", 0),
        "available_direct_count": policy.get("available_direct_count", 0),
        "available_context_count": policy.get("available_context_count", 0),
        "available_disease_only_count": int(counts.get(BACKGROUND_BUCKET, 0) or 0),
        "available_rejected_count": int(counts.get(REJECTED_BUCKET, 0) or 0),
        "selected_count": policy.get("selected_count", len(selected)),
        "selected_direct_count": policy.get("selected_direct_count", 0),
        "selected_context_count": policy.get("selected_context_count", 0),
        "direct_truncated_count": policy.get("direct_truncated_count", 0),
        "context_truncated_count": policy.get("context_truncated_count", 0),
        "leakage_count": leakage_count,
        "unique_pmid_count": len(set(pmids)),
        "duplicate_selected_count": len(pmids) - len(set(pmids)),
        "selected_pmids": ";".join(pmids),
        "journal_quality_count": len(journal_values),
        "journal_quality_mean": _mean(journal_values),
        "journal_quality_median": _median(journal_values),
        "journal_quality_min": round(min(journal_values), 4) if journal_values else 0.0,
        "journal_quality_max": round(max(journal_values), 4) if journal_values else 0.0,
    }
    row.update(_coverage_for_selection(selected, payload))
    row.update(_concentration_metrics(selected, payload))
    row.update(pair_metrics)
    return row


def _selected_rows(
    *,
    candidate_id: str,
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, paper in enumerate(selected, start=1):
        rows.append(
            {
                "candidate_id": candidate_id,
                "selected_rank": index,
                "pmid": paper.get("pmid", ""),
                "doi": paper.get("doi", ""),
                "title": paper.get("title", ""),
                "evidence_bucket": paper.get("evidence_bucket", ""),
                "supported_lr_pairs": json.dumps(
                    paper.get("supported_lr_pairs", []),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "journal_quality": paper.get("journal_quality", ""),
            }
        )
    return rows


def _validate_row(row: dict[str, Any]) -> None:
    cap = int(row["cap"])
    eligible = int(row["eligible_count"])
    selected = int(row["selected_count"])
    expected = min(eligible, cap)
    if selected != expected:
        raise RuntimeError(
            f"{row['candidate_id']}: selected_count {selected} != min({eligible}, {cap})"
        )
    if int(row["leakage_count"]) != 0:
        raise RuntimeError(f"{row['candidate_id']}: ineligible bucket leakage detected")
    if eligible < cap and row["eligible_all_selected"] is not True:
        raise RuntimeError(f"{row['candidate_id']}: eligible_all_selected should be true")


def _write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    total_candidates = len(rows)
    total_selected = sum(int(row["selected_count"]) for row in rows)
    total_eligible = sum(int(row["eligible_count"]) for row in rows)
    total_leakage = sum(int(row["leakage_count"]) for row in rows)
    below_cap = sum(1 for row in rows if bool(row["eligible_all_selected"]))
    lines = [
        "# RAG-ready Literature Handoff QC 결과",
        "",
        f"- 생성 시각: {_utc_now()}",
        f"- policy: `{HANDOFF_POLICY_NAME}`",
        f"- candidate_count: {total_candidates}",
        f"- eligible_count 합계: {total_eligible}",
        f"- selected_count 합계: {total_selected}",
        f"- below-cap eligible-all-selected case: {below_cap}",
        f"- leakage_count 합계: {total_leakage}",
        "",
        "## 판정",
        "",
    ]
    if total_leakage:
        lines.append("FAIL: disease-only 또는 rejected bucket이 handoff에 포함되었습니다.")
    else:
        lines.append(
            "PASS: `papers.json`은 direct/context evidence만 포함하며, "
            "selected_count는 `min(eligible_count, cap)` 계약을 따른다."
        )
    lines.extend(
        [
            "",
            "## 해석",
            "",
            "- eligible direct/context가 cap 100 미만이면 전부 선택하며, unused capacity는 실패가 아니다.",
            "- eligible direct/context가 cap을 초과할 때만 direct 보존 및 LR pair round-robin으로 truncation한다.",
            "- 이전 cap-40 ranking benchmark는 legacy diagnostic이며 이번 QC의 primary evidence가 아니다.",
            "",
            "## 산출물",
            "",
            "- `rag_handoff_qc_summary.csv`",
            "- `rag_handoff_pair_coverage.csv`",
            "- `rag_handoff_selected_papers.csv`",
            "- `rag_handoff_excluded_bucket_qc.json`",
            "- `selected_papers/<candidate_id>/papers.json`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_qc(
    *,
    candidate_paths: list[Path],
    output_dir: Path,
    cap: int = DEFAULT_HANDOFF_CAP,
) -> dict[str, Any]:
    if not candidate_paths:
        raise ValueError("no citation_candidates.json inputs found")

    candidate_id_by_path = _candidate_ids(candidate_paths)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    excluded_qc_rows: list[dict[str, Any]] = []

    for candidate_path in candidate_paths:
        payload = _read_json(candidate_path)
        if not isinstance(payload, dict):
            raise ValueError(f"candidate JSON must be an object: {candidate_path}")
        candidate_id = candidate_id_by_path[candidate_path]
        all_papers = _clean_candidate_papers(payload)
        handoff = build_literature_handoff(
            all_papers,
            cap=cap,
            lr_pairs=_as_list((payload.get("inputs") or {}).get("lr_pairs")),
        )
        handoff["source"]["citation_candidates_path"] = str(candidate_path)
        handoff["source"]["candidate_id"] = candidate_id
        _write_json(output_dir / "selected_papers" / candidate_id / "papers.json", handoff)

        candidate_pair_rows, pair_metrics = _pair_counts(
            candidate_id=candidate_id,
            payload=payload,
            selected=handoff["papers"],
            all_papers=all_papers,
        )
        pair_rows.extend(candidate_pair_rows)
        row = _summary_row(
            candidate_id=candidate_id,
            candidate_path=candidate_path,
            payload=payload,
            handoff=handoff,
            all_papers=all_papers,
            pair_metrics=pair_metrics,
        )
        _validate_row(row)
        summary_rows.append(row)
        selected_rows.extend(_selected_rows(candidate_id=candidate_id, selected=handoff["papers"]))
        excluded_qc_rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_path": str(candidate_path),
                "available_disease_only_count": row["available_disease_only_count"],
                "available_rejected_count": row["available_rejected_count"],
                "selected_disease_only_or_rejected_count": row["leakage_count"],
            }
        )

    _write_csv(output_dir / "rag_handoff_qc_summary.csv", summary_rows)
    _write_csv(output_dir / "rag_handoff_pair_coverage.csv", pair_rows)
    _write_csv(output_dir / "rag_handoff_selected_papers.csv", selected_rows)
    _write_json(output_dir / "rag_handoff_excluded_bucket_qc.json", excluded_qc_rows)
    _write_json(
        output_dir / "run_config.json",
        {
            "created_at_utc": _utc_now(),
            "policy": HANDOFF_POLICY_NAME,
            "cap": cap,
            "candidate_paths": [str(path) for path in candidate_paths],
            "candidate_count": len(candidate_paths),
            "contract": {
                "selected_count": "min(eligible_direct_context_count, cap)",
                "excluded_buckets": [BACKGROUND_BUCKET, REJECTED_BUCKET],
                "eligible_all_selected_when_below_cap": True,
            },
        },
    )
    _write_report(output_dir / "RAG_HANDOFF_QC_KO.md", summary_rows)
    return {"summary": summary_rows, "pair_coverage": pair_rows, "selected": selected_rows}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-path", action="append", default=[])
    parser.add_argument("--candidate-glob", action="append", default=[])
    parser.add_argument(
        "--output-dir",
        default=(
            "docs/benchmarks/lr_retrieval_relevance/results/"
            "cci_rag_ready_handoff_cap100_20260603"
        ),
    )
    parser.add_argument("--cap", type=int, default=DEFAULT_HANDOFF_CAP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    candidate_paths = _load_candidate_paths(args)
    result = run_qc(
        candidate_paths=candidate_paths,
        output_dir=output_dir,
        cap=args.cap,
    )
    print(
        f"Saved RAG handoff QC to {output_dir} "
        f"({len(result['summary'])} candidates, policy={HANDOFF_POLICY_NAME})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
