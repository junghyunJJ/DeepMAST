"""Prompt constants for the finalize_report LangGraph node.

Kept in a separate module so the prompt text can be unit-tested independently
of the node implementation and so it is clearly separated from the summarizer
subagent prompts in subagents/prompts.py.
"""

FINALIZE_REPORT_SYSTEM_PROMPT = """
You are a structured-output generator for drug-target report expansions.
Your task: given an expansion schema spec and evidence payload, emit a
ReportExpansionsPayload that obeys cited-only provenance — every sentence's
source_provenance.source_value MUST appear in the provided reference_card's
provenance index.

HARD RULES:
- Never invent drug names, gene names, or indication codes.
- Every `source_fields` entry MUST reference a real evidence path that exists
  in the reference_card.
- Output exactly one SlotItem per slot_id in the spec.
- Do not narrate; emit only the structured ReportExpansionsPayload.
""".strip()

FINALIZE_REPORT_USER_TEMPLATE = """
Expansion schema spec:
```json
{spec_json}
```

Reference card (cited values index):
```json
{reference_card_json}
```

Evidence summary (per-target):
```json
{evidence_summary_json}
```

Return a ReportExpansionsPayload conforming to the spec above.
""".strip()

__all__ = ["FINALIZE_REPORT_SYSTEM_PROMPT", "FINALIZE_REPORT_USER_TEMPLATE"]
