---
name: skill-activator
description: Two-phase skill activator — classify task, then activate only relevant skills
---

# Skill Evaluation Protocol

## Phase 1 — QUICK SCREEN
Before evaluating individual skills, answer:
**"Does this task require reading a skill guide for interpreting results or planning a query strategy?"**

Answer NO (write "NO_SKILLS_NEEDED" and skip to Phase 3) when:
- The task uses tools directly without needing interpretation guidance
- The task is internal (save, load, finalize, validate, organize data)
- The task is about visualization, reporting, or general explanation
- You are unsure whether a skill is needed

Answer YES and proceed to Phase 2 only when:
- The task explicitly involves a database/API whose interpretation guide you need
- The task requires strategy guidance that a skill document provides

## Phase 2 — EVALUATE (only if Phase 1 = YES)
Review each skill listed below. Apply these rules IN ORDER:

1. **Context-match rule**: **YES** only if the task clearly requires this skill's guidance.
2. **Default rule**: When in doubt → **NO**. Only mark YES when the task clearly demands
   this skill's guidance.

For each skill: [skill-name] — YES / NO — [one-sentence reason]
For YES skills: call `read_skill_file(skill_path="<path>")` to load the guide.

{{available_skills}}

## Phase 3 — IMPLEMENT
Proceed with the task. Reference activated skill guidance when making
decisions covered by those skills.
