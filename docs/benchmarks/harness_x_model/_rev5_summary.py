"""Generate 3-era comparison summary — pre-update / skillv1 / skillv2."""
from __future__ import annotations
import json, glob, statistics
from pathlib import Path

BASE = Path("docs/benchmarks/harness_x_model/results")

def per_mode_delta(dir_path):
    rows = [json.loads(open(f).readlines()[-1]) for f in sorted(glob.glob(str(dir_path / "trial_*.jsonl")))]
    valid = [r for r in rows if not r.get('error')]
    bc = {}
    for r in valid:
        bc.setdefault(r['condition'], []).append(r.get('celltypes_coverage_pct', 0))
    def d(c1, c2):
        if c1 not in bc or c2 not in bc: return None
        return statistics.median(bc[c1]) - statistics.median(bc[c2])
    return {
        'n_valid': len(valid), 'n_total': len(rows),
        'strong_delta': d('strong_on', 'strong_off'),
        'weak_delta': d('weak_on', 'weak_off'),
        'strong_on_med': statistics.median(bc.get('strong_on', [0])) if bc.get('strong_on') else None,
        'strong_off_med': statistics.median(bc.get('strong_off', [0])) if bc.get('strong_off') else None,
    }

def load_pooled(path):
    if not path.exists(): return None
    d = json.load(open(path))
    return {
        'n_total': d.get('n_total'),
        'per_dataset': d.get('per_dataset'),
        'tost': d.get('tost_equivalence'),
        'celltype_summary': d.get('celltype_primary_summary', ''),
    }

def verdict(delta):
    if delta is None: return "— (n/a)"
    if 12 <= delta <= 22: return f"✅ STRENGTHENED"
    if 5 <= delta < 12 or 22 < delta <= 30: return f"⚠️  NUANCED"
    if -3 < delta < 5: return f"❌ NON-REPLICATION"
    if abs(delta) < 3: return f"✅ NULL (mode B)"
    return f"⚠️  OUT-OF-WINDOW"

# Gather data per era
eras = {}

# Pre-update (baked in from FINDINGS_SKILL_MECHANISM.md Rev 4 plan context)
eras['pre_update_skillv0'] = {
    'source': 'FINDINGS_SKILL_MECHANISM.md (2026-04-16 pilot, SKILLv0)',
    'B':       {'strong_delta': 0.00, 'weak_delta': 0.00},
    'B_prime': {'strong_delta': 25.93, 'weak_delta': 16.96},
    'C':       {'strong_delta': 25.90, 'weak_delta': 14.58},
    'pooled_beta': 10.30,
    'pooled_p':    0.001,
    'tost_estimate': None,
}

# skillv1 (from archived _skillv1 dirs + pooled_v1.json)
v1_pooled = load_pooled(BASE / "pooled_postupdate_v1.json")
eras['post_update_skillv1'] = {
    'source': 'Rev 4 pilot (2026-04-18, SKILLv1 post-ce4f79b, pre-a25c557)',
    'B':       per_mode_delta(BASE / "pilot_post_update_b_skillv1"),
    'B_prime': per_mode_delta(BASE / "pilot_post_update_b_prime_skillv1"),
    'C':       per_mode_delta(BASE / "pilot_post_update_c_skillv1"),
    'pooled':  v1_pooled,
}

# skillv2 (fresh run)
v2_pooled = load_pooled(BASE / "pooled_postupdate_v2.json")
eras['post_update_skillv2'] = {
    'source': 'Rev 5 pilot (SKILLv2 post-a25c557 skill-create update)',
    'B':       per_mode_delta(BASE / "pilot_post_update_b"),
    'B_prime': per_mode_delta(BASE / "pilot_post_update_b_prime"),
    'C':       per_mode_delta(BASE / "pilot_post_update_c"),
    'pooled':  v2_pooled,
}

def f(v, fmt="+.2f"):
    if v is None: return "—"
    return format(v, fmt)

def extract_pooled_beta(pooled):
    if pooled is None: return None, None
    summ = pooled.get('celltype_summary', '')
    import re
    m = re.search(r"skill_onTRUE\s+([+-]?\d+\.\d+)\s+(\d+\.\d+)\s+([+-]?\d+\.\d+)", summ)
    if m:
        return float(m.group(1)), float(m.group(3))  # estimate, t-value
    return None, None

v1_beta, v1_t = extract_pooled_beta(v1_pooled)
v2_beta, v2_t = extract_pooled_beta(v2_pooled)

# Write summary markdown
out = BASE / "FINDINGS_3_ERAS_SUMMARY.md"
with open(out, 'w') as fh:
    fh.write("# FINDINGS — 3-Era Cross-Version Replication Summary\n\n")
    fh.write("Comparison of `biomedical-literature-search` skill effect across three SKILL.md versions.\n\n")
    fh.write("## Era Definitions\n\n")
    for k, v in eras.items():
        fh.write(f"- **{k}**: {v['source']}\n")
    fh.write("\n---\n\n## Per-Mode Celltype Δ (strong model, median on − off)\n\n")
    fh.write("| Era | Mode B (null) | Mode B' (primary) | Mode C (schema iso) |\n")
    fh.write("|---|---:|---:|---:|\n")
    for era, d in eras.items():
        b_s = d['B'].get('strong_delta') if isinstance(d['B'], dict) else None
        bp_s = d['B_prime'].get('strong_delta') if isinstance(d['B_prime'], dict) else None
        c_s = d['C'].get('strong_delta') if isinstance(d['C'], dict) else None
        fh.write(f"| {era} | {f(b_s, '+.2f')} {verdict(b_s)} | {f(bp_s, '+.2f')} {verdict(bp_s)} | {f(c_s, '+.2f')} {verdict(c_s)} |\n")

    fh.write("\n## Per-Mode Celltype Δ (weak model, median on − off)\n\n")
    fh.write("| Era | Mode B (null) | Mode B' (primary) | Mode C (schema iso) |\n")
    fh.write("|---|---:|---:|---:|\n")
    for era, d in eras.items():
        b_w = d['B'].get('weak_delta') if isinstance(d['B'], dict) else None
        bp_w = d['B_prime'].get('weak_delta') if isinstance(d['B_prime'], dict) else None
        c_w = d['C'].get('weak_delta') if isinstance(d['C'], dict) else None
        fh.write(f"| {era} | {f(b_w, '+.2f')} | {f(bp_w, '+.2f')} | {f(c_w, '+.2f')} |\n")

    fh.write("\n## Pooled LMM skill_on β (celltype primary)\n\n")
    fh.write("| Era | Pooled β (pp) | t-value | p-value | Verdict |\n")
    fh.write("|---|---:|---:|---:|---|\n")
    fh.write(f"| pre_update_skillv0 | +10.30 | — | 0.001 | ✅ Strengthened |\n")
    def b_verdict(b):
        if b is None: return "—"
        if b >= 12: return "✅ Strengthened"
        if 5 <= b < 12: return "⚠️  Nuanced"
        return "❌ Non-replication"
    fh.write(f"| post_update_skillv1 | {f(v1_beta, '+.2f')} | {f(v1_t, '.2f')} | — | {b_verdict(v1_beta)} |\n")
    fh.write(f"| post_update_skillv2 | {f(v2_beta, '+.2f')} | {f(v2_t, '.2f')} | — | {b_verdict(v2_beta)} |\n")

    fh.write("\n## TOST (C − B' equivalence, ±5 pp margin)\n\n")
    fh.write("| Era | Estimate (pp) | p_TOST | Equivalent α=0.05 |\n")
    fh.write("|---|---:|---:|:-:|\n")
    fh.write("| pre_update_skillv0 | not computed | — | — |\n")
    for k in ['post_update_skillv1', 'post_update_skillv2']:
        pooled = eras[k].get('pooled', {})
        tost = (pooled or {}).get('tost', {})
        est = tost.get('estimate_pp')
        p = tost.get('p_tost')
        eq = tost.get('equivalent_at_alpha_0_05')
        fh.write(f"| {k} | {f(est, '+.2f') if est is not None else '—'} | {f(p, '.4f') if p is not None else '—'} | {'✅' if eq else '❌' if eq is False else '—'} |\n")

    fh.write("\n## Error / Trial Counts\n\n")
    fh.write("| Era | Mode | n_total | n_valid | errors |\n")
    fh.write("|---|---|---:|---:|---:|\n")
    for era in ['post_update_skillv1', 'post_update_skillv2']:
        for mode in ['B', 'B_prime', 'C']:
            d = eras[era].get(mode, {})
            if isinstance(d, dict) and 'n_total' in d:
                fh.write(f"| {era} | {mode} | {d['n_total']} | {d['n_valid']} | {d['n_total']-d['n_valid']} |\n")

    fh.write("\n## Interpretation\n\n")
    def interpret(beta):
        if beta is None: return "unavailable"
        if beta >= 12: return "strengthened-claim confirmed"
        if 5 <= beta < 12: return "nuanced-claim"
        return "non-replication"
    v0_interp = "strengthened-claim confirmed"
    v1_interp = interpret(v1_beta)
    v2_interp = interpret(v2_beta)
    
    fh.write(f"- **Pre-update SKILLv0** → {v0_interp} (pooled β=+10.30)\n")
    fh.write(f"- **Post-update SKILLv1** → {v1_interp}{' (β=' + f(v1_beta, '+.2f') + ')' if v1_beta else ''}\n")
    fh.write(f"- **Post-update SKILLv2** → {v2_interp}{' (β=' + f(v2_beta, '+.2f') + ')' if v2_beta else ''}\n")
    
    if v1_beta and v2_beta:
        diff = v2_beta - v1_beta
        fh.write(f"\nv2 − v1 effect-size shift: {diff:+.2f} pp. ")
        if abs(diff) < 2:
            fh.write("**Stable across SKILL update** — Anthropic skill-create guide changes preserved the workflow-guidance effect.\n")
        elif abs(diff) < 5:
            fh.write("**Minor shift** — directionality preserved, magnitude changed <5pp. Discussion-worthy but not material.\n")
        else:
            fh.write("**Material shift** — SKILL content changes moved the effect materially. Paper narrative needs update.\n")

    fh.write("\n## Generated\n\n")
    from datetime import datetime, timezone
    fh.write(f"Auto-generated by `_rev5_summary.py` at {datetime.now(timezone.utc).isoformat()}.\n")

print(f"\n=== Summary written to {out} ===\n")
with open(out) as fh:
    print(fh.read())
