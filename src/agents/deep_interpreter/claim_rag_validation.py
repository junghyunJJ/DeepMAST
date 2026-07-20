from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from scripts import validate_report as validate_report_script
from src.agents.deep_interpreter.tools.literature_rag import (
    search_literature_fulltext as _search_literature_fulltext,
)
from src.agents.deep_interpreter.tools.mcp_clients import run_async
from src.agents.model import create_llm


REFERENCE_BLOCK_RE = re.compile(
    r"^### References\s*$\n?(.*?)(?=^### |\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
MARKDOWN_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
EXPLICIT_HYPOTHESIS_RE = re.compile(
    r"\b(hypothesis|hypothesized|needs validation|requiring validation|novel finding)\b",
    re.IGNORECASE,
)
HIGH_RISK_CLAIM_RE = re.compile(
    r"\b(activat(?:e|es|ed|ing|ion)|caus(?:e|es|ed|ing|al)|"
    r"drives?|driving|induces?|inhibits?|mediates?|mechanis[ms]?|"
    r"promotes?|regulat(?:e|es|ed|ing|ion|ory)|suppresses?|"
    r"therapeutic|therapy|treatment|drug(?:gability)?|target(?:ing)?|"
    r"resistan(?:ce|t)|sensitive|clinical|prognos(?:is|tic))\b",
    re.IGNORECASE,
)
MAX_CLAIMS_PER_JUDGMENT = 5
MAX_SKIPPED_CLAIM_SAMPLES = 50
CLAIM_RAG_CHECKPOINT_FILENAME = "claim_rag_checkpoint.json"
DEFAULT_JUDGE_NUM_PREDICT = 3000
DEFAULT_JUDGE_TIMEOUT_SECONDS = 300.0
DEFAULT_SINGLE_CLAIM_TIMEOUT_SECONDS = 120.0


class ClaimJudgment(BaseModel):
    claim_index: int = Field(ge=0)
    status: Literal["supported", "overclaimed", "unsupported", "unverifiable"]
    reason: str
    supporting_pmids: list[str] = Field(default_factory=list)
    evidence_quote: str = ""


class ClaimJudgmentBatch(BaseModel):
    judgments: list[ClaimJudgment]


class _SearchLiteratureFulltext:
    def invoke(self, args: dict[str, Any]) -> Any:
        return _search_literature_fulltext.invoke(args)


search_literature_fulltext = _SearchLiteratureFulltext()


def _positive_int_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_float_env(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _judge_timeout_seconds(*, single_claim: bool = False) -> float:
    return _positive_float_env(
        "CLAIM_RAG_SINGLE_CLAIM_TIMEOUT_SECONDS"
        if single_claim
        else "CLAIM_RAG_JUDGE_TIMEOUT_SECONDS",
        DEFAULT_SINGLE_CLAIM_TIMEOUT_SECONDS
        if single_claim
        else DEFAULT_JUDGE_TIMEOUT_SECONDS,
    )


def _create_judge_llm(provider: str | None, *, single_claim: bool = False) -> Any:
    effective_provider = (provider or os.getenv("LLM_PROVIDER", "openai")).lower()
    thinking_kwargs: dict[str, bool] = {}
    if effective_provider == "ollama":
        thinking_kwargs["reasoning"] = True
    elif effective_provider in {"vllm", "ollama-openai"}:
        thinking_kwargs["enable_thinking"] = True
    return create_llm(
        provider,
        **thinking_kwargs,
        num_predict=_positive_int_env(
            "CLAIM_RAG_JUDGE_NUM_PREDICT", DEFAULT_JUDGE_NUM_PREDICT
        ),
        request_timeout=_judge_timeout_seconds(single_claim=single_claim),
    )


def _is_high_risk_claim(claim: str) -> bool:
    return bool(HIGH_RISK_CLAIM_RE.search(claim))


def _paper_map(data_dir: Path) -> dict[str, dict[str, Any]]:
    data = json.loads((data_dir / "papers.json").read_text(encoding="utf-8"))
    rows = data.get("papers") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {}
    return {
        str(row["pmid"]): row
        for row in rows
        if isinstance(row, dict) and row.get("pmid")
    }


def _clean_claims(text: str) -> list[str]:
    claims: list[str] = []
    for window in validate_report_script._claim_windows(text):
        claim = re.sub(r"^[-*]\s+", "", window).strip()
        if (
            not claim
            or claim.startswith("#")
            or MARKDOWN_TABLE_RE.match(claim)
            or len(claim.split()) < 4
        ):
            continue
        claims.append(claim)
    return claims


def _reference_pmids(section_body: str) -> list[str]:
    match = REFERENCE_BLOCK_RE.search(section_body)
    if match is None:
        return []
    return sorted(set(validate_report_script.PMID_RE.findall(match.group(1))))


def _claim_items(
    claims: list[str],
    fallback_pmids: list[str],
    known_pmids: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        if EXPLICIT_HYPOTHESIS_RE.search(claim):
            continue
        inline_pmids = sorted(set(validate_report_script.PMID_RE.findall(claim)))
        following = claims[index + 1] if index + 1 < len(claims) else ""
        candidate_pmids = [
            pmid for pmid in (inline_pmids or fallback_pmids) if pmid in known_pmids
        ]
        items.append(
            {
                "index": index,
                "claim": claim,
                "candidate_pmids": candidate_pmids,
                "hedged": bool(
                    validate_report_script.MECHANISTIC_HEDGE_RE.search(claim)
                    or EXPLICIT_HYPOTHESIS_RE.search(following)
                ),
            }
        )
    return items


def _extract_claim_groups(
    data_dir: Path, filenames: tuple[str, ...]
) -> list[dict[str, Any]]:
    data_dir = data_dir.resolve()
    papers = _paper_map(data_dir)
    paper_pmids = sorted(papers)
    groups: list[dict[str, Any]] = []

    for filename in filenames:
        path = data_dir / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for section in validate_report_script._sections(text):
            section_body = str(section["body"])
            if filename == "synthesis.md":
                claims = _clean_claims(section_body)
                fallback_pmids = paper_pmids
            else:
                blocks = validate_report_script._biological_interpretation_blocks(
                    section_body
                )
                claims = [claim for block in blocks for claim in _clean_claims(block)]
                fallback_pmids = _reference_pmids(section_body)
            claim_items = _claim_items(claims, fallback_pmids, set(paper_pmids))
            if claim_items:
                groups.append(
                    {
                        "file": filename,
                        "section": str(section["heading"]),
                        "claims": claim_items,
                    }
                )
    return groups


def _result_pmid(result: dict[str, Any]) -> str | None:
    metadata = result.get("metadata") or {}
    direct = metadata.get("pmid")
    if direct:
        return str(direct)
    source = " ".join(
        str(metadata.get(key) or "") for key in ("filename", "source", "file_path")
    )
    match = re.search(r"pmid[_:\s-]?(\d{6,9})", source, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _abstract_evidence(
    claim: str,
    candidate_pmids: Sequence[str],
    papers: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    claim_tokens = set(re.findall(r"[a-z][a-z0-9-]{2,}", claim.lower()))
    ranked: list[tuple[int, str, str]] = []
    for pmid in candidate_pmids:
        abstract = str(papers.get(pmid, {}).get("abstract") or "").strip()
        if not abstract:
            continue
        abstract_tokens = set(re.findall(r"[a-z][a-z0-9-]{2,}", abstract.lower()))
        ranked.append((len(claim_tokens & abstract_tokens), pmid, abstract))
    ranked.sort(reverse=True)
    return [
        {"pmid": pmid, "source": "abstract", "text": abstract[:1200]}
        for score, pmid, abstract in ranked[:3]
        if score > 0 or len(candidate_pmids) == 1
    ]


def _retrieve_evidence(
    claim: str,
    candidate_pmids: Sequence[str],
    data_dir: Path,
) -> list[dict[str, str]]:
    return _retrieve_evidence_status(claim, candidate_pmids, data_dir)[0]


def _retrieve_evidence_status(
    claim: str,
    candidate_pmids: Sequence[str],
    data_dir: Path,
) -> tuple[list[dict[str, str]], str | None]:
    allowed = set(candidate_pmids)
    if not allowed:
        return [], None
    try:
        results = search_literature_fulltext.invoke(
            {
                "query": claim,
                "part_name": "all",
                "limit": 15,
                "data_dir": str(data_dir),
                "strict": True,
            }
        )
    except Exception as exc:
        return [], f"Literature retrieval failed: {type(exc).__name__}: {exc}."
    evidence: list[dict[str, str]] = []
    for result in results:
        pmid = _result_pmid(result)
        text = str(result.get("page_content") or "").strip()
        if pmid in allowed and text:
            evidence.append({"pmid": pmid, "source": "full_text", "text": text[:1200]})
        if len(evidence) == 3:
            break
    return (
        evidence or _abstract_evidence(claim, candidate_pmids, _paper_map(data_dir)),
        None,
    )


def _judgment_prompt(group: dict[str, Any]) -> str:
    payload = [
        {
            "claim_index": item["index"],
            "claim": item["claim"],
            "candidate_pmids": item["candidate_pmids"],
            "evidence": item["evidence"],
        }
        for item in group["claims"]
    ]
    return f"""Judge each biological claim using only its supplied evidence.

Statuses:
- supported: evidence directly supports the same subject, relation, direction, disease, and cell context.
- overclaimed: evidence supports a weaker association but the claim adds causality, mechanism, direction, therapeutic effect, or unsupported context.
- unsupported: supplied evidence directly conflicts with the claim or supports a materially different relation.
- unverifiable: evidence is absent, ambiguous, or insufficient. Absence of a statement is not contradiction.

Do not use outside knowledge. Retrieval similarity is not support. Return exactly one judgment for every claim_index. Keep evidence_quote short and copied from supplied evidence.

Claims and evidence:
{json.dumps(payload, indent=2, ensure_ascii=False)}
"""


def _unverifiable(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **item,
        "status": "unverifiable",
        "reason": reason,
        "supporting_pmids": [],
        "evidence_quote": "",
    }


def _checkpoint_key(group: dict[str, Any], claims: list[dict[str, Any]]) -> str:
    payload = {
        "file": group["file"],
        "section": group["section"],
        "claims": [
            {
                "index": item["index"],
                "claim": item["claim"],
                "candidate_pmids": item["candidate_pmids"],
                "hedged": item["hedged"],
            }
            for item in claims
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _load_checkpoint(path: Path) -> dict[str, Any]:
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "batches": {}}
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("version") != 1
        or not isinstance(checkpoint.get("batches"), dict)
    ):
        return {"version": 1, "batches": {}}
    return checkpoint


def _write_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(checkpoint, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _has_incomplete_judge_result(results: list[dict[str, Any]]) -> bool:
    return any(
        str(item.get("reason", "")).startswith("Claim judge failed:")
        or str(item.get("reason", "")) == "Claim judge omitted this claim."
        or str(item.get("reason", "")).startswith("Literature retrieval failed:")
        for item in results
    )


def _invoke_judgment(
    model: Any, group: dict[str, Any], *, timeout_seconds: float | None = None
) -> list[ClaimJudgment]:
    structured_model = model.with_structured_output(ClaimJudgmentBatch)
    messages = [HumanMessage(content=_judgment_prompt(group))]
    if hasattr(structured_model, "ainvoke"):
        response = run_async(structured_model.ainvoke(messages), timeout=timeout_seconds)
    else:
        response = structured_model.invoke(messages)
    return response.judgments


def _judge_source_batch(
    group: dict[str, Any],
    batch: list[dict[str, Any]],
    model: Any,
    get_model: Any | None,
    fallback_model: Any | None,
    get_fallback_model: Any | None,
    stats: dict[str, int],
) -> list[dict[str, Any]]:
    evidence_items = [item for item in batch if item["evidence"]]
    missing = {
        item["index"]: _unverifiable(
            item,
            item.get("unverifiable_reason")
            or "No allowed PMID evidence was retrieved.",
        )
        for item in batch
        if not item["evidence"]
    }
    judgments: dict[int, ClaimJudgment] = {}
    failed: dict[int, dict[str, Any]] = {}
    primary_timeout = _judge_timeout_seconds()
    fallback_timeout = _judge_timeout_seconds(single_claim=True)
    if evidence_items:
        try:
            if model is None and get_model is not None:
                model = get_model()
            stats["judgment_batch_count"] += 1
            judgments.update(
                {
                    item.claim_index: item
                    for item in _invoke_judgment(
                        model,
                        {**group, "claims": evidence_items},
                        timeout_seconds=primary_timeout,
                    )
                }
            )
        except Exception as primary_exc:
            for item in evidence_items:
                try:
                    if fallback_model is None and get_fallback_model is not None:
                        fallback_model = get_fallback_model()
                    if fallback_model is None:
                        raise primary_exc
                    stats["single_claim_fallback_count"] += 1
                    judgments.update(
                        {
                            judgment.claim_index: judgment
                            for judgment in _invoke_judgment(
                                fallback_model,
                                {**group, "claims": [item]},
                                timeout_seconds=fallback_timeout,
                            )
                        }
                    )
                except Exception as fallback_exc:
                    failed[item["index"]] = _unverifiable(
                        item, f"Claim judge failed: {type(fallback_exc).__name__}."
                    )

    results: list[dict[str, Any]] = []
    for item in batch:
        if item["index"] in missing:
            results.append(missing[item["index"]])
            continue
        if item["index"] in failed:
            results.append(failed[item["index"]])
            continue
        judgment = judgments.get(item["index"])
        if judgment is None:
            results.append(_unverifiable(item, "Claim judge omitted this claim."))
            continue
        results.append(
            {
                **item,
                "status": judgment.status,
                "reason": judgment.reason,
                "supporting_pmids": judgment.supporting_pmids,
                "evidence_quote": judgment.evidence_quote,
            }
        )
    return results


def _judge_group(
    group: dict[str, Any],
    model: Any,
    fallback_model: Any | None = None,
    checkpoint: dict[str, Any] | None = None,
    flush_checkpoint: Any | None = None,
    *,
    data_dir: Path | None = None,
    stats: dict[str, int] | None = None,
    get_model: Any | None = None,
    get_fallback_model: Any | None = None,
) -> list[dict[str, Any]]:
    checkpoint = checkpoint if checkpoint is not None else {"version": 1, "batches": {}}
    batches = checkpoint.setdefault("batches", {})
    if flush_checkpoint is None:
        flush_checkpoint = lambda: None
    stats = stats if stats is not None else {
        "checkpoint_hits": 0,
        "judgment_batch_count": 0,
        "single_claim_fallback_count": 0,
    }
    results: list[dict[str, Any]] = []
    for start in range(0, len(group["claims"]), MAX_CLAIMS_PER_JUDGMENT):
        batch = group["claims"][start : start + MAX_CLAIMS_PER_JUDGMENT]
        key = _checkpoint_key(group, batch)
        saved = batches.get(key)
        if isinstance(saved, dict) and isinstance(saved.get("results"), list):
            stats["checkpoint_hits"] += 1
            results.extend(saved["results"])
            continue

        enriched = []
        for item in batch:
            evidence = item.get("evidence") if "evidence" in item else None
            unverifiable_reason = item.get("unverifiable_reason")
            if "evidence" not in item and data_dir is not None:
                evidence, unverifiable_reason = _retrieve_evidence_status(
                    item["claim"], item["candidate_pmids"], data_dir
                )
            enriched.append(
                {
                    **item,
                    "file": group["file"],
                    "section": group["section"],
                    "evidence": evidence or [],
                    "unverifiable_reason": unverifiable_reason,
                }
            )
        judged = _judge_source_batch(
            group,
            enriched,
            model,
            get_model,
            fallback_model,
            get_fallback_model,
            stats,
        )
        if not _has_incomplete_judge_result(judged):
            batches[key] = {"results": judged}
            flush_checkpoint()
        results.extend(judged)
    return results


def _issue_for(result: dict[str, Any]) -> dict[str, str] | None:
    status = str(result["status"])
    if status == "supported":
        return None
    hedged = bool(result["hedged"])
    severity = "warning" if status == "unverifiable" or hedged else "error"
    code = "claim_rag_hypothesis_warning" if hedged else f"claim_rag_{status}"
    pmids = ", ".join(result["supporting_pmids"]) or "none"
    quote = str(result["evidence_quote"]).strip()
    evidence = f"{result['reason']} PMIDs: {pmids}."
    if quote:
        evidence += f" Evidence: {quote}"
    instruction = (
        "Leave this claim unchanged and record the evidence gap."
        if severity == "warning"
        else "Rewrite only this claim to match the supported association; do not add a new PMID."
        if status == "overclaimed"
        else "Remove the unsupported assertion or mark it as a hypothesis requiring validation; do not add a new PMID."
    )
    return {
        "code": code,
        "severity": severity,
        "file": str(result["file"]),
        "section": str(result["section"]),
        "value": str(result["claim"]),
        "evidence": evidence,
        "repair_instruction": instruction,
    }


def validate_claims(
    data_dir: str | Path,
    filenames: tuple[str, ...],
    *,
    provider: str | None = None,
    llm: Any | None = None,
    cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir).expanduser().resolve()
    cache = cache if cache is not None else {}
    model = llm
    fallback_model: Any | None = None
    checkpoint_path = data_dir / CLAIM_RAG_CHECKPOINT_FILENAME
    checkpoint = _load_checkpoint(checkpoint_path)
    stats = {
        "checkpoint_hits": 0,
        "judgment_batch_count": 0,
        "single_claim_fallback_count": 0,
    }
    results: list[dict[str, Any]] = []
    selection: dict[str, Any] = {
        "extracted_claim_count": 0,
        "selected_claim_count": 0,
        "skipped_claim_count": 0,
        "skipped_claims_truncated": False,
        "skipped_claims": [],
        "checkpoint_hits": 0,
        "judgment_batch_count": 0,
        "single_claim_fallback_count": 0,
    }
    selected_groups: list[dict[str, Any]] = []

    for group in _extract_claim_groups(data_dir, filenames):
        selected_claims: list[dict[str, Any]] = []
        for item in group["claims"]:
            selection["extracted_claim_count"] += 1
            if _is_high_risk_claim(str(item["claim"])):
                selection["selected_claim_count"] += 1
                selected_claims.append(item)
                continue
            selection["skipped_claim_count"] += 1
            if len(selection["skipped_claims"]) < MAX_SKIPPED_CLAIM_SAMPLES:
                selection["skipped_claims"].append(
                    {
                        "file": group["file"],
                        "section": group["section"],
                        "index": item["index"],
                        "claim": item["claim"],
                        "reason": "outside_high_risk_scope",
                    }
                )
            else:
                selection["skipped_claims_truncated"] = True
        if selected_claims:
            selected_groups.append({**group, "claims": selected_claims})

    for group in selected_groups:
        cache_key = json.dumps(group, sort_keys=True, ensure_ascii=False)
        cached = cache.get(cache_key)
        if cached is not None:
            results.extend(cached)
            continue

        def get_fallback_model() -> Any:
            nonlocal fallback_model
            if fallback_model is None:
                fallback_model = _create_judge_llm(provider, single_claim=True)
            return fallback_model

        def get_model() -> Any:
            nonlocal model
            if model is None:
                model = _create_judge_llm(provider)
            return model

        judged = _judge_group(
            group,
            model,
            fallback_model,
            checkpoint,
            lambda: _write_checkpoint(checkpoint_path, checkpoint),
            data_dir=data_dir,
            stats=stats,
            get_model=get_model,
            get_fallback_model=get_fallback_model,
        )
        if not _has_incomplete_judge_result(judged):
            cache[cache_key] = judged
        results.extend(judged)

    selection.update(stats)
    issues = [issue for result in results if (issue := _issue_for(result)) is not None]
    return {"claims": results, "issues": issues, "selection": selection}
