---
name: skill-activation-governor
description: Coordinate flexible skill discovery with deterministic hard-required skill coverage. Use this when an agent has available skills, hard_required_skill_names, candidate_skill_names, activation traces, artifact gates, or must prevent missing needed skill reads before producing or saving final output. Use it to combine SkillActivator-style YES/NO relevance selection with hard coverage enforcement without embedding domain-specific routing rules.
---

# Skill Activation Governor

Use this skill to control skill activation when both flexibility and reliability matter.

This skill does not decide domain-specific mappings such as which biomedical evidence
requires which database guide. The caller, tool output, manifest, or agent contract
must provide required skills when deterministic coverage is needed. This skill then
governs activation:

- Hard required skills are caller-supplied skills that must be activated.
- Candidate skills are caller-supplied or registry-derived skills that must each
  receive a YES or NO decision.
- Needed skills are hard required skills plus YES candidates.
- Suppressed skills are NO candidates and must not be activated for this artifact.
- Final artifacts should not be produced until needed skill coverage is complete.

For machine-readable fields and the bundled checker script, see
`references/coverage-contract.md`.

## Activation Contract

Before doing task work, identify these fields when they are available:

- `available_skill_names`: skills that can be activated for this task.
- `hard_required_skill_names`: skills that must be activated before the artifact gate.
- `required_skill_names`: backward-compatible alias for `hard_required_skill_names`.
- `candidate_skill_names`: skills that must be evaluated with YES or NO.
- `needed_skill_names`: hard required skills plus YES candidates.
- `suppressed_skill_names`: NO candidates that must remain inactive.
- `activated_skill_names`: skills already read through prior `read_skill_file` calls.
- `activation_trace`: tool-call history that can prove which skills were read.
- `artifact_gate`: the point where required coverage must be complete.

If `hard_required_skill_names` is absent, treat legacy `required_skill_names` as
the hard-required list when present. If neither field is present, perform
candidate discovery only. Do not invent hard-required skills from domain
assumptions unless the task, manifest, or tool output explicitly provides that
mapping.

## Protocol

### 1. Establish the Contract

Summarize the current activation contract:

```text
Hard required skills: [names or NONE]
Required skills: [names or NONE]
Candidate skills: [names or NONE]
Available skills: [names or UNKNOWN]
Artifact gate: [gate or final response]
Already activated: [names or UNKNOWN]
```

If `hard_required_skill_names` is absent and `required_skill_names` is present,
copy the alias into the hard-required list. Treat hard-required skills as
authoritative. They do not need candidate relevance judgment.

### 2. Flexible Discovery

Evaluate every candidate skill with YES or NO:

```text
[skill-name] - YES or NO - one-sentence reason
```

Use YES only if the current artifact will interpret, cite, transform, validate,
or rely on that skill's modality or procedure.

Use NO if the skill is merely related, uncertain, unavailable in the evidence, or
the wrong artifact type. NO candidates must remain suppressed and must not be
activated for this artifact.

### 3. Required Coverage

Set `needed_skill_names` to hard required skills plus YES candidates. Set
`suppressed_skill_names` to NO candidates.

Compare `needed_skill_names` with `activated_skill_names` or `activation_trace`.

For every missing needed skill:

```text
read_skill_file("skills/[skill-name]/SKILL.md")
```

After reading missing needed skills, update the activated list. Needed coverage
is complete only when every hard required skill and every YES candidate has been
read. NO candidates remain suppressed.

### 4. Final Gate

Before producing the final artifact, final answer, save call, or handoff named by
`artifact_gate`, run a final needed coverage check.

If needed coverage is complete, proceed.

If needed coverage is incomplete, do not produce the final artifact. Report:

```text
Needed skill coverage incomplete.
Missing needed skills: [names]
Next action: read the missing skill guide(s), then retry the artifact gate.
```

### 5. Output

When reporting activation status, use this compact format:

```text
Hard required skills: [names or NONE]
YES candidate skills: [names or NONE]
Suppressed candidate skills: [names or NONE]
Needed skills: [names or NONE]
Activated skills: [names]
Missing needed skills: [names or NONE]
Coverage complete: true or false
```

## Examples

### Required coverage with optional discovery

Input context:

```json
{
  "hard_required_skill_names": ["database-a", "statistics-b"],
  "candidate_skill_names": ["plotting-c"],
  "available_skill_names": ["database-a", "statistics-b", "plotting-c"],
  "activated_skill_names": ["database-a"],
  "artifact_gate": "save_report"
}
```

Action:

- Read `skills/statistics-b/SKILL.md` because it is required and missing.
- Evaluate `plotting-c` as YES or NO. Activate it only if the current artifact
  will interpret, cite, transform, validate, or rely on plotting guidance.
- Do not call `save_report` until `statistics-b` is activated.

### Candidate discovery without hard-required skills

Input context has candidate skills but no `hard_required_skill_names` or legacy
`required_skill_names`.

Action:

- Evaluate each candidate skill with YES or NO.
- Read only YES skills.
- Keep NO candidates suppressed.
- Needed coverage is only the YES candidate set.

### Artifact gate failure

Input context says `hard_required_skill_names=["safety-review"]`, but no trace
proves that `safety-review` was read.

Action:

- Stop before the final artifact.
- Read `skills/safety-review/SKILL.md` if the tool is available.
- If the read cannot be completed, report the missing needed skill instead of
  producing the gated artifact.

## Common Issues

### Hard Required Skills Are Missing

If `hard_required_skill_names` is expected but absent:

1. Check whether the caller, manifest, or tool output should have supplied it.
2. Check whether legacy `required_skill_names` was supplied as the alias.
3. Continue with candidate discovery only if no deterministic requirement exists.
4. State that hard-required coverage cannot be guaranteed without an explicit list.

### Skill Is Required But Not Available

If a hard-required or YES candidate skill name is not in the available skill registry:

1. Report the unavailable needed skill.
2. Do not substitute a different skill unless the caller explicitly allows it.
3. Stop before the artifact gate if the missing skill is mandatory.

### Activation Trace Is Incomplete

If the trace is missing or cannot prove prior skill reads:

1. Prefer re-reading the needed skills if `read_skill_file` is available.
2. If re-reading is impossible, treat coverage as incomplete.
3. Report the uncertainty before the final artifact.

### Too Many Candidate Skills Are Being Activated

If candidate discovery activates broad or weakly related skills:

1. Reapply the YES-only-if rule.
2. Mark uncertain skills as NO.
3. Keep hard-required coverage separate from candidate discovery.
