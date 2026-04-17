---
name: valid-skill-minimal
description: Parse timestamps from log files. Use when the user asks to extract or analyze timestamps, convert log formats, or find events in a log window.
---

# Valid Skill Minimal

## Instructions
1. Read the provided log file.
2. Parse each line to extract the timestamp.
3. Report the earliest and latest timestamps.

## Examples
Example 1: If the log says `2026-01-01T10:00:00Z INFO ready`, return that timestamp.

## Common Issues
### Malformed timestamp
If a line has no parseable timestamp, skip it and record the line number.
