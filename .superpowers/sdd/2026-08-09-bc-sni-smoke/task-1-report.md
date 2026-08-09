# Task 1 Report: BC SNI Smoke Preflight

## Scope
- Worktree: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/bc-sni-smoke`
- Brief: `.superpowers/sdd/2026-08-09-bc-sni-smoke/task-1-brief.md`
- Non-destructive preflight only.
- Did not call `llm-wiki/rebuild` or `agentic-search` endpoints.

## Commands / Tests
- `curl -fsS http://localhost:8888/health | jq .`
  - Result: `{ "status": "ok" }`
- `curl -fsS http://localhost:8888/collections/a208e916-bd32-405a-9eee-de4cd82b2a3b | jq . > res/deep_interpreter/bc/bc/sni_smoke_test/collection_before.json`
  - Saved the starting BC collection state.
- `curl -fsS http://localhost:8888/openapi.json | jq '{paths: {"/collections/{collection_id}/llm-wiki/rebuild": .paths["/collections/{collection_id}/llm-wiki/rebuild"], "/collections/{collection_id}/agentic-search": .paths["/collections/{collection_id}/agentic-search"]}, components: {schemas: {AgenticSearchQuery: .components.schemas.AgenticSearchQuery, AgenticSearchResult: .components.schemas.AgenticSearchResult, LLMWikiRebuildRequest: .components.schemas.LLMWikiRebuildRequest, LLMWikiRebuildResponse: .components.schemas.LLMWikiRebuildResponse}}}' > res/deep_interpreter/bc/bc/sni_smoke_test/api_contract.json`
  - Saved the relevant OpenAPI path operations and component schemas.
- `jq -e '.uuid == "a208e916-bd32-405a-9eee-de4cd82b2a3b" and .document_count == 100 and .chunk_count == 1553' res/deep_interpreter/bc/bc/sni_smoke_test/collection_before.json`
  - Result: `true`
- `jq -e '.components.schemas.AgenticSearchQuery.properties.use_wiki_context.type == "boolean"' res/deep_interpreter/bc/bc/sni_smoke_test/api_contract.json`
  - Result: `true`

## Files Changed
- `res/deep_interpreter/bc/bc/sni_smoke_test/collection_before.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/api_contract.json`
- `.superpowers/sdd/2026-08-09-bc-sni-smoke/task-1-report.md`

## Commit
- Commit SHA: pending until commit creation; final SHA is reported in the parent response.

## Self-Review
- Confirmed localhost health returned `status: ok` before saving artifacts.
- Confirmed the saved collection invariant matches UUID `a208e916-bd32-405a-9eee-de4cd82b2a3b`, `document_count` `100`, and `chunk_count` `1553`.
- Confirmed `use_wiki_context` is present in the live OpenAPI `AgenticSearchQuery` schema as a boolean property.
- Used only read-only `GET /health`, `GET /collections/{id}`, and `GET /openapi.json` requests.
- Did not edit production code or `.omx/plans/`.

## Concerns
- The artifact paths are ignored by repository rules, so they were force-added explicitly by path.
