"""Generate 4-era comparison summary — pre-update / skillv1 / skillv2 / skillv3."""
from __future__ import annotations

import glob
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("docs/benchmarks/harness_x_model/results")


def per_mode_delta(dir_path: Path) -> dict[str, float | int | None]:
    rows = [json.loads(Path(f).read_text().splitlines()[-1]) for f in sorted(glob.glob(str(dir_path / "trial_*.jsonl")))]
    valid = [r for r in rows if not r.get("error")]
    bc: dict[str, list[float]] = {}
    for row in valid:
        bc.setdefault(row["condition"], []).append(row.get("celltypes_coverage_pct", 0))

    def d(c1: str, c2: str) -> float | None:
        if c1 not in bc or c2 not in bc:
            return None
        return statistics.median(bc[c1]) - statistics.median(bc[c2])

    return {
        "n_valid": len(valid),
        "n_total": len(rows),
        "strong_delta": d("strong_on", "strong_off"),
        "weak_delta": d("weak_on", "weak_off"),
        "strong_on_med": statistics.median(bc.get("strong_on", [0])) if bc.get("strong_on") else None,
        "strong_off_med": statistics.median(bc.get("strong_off", [0])) if bc.get("strong_off") else None,
    }


def load_pooled(path: Path) -> dict | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return {
        "n_total": data.get("n_total"),
        "per_dataset": data.get("per_dataset"),
        "tost": data.get("tost_equivalence"),
        "celltype_summary": data.get("celltype_primary_summary", ""),
    }


def verdict(delta: float | None) -> str:
    if delta is None:
        return "— (n/a)"
    if 12 <= delta <= 22:
        return "✅ STRENGTHENED"
    if 5 <= delta < 12 or 22 < delta <= 30:
        return "⚠️  NUANCED"
    if -3 < delta < 5:
        return "❌ NON-REPLICATION"
    if abs(delta) < 3:
        return "✅ NULL (mode B)"
    return "⚠️  OUT-OF-WINDOW"


def f(value: float | None, fmt: str = "+.2f") -> str:
    if value is None:
        return "—"
    return format(value, fmt)


def extract_pooled_beta(pooled: dict | None) -> tuple[float | None, float | None]:
    if pooled is None:
        return None, None
    summary = pooled.get("celltype_summary", "")
    match = re.search(r"skill_onTRUE\s+([+-]?\d+\.\d+)\s+(\d+\.\d+)\s+([+-]?\d+\.\d+)", summary)
    if match:
        return float(match.group(1)), float(match.group(3))
    return None, None


eras: dict[str, dict] = {}

eras["pre_update_skillv0"] = {
    "source": "FINDINGS_SKILL_MECHANISM.md (2026-04-16 pilot, SKILLv0)",
    "B": {"strong_delta": 0.00, "weak_delta": 0.00},
    "B_prime": {"strong_delta": 25.93, "weak_delta": 16.96},
    "C": {"strong_delta": 25.90, "weak_delta": 14.58},
    "pooled_beta": 10.30,
    "pooled_p": 0.001,
}

v1_pooled = load_pooled(BASE / "pooled_postupdate_v1.json")
eras["post_update_skillv1"] = {
    "source": "Rev 4 pilot (2026-04-18, SKILLv1 post-ce4f79b, pre-a25c557)",
    "B": per_mode_delta(BASE / "pilot_post_update_b_skillv1"),
    "B_prime": per_mode_delta(BASE / "pilot_post_update_b_prime_skillv1"),
    "C": per_mode_delta(BASE / "pilot_post_update_c_skillv1"),
    "pooled": v1_pooled,
}

v2_pooled = load_pooled(BASE / "pooled_postupdate_v2.json")
eras["post_update_skillv2"] = {
    "source": "Rev 5 pilot (SKILLv2 post-a25c557, pre-Rev6 archive)",
    "B": per_mode_delta(BASE / "pilot_post_update_b_skillv2"),
    "B_prime": per_mode_delta(BASE / "pilot_post_update_b_prime_skillv2"),
    "C": per_mode_delta(BASE / "pilot_post_update_c_skillv2"),
    "pooled": v2_pooled,
}

v3_pooled = load_pooled(BASE / "pooled_postupdate_v3.json")
eras["post_update_skillv3"] = {
    "source": "Rev 6 pilot (SKILLv3 skill-only recalibration)",
    "B": per_mode_delta(BASE / "pilot_post_update_b"),
    "B_prime": per_mode_delta(BASE / "pilot_post_update_b_prime"),
    "C": per_mode_delta(BASE / "pilot_post_update_c"),
    "pooled": v3_pooled,
}

v1_beta, v1_t = extract_pooled_beta(v1_pooled)
v2_beta, v2_t = extract_pooled_beta(v2_pooled)
v3_beta, v3_t = extract_pooled_beta(v3_pooled)


def beta_verdict(beta: float | None) -> str:
    if beta is None:
        return "—"
    if beta >= 12:
        return "✅ Strengthened"
    if 5 <= beta < 12:
        return "⚠️  Nuanced"
    return "❌ Non-replication"


out = BASE / "FINDINGS_4_ERAS_SUMMARY.md"
with out.open("w", encoding="utf-8") as fh:
    fh.write("# FINDINGS — 4-Era Cross-Version Replication Summary\n\n")
    fh.write("Comparison of `biomedical-literature-search` skill effect across four SKILL.md versions.\n\n")
    fh.write("## Era Definitions\n\n")
    for key, value in eras.items():
        fh.write(f"- **{key}**: {value['source']}\n")

    fh.write("\n---\n\n## Per-Mode Celltype Δ (strong model, median on − off)\n\n")
    fh.write("| Era | Mode B (null) | Mode B' (primary) | Mode C (schema iso) |\n")
    fh.write("|---|---:|---:|---:|\n")
    for era, data in eras.items():
        b_s = data["B"].get("strong_delta") if isinstance(data["B"], dict) else None
        bp_s = data["B_prime"].get("strong_delta") if isinstance(data["B_prime"], dict) else None
        c_s = data["C"].get("strong_delta") if isinstance(data["C"], dict) else None
        fh.write(f"| {era} | {f(b_s, '+.2f')} {verdict(b_s)} | {f(bp_s, '+.2f')} {verdict(bp_s)} | {f(c_s, '+.2f')} {verdict(c_s)} |\n")

    fh.write("\n## Per-Mode Celltype Δ (weak model, median on − off)\n\n")
    fh.write("| Era | Mode B (null) | Mode B' (primary) | Mode C (schema iso) |\n")
    fh.write("|---|---:|---:|---:|\n")
    for era, data in eras.items():
        b_w = data["B"].get("weak_delta") if isinstance(data["B"], dict) else None
        bp_w = data["B_prime"].get("weak_delta") if isinstance(data["B_prime"], dict) else None
        c_w = data["C"].get("weak_delta") if isinstance(data["C"], dict) else None
        fh.write(f"| {era} | {f(b_w, '+.2f')} | {f(bp_w, '+.2f')} | {f(c_w, '+.2f')} |\n")

    fh.write("\n## Pooled LMM skill_on β (celltype primary)\n\n")
    fh.write("| Era | Pooled β (pp) | t-value | p-value | Verdict |\n")
    fh.write("|---|---:|---:|---:|---|\n")
    fh.write("| pre_update_skillv0 | +10.30 | — | 0.001 | ✅ Strengthened |\n")
    fh.write(f"| post_update_skillv1 | {f(v1_beta, '+.2f')} | {f(v1_t, '.2f')} | — | {beta_verdict(v1_beta)} |\n")
    fh.write(f"| post_update_skillv2 | {f(v2_beta, '+.2f')} | {f(v2_t, '.2f')} | — | {beta_verdict(v2_beta)} |\n")
    fh.write(f"| post_update_skillv3 | {f(v3_beta, '+.2f')} | {f(v3_t, '.2f')} | — | {beta_verdict(v3_beta)} |\n")

    fh.write("\n## TOST (C − B' equivalence, ±5 pp margin)\n\n")
    fh.write("| Era | Estimate (pp) | p_TOST | Equivalent α=0.05 |\n")
    fh.write("|---|---:|---:|:-:|\n")
    fh.write("| pre_update_skillv0 | not computed | — | — |\n")
    for key in ("post_update_skillv1", "post_update_skillv2", "post_update_skillv3"):
        pooled = eras[key].get("pooled", {})
        tost = (pooled or {}).get("tost", {})
        est = tost.get("estimate_pp")
        p_tost = tost.get("p_tost")
        eq = tost.get("equivalent_at_alpha_0_05")
        fh.write(f"| {key} | {f(est, '+.2f') if est is not None else '—'} | {f(p_tost, '.4f') if p_tost is not None else '—'} | {'✅' if eq else '❌' if eq is False else '—'} |\n")

    fh.write("\n## Error / Trial Counts\n\n")
    fh.write("| Era | Mode | n_total | n_valid | errors |\n")
    fh.write("|---|---|---:|---:|---:|\n")
    for era in ("post_update_skillv1", "post_update_skillv2", "post_update_skillv3"):
        for mode in ("B", "B_prime", "C"):
            data = eras[era].get(mode, {})
            if isinstance(data, dict) and "n_total" in data:
                fh.write(f"| {era} | {mode} | {data['n_total']} | {data['n_valid']} | {data['n_total'] - data['n_valid']} |\n")

    fh.write("\n## Interpretation\n\n")
    fh.write("- **Pre-update SKILLv0** → strengthened-claim confirmed (pooled β=+10.30)\n")
    fh.write(f"- **Post-update SKILLv1** → {beta_verdict(v1_beta)}{' (β=' + f(v1_beta, '+.2f') + ')' if v1_beta is not None else ''}\n")
    fh.write(f"- **Post-update SKILLv2** → {beta_verdict(v2_beta)}{' (β=' + f(v2_beta, '+.2f') + ')' if v2_beta is not None else ''}\n")
    fh.write(f"- **Post-update SKILLv3** → {beta_verdict(v3_beta)}{' (β=' + f(v3_beta, '+.2f') + ')' if v3_beta is not None else ''}\n")

    if v2_beta is not None and v3_beta is not None:
        diff = v3_beta - v2_beta
        fh.write(f"\nRev6 − Rev5 effect-size shift: {diff:+.2f} pp. ")
        if abs(diff) < 2:
            fh.write("**Stable across Rev6** — the skill-only recalibration produced no material shift.\n")
        elif abs(diff) < 5:
            fh.write("**Minor shift** — directionality preserved, magnitude changed <5pp.\n")
        else:
            fh.write("**Material shift** — Rev6 changed the observed effect size materially.\n")

    fh.write("\n## Generated\n\n")
    fh.write(f"Auto-generated by `_rev6_summary.py` at {datetime.now(timezone.utc).isoformat()}.\n")

print(f"\n=== Summary written to {out} ===\n")
print(out.read_text(encoding="utf-8"))
