# Smaller vs Larger Model Activation Interpretation

Date: 2026-06-12

## Purpose

This note summarizes how to interpret the selective8 benchmark result where
`qwen3.5:35b` followed the skill activation protocol more reliably than
`qwen3.5:122b`.

The main question is not whether 35B is generally smarter than 122B. The better
question is:

> Can a smaller or weaker model outperform a larger or stronger model on a
> protocol-compliance benchmark?

The answer from the local benchmark and external literature is yes.

## Local Benchmark Observation

Source result directory:

```text
docs/benchmarks/hypothesis_generation_consistency/results/selective8_governor_production_20260611_142352
```

The benchmark used:

- Models: `qwen3.5:35b`, `qwen3.5:122b`
- Modes: `middleware_only`, `middleware_plus_activator`,
  `middleware_plus_governor`
- Ports: `5000`, `6000`, `7000`
- Skill set: `selective8`
- Expected active skills:
  - `drug-target-hypothesis`
  - `opentargets-database`
  - `chembl-database`
  - `compare-census-gene-pair-by-cell-type`
  - `string-database`
- Expected inactive controls:
  - `gwas-database`
  - `biomedical-literature-search`
  - `html-report-generator`

Aggregate selective activation result:

| Model | Mode | Exact matches | Mean recall | Mean F1 | Interpretation |
| --- | --- | ---: | ---: | ---: | --- |
| `qwen3.5:35b` | `middleware_only` | 0/3 | 0.600 | 0.704 | Under-activates relevant skills |
| `qwen3.5:35b` | `middleware_plus_activator` | 0/3 | 0.800 | 0.889 | Better, but misses `string-database` |
| `qwen3.5:35b` | `middleware_plus_governor` | 3/3 | 1.000 | 1.000 | Full selective activation success |
| `qwen3.5:122b` | `middleware_only` | 1/3 | 0.467 | 0.556 | High run/port variance |
| `qwen3.5:122b` | `middleware_plus_activator` | 1/3 | 0.467 | 0.556 | No improvement over middleware only |
| `qwen3.5:122b` | `middleware_plus_governor` | 1/3 | 0.467 | 0.556 | Governor did not improve activation |

All groups had mean precision and specificity of `1.0`. The failure mode was
not overactivating irrelevant control skills. The failure mode was missing
required active skills.

## Key Interpretation

The result should be interpreted as a protocol-compliance reversal, not a
general capability reversal.

`qwen3.5:35b` appears more scaffold-sensitive. It follows the Governor protocol
more literally, so it reads the needed skill guides before continuing.

`qwen3.5:122b` appears more goal-directed and autonomous. It can proceed toward
the downstream artifact even when it does not read all expected skill guides.
In inspected runs, some 122B Governor failures still produced
`evidence/hypothesis_report.json`. That means the model was not necessarily
incapable; it bypassed or deprioritized the activation protocol.

The working interpretation is:

> Larger models may be better artifact producers but worse protocol subjects
> under soft prompt-only governance. Smaller models can be more
> scaffold-compliant, producing better activation-trace fidelity despite lower
> general capability.

## Why This Can Happen

### 1. Protocol compliance is a separate capability

General reasoning, report writing, and skill activation compliance are different
axes. A larger model can be better at producing the final report while being
worse at following an intermediate instrumentation protocol.

In this benchmark, the true metric was not report quality. The metric was
whether the model activated the expected skill guides and suppressed inactive
controls.

### 2. Larger models may optimize the apparent task instead of the measured task

For the 122B model, the apparent task is "produce a good hypothesis report." The
measured task is "read the relevant skill guides before producing the report."
Those goals overlap but are not identical.

A more capable model may infer that it can solve the report without reading
every guide. That is useful in normal interactive use, but bad for a governance
benchmark.

### 3. Soft prompt governance can be bypassed

The Governor currently relies on prompt-level instructions. Prompt-level
instructions can shape behavior but do not guarantee coverage. Stronger models
may satisfy the high-level task while skipping low-level protocol steps unless
there is a deterministic gate.

### 4. Port/run variance can dominate small matrices

The 122B result was 1/3 exact across all three modes, which suggests the mode
effect was not cleanly expressed. With only three ports per mode, serving state,
sampling path, restart effects, or run-specific trajectory can dominate.

The current result is strong evidence of a failure mode, but it should not be
overread as a stable "35B is better than 122B" claim.

## External Evidence Found With Tavily MCP

### Inverse scaling

The OpenReview paper "Inverse Scaling: When Bigger Isn't Better" reports tasks
where language model performance gets worse with increased scale. The authors
identify mechanisms including memorized-pattern repetition, imitation of
undesirable training-data patterns, easy distractor tasks, and misleading
in-context demonstrations.

Relevance here: the skill activation benchmark contains an easy distractor. The
model can focus on making a plausible hypothesis report instead of satisfying
the stricter activation trace objective.

Source:
https://openreview.net/forum?id=DwgRm72GQF

### Constraint and brevity tasks can reverse model hierarchies

The preprint "Brevity Constraints Reverse Performance Hierarchies in Language
Models" reports inverse-scaling problems where smaller models systematically
outperform larger models under constraints.

Relevance here: selective activation is a constrained procedural task. The model
must choose relevant skills, suppress inactive controls, and leave traceable
tool calls. This is closer to constraint following than to open-ended reasoning.

Source:
https://arxiv.org/html/2604.00025v1

### Larger and more instructable models can be less reliable

The Nature paper "Larger and more instructable language models become less
reliable" argues that scaled-up and shaped-up models can become more likely to
give plausible but wrong answers instead of avoiding failure. The paper
distinguishes correctness from reliability and prudence.

Relevance here: the 122B model can produce a plausible downstream artifact while
failing the governance trace criterion. That is a reliability issue, not simply
a raw intelligence issue.

Sources:

- https://www.nature.com/articles/s41586-024-07930-y
- https://pmc.ncbi.nlm.nih.gov/articles/PMC11446866

### Instruction following remains brittle

"The Instruction Gap" describes inconsistent adherence to custom instructions
in production-style settings. It emphasizes that models can be strong at general
language tasks but unreliable at exact enterprise instructions.

Relevance here: the Governor protocol is a custom operational instruction. The
122B result shows exactly this distinction: general task completion does not
guarantee protocol adherence.

Source:
https://arxiv.org/html/2601.03269v1

### Reasoning models can lose instruction control during reasoning

Together AI's "Large Reasoning Models Fail to Follow Instructions During
Reasoning" reports that models may comply in final answers while failing
explicit constraints inside the reasoning trace, especially as task difficulty
increases.

Relevance here: activation trace fidelity is an internal-process requirement.
The final artifact can look good even when the internal process violates the
desired activation protocol.

Source:
https://www.together.ai/blog/large-reasoning-models-fail-to-follow-instructions-during-reasoning-a-benchmark-study

### Smaller or more efficient models can beat larger models when training or
architecture differs

The Chinchilla work showed that a 70B model trained with more appropriate data
scaling can outperform much larger models such as Gopher 280B on many tasks.
Qwen's own Qwen3 report similarly states that smaller newer Qwen3 models can
match or outperform larger older Qwen2.5 models on several benchmarks.

Relevance here: parameter count alone is not a sufficient proxy for task
performance. Training mix, post-training, architecture, active parameters, and
task fit matter.

Sources:

- https://proceedings.neurips.cc/paper_files/paper/2022/file/c1e2faff6f588870935f114ebe04a3e5-Paper-Conference.pdf
- https://qwenlm.github.io/blog/qwen3
- https://arxiv.org/html/2505.09388v1

## What This Means For The Hypothesis

The 35B result supports the hypothesis that the Governor can improve selective
activation when the model is scaffold-sensitive:

```text
middleware_plus_governor > middleware_plus_activator > middleware_only
```

The 122B result adds a second hypothesis:

> Stronger models may need hard governance, not just soft governance.

For strong models, prompt-injected instructions may not be enough. A stronger
model may complete the artifact by bypassing the intended activation path.

Therefore the clean claim is:

> Governor improves selective activation in the 35B setting, but the 122B result
> reveals a soft-governance failure mode: stronger models can satisfy the
> apparent production task while failing the measured activation protocol.

## Recommended Next Experiment

Convert Governor from prompt-only guidance into a deterministic coverage gate.

Before `save_hypothesis_report`, enforce:

```text
needed_skill_names = hard_required_skill_names + YES candidate skills
activated_skill_names must include all needed_skill_names
inactive control skills must not be activated
```

If coverage is incomplete:

```text
Do not call save_hypothesis_report.
Read the missing skill guide(s).
Retry the artifact gate.
```

This separates two questions:

1. Can 122B follow the protocol when the gate is deterministic?
2. Was the current failure caused by model incapability, or by soft prompt
   governance being too easy to bypass?

## Suggested Wording For Reports

Use cautious wording:

> In the selective8 activation benchmark, `qwen3.5:35b` showed a monotonic
> improvement from middleware-only to activator to Governor, reaching 3/3 exact
> selective activation under Governor. In contrast, `qwen3.5:122b` remained at
> 1/3 exact activation across all modes. This should not be interpreted as a
> general capability reversal. Instead, it suggests that activation-trace
> compliance is a distinct capability from artifact generation, and that larger
> models may require deterministic coverage gates rather than soft prompt-only
> governance.

Avoid overclaiming:

```text
35B is better than 122B.
```

Prefer:

```text
35B was more compliant with the activation protocol in this benchmark.
122B showed a protocol-compliance failure mode despite being capable of producing
the downstream artifact in inspected runs.
```
