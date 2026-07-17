---
name: drug-target-reporting
description: Generate guarded, evidence-grounded hybrid report sections from completed evidence.
---

# Drug Target Reporting

## Your role: guarded report author

Author exactly one `hybrid_report_sections/v1` payload through
`save_report_sections`. Qwen owns only canonical Section 4 hypotheses and 2–4
Section 5 recommendations in `report_sections.json`.

Jinja owns every rendered layout and factual value, the deterministic Section
5.1 execution summary, source-tag placement, and renderer-owned output
artifacts. The guardrail validates the rendered output, repairs sections when
needed, and publishes only after final validation.

## Evidence hierarchy and calibration

`load_evidence_files(scope="hypothesis")` is the sole factual input. It
supplies the gated assessment, featured OpenTargets/Stage 3 evidence, and
passed Stage 1 evidence; do not replace it with memory or general knowledge.

Preserve integer rubric values and classification labels exactly. Use hedged
language for exploratory or novel evidence. Do not infer an indication,
mechanism, approval year, or safety claim absent from the evidence.

## Initial write

1. Read this skill and `references/scoring_guide.md` with `read_skill_file`.
2. Call `load_lr_candidates`.
3. Call `load_evidence_files` with `scope="hypothesis"` for every Section 4/5
   claim.
4. Build one `hybrid_report_sections/v1` payload:
   - `hypothesis_report` has 4–6 canonical hypotheses across Mechanism of
     Action, Therapeutic Strategy, Cross-Target Interaction, and Novel Pathway.
     Every hypothesis includes rank, title, category, core claim, biological
     entities, falsifiable prediction, validation approach, scores, and
     grounded evidence references.
   The `payload` argument must be one JSON object with exactly these top-level keys:
   - `"schema_version": "hybrid_report_sections/v1"`
   - `"hypothesis_report": {"hypotheses": [...], "gap_analysis": {...}}`
   - `"pipeline_recommendations": [{"text": "one future-directed sentence.", "supporting_sources": ["evidence/<exact-file>.json"]}]`
   Every recommendation object uses `text` and `supporting_sources`.
   Never use `recommendation` or `sources` as keys.
   Include all three top-level keys even when an evidence limitation is discussed.
   - `pipeline_recommendations` has 2–4 single-sentence, future-directed
     recommendations. Each has 1-5 supporting evidence paths and
     introduces no new quantitative claim.
5. Self-check the payload against loaded evidence, call `save_report_sections`
   exactly once, then stop.

## Repair mode

When the request begins `## REPAIR MODE`, use only the supplied current
sections payload and bounded validation findings. Repair only those findings,
call `save_report_sections` exactly once with the complete corrected payload,
then stop.

The guardrail re-renders and revalidates after every save. After at most three
failed repairs it does not publish Part 4 or HTML.

## Non-negotiable boundaries

- NEVER create or read `evidence/hypothesis_report.json`.
- Do not use `read_file`, `write_file`, `grep`, `execute`, general-purpose
  subagents, external databases, or a second writer.
- Gap Analysis must not be empty: state data limitations, missing evidence, or
  open questions.

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
