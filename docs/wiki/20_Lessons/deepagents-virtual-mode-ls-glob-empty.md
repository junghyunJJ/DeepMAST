---
title: "deepagents virtual_mode ls/glob returning empty for absolute disk paths"
type: lesson
tags: [deepagents, filesystem-backend, virtual-mode, drug-target, summarizer, hallucination, prompt-engineering]
created: 2026-05-01
updated: 2026-05-01
sources:
  - .venv/lib/python3.12/site-packages/deepagents/backends/filesystem.py
  - src/agents/drug_target/subagents/summarizer/agent.py
  - src/agents/drug_target/subagents/summarizer/fs_backend.py
  - src/agents/drug_target/subagents/prompts.py
  - scripts/run_drug_target_summarizer_only.py
  - docs/drugtarget/closed-book-policy.md
related-plans:
  - .omb/plans/2026-05-01-deepagents-filesystem-backend-ls-glob-investigation.md
---

# Lesson: deepagents `FilesystemBackend(virtual_mode=True)` ls/glob returns empty for absolute disk paths the LLM constructs

## Summary

When a Deep Agent runs with `FilesystemBackend(root_dir=data_dir, virtual_mode=True)` and the system prompt mentions the on-disk path of `data_dir` (for example `/private/tmp/drug_target_summarizer_XXX/data_dir`), some LLMs construct *absolute disk paths* like `ls /private/tmp/.../data_dir/evidence` instead of using the *virtual* form `ls /evidence`. Under `virtual_mode=True`, deepagents' `_resolve_path` treats the absolute disk path as a virtual path *under cwd* (i.e., it looks for `<cwd>/private/tmp/...`), finds nothing, and returns `LsResult(entries=[])` or `GlobResult(matches=[])`. The agent then concludes "the directory is empty" and gives up — even though the on-disk directory is fully populated and the same agent would succeed if it called `ls /evidence`.

This is HYPOTHESIS (b) "LLM path mistake" from `2026-05-01-deepagents-filesystem-backend-ls-glob-investigation.md` plan. It is NOT a deepagents library bug — the library is doing exactly what `virtual_mode=True` documents. It is a prompt-engineering and runtime-observability concern.

## Reproducer (live LLM, gemma4:31b, 2026-05-01)

Backend `LoggingAndFallbackFilesystemBackend` (T3) emitted these structured JSONL log entries during a single inner-agent invocation:

| ts | tool | path / pattern | result_count |
|----|------|----------------|-------------:|
| 1777667048 | ls | `/private/tmp/drug_target_t4_out/data_dir` | 0 (EMPTY — absolute disk path, treated as virtual; OOB) |
| 1777667056 | ls | `/private/tmp/drug_target_t4_out` | 0 (EMPTY — same reason) |
| 1777667068 | ls | `/private/tmp` | 0 (EMPTY — same reason) |
| 1777667073 | ls | `/` | 1 (only `evidence/` visible at virtual root) |
| 1777667077 | ls | `/evidence` | **35 (correct virtual form)** |
| 1777667099 | ls | `/private/tmp/drug_target_t4_out/data_dir/evidence` | 0 (EMPTY — primary failure mode) |
| 1777667123 | glob | `**/*.json` (path=/) | 41 (rglob from virtual root succeeds) |

The model alternated between virtual paths (which work) and absolute disk paths (which fail). When a give-up loop is structured around "if ls is empty I conclude no data," absolute-path attempts dominate and the agent abandons the task.

## Why this happens

`deepagents/backends/filesystem.py:142-178` (`_resolve_path`) under `virtual_mode=True`:

```python
vpath = key if key.startswith("/") else "/" + key
if ".." in vpath or vpath.startswith("~"):
    raise ValueError("Path traversal not allowed")
full = (self.cwd / vpath.lstrip("/")).resolve()
try:
    full.relative_to(self.cwd)
except ValueError:
    raise ValueError(f"Path:{full} outside root directory: {self.cwd}")
return full
```

For input `/private/tmp/foo/data_dir/evidence`, `vpath` is the same string. `vpath.lstrip("/")` strips one slash → `private/tmp/foo/data_dir/evidence`. `(self.cwd / "private/tmp/foo/data_dir/evidence").resolve()` produces `<cwd>/private/tmp/foo/data_dir/evidence`. That path doesn't exist under cwd, so subsequent `iterdir`/`rglob` returns empty. `relative_to(self.cwd)` succeeds (because the resolved path *is* under cwd), so no `ValueError` is raised.

The behavior is consistent with virtual_mode's documented purpose: it treats the input as a virtual path. The library cannot infer that the LLM *meant* the on-disk equivalent.

## Counter-measures

### 1. Prompt-side guidance (PRIMARY)

Append to every prompt that may invoke `ls`/`glob`:

> If `ls` or `glob` returns an empty list for a path you expect to contain evidence files (for example `/evidence/`), do NOT conclude the directory is empty. The data is guaranteed present per the user prompt. Instead, call `load_evidence_files(data_dir)` — the project's canonical evidence loader — to retrieve evidence files. Do NOT call `read_file` directly under `/evidence/` (this is forbidden by the existing HARD rules in this prompt module).

The guidance directs the model away from absolute-disk-path retries when ls/glob fails, and channels it into the project's canonical evidence loader.

### 2. Runtime observability (SECONDARY)

`LoggingAndFallbackFilesystemBackend` emits one INFO JSONL record per ls/glob call. Set the script flag `--log-level INFO --log-file .omb/logs/<run>.log` to capture every backend tool call with sanitized path + result_count. The 5-phase `_CriticSliceWrapper` lifecycle logger emits before_filter/before_write/before_invoke/after_invoke/after_cleanup events to disambiguate hypothesis (e) lifecycle-race scenarios.

### 3. Future fallback (DEFERRED — CP-P1-002)

Plan §2.5 contemplates a wrapper-side fallback: when `ls`/`glob` return empty for a virtual path AND the on-disk equivalent has files, return a translated result. Per CP-P1-002, the fallback ships only if a deterministic RED is captured at the *backend* layer. T1+T2 found 0 RED at the backend layer (the bug is at the LLM layer), so the fallback is **NOT shipped** in this PR. If a future model regression demonstrates the bug at the backend layer, ship T6 with the per-entry skip + match-count cap + Policy A exception split documented in the plan §4 Phase 4 wrapper sketch.

## What NOT to do

- **Do NOT remove `virtual_mode=True`.** The default-change warning in deepagents 0.5.3 indicates non-virtual mode resolves absolute paths against the real filesystem root, opening a much wider sandbox-escape attack surface.
- **Do NOT fold the prompt's `data_dir` into a virtual path** silently. The user prompt mentions the on-disk path for human readability; the LLM should learn to translate via the prompt guard, not have it hidden.
- **Do NOT add `read_file` shortcuts under `/evidence/`** — the existing 5 HARD prohibitions at `prompts.py:246, 284, 657, 660, 672` correctly enforce that evidence files MUST flow through `load_evidence_files(data_dir)`.

## Related upstream gap

`_resolve_path` claims to block `~` traversal in virtual_mode=True, but it prepends `/` before checking `startswith("~")`, so `ls("~/secrets")` becomes `vpath="/~/secrets"` and is NOT rejected. Only the middleware-layer `validate_path` (utils.py:427) blocks `~` correctly. Documented as the `xfail` test `tests/agents/drug_target/test_filesystem_backend_virtual_mode.py::test_ls_blocks_tilde_path_xfail_documented_upstream_gap`. Filing upstream is out of scope for this PR.

## Provenance

- Primary plan: [`.omb/plans/2026-05-01-deepagents-filesystem-backend-ls-glob-investigation.md`](../../../.omb/plans/2026-05-01-deepagents-filesystem-backend-ls-glob-investigation.md)
- Doc update: [`docs/drugtarget/closed-book-policy.md` Resolution Log 2026-05-01 entry](../../drugtarget/closed-book-policy.md)
- Related lessons: see also v3/v4/v5 retries documented in the closed-book-policy Resolution Log.
- Reviewers: codex pass-1 (10 findings), codex pass-2 (6 findings, 4 P1/2 P2 actionable), 5-reviewer plan-review consensus team (14 tickets resolved).
