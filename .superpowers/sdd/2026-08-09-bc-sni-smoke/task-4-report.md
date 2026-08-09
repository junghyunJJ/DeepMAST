## Task 4 Report: Paired SNI-on/off agentic searches

Status: PASS

Collection: `a208e916-bd32-405a-9eee-de4cd82b2a3b`
Endpoint: `POST http://localhost:8888/collections/a208e916-bd32-405a-9eee-de4cd82b2a3b/agentic-search`

## Requests

Each query pair used identical request fields except `use_wiki_context`.

Shared fields:
- `search_type`: `hybrid`
- `search_limit`: `5`
- `max_rewrites`: `3`
- `llm_provider`: `ollama`
- `llm_model`: `qwen3.5:122b`

Questions:
1. `What evidence supports EGF-ERBB2 signaling in the breast cancer tumor microenvironment?`
2. `Which ligand-receptor interactions are implicated in breast cancer cell-cell communication?`
3. `What stromal or vascular signaling programs are reported in the breast cancer microenvironment?`

## Exact Test Assertions

For every `*_sni_on.json` artifact:
- `curl_returncode == 0`
- `http_status == 200`
- `body.error is None`
- `len(body.relevant_documents) >= 1`
- `body.wiki_context_status == "selected"`

For every `*_sni_off.json` artifact:
- `curl_returncode == 0`
- `http_status == 200`
- `body.error is None`
- `len(body.relevant_documents) >= 1`
- `body.wiki_context_status == "disabled"`

For every query pair:
- Request objects are identical after removing `use_wiki_context`.
- SNI-on request has `use_wiki_context is True`.
- SNI-off request has `use_wiki_context is False`.

## Results

| Artifact | HTTP | Error | Relevant documents | Wiki context status | Result |
| --- | ---: | --- | ---: | --- | --- |
| `query_01_sni_on.json` | 200 | `None` | 4 | `selected` | PASS |
| `query_01_sni_off.json` | 200 | `None` | 3 | `disabled` | PASS |
| `query_02_sni_on.json` | 200 | `None` | 4 | `selected` | PASS |
| `query_02_sni_off.json` | 200 | `None` | 2 | `disabled` | PASS |
| `query_03_sni_on.json` | 200 | `None` | 8 | `selected` | PASS |
| `query_03_sni_off.json` | 200 | `None` | 1 | `disabled` | PASS |

## Files Changed

- `res/deep_interpreter/bc/bc/sni_smoke_test/query_01_sni_on.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/query_01_sni_off.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/query_02_sni_on.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/query_02_sni_off.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/query_03_sni_on.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/query_03_sni_off.json`
- `.superpowers/sdd/2026-08-09-bc-sni-smoke/task-4-report.md`

## Verification Evidence

Validation command:

```bash
python - <<'PY'
import json
from pathlib import Path
base = Path('res/deep_interpreter/bc/bc/sni_smoke_test')
failures = []
summary = []
for i in range(1, 4):
    pair = []
    for suffix, expected_status in [('sni_on', 'selected'), ('sni_off', 'disabled')]:
        path = base / f'query_{i:02d}_{suffix}.json'
        data = json.loads(path.read_text())
        body = data.get('body') or {}
        docs = body.get('relevant_documents') or []
        checks = {
            'curl_returncode_is_0': data.get('curl_returncode') == 0,
            'http_status_is_200': data.get('http_status') == 200,
            'no_error': body.get('error') is None,
            'has_relevant_documents': len(docs) >= 1,
            'wiki_context_status': body.get('wiki_context_status') == expected_status,
        }
        bad = [k for k, v in checks.items() if not v]
        if bad:
            failures.append((str(path), bad))
        summary.append((path.name, data.get('http_status'), body.get('error'), len(docs), body.get('wiki_context_status'), checks))
        pair.append(data['request'])
    on_req, off_req = pair
    on_cmp = dict(on_req); off_cmp = dict(off_req)
    on_cmp.pop('use_wiki_context', None); off_cmp.pop('use_wiki_context', None)
    if on_cmp != off_cmp or on_req.get('use_wiki_context') is not True or off_req.get('use_wiki_context') is not False:
        failures.append((f'query_{i:02d}_request_pair', ['request_fields_not_identical_except_use_wiki_context']))

for name, http, err, docs, wiki, checks in summary:
    print(f'{name}: http={http}, error={err!r}, relevant_documents={docs}, wiki_context_status={wiki!r}')
    print('  ' + ', '.join(f'{k}={v}' for k, v in checks.items()))
if failures:
    print('FAILURES:')
    for path, bad in failures:
        print(f'  {path}: {bad}')
    raise SystemExit(1)
print('ALL_ASSERTIONS_PASSED')
PY
```

Validation output:

```text
query_01_sni_on.json: http=200, error=None, relevant_documents=4, wiki_context_status='selected'
  curl_returncode_is_0=True, http_status_is_200=True, no_error=True, has_relevant_documents=True, wiki_context_status=True
query_01_sni_off.json: http=200, error=None, relevant_documents=3, wiki_context_status='disabled'
  curl_returncode_is_0=True, http_status_is_200=True, no_error=True, has_relevant_documents=True, wiki_context_status=True
query_02_sni_on.json: http=200, error=None, relevant_documents=4, wiki_context_status='selected'
  curl_returncode_is_0=True, http_status_is_200=True, no_error=True, has_relevant_documents=True, wiki_context_status=True
query_02_sni_off.json: http=200, error=None, relevant_documents=2, wiki_context_status='disabled'
  curl_returncode_is_0=True, http_status_is_200=True, no_error=True, has_relevant_documents=True, wiki_context_status=True
query_03_sni_on.json: http=200, error=None, relevant_documents=8, wiki_context_status='selected'
  curl_returncode_is_0=True, http_status_is_200=True, no_error=True, has_relevant_documents=True, wiki_context_status=True
query_03_sni_off.json: http=200, error=None, relevant_documents=1, wiki_context_status='disabled'
  curl_returncode_is_0=True, http_status_is_200=True, no_error=True, has_relevant_documents=True, wiki_context_status=True
ALL_ASSERTIONS_PASSED
```

## Commit

Commit SHA: pending

## Self-review

- Confirmed no SNI rebuild, fallback chunk search, ingest/delete, production code change, or altered-input retry was performed.
- Confirmed calls were run serially.
- Confirmed every raw artifact includes `url`, exact `request`, timing, `curl_returncode`, `http_status`, headers, parsed `body`, `raw_body`, and `stderr`.
- Confirmed unrelated modified file `.superpowers/sdd/2026-08-09-bc-sni-smoke/task-1-report.md` was not part of Task 4 and must not be staged.
