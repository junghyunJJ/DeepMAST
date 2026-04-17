# Error Handling Template

## Required Section in SKILL.md

Every skill should include a "Common Issues" section. Use one of these two formats:

### Format A: Numbered diagnostic steps

```
## Common Issues

### [Error Type 1]
If you see "[error message or symptom]":
1. [First diagnostic step]
2. [Second diagnostic step]
3. [Resolution action]
```

### Format B: Cause/Solution/Prevention

```
### [Error Type 2]
If [condition]:
- **Cause:** [Why this happens]
- **Solution:** [How to fix]
- **Prevention:** [How to avoid in future]
```

## Example: MCP-based Skill

```
## Common Issues

### Connection Failed
If you see "Connection refused":
1. Verify MCP server is running: Check Settings > Extensions
2. Confirm API key is valid
3. Try reconnecting: Settings > Extensions > [Service] > Reconnect

### Authentication Error
If you see "401 Unauthorized":
- **Cause:** API key expired or insufficient permissions
- **Solution:** Regenerate API key in service dashboard
- **Prevention:** Set up key rotation reminder

### Rate Limiting
If you see "429 Too Many Requests":
1. Wait 60 seconds before retrying
2. If persistent, reduce batch size
3. Check service plan limits
```

## Example: Script-based Skill

```
## Common Issues

### Script Not Found
If `scripts/process.py` fails with "No such file":
1. Verify skill directory structure: `ls -la scripts/`
2. Check file permissions: `chmod +x scripts/process.py`
3. Ensure Python 3.12+ is available: `python3 --version`

### Invalid Input Format
If validation fails, common issues include:
- Missing required fields (add them to the input)
- Invalid date formats (use YYYY-MM-DD)
- Encoding issues (ensure UTF-8)
```
