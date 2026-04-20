---
name: hypothesis-generation
description: Generate structured, testable scientific hypotheses from observations, literature, or preliminary data. Use whenever the user asks what could explain a pattern, wants competing mechanisms, needs falsifiable predictions, or wants experiments that can discriminate between explanations. Prefer this skill for evidence-backed hypothesis formulation; for open-ended ideation use brainstorming, for automated dataset-scale hypothesis generation and testing use hypogenic, and for drug-target evidence workflows use drug-target-hypothesis.
allowed-tools: Read Write Edit Bash
license: MIT
metadata:
  skill-author: K-Dense Inc.
  version: 1.1.0
---

# Scientific Hypothesis Generation

Generate evidence-backed, testable scientific hypotheses from observations, literature, and preliminary data. The default job of this skill is to produce a structured hypothesis brief, not a publication-formatted report.

## When to Use This Skill

Use this skill when the user needs to:
- Explain an observation, pattern, or unexpected result
- Formulate 3-5 competing mechanistic hypotheses
- Derive falsifiable predictions from existing evidence
- Design experiments or analyses that can distinguish between explanations
- Turn literature and preliminary findings into a focused hypothesis set
- Compare multiple plausible explanations instead of committing to one too early

## Do Not Use This Skill

Do not use this skill when:
- The user wants wide-open ideation without an evidence-backed framing; use `brainstorming`
- The task is automated hypothesis generation or testing over tabular datasets; use `hypogenic`
- The task is a runtime-scoped drug-target hypothesis workflow tied to saved evidence artifacts; use `drug-target-hypothesis`
- The user only wants a figure, schematic, or visual summary; use `scientific-schematics`

## Default Output

By default, return a structured Markdown hypothesis brief using this shape:

```markdown
## Phenomenon
- What needs explanation
- Relevant scope, context, and constraints

## Current Evidence
- Key observations
- Important literature anchors
- Known unknowns

## Competing Hypotheses
### Hypothesis 1: [short title]
- Mechanism:
- Why it fits:
- What would weaken it:

### Hypothesis 2: [short title]
- Mechanism:
- Why it fits:
- What would weaken it:

## Discriminating Predictions
- Prediction A:
- Prediction B:

## Proposed Experiments or Analyses
- Experiment 1:
- Experiment 2:

## Key Uncertainties
- Remaining gaps
- Assumptions that need validation
```

Keep the brief concise, comparative, and falsifiable. Default to 3-5 competing hypotheses unless the user asks for a different count.

## Workflow

Follow this process in order.

### Step 1: Clarify the Phenomenon

Start by pinning down the thing that needs explanation:
- Identify the exact observation, trend, or discrepancy
- Separate established facts from inference
- Note the domain, system, and scale involved
- Capture important constraints such as model system, tissue, intervention, timepoint, or measurement limits

### Step 2: Ground the Problem in Existing Evidence

Build a compact evidence base before proposing mechanisms:
- Summarize the most relevant prior knowledge
- Look for known pathways, analogies, and competing theories
- Identify contradictions, missing links, and unresolved debates
- Use `references/literature_search_strategies.md` for search tactics when the literature needs to be expanded

For biomedical topics, prioritize authoritative sources and recent reviews before leaning on speculative mechanism-building.

### Step 3: Generate Competing Mechanistic Hypotheses

Produce 3-5 genuinely different hypotheses:
- Make each one mechanistic rather than purely descriptive
- Keep them distinguishable from one another
- Vary the level of explanation when useful, such as molecular, cellular, systems, or population level
- Avoid collapsing similar ideas into cosmetic variants

Use hypotheses to cover the plausible space, not to force premature certainty.

### Step 4: Evaluate Hypothesis Quality

Assess each candidate against the criteria in `references/hypothesis_quality_criteria.md`:
- Testability
- Falsifiability
- Parsimony
- Explanatory power
- Scope
- Consistency with established knowledge
- Novelty

Call out the strongest and weakest feature of each hypothesis. If one is too vague to test, discard or rewrite it.

### Step 5: Derive Discriminating Predictions

For each retained hypothesis:
- State what should be observed if it is true
- Identify observations that would argue against it
- Prefer predictions that separate one hypothesis from the others
- Be quantitative when the context supports it

### Step 6: Design Experiments or Analyses

Propose the smallest set of tests that can resolve the main uncertainty:
- Define what would be measured
- Specify controls or comparison groups
- Note likely confounds
- Favor experiments that clearly discriminate between competing explanations

Use `references/experimental_design_patterns.md` when you need a study-design menu across experimental settings.

### Step 7: Present the Structured Brief

End the default path with the Markdown hypothesis brief described above.

Prefer a focused deliverable:
- concise phenomenon summary
- 3-5 competing hypotheses
- evidence basis for each
- falsifiable predictions
- experiments or analyses that can separate them

Do not switch into publication formatting unless the user explicitly asks for it.

## Optional: Publication-ready Output

Activate this branch only if the user explicitly asks for:
- a publication-ready report
- LaTeX or template-based export
- appendix-style formatted output
- figures or schematics alongside the hypothesis brief

If that happens:
- Treat the structured hypothesis brief as the source content
- Use `assets/hypothesis_report_template.tex` as the starting template
- Use `assets/hypothesis_generation.sty` and `assets/FORMATTING_GUIDE.md` for layout details
- Keep the scientific logic identical; this branch changes packaging, not reasoning
- If figures are requested, route figure generation through `scientific-schematics` rather than a local script

Compile LaTeX only when the user actually needs a local report artifact:

```bash
xelatex hypothesis_report.tex
bibtex hypothesis_report
xelatex hypothesis_report.tex
xelatex hypothesis_report.tex
```

## Quality Standards

Every final hypothesis brief should be:
- Evidence-backed rather than purely imaginative
- Mechanistic rather than descriptive
- Falsifiable rather than vague
- Comparative across multiple plausible explanations
- Actionable enough to support a next experiment or analysis

## Examples

### Example 1: Positive trigger from an experimental result

User says: "We see cytokine X rise only after stress exposure. Give me 3 competing mechanisms and experiments to separate them."

Result: produce a structured hypothesis brief with competing mechanisms, discriminating predictions, and experiments.

### Example 2: Positive trigger from literature plus preliminary data

User says: "Based on these pilot RNA-seq results and the literature, what mechanisms could explain the phenotype?"

Result: synthesize current evidence, propose competing mechanistic hypotheses, and identify the next validation steps.

### Example 3: Positive paraphrase

User says: "What could explain this pattern, and what data would falsify each explanation?"

Result: treat this as a direct request for evidence-backed competing hypotheses and falsifiable predictions.

### Example 4: Boundary case

User says: "Make me a schematic of this pathway."

Result: do not use this skill as the primary path unless hypothesis formulation is also requested. Route figure-only work to `scientific-schematics`.

## Common Issues

### The request is too broad

If the user asks for "some ideas" without a clear phenomenon:
1. Narrow the problem to a specific observation, discrepancy, or research question.
2. Identify the system, context, and available evidence.
3. If the user only wants open-ended ideation, use `brainstorming` instead.

### The evidence base is too thin

If there is not enough grounding to build strong mechanisms:
- **Cause:** The observation is underspecified or the literature search is too shallow.
- **Solution:** Summarize what is actually known, identify the biggest missing facts, and propose provisional hypotheses with explicit uncertainty.
- **Prevention:** Gather a minimal literature set before trying to rank mechanisms confidently.

### The task is really about automated dataset mining

If the user wants large-scale or automated hypothesis generation over tabular data:
- **Cause:** The task is drifting from manual scientific reasoning into programmatic hypothesis generation and testing.
- **Solution:** Route that work to `hypogenic`.
- **Prevention:** Reserve this skill for analyst-style hypothesis formulation rather than batch automation.

### The user actually wants formatting or figures

If the request is mostly about presentation:
- **Cause:** The hypothesis content already exists and the remaining work is packaging.
- **Solution:** Use the optional publication-ready branch for report export, and use `scientific-schematics` for figures.
- **Prevention:** Treat formatting as downstream of reasoning, not as the default contract.

## Resources

### references/

- `hypothesis_quality_criteria.md` - rubric for evaluating testability, falsifiability, parsimony, explanatory power, scope, consistency, and novelty
- `experimental_design_patterns.md` - common study and experiment patterns across domains
- `literature_search_strategies.md` - practical literature search guidance for biomedical and broader scientific topics

### assets/

- `hypothesis_report_template.tex` - optional LaTeX template for publication-style packaging
- `hypothesis_generation.sty` - LaTeX style file used by the optional report template
- `FORMATTING_GUIDE.md` - optional formatting reference for the publication-ready branch

## Related Skills

- `brainstorming` - open-ended ideation before evidence-backed hypothesis work
- `hypogenic` - automated dataset-scale hypothesis generation and testing
- `drug-target-hypothesis` - structured drug-target hypothesis generation from scoped evidence artifacts
- `scientific-schematics` - figure and schematic generation once the hypothesis content is already defined
- `pubmed-eutils-search` - deeper PubMed-specific search support when the evidence base needs to be expanded
