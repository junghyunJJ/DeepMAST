# Interpreter Fresh Save Recovery Design

## Goal

Make the existing bounded interpreter save recovery escape a drifted Part
conversation before its final attempt, without adding retries, auto-saving chat
content, changing the interpreter graph, or weakening output/guardrail checks.

After the fix, prove Part 3 can save in a production-shaped smoke, then run one
fresh canonical pair 05 globally serial from no-SNI to SNI.

## Failure Evidence

The second fresh pair attempt produced Part 1 and Part 2, then failed Part 3
before Claim-RAG or Report Guardrail execution:

- `part3_final.md` did not exist;
- the runner made three total interpreter invocations;
- both save retries reused the complete accumulated conversation;
- the final assistant response summarized a CSV-like interaction dataset
  instead of writing the assigned Part 3 report;
- no `write_file` failure, filesystem error, traceback, or Ollama connection
  failure occurred; and
- port 6000 still served `qwen3.5:122b` after failure.

The filesystem path and write tool are functional because the same execution
saved Part 1 and Part 2 in the same condition directory. The failing boundary
is retry context: once the model drifts, every current retry carries the drifted
messages and tool results forward.

## Chosen Design

Keep `MAX_INTERPRETER_INVOKE_ATTEMPTS = 3` and use two different recovery
shapes:

1. Initial invocation: unchanged.
2. First save retry: unchanged continuation with prior messages and tool
   results, allowing a nearly complete report to be saved cheaply.
3. Final save retry: invoke the same interpreter graph with a fresh one-message
   context containing the complete Part-specific assignment and mandatory
   `write_file` contract.

The final fresh message explicitly states that no prior conversation or tool
results are attached and requires `load_analysis_data` before writing. For Part
3 it retains the selected-gene, selected-LR-pair, therapeutic-boundary, and
output-template requirements already present in the base interpreter prompt.

The compiled graph, tools, system prompt, data directory, RAG binding, model,
and guardrail middleware remain unchanged. Only the message payload of the last
existing retry changes.

## Audit Contract

Every save-retry start event and retry-history entry records:

```json
{"fresh_context": false}
```

for the first retry and:

```json
{"fresh_context": true}
```

for the final retry. Existing retry counts, missing-output fields, output
status, exception metadata, and terminal return code remain unchanged.

## Safety

- A report is complete only when the expected `partN_final.md` file exists.
- Chat content is never copied or inferred into a report file by Python.
- The model must still use the `write_file` tool.
- The maximum remains three total invocations.
- A missing file after the fresh final retry returns nonzero and stays
  fail-closed.
- Report Guardrail behavior is unchanged and runs only after a real report
  file exists.
- No new dependency, agent, middleware, graph, or fallback report generator is
  introduced.

## Verification

Verification proceeds in increasing cost:

1. Unit tests prove the first retry preserves history and the final retry uses
   exactly one fresh user message for Parts 1, 2, and 3.
2. Existing save-success, save-exhaustion, guardrail-failure, and CLI tests
   remain green.
3. A disposable production-shaped Part 3 smoke uses port 6000,
   `qwen3.5:122b`, condition API 8883, fixed collection UUID
   `a208e916-bd32-405a-9eee-de4cd82b2a3b`, and wiki context off. It must save
   `part3_final.md`; the scoped Part 3 guardrail must finish with zero hard
   errors and preserved headings.
4. One fresh canonical pair 05 runs no-SNI then SNI without an external
   timeout. SNI starts only if no-SNI passes.

## Out of Scope

- Increasing save retries beyond three.
- Automatically saving the last assistant message.
- Parsing Markdown from generic chat output.
- Redesigning Part 3 scientific content, input data, RAG, SNI, or the Report
  Guardrail.
- Changing the Part 3 selected genes or selected LR pairs.
- Reusing partially generated condition directories in the final comparison.
- Replicated experiments before one canonical pair completes.

