---
name: valid-skill-full
description: Summarize CSV datasets and produce descriptive statistics. Use when the user uploads a `.csv`, asks for column stats, or requests a data profile.
license: MIT
compatibility: Requires Python 3.10+ with pandas available in the runtime.
metadata:
  author: skill-creator-x test fixtures
  version: 0.1.0
---

# Valid Skill Full

## Instructions
1. Load the CSV with pandas.
2. Run `python scripts/runner.py PATH` for the descriptive statistics block (replace PATH with your CSV path).
3. See `references/notes.md` for edge-case handling.

## Examples
Example 1: For `sales.csv`, emit mean and median per numeric column.

## Common Issues
### Missing file
If the CSV cannot be opened, ask the user for the correct path.
