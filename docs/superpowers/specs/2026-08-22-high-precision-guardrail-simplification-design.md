# High-Precision Guardrail Simplification Design

## Problem

The guardrail now combines objective validation, broad natural-language
interpretation, RAG judgment, specialized semantic repair, frontier tracking,
and structural repair. This improved fail-closed safety but made valid stochastic
wording capable of blocking the full experiment.

The latest no-SNI run stopped on four false positives:

- three Factor3 pathway-direction issues where positive cluster/analysis wording
  coexisted with correct negative pathway wording;
- one Part3 sentence explicitly reserving therapeutic synthesis for Part4.

Historical replay passing was insufficient because it covered known strings,
not semantic-equivalent wording variants.

## Goal

Reduce the guardrail to a high-precision hard gate for objective or explicit
errors, keep uncertain natural-language judgments as auditable warnings, and
delete repair paths that exist only to satisfy low-precision semantic rules.

## Hard Errors

- required artifact missing or malformed;
- synthesis is HTML or lacks an H1 title;
- `papers.json` missing/malformed;
- cited PMID absent from `papers.json`;
- exact LR metric differs from the source CSV;
- factor/pathway wording has one unambiguous polarity that contradicts the
  numeric estimate sign;
- Part3 contains an actual therapeutic recommendation, ranking, drug choice, or
  clinical prioritization;
- an explicit inline PMID citation is unsupported or contradicts its evidence;
- deterministic consistency mismatch with a canonical source.

## Soft Audit Warnings

- uncited `claim_rag_unsupported`, `claim_rag_overclaimed`, or unverifiable
  general claims;
- report-derived mechanistic or therapeutic interpretation without an explicit
  contradictory inline citation;
- factor/pathway windows containing both positive and negative polarity;
- general synthesis overclaim or overclaiming heading;
- evidence gaps that can be read as hypotheses.

Warnings remain in validation JSON and comparison metrics. They do not carry
`target_text`, do not enter automatic repair, and do not block rendering or the
no-SNI/SNI boundary.

## Direction Rule

For each supported factor/pathway pair:

- a claim with exactly one pathway and positive-only wording + negative estimate:
  hard mismatch;
- a claim with exactly one pathway and negative-only wording + positive estimate:
  hard mismatch;
- positive and negative present: `factor_pathway_direction_ambiguous` warning;
- multiple pathway mentions with an apparent mismatch:
  `factor_pathway_direction_ambiguous` warning;
- neither present: no direction issue.

This keeps true injected contradictions hard while preventing cluster
enrichment or analysis-name wording from contaminating a pathway direction.

## Part3 Boundary Rule

Therapeutic vocabulary is not spillover when the same claim is meta-language
that assigns the content to Part4, using a Part4 reference plus a boundary verb
such as reserve, defer, belong, own, exclude, or avoid. Actual recommendations
remain hard errors.

## Simplified Repair Surface

Retain:

- exact target splicing;
- structured replace/delete for hard issues;
- byte-exact atomic rollback;
- deterministic-first ordering;
- H1 structural promotion;
- explicit inline citation repair;
- deterministic metric/PMID/consistency repair.

Delete or stop routing:

- general uncited Claim-RAG semantic repair;
- general synthesis overclaim repair;
- trusted semantic-heading repair;
- automatic hypothesis caveat appending;
- equal-count semantic frontier acceptance.

Same-phase progress returns to strict hard-error decrease. A
deterministic-to-semantic phase transition remains valid; semantic-to-
deterministic remains a rollback.

## Validation Strategy

1. Exact current four false-positive claims become warnings/no-issues with zero
   document changes.
2. Injected opposite-sign claims remain hard errors.
3. Explicit Part3 therapeutic recommendation remains hard while Part4 boundary
   meta-language passes.
4. Explicit inline citation contradiction remains hard and repairable.
5. Historical corpus remains final hard-error zero and idempotent.
6. One fresh Part2/Part3 smoke yields zero false-positive hard errors.
7. Only then run one fresh no-SNI → SNI pair.

## Non-Goals

- No LLM-based validator classifier.
- No new NLP/Markdown dependency.
- No phrase-specific report rewrite.
- No weakening of objective numeric, citation, structure, or explicit boundary
  violations.
- No parallel pair execution or collection mutation.

## Acceptance

- current failed no-SNI artifact: hard errors 0, repairs 0, byte-identical Parts;
- metamorphic paraphrase set: false-positive hard errors 0;
- injected contradiction set: all expected hard errors retained;
- soft issues present in audit with severity warning and no repair target;
- historical replay and fresh Part smoke pass;
- final no-SNI and SNI manifests pass under one reviewed HEAD.
