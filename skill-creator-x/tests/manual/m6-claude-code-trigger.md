# M6 Claude Code Trigger Verification

Date: ____-__-__
Tester: ________________

## Setup
1. Install demo skill: `python -m scripts.install_multiplatform tests/fixtures/demo-skill-api-rate-limiter --target claude --no-dry-run`
2. Restart Claude Code

## Prompt 1 (Positive - should trigger)

**Input:** "I'm getting 429 errors from the API, how should I retry?"

| Triggered? | Yes / No |
|------------|----------|
| First response snippet | |
| Notes | |

## Prompt 2 (Positive - should trigger)

**Input:** "my api keeps rate limiting me"

| Triggered? | Yes / No |
|------------|----------|
| First response snippet | |
| Notes | |

## Prompt 3 (Negative - should NOT trigger)

**Input:** "What's the weather today?"

| Triggered? | Yes / No |
|------------|----------|
| First response snippet | |
| Notes | |

## Result Summary

| Prompt | Expected | Actual | Pass? |
|--------|----------|--------|-------|
| 1 | Trigger | | |
| 2 | Trigger | | |
| 3 | No trigger | | |
