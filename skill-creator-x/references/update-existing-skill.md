# Updating an Existing Skill

## When to Use This Workflow

Use the UPDATE workflow when your skill already has a valid SKILL.md and
frontmatter but has specific validation failures (< 5 issues). For skills
that need structural overhaul (missing SKILL.md, no frontmatter, 5+ issues),
use the MIGRATE workflow instead (see `migration-guide.md`).

## Steps

1. **Audit** your skill to identify issues:
   ```bash
   python -m scripts.audit_all /path/to/skills/ --json
   python -m scripts.validate_strict /path/to/your-skill/
   ```

2. **Preview** safe auto-fixes (dry-run is default):
   ```bash
   python -m scripts.autofix /path/to/your-skill/
   ```

3. **Apply** specific fixes:
   ```bash
   python -m scripts.autofix /path/to/your-skill/ --fix FM-014 --yes
   ```

4. **Apply all** safe fixes at once:
   ```bash
   python -m scripts.autofix /path/to/your-skill/ --fix-all-safe --yes
   ```

5. **Re-validate** to confirm fixes (autofix does this automatically):
   ```bash
   python -m scripts.validate_strict /path/to/your-skill/
   ```

6. **Manual fixes** for rules that require human judgment:
   - FM-012 (description WHAT+WHEN): Rewrite to include both what the skill
     does and when to use it. Use `run_loop.py` for LLM-assisted optimization.
   - BD-003 (body XML outside fences): Wrap XML in fenced code blocks.
   - BD-004 (actionable instructions): Add numbered steps or code examples.

## Backup and Recovery

All fixes create automatic backups at `your-skill/backups/{timestamp}/`.
To restore: copy `backups/{timestamp}/SKILL.md` back to the skill root.

## See Also

- `references/autofix-rules.md` — Full list of auto-fixable rules
- `scripts/validate_strict.py` — Validation rule definitions
