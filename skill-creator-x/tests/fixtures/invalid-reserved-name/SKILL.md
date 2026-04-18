---
name: claude-helper
description: Demonstrate the reserved word violation. Use when a skill author accidentally includes the token `claude` or `anthropic` in the name field.
---

# Invalid — Reserved Name

## Instructions
1. This fixture intentionally violates FM-009.

## Examples
Example 1: The name "claude-helper" must be rejected by validate_strict.

## Common Issues
### Rename required
Pick a name without `claude` or `anthropic`.
