# DeepMAST Figure 1 Design

## Goal

Create a paper-ready overview figure for DeepMAST that communicates the system as an end-to-end translational workflow from spatial transcriptomics input to biological interpretation, therapeutic target discovery, and final report generation.

## Design Decisions

### 1. Figure role

- This figure is the main overview figure for the paper.
- The primary message is `end-to-end translational pipeline`, not a standalone software architecture chart.
- The layout should be a single large panel rather than multiple application panels.

### 2. Overall layout

The figure uses a hybrid layout:

- A large central workflow layer shows the end-to-end scientific pipeline.
- A capability layer below the workflow highlights how DeepMAST operates.
- A resource layer below that shows the tool and knowledge substrate.

This keeps the biological workflow legible while still surfacing the system-level novelty.

### 3. Input and output framing

**Input**

- `Spatial transcriptomics dataset and user-defined biological question`

**Output**

- `Interpretable ST findings, prioritized ligand-receptor interactions, therapeutic target evidence, and final report`

### 4. Workflow layer modules

The workflow layer contains these top-level elements in order:

1. `Study Setup / Pipeline Builder`
2. `ST Analysis Pipeline`
3. `Prioritized L-R Candidates`
4. `Deep Biological Interpreter`
5. `Deep Drug Target Discovery`
6. `Final Report Synthesis`

### 5. Workflow module text

**Study Setup / Pipeline Builder**

`Constructs an analysis plan from the study objective, dataset context, and required inputs.`

**ST Analysis Pipeline**

`Executes a standardized spatial transcriptomics workflow for clustering, neighborhood analysis, pathway activity, and cell-cell communication.`

**Prioritized L-R Candidates**

`Generates top-ranked ligand-receptor candidates using hybrid spatial and biological relevance scoring.`

Note:

- This is an intermediate artifact, not a standalone agent.
- It should appear visually smaller than the major deep-agent modules.

**Deep Biological Interpreter**

`Produces literature-grounded biological interpretation through specialized subagents for planning, evidence retrieval, mechanistic reasoning, and synthesis preparation.`

Subagent ribbon:

- `Planner -> Searcher -> Interpreter`

**Deep Drug Target Discovery**

`Evaluates prioritized candidates with staged translational evidence assessment and hypothesis generation for therapeutic target discovery.`

Subagent ribbon:

- `Evidence Assessor -> Deep Diver -> Hypothesis Generator -> Summarizer`

**Final Report Synthesis**

`Integrates biological interpretation and therapeutic evidence into a unified final report.`

Small note:

- `drug-target outputs are incorporated into final synthesis`

Implementation note:

- Although the reporter belongs to the Deep Biological Interpreter workflow in code, the figure should elevate final synthesis into a separate final-stage box for readability.

### 6. Internal dependency clarification

- `Deep Drug Target Discovery` produces `drug.md` and target assessment outputs before final synthesis.
- `Final Report Synthesis` consumes outputs from both `Deep Biological Interpreter` and `Deep Drug Target Discovery`.
- This relationship should be shown as convergence into the final synthesis stage instead of exposing all file-level handoffs.

### 7. Capability layer

Label:

- `Capability Layer`

Boxes:

- `Hierarchical Agents`
- `Skills-guided Reasoning`
- `MCP Tool Interface`

Key emphasis:

- `Skills-guided Reasoning` should be the most visually prominent capability block.
- The figure should explicitly communicate that DeepMAST is not only an MCP tool-calling system, but a skills-guided scientific agent system.

### 8. Resource layer

Label:

- `Resource Layer`

Boxes:

- `ST analysis engines`
- `MCP servers`
- `Biological databases`
- `Literature and full-text RAG`

### 9. Arrow semantics

**Main workflow arrows**

```text
Input
  -> Study Setup / Pipeline Builder
  -> ST Analysis Pipeline
  -> Prioritized L-R Candidates
     -> Deep Biological Interpreter
     -> Deep Drug Target Discovery
Deep Biological Interpreter
  -> Final Report Synthesis
Deep Drug Target Discovery
  -> Final Report Synthesis
Final Report Synthesis
  -> Output
```

**Capability support arrows**

- `Skills-guided Reasoning` -> `Deep Biological Interpreter`
- `Skills-guided Reasoning` -> `Deep Drug Target Discovery`
- `MCP Tool Interface` -> `ST Analysis Pipeline`
- `MCP Tool Interface` -> `Deep Drug Target Discovery`
- `Hierarchical Agents` -> `Study Setup / Pipeline Builder`
- `Hierarchical Agents` -> `Deep Biological Interpreter`
- `Hierarchical Agents` -> `Deep Drug Target Discovery`
- `Hierarchical Agents` -> `Final Report Synthesis`

Visual rule:

- Solid arrows = workflow or artifact flow
- Dashed arrows = capability support

### 10. HITL treatment

- Human-in-the-loop checkpoints should not interrupt the main flow.
- They should be shown as small side callouts only.
- Recommended checkpoints:
  - `study setup`
  - `target selection / interpretation confirmation`

### 11. Visual emphasis

- The workflow layer is the dominant visual region.
- The capability and resource layers should appear as lower supporting bands.
- `Deep Biological Interpreter` and `Deep Drug Target Discovery` should be larger than `Prioritized L-R Candidates`.
- `Final Report Synthesis` should visually read as the convergence point of the system.

## Draft Figure Legend

`DeepMAST is a layered multi-agent system that translates spatial transcriptomics data and user-defined biological questions into interpretable findings and therapeutic target evidence. The workflow layer comprises study setup, standardized ST analysis, candidate ligand-receptor prioritization, deep biological interpretation, deep drug target discovery, and final report synthesis. Beneath this workflow, a capability layer highlights hierarchical agents, skills-guided reasoning, and MCP-based tool invocation, while a resource layer provides access to ST analysis engines, MCP servers, biological databases, and literature/full-text RAG resources. This design emphasizes DeepMAST’s core strength as a skills-guided scientific agent system rather than a tool-calling pipeline alone.`

## Recommended Deliverables

- Editable wireframe in Mermaid
- Exported SVG for manuscript assembly
- Optional PPTX or Illustrator-polished version for final submission
