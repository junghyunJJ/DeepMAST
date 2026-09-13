# BC SNI smoke test summary

This is a mechanism smoke test only; it is not repair-quality or replicate evidence.

## Collection invariants

| Field | Before | After |
| --- | ---: | ---: |
| UUID | `a208e916-bd32-405a-9eee-de4cd82b2a3b` | `a208e916-bd32-405a-9eee-de4cd82b2a3b` |
| Name | `deep_interpreter_bc_cfd96ddb_all` | `deep_interpreter_bc_cfd96ddb_all` |
| Documents | 100 | 100 |
| Chunks | 1553 | 1553 |

Selected model: `ollama` / `qwen3.5:122b`.

## SNI rebuild attempts

| Attempt | HTTP | Result | Elapsed seconds | UTC start | UTC end |
| --- | ---: | --- | ---: | --- | --- |
| Initial stale-container attempt | 500 | `Internal Server Error` | 0.7203994589999638 | 2026-08-09T08:33:52.406519Z | 2026-08-09T08:33:53.127121Z |
| After environment reload | 200 | `rebuilt`; 100 source pages, 10 concept pages, 110 total pages | 506.383493458 | 2026-08-09T08:45:46.656561Z | 2026-08-09T08:54:13.039147Z |

## Paired agentic search results

| Pair | Query | SNI off | SNI on |
| --- | --- | --- | --- |
| 01 | What evidence supports EGF-ERBB2 signaling in the breast cancer tumor microenvironment? | HTTP 200; wiki `disabled`; promotion `disabled`; retrieved 5; relevant 3; selected wiki pages 0; wiki refs 0; rewrites 0 | HTTP 200; wiki `selected`; promotion `promoted`; retrieved 13; relevant 4; selected wiki pages 3; wiki refs 8; promoted docs 8; rewrites 0 |
| 02 | Which ligand-receptor interactions are implicated in breast cancer cell-cell communication? | HTTP 200; wiki `disabled`; promotion `disabled`; retrieved 2; relevant 2; selected wiki pages 0; wiki refs 0; rewrites 1 | HTTP 200; wiki `selected`; promotion `promoted`; retrieved 9; relevant 4; selected wiki pages 3; wiki refs 8; promoted docs 8; rewrites 0 |
| 03 | What stromal or vascular signaling programs are reported in the breast cancer microenvironment? | HTTP 200; wiki `disabled`; promotion `disabled`; retrieved 1; relevant 1; selected wiki pages 0; wiki refs 0; rewrites 0 | HTTP 200; wiki `selected`; promotion `promoted`; retrieved 13; relevant 8; selected wiki pages 3; wiki refs 8; promoted docs 8; rewrites 1 |
