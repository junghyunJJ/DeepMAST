---
name: skill-load-harness
description: Two-phase skill evaluation harness — classify task, then activate only relevant skills
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

1. **TOOL-ONLY rule**: If a skill's Hint contains "TOOL-ONLY" → **ALWAYS NO**.
   These skills are accessed via dedicated tools and never need their guide read.
2. **Context-match rule**: If a skill's Hint specifies a stage, phase, or context
   (e.g., "Stage 3 only", "Search phase") → **YES only if your task matches that context**.
3. **Default rule**: When in doubt → **NO**. Only mark YES when the task clearly demands
   this skill's guidance.

For each skill: [skill-name] — YES / NO — [one-sentence reason]
For YES skills: call `read_skill_file(skill_path="<path>")` to load the guide.

{{available_skills}}

## Phase 3 — IMPLEMENT
Proceed with the task. Reference activated skill guidance when making
decisions covered by those skills.
