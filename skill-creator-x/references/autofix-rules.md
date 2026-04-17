# Auto-fix Rules Reference

## Safe Auto-fix Rules (9 rules)

These rules are applied deterministically by `scripts/autofix.py`.
All follow ADR-011 safety principles (dry-run default, backup, diff, re-validation).

| Rule | Category | Fix Action | Safety Notes |
|------|----------|-----------|--------------|
| FM-004 | Structure | Move `README.md` to `references/` | File move, not delete |
| FM-007 | Frontmatter | Convert name to kebab-case (`re.sub(r'[_\s]+', '-', name.lower())`) | Preserves semantic meaning |
| FM-008 | Frontmatter | Remove spaces/capitals from name (same as FM-007) | Same handler |
| FM-013 | Frontmatter | Truncate description at sentence boundary to 1024 chars | ADR-011 principle 6 |
| FM-014 | Frontmatter | Strip XML tags (`<...>`) from description | Regex removal |
| FM-015 | Frontmatter | Truncate compatibility at sentence boundary to 500 chars | ADR-011 principle 6 |
| FM-016 | Frontmatter | Move unknown top-level keys under `metadata:` | Preserves data |
| BD-005 | Body | Append `## Common Issues` template section | Template insertion |
| BD-006 | Body | Append `## Examples` template section | Template insertion |

## Manual-only Rules (not auto-fixable)

| Rule | Category | Why Manual | Suggested Action |
|------|----------|-----------|-----------------|
| FM-001 | Structure | Filename rename needs user intent | Rename file to `SKILL.md` |
| FM-002 | Structure | Folder rename may break references | Rename folder to kebab-case |
| FM-003 | Frontmatter | Folder/name mismatch needs decision | Align folder name with `name:` field |
| FM-005 | Frontmatter | Missing delimiters needs structural rewrite | Add `---` delimiters |
| FM-006 | Frontmatter | Missing name needs user input | Add `name:` to frontmatter |
| FM-009 | Frontmatter | Reserved word removal changes identity | Choose a non-reserved name |
| FM-010 | Frontmatter | Name too long needs semantic decision | Shorten name meaningfully |
| FM-011 | Frontmatter | Missing description needs user input | Write description with WHAT + WHEN |
| FM-012 | Frontmatter | WHAT+WHEN heuristic needs LLM/human | Use `run_loop.py` for optimization |
| BD-001 | Body | Line count reduction needs content judgment | Remove low-value sections |
| BD-002 | Body | Word count reduction needs content judgment | Condense verbose sections |
| BD-003 | Body | XML in body needs context-aware fencing | Wrap XML in fenced code blocks |
| BD-004 | Body | Actionable instructions need domain knowledge | Add numbered steps |
| SC-001 | Structure | Script runnability needs runtime context | Add shebang or correct extension |
| SC-002 | Structure | Missing referenced files need creation | Create or fix file references |
| ST-001 | Structure | Folder size needs content audit | Remove large unnecessary files |

## CLI Usage

```bash
# Preview all safe fixes (dry-run default)
python -m scripts.autofix /path/to/skill/

# Apply specific rule
python -m scripts.autofix /path/to/skill/ --fix FM-014 --yes

# Apply all safe rules
python -m scripts.autofix /path/to/skill/ --fix-all-safe --yes

# JSON output for CI
python -m scripts.autofix /path/to/skill/ --fix-all-safe --yes --json
```
