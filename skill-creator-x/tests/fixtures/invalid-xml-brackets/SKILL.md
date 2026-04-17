---
name: invalid-xml-brackets
description: Demonstrate the XML bracket violation. Use when a description contains forbidden characters like <tag> inside the frontmatter.
---

# Invalid — XML Brackets

## Instructions
1. This fixture intentionally violates FM-014.

## Examples
Example 1: The frontmatter description above contains `<tag>` and must be rejected.

## Common Issues
### Remove angle brackets
Strip all `<` and `>` from the description.
