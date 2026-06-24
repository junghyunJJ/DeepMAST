from __future__ import annotations

import csv
import json
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BENCHMARK_DIR / "results"
RAW_DIR = RESULTS_DIR / "raw"
FIGURES_DIR = BENCHMARK_DIR / "figures"

RAW_EXPECTATIONS = {
    "multihop_full_qwen35_35b_port7000_wiki_off_rw3.jsonl": {
        "rows": 2556,
        "contains": 672,
        "recall_n": 2255,
    },
    "multihop_full_qwen35_35b_port7000_wiki_doc_routing_rw3.jsonl": {
        "rows": 2556,
        "contains": 892,
        "recall_n": 2255,
    },
    "multihop_full_qwen35_35b_port7000_wiki_static_refs_rw3.jsonl": {
        "rows": 2556,
        "contains": 740,
        "recall_n": 2255,
    },
    "multihop_full_qwen35_122b_port6000_wiki_off_rw3.jsonl": {
        "rows": 2556,
        "contains": 717,
        "recall_n": 2255,
    },
    "multihop_full_qwen35_122b_port6000_wiki_doc_routing_rw3.jsonl": {
        "rows": 2556,
        "contains": 811,
        "recall_n": 2255,
    },
    "multihop_full_qwen35_122b_port6000_wiki_static_refs_rw3.jsonl": {
        "rows": 2556,
        "contains": 640,
        "recall_n": 2255,
    },
}

SUMMARY_EXPECTATIONS = {
    ("35B", "wiki_off", "Exact-answer accuracy"): (0.262910798122066, 2556),
    ("35B", "wiki_off", "Evidence recall"): (0.154879920522936, 2255),
    ("35B", "wiki_doc_routing", "Exact-answer accuracy"): (0.348982785602504, 2556),
    ("35B", "wiki_doc_routing", "Evidence recall"): (0.255665684401826, 2255),
    ("122B", "wiki_off", "Exact-answer accuracy"): (0.280516431924883, 2556),
    ("122B", "wiki_off", "Evidence recall"): (0.191621408894136, 2255),
    ("122B", "wiki_doc_routing", "Exact-answer accuracy"): (0.317292644757434, 2556),
    ("122B", "wiki_doc_routing", "Evidence recall"): (0.257708027375433, 2255),
}

TEST_EXPECTATIONS = {
    ("35B", "Exact-answer accuracy"): (2556, 0.0860719874804382),
    ("35B", "Evidence recall"): (2255, 0.10078576387889),
    ("122B", "Exact-answer accuracy"): (2556, 0.0367762128325509),
    ("122B", "Evidence recall"): (2255, 0.0660866184812971),
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _assert_close(actual: float, expected: float, label: str, tolerance: float = 1e-12) -> None:
    if abs(actual - expected) > tolerance:
        raise SystemExit(f"{label}: expected {expected}, found {actual}")


def _to_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    value_text = str(value).strip().lower()
    if value_text in {"true", "t", "1", "yes", "y"}:
        return True
    if value_text in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _validate_raw() -> None:
    for filename, expected in RAW_EXPECTATIONS.items():
        path = RAW_DIR / filename
        rows = 0
        contains = 0
        recall_n = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                obj = json.loads(line)
                rows += 1
                if "id" not in obj or "contains" not in obj or "evidence_recall" not in obj:
                    raise SystemExit(f"{filename}: missing required row fields")
                contains += int(_to_bool(obj.get("contains")) is True)
                recall_n += int(obj.get("evidence_recall") is not None)

        if rows != expected["rows"]:
            raise SystemExit(f"{filename}: expected {expected['rows']} rows, found {rows}")
        if contains != expected["contains"]:
            raise SystemExit(f"{filename}: expected {expected['contains']} contains rows, found {contains}")
        if recall_n != expected["recall_n"]:
            raise SystemExit(f"{filename}: expected {expected['recall_n']} recall rows, found {recall_n}")


def _validate_summary() -> None:
    rows = _read_csv(RESULTS_DIR / "sgcp_accuracy_recall_summary.csv")
    if len(rows) != 8:
        raise SystemExit(f"expected 8 summary rows, found {len(rows)}")

    seen = set()
    for row in rows:
        key = (row["model"], row["condition"], row["metric"])
        seen.add(key)
        if key not in SUMMARY_EXPECTATIONS:
            raise SystemExit(f"unexpected summary row: {key}")
        expected_value, expected_n = SUMMARY_EXPECTATIONS[key]
        _assert_close(float(row["value"]), expected_value, f"{key} value")
        if int(row["n"]) != expected_n:
            raise SystemExit(f"{key}: expected n={expected_n}, found n={row['n']}")

    missing = sorted(set(SUMMARY_EXPECTATIONS) - seen)
    if missing:
        raise SystemExit(f"missing summary rows: {missing}")


def _validate_tests() -> None:
    rows = _read_csv(RESULTS_DIR / "sgcp_accuracy_recall_tests.csv")
    if len(rows) != 4:
        raise SystemExit(f"expected 4 test rows, found {len(rows)}")

    seen = set()
    for row in rows:
        key = (row["model"], row["metric"])
        seen.add(key)
        if key not in TEST_EXPECTATIONS:
            raise SystemExit(f"unexpected paired-test row: {key}")
        expected_n, expected_delta = TEST_EXPECTATIONS[key]
        if int(row["n_pairs"]) != expected_n:
            raise SystemExit(f"{key}: expected n_pairs={expected_n}, found {row['n_pairs']}")
        _assert_close(float(row["delta"]), expected_delta, f"{key} delta")

    missing = sorted(set(TEST_EXPECTATIONS) - seen)
    if missing:
        raise SystemExit(f"missing paired-test rows: {missing}")


def _validate_json_summaries() -> None:
    summaries = [
        RESULTS_DIR / "multihop_full_summary_35b_7000_20260604T003510Z_rw3.json",
        RESULTS_DIR / "multihop_full_summary_122b_6000_20260605T004513Z_rw3.json",
    ]
    for path in summaries:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("metadata", {}).get("max_rewrites") != 3:
            raise SystemExit(f"{path.name}: expected max_rewrites=3")
        result_keys = set(obj.get("results", {}))
        joined_keys = " ".join(result_keys)
        for condition in ("wiki_off", "wiki_static_refs", "wiki_doc_routing"):
            if condition not in joined_keys:
                raise SystemExit(f"{path.name}: expected {condition} results")


def _validate_writing_tables() -> None:
    summary_rows = _read_csv(RESULTS_DIR / "sgcp_all_conditions_summary.csv")
    if len(summary_rows) != 6:
        raise SystemExit(f"expected 6 all-condition summary rows, found {len(summary_rows)}")
    summary_keys = {(row["model"], row["condition"]) for row in summary_rows}
    expected_summary_keys = {
        ("35B", "wiki_off"),
        ("35B", "wiki_static_refs"),
        ("35B", "wiki_doc_routing"),
        ("122B", "wiki_off"),
        ("122B", "wiki_static_refs"),
        ("122B", "wiki_doc_routing"),
    }
    if summary_keys != expected_summary_keys:
        raise SystemExit(f"unexpected all-condition summary keys: {sorted(summary_keys)}")

    static_rows = [
        row for row in summary_rows
        if row["condition"] == "wiki_static_refs"
    ]
    expected_static_correct = {"35B": 740, "122B": 640}
    for row in static_rows:
        model = row["model"]
        if int(row["correct_contains"]) != expected_static_correct[model]:
            raise SystemExit(
                f"{model} static refs: expected correct_contains="
                f"{expected_static_correct[model]}, found {row['correct_contains']}"
            )

    test_rows = _read_csv(RESULTS_DIR / "sgcp_static_reference_tests.csv")
    if len(test_rows) != 4:
        raise SystemExit(f"expected 4 static-reference test rows, found {len(test_rows)}")
    test_keys = {
        (row["model"], row["baseline_condition"], row["comparison_condition"])
        for row in test_rows
    }
    expected_test_keys = {
        ("35B", "wiki_off", "wiki_static_refs"),
        ("35B", "wiki_doc_routing", "wiki_static_refs"),
        ("122B", "wiki_off", "wiki_static_refs"),
        ("122B", "wiki_doc_routing", "wiki_static_refs"),
    }
    if test_keys != expected_test_keys:
        raise SystemExit(f"unexpected static-reference test keys: {sorted(test_keys)}")


def _validate_figures() -> None:
    for filename in ["sgcp_accuracy_recall_main.png", "sgcp_accuracy_recall_main.svg"]:
        path = FIGURES_DIR / filename
        if not path.exists() or path.stat().st_size == 0:
            raise SystemExit(f"missing or empty figure: {filename}")


def main() -> None:
    _validate_raw()
    _validate_summary()
    _validate_tests()
    _validate_json_summaries()
    _validate_writing_tables()
    _validate_figures()

    print("[offline] validated SGCP reference artifacts")
    print("[offline] 35B accuracy_delta=+8.6pp")
    print("[offline] 35B recall_delta=+10.1pp")
    print("[offline] 122B accuracy_delta=+3.7pp")
    print("[offline] 122B recall_delta=+6.6pp")
    print("[offline] static-reference artifacts included for writing tables")


if __name__ == "__main__":
    main()
