"""
Prompt templates for ST Pipeline Agent.

This module contains prompt generation functions for spatial transcriptomics
pipeline analysis, including ReAct agent prompts and pipeline generation prompts.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.base.base_state import STPipelineState


def selection_node_prompt(state: dict, is_spot_based: bool, cell_type_task: str) -> str:
    """Create the prompt for the ReAct agent."""
    return f"""You are an expert in spatial transcriptomics pipeline development.
You must build a customized 3-step analysis pipeline by searching for appropriate tools in the CCI-RAG 'pipeline' collection.

COLLECTED INFORMATION:
- Technology: {state["st_technology"]}
- Disease: {state["disease"]}
- Species: {state["species"]}
- OS: {state["os_type"]}
- Hardware: {state["gpu_available"]}
- Data Type: {'Spot-based' if is_spot_based else 'Single-cell resolution'}

PIPELINE STRUCTURE (MUST FOLLOW EXACTLY):
1. Data Normalization - Normalization and Normalization (Fixed: log)
2. Cell Type Analysis - {cell_type_task.capitalize()} (for {state["st_technology"]})
3. Spatial Clustering - Spatial Clustering

STEP-BY-STEP INSTRUCTIONS:

### Step 1: Data Normalization (FIXED)
- log

### Step 2: Cell Type Analysis
- For spot-based ST ({state["st_technology"]}): Search for DECONVOLUTION methods
- For single-cell resolution: Search for ANNOTATION methods (Note: CellTypist is currently available)
- Search in the 'pipeline' collection

### Step 3: Spatial Clustering
- Search for spatial clustering analysis methodologies
- Focus on spatial clustering tools
- Search in the 'pipeline' collection

IMPORTANT: MUST use the 'server-sequential-thinking' tool :
- MUST use `create_thought_sequence` to analyze and structure your search strategy before starting
- MUST use it to systematically evaluate and compare different tool options for each step
- MUST use it to reason about programming language compatibility across the pipeline
- MUST use it to create a comprehensive plan that considers all collected information
- MUST use it to ensure logical consistency in your pipeline recommendations

SEARCH GUIDELINES:
1. Use `list_collections` to find the 'pipeline' collection ID
2. Use one broad hybrid `search_documents` query per non-fixed pipeline step first, with limit=20
3. Use detail follow-up searches for installation, compatibility, or computational requirements with limit=10
4. Keep the total search budget to 12-15 total search calls
5. Build the pipeline based on found tools

IMPORTANT NOTES:
- Target Collection: pipeline
- Search Type: hybrid (preferred)
- File names represent tool names
- Consider programming language compatibility when selecting tools
- Provide computational requirements for each method

OUTPUT REQUIREMENTS:
1. Complete 3-step pipeline with specific tool names
2. Programming language recommendation with evidence
3. Computational requirements
4. Integrated workflow
5. Sources for each tool recommendation

STOP CONDITIONS:
- STOP searching once you have found suitable tools for all 3 steps
- STOP if you've made 12-15 total search calls
- STOP and provide recommendations based on what you've found so far if searches are not yielding results
- Focus on efficiency - don't search endlessly for perfect tools

Begin by listing collections to find the pipeline collection, then search for tools for each step."""



def create_pipeline_prompt(state: dict) -> str:
    """Create the prompt for pipeline generation."""
    # Extract optional fields
    sample_count = state.get("sample_count")
    pipeline_config = state.get("pipeline_config")

    # Build sample count line if available
    sample_info = f"- Sample Count: {sample_count}\n" if sample_count else ""

    # Build pipeline configuration section if available
    config_section = ""
    if pipeline_config:
        config_section = f"""
PIPELINE CONFIGURATION (User-Selected):
- Normalization Method: {pipeline_config.normalization}
- Cell Type Analysis Method: {pipeline_config.celltype_analysis}
- Spatial Clustering Method: {pipeline_config.spatial_clustering}
- Platform Type: {pipeline_config.platform_type}

"""

    return f"""

ANALYSIS PARAMETERS:
- Technology: {state["st_technology"]}
- Disease: {state["disease"]}
- Species: {state["species"]}
- OS: {state["os_type"]}
- Hardware: {state["gpu_available"]}
{sample_info}{config_section}
FORMAT THE FINAL PIPELINE AS FOLLOWS:

## 🧬 Spatial Transcriptomics Analysis Pipeline

### 📋 Pipeline Summary
Provide a one-line summary of the recommended pipeline with tool names:
"[Normalization method] → [Cell Type analysis method (Deconvolution/Annotation)] → [Spatial clustering method]"


### 🔧 Step 1: Data Normalization  
- **Tool**: [Name from pipeline collection]
- **Purpose**: Normalization
- **Language**: [R/Python - based on other tools]
- **Computational Requirements**: [CPU/GPU, Memory]
- **why this tool**: [explan why choose this tool]

### 🔬 Step 2: Cell Type Analysis
- **Tool**: [Name from pipeline collection]
- **Purpose**: [Deconvolution for spot-based OR Annotation for single-cell]
- **Language**: [R/Python]
- **Computational Requirements**: [CPU/GPU, Memory]
- **why this tool**: [explan why choose this tool]

### 🔬 Step 3: Spatial Clustering
- **Tool**: [Name from pipeline collection]
- **Purpose**: Spatial clustering
- **Language**: [R/Python]
- **Computational Requirements**: [CPU/GPU, Memory]
- **why this tool**: [explan why choose this tool]

### 📊 Computational Overview
- **Total RAM Required**: [Amount]
- **GPU Required**: [Yes/No, which steps]
- **Estimated Runtime**: [For typical dataset]

### 📚 Sources
List all sources from the pipeline collection that were used.
"""
