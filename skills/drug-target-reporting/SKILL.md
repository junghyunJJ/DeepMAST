---
name: drug-target-reporting
description: Generate guarded Section 5 recommendations from a validated hypothesis handoff.
---

# Drug Target Reporting

## Your role: guarded report synthesizer

Qwen owns only 2–4 Section 5 recommendations in `report_sections.json`.
The interpreter already created and validated the canonical hypothesis handoff.
The host injects that handoff, then Jinja renders every factual field. Never
author Markdown or a hypothesis JSON object.

Jinja owns every rendered layout and factual value, the deterministic Section
5.1 execution summary, source-tag placement, and renderer-owned output
artifacts. The guardrail validates the rendered output, repairs sections when
needed, and publishes only after final validation.

`hypothesis_report.json` is read only via `load_validated_hypothesis_report` and is never cited.

## Initial write

1. Read this skill with `read_skill_file`.
2. Call `load_validated_hypothesis_report`. Stop if `valid` is false.
3. Create one payload with exactly `schema_version` and `pipeline_recommendations`.
   Each of the 2–4 recommendations has one future-directed sentence and 1-5 exact `evidence/<filename>.json` paths from the handoff.
4. Call `save_report_sections` once. If its receipt has `saved:true`, stop. If
   its receipt has `saved:false`, repair only returned recommendation violations
   and call `save_report_sections` once more, then stop.

## Repair mode

When the request begins `## REPAIR MODE`, use only the supplied recommendation
payload and bounded validation findings. Repair only those findings. Call
`save_report_sections` exactly once with the corrected recommendation payload,
then stop.

## Non-negotiable boundaries

- Do not use `read_file`, `write_file`, `grep`, `execute`, general-purpose
  subagents, external databases, or a second writer.

## Supported local Ollama diagnostic invocation

This invocation is diagnostic; no successful report was produced.

Use OpenAI-compatible Ollama because the writer needs tool schemas:

```bash
export OLLAMA_BASE_URL=http://localhost:6000
export OLLAMA_MODEL=qwen3.5:122b
python scripts/run_report_writer_only.py \
  --data-dir /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/final_bc_hybrid_qwen_test \
  --disease "breast cancer" \
  --provider ollama-openai \
  --model qwen3.5:122b
```
