# Task 9 Report: Split Shared RAG Lane From BC Inference

## Changes

- `scripts/sgcp_rag_sni_ablation.compose.yml`: all four SGCP RAG API services now bind `AGENT_LLM_BASE_URL` and `OLLAMA_BASE_URL` to `http://host.docker.internal:4000`.
- `scripts/sni_ablation_api_stack.py`: topology smoke reports `backend_port: 4000` for every SGCP API lane and serializes wrapped connection errors.
- `scripts/run_bc_sni_repair_ablation.py`: replacement manifest validation requires `rag_backend_port: 4000`, validates the new exact 10-pair direct schedule, persists `rag_backend_port` in each condition run manifest, and makes `--all` globally serial.
- `tests/test_sni_ablation_runner.py`: focused tests cover shared RAG topology, replacement manifest validation/rejection, serial scheduling, condition manifest persistence, and smoke error reporting.
- `res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json`: new replacement manifest; historical manifest and run roots were not edited.

## RED Evidence

Command:

```bash
pytest tests/test_sni_ablation_runner.py
```

Result before production changes:

```text
14 failed, 17 passed in 0.46s
```

Expected failures included:

```text
assert {4000, 5000, 6000, 7000} == {4000}
assert text.count("http://host.docker.internal:4000") == 8
FileNotFoundError: experiment_manifest_rag4000.json
```

Additional RED for the smoke error serializer found during live smoke:

```bash
pytest tests/test_sni_ablation_runner.py::test_smoke_serializes_connection_errors_in_report
```

```text
TypeError: Object of type ConnectionRefusedError is not JSON serializable
```

## GREEN Evidence

Focused tests:

```bash
pytest tests/test_sni_ablation_runner.py
```

```text
32 passed in 0.19s
```

Manifest dry smoke:

```bash
python scripts/run_bc_sni_repair_ablation.py --smoke --output-root /tmp/bc-sni-task9-smoke/pairs --manifest res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/bc_interpreter
```

```text
"ok": true
schedule: 10 one-pair batches in pair order 01 through 10
direct backend/API pairs: 5000/8882, 6000/8883, 7000/8884
rag_backend_port: 4000 on every pair
```

Ruff:

```bash
ruff check scripts/sni_ablation_api_stack.py scripts/run_bc_sni_repair_ablation.py tests/test_sni_ablation_runner.py
```

```text
All checks passed!
```

Pyright:

```bash
pyright scripts/sni_ablation_api_stack.py scripts/run_bc_sni_repair_ablation.py
```

```text
0 errors, 0 warnings, 0 informations
```

`pyright` on the changed test file was attempted, but this environment cannot resolve the `pytest` import:

```text
tests/test_sni_ablation_runner.py:8:8 - error: Import "pytest" could not be resolved
```

Whitespace:

```bash
git diff --check
```

```text
no output
```

## Live Topology Smoke

Command:

```bash
python scripts/sni_ablation_api_stack.py smoke --collection-id a208e916-bd32-405a-9eee-de4cd82b2a3b --question 'Which SNI behavior is active?' --report /tmp/bc-sni-task9-topology-smoke.json --expected-collection '{"uuid":"a208e916-bd32-405a-9eee-de4cd82b2a3b","name":"deep_interpreter_bc_cfd96ddb_all","metadata":{"type":"literature_rag","created_by":"deep_interpreter"},"document_count":100,"chunk_count":1553}'
```

Result: command exited `1` because SGCP API endpoints on `8881-8884` refused connections in this local session. The report was still written successfully and showed:

```text
backend_ports=[4000, 4000, 4000, 4000]
api_ports=[8881, 8882, 8883, 8884]
services=['sgcp-sni-api-4000', 'sgcp-sni-api-5000', 'sgcp-sni-api-6000', 'sgcp-sni-api-7000']
model qwen3.5:122b present on backend 4000
```

Full pass/fail live collection and agentic checks require running SGCP API containers, which were not reachable here.

## Notes

- Existing collection UUID `a208e916-bd32-405a-9eee-de4cd82b2a3b`, document/chunk counts, source dataset, and SNI semantics remain unchanged.
- Direct Deep Interpreter inference is pinned to only `5000/8882`, `6000/8883`, and `7000/8884`.
- The replacement manifest allocates pairs `4/3/3` across direct backend ports and has five SNI-first plus five no-SNI-first pairs.

## Review Fix

- Corrected the `--all` CLI help text from the old "max four backend lanes" description to "globally serial."
- Verification: `pytest tests/test_sni_ablation_runner.py::test_bc_runner_all_schedules_one_pair_batches_in_manifest_order tests/test_sni_ablation_runner.py::test_bc_runner_smoke_is_dry_manifest_preflight` passed; `ruff check scripts/run_bc_sni_repair_ablation.py` passed; `git diff --check` passed.
