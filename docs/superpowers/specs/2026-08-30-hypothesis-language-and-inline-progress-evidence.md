# Hypothesis Language and Inline Progress Diagnostic Evidence

This file preserves the compact outputs used by the superseding design review.
It does not replace the original run artifacts or the immutable `/tmp`
diagnostic copies. All checks used production code at HEAD `3dcd928` and wrote
only to fresh temporary copies.

## Preflight

- Worktree: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/fix/post-repair-integrity`
- Branch: `fix/post-repair-integrity`
- HEAD: `3dcd928085424d691a93f08d1ff70e9840afb4f8`
- Initial tracked status: clean
- Stopped tmux session absent; no `run_sequence` or Deep Interpreter process
- Health: ports 6000 and 4000 listed `qwen3.5:122b`; port 8883 returned `{"status":"ok"}`
- Fixed collection: `a208e916-bd32-405a-9eee-de4cd82b2a3b`

## Pair-15-R2 no-SNI

Original root:
`res/deep_interpreter/bc/sni_repair_ablation/post_bounded_inline_frontier_pair15r2_pair20_sequential_20260829T204054Z/pairs/pair-15-R2/wiki-off`

Original `parts_guardrail_result.json`:

```json
{
  "status": "failed",
  "initial_error_count": 1,
  "repair_attempt_count": 3,
  "changed_sections": 0,
  "final_error_count": 1
}
```

Sole hard issue:

```json
{
  "code": "unsupported_pathway_factor_significance",
  "file": "part2_final.md",
  "section": "## Analysis 2-8: Pathway-Factor Enrichment",
  "value": "Factor3: Hypoxia",
  "target_text": "- **Connection to Analysis 2-7 (NMF Factor)**: The pathway enrichments provide annotation-based hypotheses for Factor3's biological program, suggesting potential associations with estrogen-independent, hypoxia-resistant states and restrained EGFR signaling."
}
```

Fresh in-memory regex and full-validator diagnosis:

```json
{
  "annotation-based hypotheses present": true,
  "potential associations present": true,
  "current_regex_match": false,
  "candidate_regex_match": true,
  "current_hard_count": 1,
  "current_exact_error_present": true,
  "candidate_hard_count": 0,
  "candidate_exact_error_present": false,
  "explicit_significance_hard": {
    "code": "unsupported_pathway_factor_significance",
    "value": "Factor2: EGFR",
    "target_text": "Factor2 showed significant enrichment for NFkB and EGFR."
  },
  "original_hashes_unchanged": true
}
```

Original hashes after diagnosis:

- `part2_final.md`: `811cddb1b5edb16ef884bec828606c3631896fd2831e2bfc7f5e4cee4e895888`
- `report_validation_final.json`: `b77993512322297b178e076e1a09b7872bd57776335d2c802119754bcd6cbdad`
- `parts_guardrail_result.json`: `24bf3b78da4a0fed0587021fff8937dd0f8faa9d6e7f86aa514dda180e6a704f`

## Pair-16 SNI

Original root:
`res/deep_interpreter/bc/sni_repair_ablation/post_bounded_inline_frontier_pair15r2_pair20_sequential_20260829T204054Z/pairs/pair-16/wiki-on`

Preserved diagnostic inputs:

- `/tmp/deepmast-p16-candidate-diag.5QKhhY/candidate_diagnosis.json`
  (`sha256 be70280a70a114ec6f97d803fe32763f6a5a28628e09dae221c7d1e66fe7f930`)
- `/tmp/deepmast-p16-candidate-diag.5QKhhY/synthesis.md`
  (`sha256 9755a03091a218da30b31297b1b9fa2603dd863f08935024c2672e41561983b4`)
- `/tmp/deepmast-p16-after-first-repair.p0lxYH/second_guardrail_result.json`
  (`sha256 777e1c5ce7f8f84aa2d7d6b520b0aff2b1b3894cc705043cfcce171dc568cc74`)

Fresh current-code repair reproduction:

```json
{
  "changed": 1,
  "repaired_synthesis_matches_captured_candidate": true,
  "before": {
    "phase": "semantic",
    "hard_count": 1,
    "code": "inline_citation_overclaimed",
    "key": [
      "synthesis.md",
      "## References",
      "PMID: 18922900 - LRIG1 suppression in ErbB2+ tumors creates feed-forward loop contributing to overexpression"
    ]
  },
  "after": {
    "phase": "semantic",
    "hard_count": 1,
    "code": "inline_citation_overclaimed",
    "key": [
      "synthesis.md",
      "## Cross-Part Themes",
      "Literature support (PMID: 28174229, 26148232, 39753722) confirms ErbB2 overexpression alters cellular phenotype, LRIG1 negatively regulates ErbB3, and NRG1-ERBB3 signaling drives CTC survival."
    ]
  },
  "keys_non_empty": true,
  "keys_disjoint": true,
  "all_codes_repairable": true,
  "current_strict_phase_progress": false,
  "source_synthesis_unchanged": true
}
```

Fresh fixed-collection continuation from the preserved first repair:

```json
{
  "status": "passed",
  "initial_error_count": 1,
  "repair_attempt_count": 1,
  "terminal_repair_count": 0,
  "changed_claims": 1,
  "final_error_count": 0,
  "checkpoint_hits": 4,
  "retrieval_cache_hits": 4,
  "judgment_batch_count": 1,
  "single_claim_fallback_count": 0,
  "judge_deadline_exhaustion_count": 0,
  "part_hashes_unchanged": true
}
```

Part hashes:

- Part 1: `3f69d9fbe629e4a6a4613820efd1139f7ef2faa4f1f370b45f82615f4576dc29`
- Part 2: `8ec467ad44e209f1969c0ea4391cd3f47623619b5b0b2efc82859e8e46bfc6dd`
- Part 3: `c70ee3bee969d1c51feea39ced56a372c39c610c2787d1fb6510005fa1544d05`

## Pair-17 no-SNI

Original root:
`res/deep_interpreter/bc/sni_repair_ablation/post_bounded_inline_frontier_pair15r2_pair20_sequential_20260829T204054Z/pairs/pair-17/wiki-off`

Preserved diagnostic result:
`/tmp/deepmast-p17-guardrail-diag.6KB9Ll/diagnostic_guardrail_result.json`
(`sha256 40f1af4bf8ea0562129eb0726083dbb9b685bed307c9efff0ac59a7a1d244f40`).

Fresh current-code replay from original final Parts with fixed collection:

```json
{
  "status": "passed",
  "initial_error_count": 2,
  "repair_attempt_count": 1,
  "terminal_repair_count": 0,
  "changed_sections": 2,
  "final_error_count": 0,
  "checkpoint_hits": 41,
  "retrieval_cache_hits": 44,
  "judgment_batch_count": 3,
  "single_claim_fallback_count": 1,
  "judge_deadline_exhaustion_count": 0,
  "source_hashes_unchanged": true,
  "copy_changed_files": ["part2_final.md"]
}
```

Original Part hashes after replay:

- Part 1: `1c41bd8c121a7e6ba2ac07a76feb6ea49dbf30ce1b376e9b169afe19f20a6d8f`
- Part 2: `e430620cff1a49b4ada24e7e2eb82393c72752ff02653d02a35a1050a904cd8f`
- Part 3: `08da49b8d61da2551ebce15c1cc08d971f7bcf42f8a86aed425a3ac3d4abe09a`

## Post-Fix Replay A Integrity Finding

Durable replay root:
`res/deep_interpreter/bc/sni_repair_ablation/post_repair_integrity_isolated_replays_20260830T080523Z/pair-15-R2/wiki-off`

Reviewed implementation HEAD: `5b4cc8a846b4487771797fa9ce036ae8c13e9fd9`.

Deterministic post-fix validation:

```json
{
  "issue_count": 11,
  "hard_error_count": 0,
  "Factor3: Hypoxia": "absent"
}
```

Full production Part guardrail:

```json
{
  "status": "passed",
  "deterministic_initial_error_count": 0,
  "semantic_initial_error_count": 19,
  "repair_attempt_count": 2,
  "changed_sections": 20,
  "final_error_count": 0,
  "headings_unchanged": true,
  "original_hashes_unchanged": true
}
```

The semantic hard errors are legitimate unsupported/overclaimed inline
citations. Most final diffs remove only the flagged PMID. The shared token
stripper produces malformed prose for three claims whose PMID is the
grammatical subject: two distinct PMID 28174229 claims (CDH1-ERBB3 and
LRIG1-ERBB2) and one PMID 39753722 claim.

```text
PMID: 28174229 demonstrates ...  ->   demonstrates ...  (two claims)
PMID: 39753722 reports ...       ->   reports ...
```

The replay summary is
`post_fix_part_replay.json`; the final artifact fragments appear in
the live replay-root `part3_final.md`. The copied `after/part3_final.md` and
`diffs/part3_final.md.diff` are older snapshots and do not represent that final
mutated file. Independent critic verdict: `BLOCK FULL SEQUENCE` until a
prose-prefix guard routes all three targets to structured exact-target repair
and Replay A is clean.

## Baseline Regression

At HEAD `3dcd928` before new production edits:

```text
pytest -q tests/scripts/test_validate_report.py tests/scripts/test_repair_report.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py
158 passed, 1 pre-existing LangGraph deprecation warning
```
