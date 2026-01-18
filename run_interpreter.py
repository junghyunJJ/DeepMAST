#!/usr/bin/env python3
"""Execute Biological Interpreter Agent via LangGraph API.

This script invokes the biological_interpreter agent running at the LangGraph dev server.
"""
import asyncio
import json
import os
from datetime import datetime
from langgraph_sdk import get_client

# Configuration
LANGGRAPH_URL = "http://127.0.0.1:2024"
GRAPH_NAME = "biological_interpreter"

async def run_biological_interpreter():
    """Execute the biological interpreter agent and save HTML output."""

    # Create LangGraph SDK client
    client = get_client(url=LANGGRAPH_URL)

    # Create initial state matching create_initial_state parameters
    initial_state = {
        "messages": [],
        "analysis_mode": "celltype_to_cluster",  # Mode B: celltypes -> clusters
        "interest_clusters": None,
        "interest_celltypes": ["Invasive Tumor", "Prolif Invasive Tumor"],
        "research_question": None,
        "adata_path": "/Users/jungj2/Dropbox/Metadata/mcp/sp_enrich_mcp/data/n_bc_starfysh.h5ad",
        "lrdata_path": None,
        "results_dir": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res",
        "force_regenerate": False,
        "skip_existing": True,
        "organism": "human",
        "cluster_key": "Cluster",
        # Initialize all other state fields
        "generated_analyses": None,
        "failed_analyses": None,
        "part1_results": None,
        "part2_results": None,
        "part1_interpretations": None,
        "selected_celltypes": None,
        "selected_clusters": None,
        "selected_pathways": None,
        "additional_clusters": None,
        "part1_selection_rationale": None,
        "part2_interpretations": None,
        "selected_factor": None,
        "factor_selection_rationale": None,
        "factor_reference_clusters": None,
        "pathway_comparison": None,
        "final_celltypes_for_ctsvg": None,
        "celltype_source": None,
        "scoring_weights": {
            "base_weights": {
                "factor": 0.35,
                "pathway": 0.30,
                "morans": 0.20,
                "ctsvg": 0.15
            },
            "weight_ranges": {
                "factor": [0.20, 0.50],
                "pathway": [0.15, 0.45],
                "morans": [0.10, 0.35],
                "ctsvg": [0.05, 0.30]
            },
            "applied_weights": {
                "factor": 0.35,
                "pathway": 0.30,
                "morans": 0.20,
                "ctsvg": 0.15
            },
            "adjustment_rationale": "Default weights - no context-specific adjustment"
        },
        "selected_lr_pairs": None,
        "lr_scores": None,
        "lr_selection_rationale": None,
        "part3_interpretations": None,
        "analysis_plan": None,
        "integrated_narrative": None,
        "claims": None,
        "literature_evidence": None,
        "reflection_result": None,
        "refinement_count": 0,
        "html_report": None,
    }

    print("=" * 80)
    print("🧬 Biological Interpreter Agent Execution")
    print("=" * 80)
    print(f"\n📊 Configuration:")
    print(f"   • Server: {LANGGRAPH_URL}")
    print(f"   • Graph: {GRAPH_NAME}")
    print(f"   • Mode: celltype_to_cluster (Mode B)")
    print(f"   • Interest Celltypes: {initial_state['interest_celltypes']}")
    print(f"   • Organism: {initial_state['organism']}")
    print(f"   • Cluster Key: {initial_state['cluster_key']}")
    print(f"   • Force Regenerate: {initial_state['force_regenerate']}")
    print(f"\n📁 Data Paths:")
    print(f"   • adata_path: {initial_state['adata_path']}")
    print(f"   • results_dir: {initial_state['results_dir']}")
    print()

    try:
        # Create a new thread
        print("🔄 Creating thread...")
        thread = await client.threads.create()
        thread_id = thread["thread_id"]
        print(f"   Thread ID: {thread_id}")

        # Run the graph with streaming
        print("\n🚀 Starting agent execution (streaming)...")
        print("-" * 80)

        html_report = None
        final_state = None

        async for chunk in client.runs.stream(
            thread_id=thread_id,
            assistant_id=GRAPH_NAME,
            input=initial_state,
            stream_mode="updates",
        ):
            # Print node updates
            if hasattr(chunk, 'data') and chunk.data:
                data = chunk.data
                if isinstance(data, dict):
                    for node_name, node_output in data.items():
                        print(f"\n📍 Node: {node_name}")
                        if isinstance(node_output, dict):
                            # Check for html_report
                            if "html_report" in node_output and node_output["html_report"]:
                                html_report = node_output["html_report"]
                                print("   ✅ HTML report generated!")
                            # Print key updates
                            for key, value in node_output.items():
                                if key == "messages":
                                    if value:
                                        print(f"   • messages: {len(value)} new message(s)")
                                elif key == "html_report":
                                    if value:
                                        print(f"   • html_report: {len(value)} chars")
                                elif value is not None:
                                    if isinstance(value, (list, dict)):
                                        print(f"   • {key}: {type(value).__name__} ({len(value) if hasattr(value, '__len__') else 'N/A'} items)")
                                    else:
                                        value_str = str(value)
                                        if len(value_str) > 100:
                                            value_str = value_str[:100] + "..."
                                        print(f"   • {key}: {value_str}")

        print("-" * 80)

        # Get final state if html_report not captured from stream
        if not html_report:
            print("\n🔍 Fetching final state...")
            state = await client.threads.get_state(thread_id)
            if state and "values" in state:
                final_state = state["values"]
                html_report = final_state.get("html_report")

        # Save HTML report
        if html_report:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"Biological_Interpreter_Report_{timestamp}.html"
            output_path = os.path.join(initial_state["results_dir"], output_filename)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_report)

            print(f"\n✅ HTML Report Saved!")
            print(f"   📄 Path: {output_path}")
            print(f"   📊 Size: {len(html_report):,} bytes")
        else:
            print("\n⚠️ No HTML report was generated.")
            print("   Check the agent execution logs for errors.")

        print("\n" + "=" * 80)
        print("🎉 Execution Complete!")
        print("=" * 80)

        return html_report

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(run_biological_interpreter())
