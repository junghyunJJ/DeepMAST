# Retry Strategies for Rate-Limited APIs

## Exponential Backoff

Wait time doubles with each retry: 1s, 2s, 4s, 8s, 16s. Best for most APIs where rate limits reset on a fixed window. Simple to implement and widely supported.

**Formula:** `wait = base * (2 ^ attempt)`

**When to use:** Default choice for single-client scenarios.

## Token Bucket

Maintain a bucket of N tokens; each request consumes one. Tokens refill at a fixed rate. Allows bursts up to bucket size while maintaining a sustainable average rate.

**Parameters:** bucket_size (max burst), refill_rate (tokens/second)

**When to use:** Sustained high-throughput with occasional bursts.

## Jittered Retry

Add random delay on top of exponential backoff to prevent thundering herd. Essential when multiple clients retry simultaneously against the same endpoint.

**Formula:** `wait = base * (2 ^ attempt) + random(0, base)`

**When to use:** Distributed systems with many concurrent clients.
