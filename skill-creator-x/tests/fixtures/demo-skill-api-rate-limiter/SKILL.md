---
name: api-rate-limiter
description: Guide for handling API rate limits, 429 errors, and request throttling. Use when users encounter rate limiting issues, need retry strategies, or want to implement backoff logic for API calls. Also use when users mention "too many requests", "API throttling", or need help with request pacing.
---

# API Rate Limiter

Handle API rate limits gracefully with iterative retry strategies.

## When to Use

- You hit 429 (Too Many Requests) errors
- An API is throttling your requests
- You need to implement backoff/retry logic

## Workflow (Pattern 3: Iterative Refinement)

### Step 1: Diagnose the Rate Limit

Run the diagnostic script to check current rate limit status:

```bash
python scripts/check_rate_limit.py --url <api-endpoint>
```

### Step 2: Choose a Retry Strategy

Read `references/retry-strategies.md` for the three main approaches:
- **Exponential Backoff** — best for most APIs
- **Token Bucket** — best for sustained high-throughput
- **Jittered Retry** — best for distributed systems

### Step 3: Implement and Validate

1. Apply the chosen strategy to your API calls
2. Re-run the diagnostic to confirm rate limits are respected
3. If still hitting limits, try a more conservative strategy or reduce batch size

## Examples

**Example 1: Simple retry with exponential backoff**

```python
import time

def call_with_backoff(fn, max_retries=5):
    for attempt in range(max_retries):
        try:
            return fn()
        except RateLimitError:
            wait = 2 ** attempt
            time.sleep(wait)
    raise Exception("Max retries exceeded")
```

**Example 2: Adding jitter**

```python
import random, time

def call_with_jitter(fn, max_retries=5):
    for attempt in range(max_retries):
        try:
            return fn()
        except RateLimitError:
            wait = (2 ** attempt) + random.uniform(0, 1)
            time.sleep(wait)
    raise Exception("Max retries exceeded")
```

## Common Issues

### Still Getting 429 After Retries
If retries don't help:
1. Check your API plan's rate limit quota
2. Reduce concurrent request count
3. Implement request queuing with a token bucket

### Inconsistent Rate Limit Headers
If the API returns varying rate limit headers:
- **Cause:** Load balancer distributing across servers with separate counters
- **Solution:** Use the most conservative limit from any response
- **Prevention:** Cache rate limit headers and use the minimum value
