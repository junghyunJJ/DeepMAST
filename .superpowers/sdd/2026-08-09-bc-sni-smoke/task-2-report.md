# Task 2 Report: BC SNI Rebuild Smoke

## Status
BLOCKED: the one authorized synchronous rebuild request returned HTTP 500.

## Scope
- Worktree: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/bc-sni-smoke`
- Brief: `.superpowers/sdd/2026-08-09-bc-sni-smoke/task-2-brief.md`
- Collection: `a208e916-bd32-405a-9eee-de4cd82b2a3b`
- Endpoint: `POST /collections/{id}/llm-wiki/rebuild`
- Request body: `{"llm_provider":"ollama","llm_model":"qwen3.5:122b"}`
- Did not call paper ingestion, deletion, or `agentic-search` endpoints.
- Did not retry with another model or collection.

## Command
```bash
python3 - <<'PY'
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

root = Path('/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/bc-sni-smoke')
out_dir = root / 'res/deep_interpreter/bc/bc/sni_smoke_test'
request_path = out_dir / 'rebuild_request.json'
response_path = out_dir / 'rebuild_response.json'
timing_path = out_dir / 'rebuild_timing.json'
headers_path = out_dir / '.rebuild_headers.tmp'
body_path = out_dir / '.rebuild_body.tmp'
url = 'http://localhost:8888/collections/a208e916-bd32-405a-9eee-de4cd82b2a3b/llm-wiki/rebuild'

start_utc = datetime.now(timezone.utc)
start = time.monotonic()
proc = subprocess.run(
    [
        'curl', '-sS', '-X', 'POST', url,
        '-H', 'Content-Type: application/json',
        '--data-binary', '@' + str(request_path),
        '-D', str(headers_path),
        '-o', str(body_path),
        '-w', '%{http_code}',
    ],
    cwd=root,
    text=True,
    capture_output=True,
)
end = time.monotonic()
end_utc = datetime.now(timezone.utc)

raw_body = body_path.read_text(encoding='utf-8', errors='replace') if body_path.exists() else ''
raw_headers = headers_path.read_text(encoding='utf-8', errors='replace') if headers_path.exists() else ''
try:
    parsed_body = json.loads(raw_body) if raw_body else None
except json.JSONDecodeError:
    parsed_body = None

response = {
    'http_status': int(proc.stdout) if proc.stdout.isdigit() else None,
    'curl_returncode': proc.returncode,
    'stderr': proc.stderr,
    'headers': raw_headers,
    'body': parsed_body,
    'raw_body': raw_body,
}
response_path.write_text(json.dumps(response, indent=2, sort_keys=True) + '\n', encoding='utf-8')

timing = {
    'utc_start': start_utc.isoformat().replace('+00:00', 'Z'),
    'utc_end': end_utc.isoformat().replace('+00:00', 'Z'),
    'elapsed_seconds': end - start,
    'clock': 'time.monotonic',
    'url': url,
}
timing_path.write_text(json.dumps(timing, indent=2, sort_keys=True) + '\n', encoding='utf-8')

for path in (headers_path, body_path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass

print(json.dumps({'http_status': response['http_status'], 'curl_returncode': proc.returncode, 'elapsed_seconds': timing['elapsed_seconds']}, indent=2))
PY
```

## Timing
- UTC start: `2026-08-09T08:33:52.406519Z`
- UTC end: `2026-08-09T08:33:53.127121Z`
- Monotonic elapsed seconds: `0.7203994589999638`

## Response
- HTTP status: `500`
- curl return code: `0`
- Response headers: `HTTP/1.1 500 Internal Server Error`
- Response body: `Internal Server Error`

## Verification
- `jq . res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_response.json`
  - Result: response evidence is readable JSON and records `http_status: 500`.
- `jq . res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_timing.json`
  - Result: timing evidence is readable JSON and records positive `elapsed_seconds: 0.7203994589999638`.
- Success criterion failed because the response was not successful.

## Files Changed
- `res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_request.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_response.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_timing.json`
- `.superpowers/sdd/2026-08-09-bc-sni-smoke/task-2-report.md`

## Commit
- Commit SHA: reported in the final Task 2 handoff; a tracked file cannot embed
  the hash of the same commit without changing that hash.

## Self-Review
- Confirmed the request body exactly matches the brief.
- Confirmed only one synchronous rebuild request was sent.
- Confirmed no retry was attempted after HTTP 500.
- Confirmed no paper ingestion, deletion, or `agentic-search` endpoint was called.
- Confirmed the failure body, status, UTC timestamps, and monotonic elapsed seconds were preserved.

## Concerns
- The service returned HTTP 500 with a plain-text body: `Internal Server Error`.
- The artifact paths are likely ignored by repository rules, so Task 2 artifacts may need force-add by explicit path.

## Root-Cause Recovery

### Status
RECOVERED: after recreating only the existing Compose `api` service under the
`langconnect_mcp` project with the current `.env`, the same saved request
returned HTTP 200 and rebuilt the SNI pack.

### Container Recovery Commands
- `docker inspect langconnect-api --format '{{range .Config.Env}}{{println .}}{{end}}' | sort | rg '^SNI_LLM_' || true`
  - Before recreate: `SNI_LLM_BASE_URL` and `SNI_LLM_MODEL` were absent.
- `cd /Users/jungj2/Dropbox/Metadata/mcp/sgcp-rag && docker compose -p langconnect_mcp config | sed -n '/SNI_LLM_/p'`
  - Confirmed current `.env` and Compose config resolve the expected SNI values.
- `cd /Users/jungj2/Dropbox/Metadata/mcp/sgcp-rag && docker compose -p langconnect_mcp up -d --no-deps --force-recreate --no-build api`
  - Recreated only `langconnect-api`; no image rebuild and no dependent service recreate.
- `docker inspect langconnect-api --format '{{range .Config.Env}}{{println .}}{{end}}' | sort | rg '^SNI_LLM_(BASE_URL|MODEL|PROVIDER)='`
  - Confirmed:
    - `SNI_LLM_BASE_URL=http://host.docker.internal:4000`
    - `SNI_LLM_MODEL=qwen3.5:122b`
    - `SNI_LLM_PROVIDER=ollama`
- `curl -fsS http://localhost:8888/health | jq .`
  - Result: `{ "status": "ok" }`

### Recovery Request Command
```bash
python3 - <<'PY'
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

root = Path('/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/bc-sni-smoke')
out_dir = root / 'res/deep_interpreter/bc/bc/sni_smoke_test'
request_path = out_dir / 'rebuild_request.json'
response_path = out_dir / 'rebuild_response_after_env_reload.json'
timing_path = out_dir / 'rebuild_timing_after_env_reload.json'
headers_path = out_dir / '.rebuild_after_headers.tmp'
body_path = out_dir / '.rebuild_after_body.tmp'
url = 'http://localhost:8888/collections/a208e916-bd32-405a-9eee-de4cd82b2a3b/llm-wiki/rebuild'

start_utc = datetime.now(timezone.utc)
start = time.monotonic()
proc = subprocess.run(
    [
        'curl', '-sS', '-X', 'POST', url,
        '-H', 'Content-Type: application/json',
        '--data-binary', '@' + str(request_path),
        '-D', str(headers_path),
        '-o', str(body_path),
        '-w', '%{http_code}',
    ],
    cwd=root,
    text=True,
    capture_output=True,
)
end = time.monotonic()
end_utc = datetime.now(timezone.utc)

raw_body = body_path.read_text(encoding='utf-8', errors='replace') if body_path.exists() else ''
raw_headers = headers_path.read_text(encoding='utf-8', errors='replace') if headers_path.exists() else ''
try:
    parsed_body = json.loads(raw_body) if raw_body else None
except json.JSONDecodeError:
    parsed_body = None

response = {
    'http_status': int(proc.stdout) if proc.stdout.isdigit() else None,
    'curl_returncode': proc.returncode,
    'stderr': proc.stderr,
    'headers': raw_headers,
    'body': parsed_body,
    'raw_body': raw_body,
}
response_path.write_text(json.dumps(response, indent=2, sort_keys=True) + '\n', encoding='utf-8')

timing = {
    'utc_start': start_utc.isoformat().replace('+00:00', 'Z'),
    'utc_end': end_utc.isoformat().replace('+00:00', 'Z'),
    'elapsed_seconds': end - start,
    'clock': 'time.monotonic',
    'url': url,
}
timing_path.write_text(json.dumps(timing, indent=2, sort_keys=True) + '\n', encoding='utf-8')

for path in (headers_path, body_path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass

print(json.dumps({'http_status': response['http_status'], 'curl_returncode': proc.returncode, 'elapsed_seconds': timing['elapsed_seconds']}, indent=2))
PY
```

### Recovery Timing
- UTC start: `2026-08-09T08:45:46.656561Z`
- UTC end: `2026-08-09T08:54:13.039147Z`
- Monotonic elapsed seconds: `506.383493458`

### Recovery Response
- HTTP status: `200`
- curl return code: `0`
- Body status: `rebuilt`
- Source pages: `100`
- Concept pages: `10`
- Total pages: `110`
- Chunk count: `1553`
- Pack path: `llm_wiki/collections/a208e916-bd32-405a-9eee-de4cd82b2a3b.json`

### Recovery Verification
- `jq -e '.http_status == 500 and .raw_body == "Internal Server Error"' res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_response.json`
  - Result: original failure remains inspectable.
- `jq -e '.http_status == 200 and .body.status == "rebuilt" and .body.collection_id == "a208e916-bd32-405a-9eee-de4cd82b2a3b" and .body.source_page_count == 100 and .body.concept_page_count == 10 and .body.page_count == 110 and .body.chunk_count == 1553' res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_response_after_env_reload.json`
  - Result: recovery response is successful and matches the expected collection counts.
- `jq -e '.elapsed_seconds > 0 and .utc_start and .utc_end and .clock == "time.monotonic"' res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_timing_after_env_reload.json`
  - Result: recovery timing is positive and uses `time.monotonic`.

### Recovery Files Changed
- `res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_response_after_env_reload.json`
- `res/deep_interpreter/bc/bc/sni_smoke_test/rebuild_timing_after_env_reload.json`
- `.superpowers/sdd/2026-08-09-bc-sni-smoke/task-2-report.md`

### Recovery Self-Review
- Recreated only the Compose `api` service in the existing `langconnect_mcp` project.
- Used `--no-build` and `--no-deps`; did not recreate PostgreSQL, Next.js, data, or model files.
- Verified required SNI environment values before the recovery request.
- Sent the same saved request body exactly once for recovery.
- Preserved the original failed response/timing artifacts and wrote recovery artifacts under the new brief names.
