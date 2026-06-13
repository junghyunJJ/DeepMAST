# Coverage Contract

This reference defines the generic data contract for `skill-activation-governor`.
It intentionally avoids domain-specific routing rules. Domain layers may compute
`required_skill_names`, but the governor only enforces coverage.

## Inputs

### required_skill_names

A list of skill names that must be activated before the artifact gate.

```json
["database-a", "statistics-b"]
```

### available_skill_names

A list of skills available to the agent. Optional discovery should only choose
skills from this set.

### activated_skill_names

A list of skill names already activated by prior `read_skill_file` calls.

### activation_trace

Tool-call history that can prove activation. Valid traces may include either:

- direct skill names in `activated_skill_names`
- `read_skill_file` calls with `skill_path`
- nested records such as `tool_history`, `all_read_skill_file_calls`, or
  subagent-scoped read-skill call lists

### artifact_gate

The step that requires complete coverage, such as `save_report`, `final_answer`,
`save_hypothesis_report`, or `handoff_to_writer`.

## Output

Coverage checks should return:

```json
{
  "required_skill_names": ["database-a", "statistics-b"],
  "activated_skill_names": ["database-a"],
  "missing_required_skills": ["statistics-b"],
  "coverage_complete": false
}
```

## Using the Checker Script

When required and activated skill data exists as JSON files, use:

```bash
python skills/skill-activation-governor/scripts/check_skill_coverage.py \
  --required required.json \
  --activated activated.json
```

The `--required` file may be a JSON list or an object with
`required_skill_names`.

The `--activated` file may be a JSON list or an object containing
`activated_skill_names`, `tool_history`, `all_read_skill_file_calls`, or similar
trace records.

The script prints JSON with `coverage_complete` and `missing_required_skills`.

## Integration Guidance

Use this separation of responsibility:

```text
Domain layer:
  context or evidence -> required_skill_names

Skill activation governor:
  required_skill_names + optional relevance -> activation + coverage check

Artifact guard:
  block final artifact when coverage_complete is false
```

This keeps the governor reusable while still allowing domain-specific systems to
define their own required skill rules.
