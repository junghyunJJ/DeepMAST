# PDF Compliance Checklist
> Source: "The Complete Guide to Building Skills for Claude" (Anthropic, 2026-01)

## Before You Start (p.8, p.30)
- [ ] 2-3 concrete use cases defined
- [ ] Required tools identified (built-in vs MCP)
- [ ] This guide and example skills reviewed
- [ ] Folder structure planned

## During Development (p.10-13, p.30)
- [ ] Folder name in kebab-case
- [ ] SKILL.md file (exact case-sensitive name)
- [ ] YAML frontmatter with --- delimiters
- [ ] name: kebab-case, no spaces or capitals
- [ ] name does not contain "claude" or "anthropic" (reserved, p.11, p.31)
- [ ] description: includes WHAT + WHEN
- [ ] description: no XML brackets (< >)
- [ ] description: under 1024 characters
- [ ] Instructions are specific and actionable (p.13)
- [ ] Error handling section included (p.12-13)
- [ ] Examples section included (p.12)
- [ ] Bundled resources referenced clearly from SKILL.md (p.13)

## Before Upload (p.15-16, p.30)
- [ ] Trigger tested on clear, unambiguous tasks
- [ ] Trigger tested on paraphrased requests
- [ ] Non-triggering confirmed on unrelated topics
- [ ] Functional tests passed
- [ ] Tool integrations working (if applicable)
- [ ] Compressed as .zip file (< 10MB)

## After Upload (p.30)
- [ ] Tested in real conversations
- [ ] Under/over-triggering monitored
- [ ] User feedback collected
- [ ] Description and instructions iteratively improved
- [ ] Version updated in metadata
