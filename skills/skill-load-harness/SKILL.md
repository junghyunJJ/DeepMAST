---
name: skill-load-harness
description: Forced skill evaluation harness for reliable skill loading
---

# Skill Load Harness — Forced Evaluation Protocol

Before beginning your task, you MUST complete the following 3-step sequence:

## Step 1 - EVALUATE (mandatory for ALL skills)
For each skill listed in {{available_skills}}, explicitly state:
- [skill-name] — YES / NO — [one-sentence reasoning]

**Judgment criteria:**
- YES = this skill is **directly required** to complete the current task
- NO = this skill is not needed, OR "might be helpful" (uncertain = NO)
- When in doubt, default to NO. Only mark YES when the task clearly demands it.

## Step 2 - ACTIVATE (for YES skills only)
For each skill marked YES:
- Call `read_skill_file(skill_path="<path>")` to load full instructions
- Summarize key guidance in 2-3 bullet points

## Step 3 - IMPLEMENT
Proceed with your task. You MUST reference activated skill guidance when making
decisions covered by those skills.

CRITICAL: Do NOT skip Step 1. Evaluate ALL skills. Step 2 is WORTHLESS without Step 1.
