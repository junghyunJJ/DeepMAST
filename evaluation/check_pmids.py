"""PMID existence checker for evidence files."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from evaluation.schema import ValidationError, load_yaml

PMID_RE = re.compile(r"^[1-9][0-9]{4,8}$")


class PMIDLookupError(RuntimeError):
    """Raised when PMID lookup cannot be completed due to connectivity/decoding issues."""


def is_valid_pmid_format(pmid: str) -> bool:
    return bool(PMID_RE.fullmatch(pmid))


def default_fetch_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch JSON with retry/backoff for transient PubMed API failures."""
    req = urllib.request.Request(url, headers={"User-Agent": "DeepMAST-Eval/1.0"})
    max_attempts = 4
    backoff_sec = 0.6

    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # NCBI occasionally throttles burst traffic (429) or returns transient 5xx.
            if exc.code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                time.sleep(backoff_sec * attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            if attempt < max_attempts:
                time.sleep(backoff_sec * attempt)
                continue
            raise

    raise PMIDLookupError("Failed to fetch PMID metadata after retries")


def pmid_exists(
    pmid: str,
    fetcher: Callable[[str], dict[str, Any]] = default_fetch_json,
    *,
    raise_on_lookup_error: bool = False,
) -> bool:
    pmid = str(pmid).strip()
    if not is_valid_pmid_format(pmid):
        return False

    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        f"esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
    )
    try:
        payload = fetcher(url)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        if raise_on_lookup_error:
            raise PMIDLookupError(f"Could not look up PMID {pmid}")
        return False

    uids = payload.get("result", {}).get("uids", [])
    return pmid in {str(uid) for uid in uids}


def iter_evidence_files(evidence_dir: str | Path) -> list[Path]:
    evidence_path = Path(evidence_dir)
    if not evidence_path.exists():
        raise FileNotFoundError(f"Evidence directory not found: {evidence_path}")

    files = [
        p
        for p in sorted(evidence_path.glob("*.yaml"))
        if p.name != "_template.yaml"
    ]
    if not files:
        raise FileNotFoundError(f"No evidence YAML files found in: {evidence_path}")
    return files


def extract_pmids_from_evidence_file(path: str | Path) -> set[str]:
    payload = load_yaml(path)
    claims = payload.get("claims", [])
    if not isinstance(claims, list):
        raise ValidationError(f"'claims' must be a list in {path}")

    pmids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for field in ("pmid_primary", "pmid_support"):
            raw = claim.get(field)
            if raw is None:
                continue
            pmids.add(str(raw).strip())
    return pmids


def collect_pmids(evidence_dir: str | Path) -> set[str]:
    pmids: set[str] = set()
    for path in iter_evidence_files(evidence_dir):
        pmids |= extract_pmids_from_evidence_file(path)
    return {p for p in pmids if p}


def check_pmids(
    evidence_dir: str | Path,
    fetcher: Callable[[str], dict[str, Any]] = default_fetch_json,
) -> tuple[list[str], list[str]]:
    """Backward-compatible checker returning only (valid, invalid)."""
    valid, invalid, unknown = check_pmids_detailed(evidence_dir, fetcher=fetcher)
    return valid, invalid + unknown


def check_pmids_detailed(
    evidence_dir: str | Path,
    fetcher: Callable[[str], dict[str, Any]] = default_fetch_json,
) -> tuple[list[str], list[str], list[str]]:
    valid: list[str] = []
    invalid: list[str] = []
    unknown: list[str] = []

    for pmid in sorted(collect_pmids(evidence_dir)):
        try:
            exists = pmid_exists(pmid, fetcher=fetcher, raise_on_lookup_error=True)
        except PMIDLookupError:
            unknown.append(pmid)
            continue

        if exists:
            valid.append(pmid)
        else:
            invalid.append(pmid)
    return valid, invalid, unknown


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate PMID existence in evidence files")
    parser.add_argument(
        "--evidence",
        default="evaluation/evidence",
        help="Directory with evidence YAML files",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if invalid PMIDs are found",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    valid, invalid, unknown = check_pmids_detailed(args.evidence)
    print(f"PMID check: valid={len(valid)} invalid={len(invalid)} unknown={len(unknown)}")
    if invalid:
        print("Invalid PMIDs:")
        for pmid in invalid:
            print(f"- {pmid}")
    if unknown:
        print("PMIDs could not be verified due to lookup errors:")
        for pmid in unknown:
            print(f"- {pmid}")

    if args.strict and (invalid or unknown):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
