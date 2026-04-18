# Skill Design Patterns

Five patterns for structuring skills, from simple to complex. Pick the one that best fits your use case.

## Pattern 1: Sequential Workflow Orchestration (p.22)
**Use when:** a multi-step process needs to happen in a specific order
**Key techniques:** explicit step ordering, inter-step dependencies, verification at each step, rollback on failure
**Example structure:**
```
### Step 1: [First Action]
Call MCP tool: `tool_name`
Parameters: param1, param2

### Step 2: [Second Action]
Wait for: step 1 verification
...
```

## Pattern 2: Multi-MCP Coordination (p.23)
**Use when:** the workflow spans multiple services
**Key techniques:** clear phase separation, data passing between MCPs, verification before next phase, centralized error handling
**Example structure:**
```
### Phase 1: [Service A] (MCP-A)
1. Export from Service A
2. Generate specifications

### Phase 2: [Service B] (MCP-B)
1. Create in Service B
2. Upload assets
...
```

## Pattern 3: Iterative Refinement (p.23)
**Use when:** output quality improves through iteration
**Key techniques:** explicit quality criteria, iterative improvement, validation scripts, stopping conditions
**Example structure:**
```
### Initial Draft
1. Fetch data
2. Generate first draft

### Quality Check
Run validation script: `scripts/check_quality.py`

### Refinement Loop
1. Address each identified issue
2. Re-validate
3. Repeat until quality threshold met
...
```

## Pattern 4: Context-aware Tool Selection (p.24)
**Use when:** the same result can be achieved by different tools depending on context
**Key techniques:** clear decision criteria, fallback options, transparency about selection rationale
**Example structure:**
```
### Decision Tree
1. Check input type and size
2. Determine best approach:
   - Large files (>10MB): Use cloud storage
   - Code files: Use GitHub
   - Temporary: Use local storage
...
```

## Pattern 5: Domain-specific Intelligence (p.24)
**Use when:** the skill provides expert knowledge beyond tool access
**Key techniques:** domain expertise embedded in logic, compliance before action, comprehensive documentation, clear governance
**Example structure:**
```
### Before Processing (Compliance Check)
1. Fetch details via MCP
2. Apply domain rules:
   - Check constraints
   - Verify requirements
   - Assess risk
3. Document decision
...
```
