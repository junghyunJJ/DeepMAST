# Use Case Definition Template

## Format

```
Use Case: [short, specific name]
Trigger: [2-3 phrases a user would actually say]
Steps:
1. [First action]
2. [Second action]
3. [Third action]
Result: [final state on success]
```

## Example 1: Document & Asset Creation

```
Use Case: Quarterly Report Generation
Trigger: User says "generate Q4 report" or "create quarterly summary"
Steps:
1. Fetch data from analytics MCP
2. Generate charts using matplotlib
3. Compile into formatted PDF using template
4. Save to designated output directory
Result: Publication-ready quarterly report PDF with charts
```

## Example 2: Workflow Automation

```
Use Case: PR Review Checklist
Trigger: User says "review this PR" or "check my pull request"
Steps:
1. Fetch PR diff via GitHub MCP
2. Run linting and type-checking scripts
3. Check test coverage delta
4. Generate structured review comments
Result: Comprehensive PR review with actionable feedback
```

## Example 3: MCP Enhancement

```
Use Case: Database Migration Validation
Trigger: User says "validate migration" or "check schema changes"
Steps:
1. Connect to database via MCP
2. Compare current vs target schema
3. Generate migration script
4. Run dry-run validation
Result: Validated migration script ready for execution
```
