# Cross-Platform Skill Deployment Guide

## Platform Tiers

| Tier | Platforms | Support Level |
|------|-----------|---------------|
| Tier 1 (Full Support) | Claude Code | SKILL.md native, automatic triggering |
| Tier 2 (Install + Verify) | Codex CLI, Cursor | Install script + functional verification |
| Tier 3 (Guide Only) | Gemini CLI, Copilot | Documentation guide only |

## Platform Details

### Claude Code (Tier 1)
- **Install path:** `~/.claude/skills/<skill-name>/SKILL.md`
- **Activation:** Automatic (description-based triggering)
- **Upload:** Settings > Capabilities > Skills or CLI `claude skill install`
- **Verification:** Ask "When would you use the [skill] skill?"
- **Constraints:** None (primary runtime)

### Codex CLI (Tier 2)
- **Install path:** `~/.codex/skills/<skill-name>/SKILL.md`
- **Activation:** Automatic (SKILL.md detection)
- **Verification:** `codex --skill <name> "test prompt"`
- **Constraints:** Verify Python path when running scripts/

### Cursor (Tier 2)
- **Install path:** `.cursor/skills/<skill-name>/SKILL.md` (project-local)
- **Activation:** Auto-loaded on project open
- **Verification:** Trigger skill in Cursor Composer
- **Constraints:** Project scope only (no global install)

### Gemini CLI (Tier 3)
- **Install path:** `~/.gemini/skills/<skill-name>/SKILL.md`
- **Activation:** May require manual configuration
- **Constraints:** Verify SKILL.md parsing scope

### Copilot (Tier 3)
- **Install path:** `.github/skills/<skill-name>/SKILL.md`
- **Activation:** Repository scope
- **Constraints:** Depends on GitHub Copilot's skills support level

## Warning

These paths are observation-based de facto conventions and may change with platform updates.
`install_multiplatform.py` verifies path existence before installation.
