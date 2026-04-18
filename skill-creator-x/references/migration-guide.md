# Migration Guide: Legacy Skills to PDF-Compliant Format

## Update vs Migrate (ADR-010)

| Workflow | When to Use | Risk | Tool |
|----------|-------------|------|------|
| **Update** | Valid SKILL.md with < 5 field-level issues | Low | `autofix.py` |
| **Migrate** | Structural overhaul needed (see criteria below) | Medium-High | `migrate_skill.py` |

### Migration Criteria (ADR-010)

A skill needs migration if **any** of these conditions are true:
1. **FM-005**: Missing frontmatter `---` delimiters
2. **FM-001 + FM-002**: Both filename and folder naming violated
3. **5+ rules** violated simultaneously
4. **SKILL.md absent**: Only free-form Markdown exists

## Workflow

### Step 1: Assess

```bash
python -m scripts.migrate_skill /path/to/legacy-skill/ --assess
python -m scripts.migrate_skill /path/to/legacy-skill/ --assess --json
```

Output tells you whether migration is needed, what changes are required,
and estimated risk level (low/medium/high).

### Step 2: Preview (dry-run)

```bash
python -m scripts.migrate_skill /path/to/legacy-skill/
```

Shows unified diff of proposed changes without modifying files.

### Step 3: Apply

```bash
python -m scripts.migrate_skill /path/to/legacy-skill/ --apply --yes
```

This will:
1. Create automatic backup at `legacy-skill/backups/{timestamp}/`
2. Create git branch `skill-migrate/{name}` (if in a git repo)
3. Restructure frontmatter (add delimiters, required fields)
4. Move unknown top-level keys under `metadata:`
5. Insert missing sections (Common Issues, Examples)
6. Fix naming — SKILL.md case-rename in place (intra-directory, atomic). If the top-level folder also needs kebab-casing, the tool emits a `MANUAL: rename folder <old> -> <new>` entry instead of renaming the directory mid-run; folder renames affect git history, IDE indexes, and CI paths and are left to the user. The manual instruction points at where the backup will live after the rename (`<new-dir>/backups/<ts>/`).
7. Run all safe autofix rules
8. Re-validate and report before/after comparison

### Step 4: Review and commit

```bash
git diff  # Review changes
git add . && git commit -m "migrate: <skill-name> to PDF-compliant format"
```

## Git Integration

By default, `migrate_skill.py` creates a `skill-migrate/{name}` branch.
Disable with `--no-git` for non-git directories or manual branch management.

## Backup and Recovery

Backups are created at `your-skill/backups/{timestamp}/SKILL.md`.
To restore: `cp backups/{timestamp}/SKILL.md ./SKILL.md`

## See Also

- `references/update-existing-skill.md` — For minor fixes (Update workflow)
- `references/autofix-rules.md` — Full auto-fix rule reference
