#!/usr/bin/env python3
"""Execute Biological Interpreter Agent directly (bypassing API).

This script runs the agent graph directly for better error visibility.
"""
import asyncio
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def run_biological_interpreter():
    """Execute the biological interpreter agent directly."""
    from dotenv import load_dotenv
    load_dotenv(override=True)

    # Import directly to avoid module-level asyncio.run()
    from langgraph.checkpoint.memory import MemorySaver
    from src.agents.interpreter.biological_interpreter_agent import BiologicalInterpreterAgent
    from src.agents.interpreter.biological_interpreter_state import (
        BiologicalInterpreterState,
        create_initial_state,
    )
    from src.agents.model import create_llm

    print("=" * 80)
    print("🧬 Biological Interpreter Agent - Direct Execution")
    print("=" * 80)

    # Create initial state
    state = create_initial_state(
        interest_celltypes=['Invasive Tumor', 'Prolif Invasive Tumor'],
        adata_path='/Users/jungj2/Dropbox/Metadata/mcp/sp_enrich_mcp/data/n_bc_starfysh.h5ad',
        results_dir='/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res',
        force_regenerate=False,
        organism='human',
        cluster_key='Cluster'
    )

    print("\n📊 Configuration:")
    print(f"   • Mode: {state['analysis_mode']}")
    print(f"   • Interest Celltypes: {state['interest_celltypes']}")
    print(f"   • Organism: {state['organism']}")
    print(f"   • Cluster Key: {state['cluster_key']}")
    print(f"   • Force Regenerate: {state['force_regenerate']}")
    print(f"\n📁 Data Paths:")
    print(f"   • adata_path: {state['adata_path']}")
    print(f"   • results_dir: {state['results_dir']}")
    print()

    try:
        # Create LLM
        print("🔧 Creating LLM...")
        llm = create_llm("openai")
        print("   LLM created successfully")

        # Create agent WITH checkpointer to test DataFrame serialization fix
        print("🔧 Creating agent with MemorySaver checkpointer...")
        checkpointer = MemorySaver()
        agent = BiologicalInterpreterAgent(
            model=llm,
            state_schema=BiologicalInterpreterState,
            checkpointer=checkpointer,  # With checkpointer - testing serialization fix
            is_debug=True
        )
        graph = agent.graph
        print("   Agent created successfully")

        # Configuration for execution (increased recursion limit for quality reflection loop)
        config = {
            "configurable": {"thread_id": "direct-run-1"},
            "recursion_limit": 50  # Increased from default 25 for refinement loops
        }

        # Run the graph with streaming
        print("\n🚀 Starting agent execution...")
        print("-" * 80)

        html_report = None
        final_state = None

        async for event in graph.astream(state, config):
            # Print node updates
            for node_name, node_output in event.items():
                print(f"\n📍 Node: {node_name}")
                if isinstance(node_output, dict):
                    for key, value in node_output.items():
                        if key == "messages":
                            if value:
                                for msg in value:
                                    content = getattr(msg, 'content', str(msg))
                                    print(f"   • message: {content[:200]}...")
                        elif key == "html_report":
                            if value:
                                html_report = value
                                print(f"   • html_report: {len(value):,} chars")
                        elif value is not None:
                            if isinstance(value, (list, dict)):
                                print(f"   • {key}: {type(value).__name__} ({len(value) if hasattr(value, '__len__') else 'N/A'} items)")
                            else:
                                value_str = str(value)
                                if len(value_str) > 150:
                                    value_str = value_str[:150] + "..."
                                print(f"   • {key}: {value_str}")

        print("-" * 80)

        # Get final state
        final_state = await graph.aget_state(config)
        if final_state and hasattr(final_state, 'values'):
            values = final_state.values
            if isinstance(values, dict):
                html_report = values.get("html_report") or html_report

        # Save HTML report
        if html_report:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"Biological_Interpreter_Report_{timestamp}.html"
            output_path = os.path.join(state["results_dir"], output_filename)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_report)

            print(f"\n✅ HTML Report Saved!")
            print(f"   📄 Path: {output_path}")
            print(f"   📊 Size: {len(html_report):,} bytes")
        else:
            print("\n⚠️ No HTML report was generated.")

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
