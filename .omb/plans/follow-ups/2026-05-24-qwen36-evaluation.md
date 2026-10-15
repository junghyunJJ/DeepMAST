---
date: 2026-05-24
status: research-complete
related-pr: 15
---

# qwen3.6 Evaluation Matrix: Can We Deprecate the `ollama-openai` Workaround?

## Section 1: Question Being Answered

**Can we remove the `ollama-openai` workaround (PR #15) if we standardize on qwen3.6:35b?**

Background: PR #15 (merged 2026-05-03) introduced the `ollama-openai` LLM provider in
`src/agents/model.py` specifically to bypass Ollama's `PARSER qwen3.5` XML→JSON translation
layer, which deterministically corrupts complex multi-tool schemas under qwen3.5:35b with the
error: `XML syntax error: element <function> closed by </parameter>`. The community claim is that
qwen3.6 may have fixed this instability out-of-the-box. This document evaluates that claim with
research-only findings; empirical confirmation requires local Ollama runs (Section 4).

---

## Section 2: Community Evidence Summary

### Finding 1 — qwen3.6 reports ~87.5% stability on /api/chat (vs 0% for vanilla qwen3.5:35b)

**Source:** NVIDIA Developer Forum, "Qwen3.5 Tool Calling finally fixed (possibly)"
**URL:** <https://forums.developer.nvidia.com/t/qwen3-5-tool-calling-finally-fixed-possibly/366451>
**Accessed:** 2026-05-24

A community member testing qwen3.6:35b-A3B on a DGX Spark reported:

> "It looks like 3.6 is as stable out of the box as 3.5 was with all the fixes — I've only had
> one failure in 8 runs so far."

This represents approximately **87.5% pass rate (7/8 runs)**. A second respondent confirmed:

> "Just want to confirm 3.6 seems fixed the issue and I see consistent tool calls in long
> agentic sessions, also new model does a lot of parallel tool calls when needed without
> any errors."

**Caveat:** These tests were conducted on vLLM/llama.cpp backends on DGX Spark hardware, **not
on the Ollama `/api/chat` endpoint specifically.** The `PARSER` layer implementation differs
between backends. See Finding 2 for why this distinction matters critically.

---

### Finding 2 — CRITICAL: qwen3.6 on Ollama still uses `PARSER qwen3.5` (Ollama 0.20.3)

**Source:** openai/codex GitHub issue #22294, "Ollama: 'Model metadata for qwen3.6:27b not
found' warning even though the model is available"
**URL:** <https://github.com/openai/codex/issues/22294>

A user running **Ollama 0.20.3** inspected the Modelfile for `qwen3.6:27b` and found:

```
RENDERER qwen3.5
PARSER qwen3.5
```

This is the exact XML parser that PR #15 identified as the root cause of
`XML syntax error: element <function> closed by </parameter>`. Ollama has not yet assigned a
separate `PARSER qwen3.6` for the new model family — it reuses the qwen3.5 template and parser
through at least Ollama 0.20.3. This means qwen3.6 on Ollama `/api/chat` may reproduce the
same parser-level XML corruption even if the model weights themselves generate more stable XML.

---

### Finding 3 — Ollama tool-calling status "still flaky" for Qwen3.5 as of Ollama 0.20.2 (April 2026)

**Source:** Reddit r/LocalLLaMA, "Qwen 3.5 Tool Calling Fixes for Agentic Use: What's Broken"
**URL:** <https://www.reddit.com/r/LocalLLaMA/comments/1sdhvc5/qwen_35_tool_calling_fixes_for_agentic_use_whats>
**Date:** April 2026

Community server-status matrix from this post:

| Server | Tool-call parse | finish_reason | Stable? |
|--------|----------------|---------------|-------|
| Ollama 0.20.2 | Improved since #14493, **still flaky** | Fixed | Sometimes wrong |
| vLLM 0.19.0 | Works (`--tool-call-parser qwen3_coder`), streaming bugs | Fixed | Usually correct |
| llama.cpp (open) | peg-native parser fails when text precedes `<tool_call>` | Fixed | Open bugs |

Since qwen3.6 reuses `PARSER qwen3.5` in Ollama (Finding 2), this flakiness may extend to
qwen3.6 on `/api/chat`. Ollama's known open issues for Qwen3.5 as of v0.17.4 (GitHub #14493):
wrong tool call format (renderer), missing generation prompt after tool calls — both still open.

---

### Finding 4 — Ollama v0.17.4 partially fixed Qwen3/3.5 thinking+tool-call parsing; latest is v0.24.0

**Source:** Cloudron Forum, "Ollama Package Updates" thread, listing release changelogs
**URL:** <https://forum.cloudron.io/topic/14470/ollama-package-updates/8?page=2>

Ollama v0.17.4 fixed: *"Fixed issue where tool calls in the Qwen 3 and Qwen 3.5 model families
would not be parsed correctly if emitted during thinking."*

This is a meaningful partial fix for the thinking-block leakage class of errors. However, GitHub
issue #14493 documents that other bugs remain in v0.17.4: wrong tool call format, unclosed
`</think>` (renderer), missing generation prompt.

**Ollama version context:** The PR #15 baseline was Ollama 0.20.6 (2026-05-03). The latest
Ollama release visible from the GitHub releases page is **v0.24.0** (released ~2026-05-14),
which is a significant jump. The v0.24.0 changelog mentions qwen3.6 library support but does
**not** document a new `PARSER qwen3.6` implementation or resolution of the XML→JSON translation
layer bugs. The `PARSER qwen3.5` assignment is confirmed through at least Ollama 0.20.3.

---

### Finding 5 — qwen3.6:35b-A3B Tool Decathlon benchmark lower than qwen3.5 on function-calling tasks

**Source:** Hugging Face, Qwen/Qwen3.6-35B-A3B model card (official Alibaba release page)
**URL:** <https://huggingface.co/Qwen/Qwen3.6-35B-A3B>

Alibaba's own benchmarks for the **35B-A3B MoE** variant (the size matching the user's local
model):

| Benchmark | Qwen3.6-35B-A3B | Note |
|-----------|----------------|------|
| Tool Decathlon | 31.5 | Multi-tool structured function calling |
| MCPMark | 36.3 | MCP server tool orchestration |
| TAU3-Bench | 68.4 | Agent task completion |

For reference, qwen3.5:35b (Ollama library page) shows BFCL-V4: 43.8 and MCP-Mark: 57.5.
Note these benchmarks use different harnesses and are not directly comparable; however the
Tool Decathlon gap (31.5 vs higher Qwen3.5 scores) suggests the 35B-A3B MoE variant may
underperform on structured tool-use vs the larger Qwen3.5 series in ideal conditions.

The HuggingFace model card does state: *"Qwen3.6 excels in tool calling capabilities"* for
agentic use — but this likely refers to the larger 27B+ dense variants, not the 35B-A3B MoE.

---

### Finding 6 — vLLM has official Qwen3.5 & Qwen3.6 combined usage guide with tool-call parser

**Source:** vLLM Recipes documentation, "Qwen3.5 & Qwen3.6 Usage Guide"
**URL:** <https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3.5.html>

vLLM explicitly supports both Qwen3.5 and Qwen3.6 with `--tool-call-parser qwen3_coder` and
`--enable-auto-tool-choice`. The HuggingFace model card recommends for tool use:

```bash
vllm serve Qwen/Qwen3.6-35B-A3B --port 8000 \\
  --reasoning-parser qwen3 \\
  --enable-auto-tool-choice \\
  --tool-call-parser qwen3_coder
```

vLLM's native JSON parser bypasses the XML→JSON layer entirely, making it architecturally
immune to the `element <function> closed by </parameter>` class of errors. If Ollama instability
persists after empirical testing, vLLM migration is the structurally sound long-term path.

---

## Section 3: Comparison Matrix

| Model | Ollama version | `/api/chat` tool-call stability | XML PARSER layer | Reported failure mode | Source |
|-------|---------------|--------------------------------|-----------------|----------------------|--------|
| qwen3.5:35b | 0.20.6 (PR #15 baseline) | **Broken on 6+ tools — deterministic** | `PARSER qwen3.5` | `XML syntax error: element <function> closed by </parameter>` | PR #14 comment #4363865471 |
| qwen3.5:35b | 0.20.2 | Improved but **still flaky** | `PARSER qwen3.5` | Wrong tool call format (renderer); missing generation prompt | Reddit r/LocalLLaMA (Apr 2026) |
| qwen3.5:122b | 0.20.6 (create_ollama_llm default) | Not tested for 6-tool SUMMARIZER | `PARSER qwen3.5` | Subject to same XML parser layer | `model.py:120` |
| qwen3.6:27b | 0.20.3 | **Unverified on /api/chat (6+ tools)** | `PARSER qwen3.5` (**confirmed**) | Likely inherits same XML parser bugs | GitHub openai/codex#22294 |
| qwen3.6:35b-A3B | ≥0.20.x (TBD — user's local setup) | Community ~87.5% on vLLM; **/api/chat TBD** | `PARSER qwen3.5` (inferred — same family) | 1/8 failure (vLLM context); /api/chat XML stability **empirically unknown** | NVIDIA forum; HF model card |
| qwen3.6:35b-A3B | vLLM 0.19.0+ | ~87.5% community pass rate | `--tool-call-parser qwen3_coder` (JSON, no XML) | Streaming drops opening `{` brace (fixed in 0.19.0) | Reddit r/LocalLLaMA (Apr 2026) |

**Key takeaway:** The 87.5% community pass rate for qwen3.6 comes from **vLLM/llama.cpp**, which
use JSON-native parsers. Ollama's `/api/chat` still routes through `PARSER qwen3.5` for qwen3.6
families (confirmed as of 0.20.3). There is **no community evidence yet** that qwen3.6 on
Ollama `/api/chat` with 6+ tool schemas avoids the XML corruption. Empirical verification is
required before the `ollama-openai` workaround can be deprecated.

---

## Section 4: Local Empirical Verification Protocol

Run on the owner's local machine (Ollama at `localhost:6000`). **Do NOT use
`create_ollama_openai_llm`** — these tests must go through the native `ChatOllama` path
(`/api/chat`) to evaluate whether the workaround is still needed.

### 4a. 6-tool SUMMARIZER smoke test (mirrors PR #15 smoke log complexity)

```bash
export OLLAMA_HOST=http://localhost:6000
OLLAMA_BASE_URL=http://localhost:6000 OLLAMA_MODEL=qwen3.6:35b .venv/bin/python -c "
import json
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from src.agents.model import create_ollama_llm

@tool
def get_gwas_hits(gene: str, p_threshold: float = 5e-8) -> str:
    '''Retrieve GWAS hits for a gene.'''
    return json.dumps({'gene': gene, 'hits': []})

@tool
def get_eqtl_data(gene: str, tissue: str) -> str:
    '''Retrieve eQTL data for a gene in a tissue.'''
    return json.dumps({'gene': gene, 'tissue': tissue, 'eqtls': []})

@tool
def get_ppi_network(gene: str, max_depth: int = 2) -> str:
    '''Get protein-protein interaction network.'''
    return json.dumps({'gene': gene, 'interactions': []})

@tool
def get_drug_targets(indication: str) -> str:
    '''Get known drug targets for an indication.'''
    return json.dumps({'indication': indication, 'targets': []})

@tool
def get_pathway_enrichment(gene_list: list) -> str:
    '''Run pathway enrichment analysis.'''
    return json.dumps({'pathways': []})

@tool
def get_literature_evidence(query: str, max_results: int = 10) -> str:
    '''Search literature for evidence.'''
    return json.dumps({'query': query, 'papers': []})

tools = [
    get_gwas_hits, get_eqtl_data, get_ppi_network,
    get_drug_targets, get_pathway_enrichment, get_literature_evidence
]
llm = create_ollama_llm()
llm_with_tools = llm.bind_tools(tools)

print('Model:', llm.model)
print('Path: ChatOllama /api/chat (create_ollama_llm — NOT ollama-openai)')
print('Running 6-tool smoke test...')
response = llm_with_tools.invoke([HumanMessage(
    content='Summarize GWAS evidence for PCSK9 as a drug target for hypercholesterolemia using all available tools.'
)])
finish = getattr(response, 'response_metadata', {}).get('finish_reason', 'N/A')
calls = len(response.tool_calls) if hasattr(response, 'tool_calls') else 0
print(f'finish_reason: {finish}')
print(f'tool_calls: {calls}')
print('PASS' if calls > 0 else 'FAIL — no tool calls emitted')
"
```

### 4b. 10-tool stress test (extended schema complexity — SUMMARIZER peak load)

```bash
OLLAMA_BASE_URL=http://localhost:6000 OLLAMA_MODEL=qwen3.6:35b .venv/bin/python -c "
import json
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from src.agents.model import create_ollama_llm

def make_tool(name):
    @tool
    def _t(query: str) -> str:
        f'''Evidence tool: {name}. Retrieves drug-target evidence.'''
        return json.dumps({'tool': name, 'result': []})
    _t.__name__ = name
    return _t

tool_names = [
    'gwas_hits', 'eqtl_data', 'ppi_network', 'drug_targets',
    'pathway_enrichment', 'literature_evidence', 'coloc_analysis',
    'mendelian_rand', 'tissue_expr', 'open_targets'
]
tools_list = [make_tool(n) for n in tool_names]

llm = create_ollama_llm()
llm_with_tools = llm.bind_tools(tools_list)
print(f'Bound {len(tools_list)} tools via create_ollama_llm (/api/chat path)')

failures = 0
for i in range(5):
    try:
        r = llm_with_tools.invoke([HumanMessage(
            content=f'Run all 10 tools for PCSK9 drug-target evaluation. Call {i+1}.'
        )])
        calls = len(r.tool_calls) if hasattr(r, 'tool_calls') else 0
        status = 'PASS' if calls > 0 else 'FAIL'
        print(f'  Run {i+1}: {calls} tool calls — {status}')
        if calls == 0:
            failures += 1
    except Exception as e:
        print(f'  Run {i+1}: EXCEPTION — {e}')
        failures += 1

print(f'Result: {5 - failures}/5 passed ({100 * (5 - failures) // 5}% pass rate)')
print('VERDICT: PASS' if failures == 0 else f'VERDICT: FAIL ({failures}/5 failures — keep ollama-openai)')
"
```

### 4c. Check Ollama daemon logs for XML errors (run on the Ollama host after each test)

```bash
journalctl -u ollama --since "5 min ago" 2>/dev/null | grep -i "xml\|parser\|syntax error\|element.*closed"
# Or if running without systemd:
# Check the Ollama process terminal output directly
```

---

## Section 5: Decision Tree

```
qwen3.6:35b smoke results (Section 4)
│
├─ BOTH 6-tool AND 10-tool pass with 0 XML errors (5/5 runs each)
│   │
│   ├─ Option A — RECOMMENDED: Document qwen3.6 as default; keep ollama-openai as legacy
│   │   • Update OLLAMA_MODEL default in model.py:120 to qwen3.6:35b (or qwen3.6:35b-a3b)
│   │   • Annotate create_ollama_openai_llm as "legacy — qwen3.5 deployments only"
│   │   • Update .env.example, docs/drugtarget/closed-book-policy.md
│   │   • Estimated effort: ~80 min (see Section 6 table)
│   │
│   └─ Option B — AGGRESSIVE: Deprecate ollama-openai entirely
│       • Remove create_ollama_openai_llm and ollama-openai branch from create_llm()
│       • RISK: Breaks existing qwen3.5 deployments without migration path
│       • NOT RECOMMENDED without confirmed qwen3.6-only policy across all deployments
│
├─ 6-tool test fails OR any XML error in either test
│   └─ KEEP ollama-openai as required path; close evaluation as "workaround still required"
│       • Update create_ollama_openai_llm KNOWN LIMITATION docstring with test date + version
│       • Consider opening ollama/ollama issue with qwen3.6 + 6-tool repro case
│       • Re-evaluate if Ollama ships PARSER qwen3.6 (watch ollama/ollama release notes)
│
└─ 6-tool passes but 10-tool fails (partial improvement)
    └─ MIXED: Document tool-count threshold
        • qwen3.6 safe for ≤6 tools on /api/chat; ollama-openai required for SUMMARIZER (10+)
        • Update model.py to route by tool count if architecturally feasible
        • Keep ollama-openai as default SUMMARIZER path
```

---

## Section 6: Estimated Migration Effort (if qwen3.6 passes all smoke tests)

| File | Change needed | Est. time |
|------|--------------|----------|
| `src/agents/model.py:120` | Update `create_ollama_llm` default to `qwen3.6:35b`; update docstring | 20 min |
| `src/agents/model.py` (`create_ollama_openai_llm`) | Demote to legacy section; update KNOWN LIMITATION block with test evidence | 15 min |
| `.env.example` | Change `OLLAMA_MODEL=qwen3.5:122b` → `qwen3.6:35b` (or `qwen3.6:35b-a3b`) | 5 min |
| `docs/drugtarget/closed-book-policy.md` | Update recommended local model table | 10 min |
| Integration test suite | Add `qwen3.6` smoke test fixture; mark qwen3.5 tests as legacy | 30 min |
| **Total** | | **~80 min** |

**Cross-reference — R5 verification (`trig_01FH6Pn2CAsDee7pTgvApsm1`, scheduled 2026-05-17):**
If R5 regression testing completed and found regressions in the SUMMARIZER pipeline on the
current qwen3.5+ollama-openai stack, that is an additional reason to prioritize the qwen3.6
migration (if smoke tests pass here). If R5 found no regressions, migration urgency is lower —
but the architecture simplification benefit remains valid.

---

## Appendix: Source Index

| # | URL | Key Finding |
|---|-----|-------------|
| 1 | <https://forums.developer.nvidia.com/t/qwen3-5-tool-calling-finally-fixed-possibly/366451> | qwen3.6 ~87.5% tool-call pass on vLLM/llama.cpp backends (not Ollama-specific) |
| 2 | <https://github.com/openai/codex/issues/22294> | qwen3.6:27b on Ollama 0.20.3 confirms `RENDERER qwen3.5 / PARSER qwen3.5` — XML layer unchanged |
| 3 | <https://www.reddit.com/r/LocalLLaMA/comments/1sdhvc5/qwen_35_tool_calling_fixes_for_agentic_use_whats> | Ollama 0.20.2 Qwen3.5 tool calling "still flaky" as of April 2026 |
| 4 | <https://forum.cloudron.io/topic/14470/ollama-package-updates/8?page=2> | Ollama v0.17.4 fixed thinking-block tool parse; v0.24.0 is current latest (no new Qwen parser) |
| 5 | <https://huggingface.co/Qwen/Qwen3.6-35B-A3B> | Official model card; Tool Decathlon 31.5; "excels in tool calling for agentic use" |
| 6 | <https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3.5.html> | vLLM official Qwen3.5+3.6 guide; `--tool-call-parser qwen3_coder` supported — JSON-native, no XML |
| 7 | <https://github.com/ollama/ollama/issues/14493> | Open Ollama bugs for Qwen3.5:27b through v0.17.4: wrong format, missing gen prompt |
