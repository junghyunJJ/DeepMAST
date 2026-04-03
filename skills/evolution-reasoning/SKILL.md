---
name: evolution-reasoning
description: Iteratively improve any scored items (hypotheses, analyses, answers) through evolutionary critique-and-refine cycles. Domain-agnostic — the calling context provides scoring dimensions, weights, and threshold. Use when initial generation produces items below quality threshold. For initial hypothesis generation use drug-target-hypothesis; for general brainstorming use hypothesis-generation.
metadata:
    skill-author: Junghyun Jung
---

# Evolution Reasoning

## Overview

A domain-agnostic evolutionary refinement protocol that improves any collection of scored items through iterative cycles of critique, selection, and mutation. Inspired by evolutionary algorithms: generate diverse candidates, evaluate rigorously, keep the best, improve the rest, repeat.

This skill does NOT generate initial items or define scoring dimensions. The calling context provides both. This skill takes over when items exist but their quality is below threshold.

## When to Use This Skill

Use this skill when:
- You have 2+ scored items (hypotheses, answers, analyses, designs) with per-dimension scores
- The best item's composite score is below your quality threshold
- You want structured, iterative improvement rather than starting over from scratch
- You need to preserve what works while fixing specific weaknesses identified by critique

Do NOT use for:
- Initial generation of items from scratch (use domain-specific generation skills instead)
- Items without clear scoring dimensions (define dimensions first, then use this skill)
- Single-item refinement (this skill needs a population of 2+ for selection pressure)
- Tasks where a single revision pass is sufficient (this skill adds multi-generation overhead)

## Prerequisites

The calling context must provide:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `items` | list | YES | — | Items to improve. Each: `{id, content, scores: {dim: 0-1}, critique: [str]}` |
| `dimensions` | dict | YES | — | Scoring dimensions with weights. Example: `{accuracy: 0.4, clarity: 0.3, depth: 0.3}`. Weights must sum to ~1.0 |
| `threshold` | float | NO | 0.7 | Composite score target. Evolution stops when best item meets this. |
| `generation_limit` | int | NO | 3 | Maximum improvement cycles before stopping. |
| `survivor_count` | int | NO | 2 | How many top items survive each selection round. |

If scores are not yet available for items, run the Critique & Score phase (Phase 2) first to establish baseline scores before entering the evolution loop.

---

## Workflow

### Phase 1: Initialize

1. **Validate prerequisites**: Confirm items, dimensions, and weights are provided. At least 2 items required.

2. **Compute baseline fitness** for each item:
   ```
   fitness = sum(score[dim] * weight[dim] for dim in dimensions)
   ```

3. **Check early exit**: If the best item already meets the threshold, skip evolution and return immediately.

4. **Record generation 0 state**: Store item IDs, fitness scores, and the best candidate for the evolution trace.

### Phase 2: Critique & Score

For each item in the current population, adopt the **Strict Evaluator** persona:

> **Persona: Strict Evaluator**
> You are a rigorous, skeptical evaluator. Your job is to find flaws, not to praise. Score each dimension independently from 0.0 to 1.0.
>
> Scoring calibration:
> - **0.9-1.0**: Genuinely excellent. Specific evidence supports this rating.
> - **0.7-0.89**: Good with minor issues. Clearly above average.
> - **0.5-0.69**: Acceptable but with notable weaknesses.
> - **Below 0.5**: Significant problems that must be addressed.
>
> A score of 0.9+ requires explicit justification. Default to conservative scoring.

For each item, produce:
- **Per-dimension scores**: 0.0-1.0 for each dimension
- **Critique points**: 1-3 specific, actionable weaknesses. Each must name what is wrong and suggest how to fix it.
- **Composite score**: Weighted sum across dimensions

See `references/scoring_guide.md` for detailed calibration guidance and common pitfalls.

### Phase 3: Select & Mutate

**Selection**: Sort items by composite score descending. Keep the top N (default 2) as survivors. Record which items were eliminated and why.

**Mutation**: For each survivor whose composite score is below the threshold, adopt the **Refinement** persona:

> **Persona: Targeted Refiner**
> You are improving an existing item based on specific critique points. Address each critique directly. Preserve what already works — do NOT start over. Make targeted improvements that raise the weakest dimension scores.
>
> For each critique point:
> 1. Identify the specific weakness
> 2. Apply a focused fix
> 3. Verify the fix doesn't degrade other dimensions

Produce a refined version of each item. Assign it a new ID (e.g., `{original_id}-gen-{N}`).

**Re-score**: Score the refined items using the same Strict Evaluator persona from Phase 2. Add them to the population alongside survivors.

### Phase 4: Termination Check

Evaluate termination conditions:

1. **Threshold met**: Best composite score >= threshold → **STOP. Return best item.**
2. **Generation limit reached**: Current generation >= generation_limit → **STOP. Return best available.**
3. **No improvement**: Best score did not improve from previous generation → **STOP. Stagnation detected.**
4. **Otherwise**: Increment generation counter → **Return to Phase 2.**

### Output

Return to the calling context:

1. **Best item**: The highest-scoring item with its content and scores
2. **Refined population**: All surviving items from the final generation
3. **Evolution trace**: Per-generation summary showing:
   - Generation number
   - Best fitness
   - Average fitness
   - Which items were selected, mutated, or eliminated
4. **Termination reason**: Which condition triggered the stop (threshold_met / generation_limit / stagnation)

---

## Self-Critique Mitigation

This skill uses same-model self-critique, which has known limitations. The following mitigations are built into the protocol:

1. **Persona separation**: The Strict Evaluator persona (Phase 2) uses fundamentally different instructions from the Targeted Refiner persona (Phase 3). This creates cognitive separation even within the same model.

2. **Structured dimension scoring**: Scoring on specific dimensions (e.g., "rate evidence coverage 0-1") produces more reliable evaluations than holistic judgments ("is this good?").

3. **Conservative calibration**: The scoring guide explicitly anchors 0.9+ as exceptional and requires justification. This combats score inflation.

4. **Selection pressure**: Even with noisy self-evaluation, relative ranking (A better than B) is more reliable than absolute scoring. The evolutionary selection mechanism exploits this.

5. **Critique-driven mutation**: Mutations must address specific critique points, not just rephrase. This forces directional improvement.

**Known limitation**: Same-model critique cannot identify unknown unknowns — flaws the model consistently overlooks. For higher-stakes applications, consider using different models for generation vs. critique.

---

## Quality Standards

- Every critique point must be specific and actionable (not "needs improvement" but "the evidence for X is missing; add Y")
- Scores must be calibrated per `references/scoring_guide.md`
- Mutations must demonstrably address at least one critique point
- Evolution trace must show monotonic or improving best fitness (if best fitness decreases, something is wrong)
- The skill must terminate within generation_limit cycles (no infinite loops)

---

## Integration Examples

### With drug-target-hypothesis

```
After Phase 4 UCB Scoring, if best composite < 0.7:
  read_skill_file(skill_path="skills/evolution-reasoning")
  Pass hypotheses as items with UCB dimensions:
    dimensions: {Evidence_Coverage: 0.30, Specificity: 0.30, Novelty: 0.20, Actionability: 0.20}
    threshold: 0.7
    generation_limit: 2
```

### With any analysis or report skill

```
After generating initial analysis sections:
  Score each section on {accuracy: 0.4, completeness: 0.3, clarity: 0.3}
  If best < 0.75:
    read_skill_file(skill_path="skills/evolution-reasoning")
    Pass sections as items with those dimensions
```

---

## Resources

### references/

- `scoring_guide.md` — Detailed calibration guide for 0-1 scoring, common pitfalls, domain-specific examples, and critique writing standards

### Related Skills

- `drug-target-hypothesis` — Drug target hypothesis generation with UCB scoring. Uses evolution-reasoning for iterative refinement when hypothesis quality is below threshold.
- `hypothesis-generation` — General scientific hypothesis generation with LaTeX PDF output and 8-step manual workflow.
- `hypogenic` — Automated LLM-driven hypothesis generation and testing on tabular datasets.
