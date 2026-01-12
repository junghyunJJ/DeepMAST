"""ST Pipeline Builder Agent - Comprehensive pipeline building with HITL"""
from typing import Annotated, Any, ClassVar, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.base import BaseAgent
from src.prompts.pipeline_prompts import create_pipeline_prompt
from dotenv import load_dotenv

load_dotenv(override=True)


# Platform type constants
SPOT_BASED_PLATFORMS = {
    "visium", "slide-seq", "slide-seqv2", "slideseq", "stereo-seq",
    "stereoseq", "starmap", "st", "spatial transcriptomics"
}
SINGLE_CELL_PLATFORMS = {
    "merfish", "xenium", "cosmx", "seqfish", "hdst", "resolve"
}


# Pipeline configuration model
class PipelineConfig(BaseModel):
    """Configuration for ST analysis pipeline steps"""

    normalization: str = Field(
        description="Normalization method (e.g., 'log', 'SCTransform', 'pearson residuals')"
    )
    celltype_analysis: str = Field(
        description="Cell type analysis method - annotation or deconvolution (e.g., 'IRIS', 'CyteType', 'Cell2location')"
    )
    spatial_clustering: str = Field(
        description="Spatial clustering method (e.g., 'IRIS', 'leiden', 'louvain', 'BayesSpace')"
    )
    platform_type: Literal["spot-based", "single-cell"] = Field(
        description="Platform type: 'spot-based' or 'single-cell' resolution"
    )


# Spatial Transcriptomics 파이프라인 구축에 필요한 정보를 정의하는 데이터 모델
class STPipelineInfoExtraction(BaseModel):
    """Essential information required for building an ST analysis pipeline."""

    # ST 기술/플랫폼 (예: Visium, Slide-seq, MERFISH)
    st_technology: str = Field(
        description="Spatial transcriptomics technology/platform used (e.g., Visium, Slide-seq, MERFISH, STARmap)"
    )

    # 질병 또는 표현형 정보
    disease: str = Field(
        description="Disease or phenotype being studied (e.g., breast cancer, Alzheimer's disease, healthy tissue)"
    )

    # 샘플의 종 (human 또는 mouse만 지원)
    species: Literal["human", "mouse"] = Field(
        description="Species of the sample. Currently only 'human' or 'mouse' are supported"
    )

    # ST 샘플의 개수 (양의 정수)
    sample_count: int = Field(
        gt=0, description="Number of ST samples. Must be a positive integer"
    )

    # OS 종류
    os_type: Literal["Windows", "Mac", "Linux", "HPC"] = Field(
        description="Operating system type: Windows, Mac, Linux, or HPC (High-Performance Computing cluster)"
    )

    # GPU 유무
    gpu_available: Literal["GPU", "CPU"] = Field(
        description="Computing hardware availability: GPU (if GPU is available) or CPU (if only CPU is available)"
    )

    # Spatial clustering 분석 수행 여부
    spatial_clustering: Literal["yes", "no", "undecided"] = Field(
        description="Whether to perform spatial clustering analysis: 'yes', 'no', or 'undecided'"
    )

    # Cell type analysis (deconvolution 또는 annotation) 수행 여부
    celltype_analysis: Literal["yes", "no", "undecided"] = Field(
        description="Whether to perform cell type analysis (deconvolution or annotation): 'yes', 'no', or 'undecided'"
    )


# State 정의
class STPipelineBuilderState(TypedDict):
    """State for ST Pipeline Builder Agent with full workflow support"""

    # Conversation messages
    messages: Annotated[list, add_messages]

    # Collected information from user
    st_technology: Optional[str]
    disease: Optional[str]
    species: Optional[Literal["human", "mouse"]]
    sample_count: Optional[int]
    os_type: Optional[Literal["Windows", "Mac", "Linux", "HPC"]]
    gpu_available: Optional[Literal["GPU", "CPU"]]
    spatial_clustering: Optional[Literal["yes", "no", "undecided"]]
    celltype_analysis: Optional[Literal["yes", "no", "undecided"]]

    # Pipeline configuration
    pipeline_config: Optional[PipelineConfig]

    # Workflow control flags
    info_complete: bool
    pipeline_generated: bool
    pipeline_summary: bool
    hitl_decision: Optional[Literal["default", "update", "select"]]


class STPipelineBuilderAgent(BaseAgent):
    """Agent for building complete Spatial Transcriptomics analysis pipelines with HITL"""

    NODE_NAMES: ClassVar[dict[str, str]] = {
        "CHECK_STATE": "check_state",
        "INFO_COL": "info_collection",
        "INFO_VAL": "info_validation",
        "PIPELINE_GEN": "pipeline_generation",
        "HITL": "human_decision",
        "CHECK_HITL": "check_human_decision",
        "PIPELINE_UPDATE": "pipeline_update",
        "PIPELINE_SELECT": "pipeline_selection",
        "PIPELINE_SUMMARY": "pipeline_summary",
    }

    # ST 파이프라인 정보 수집을 위한 시스템 메시지 템플릿
    SYSTEM_TEMPLATE: ClassVar[str] = """Your job is to collect essential information from a user to build a Spatial Transcriptomics (ST) analysis pipeline.

You must collect the following 8 pieces of information:

IMPORTANT: Before asking any question, mentally review what information you already have from the conversation history.
Track your progress: [Technology: ?, Disease: ?, Species: ?, Count: ?, OS: ?, GPU: ?, Clustering: ?, CellType: ?]

1. ST Technology/Platform: What spatial transcriptomics technology was used?
   - Examples: Visium (10x Genomics), Slide-seq, MERFISH, STARmap, Xenium, CosMx
   - If user mentions "10x", ask if they mean "Visium"

2. Disease/Phenotype: What disease or phenotype is being studied?
   - Ask for specific disease names or phenotype descriptions
   - Examples: "breast cancer", "Alzheimer's disease", "healthy brain tissue"

3. Species: What species is the sample from?
   - IMPORTANT: Currently only "human" or "mouse" are supported
   - If user mentions other species, politely inform them of this limitation

4. Sample Count: How many ST samples do you have?
   - Must be a positive integer (1, 2, 3, ...)
   - If user provides a range, ask them to specify the exact number

5. OS Type: What operating system are you using?
   - Options: Windows, Mac, Linux, or HPC (High-Performance Computing cluster)
   - Ask clearly which OS they are working on

6. GPU Availability: Do you have GPU available?
   - Options: GPU (if GPU is available) or CPU (if only CPU is available)
   - Ask if they have access to GPU hardware for computation

7. Spatial Clustering: Do you want to perform spatial clustering analysis?
   - Answer "yes" if you need to identify spatial domains or regions
   - Answer "no" if you don't need clustering
   - Answer "undecided" if you haven't decided yet

8. Cell Type Analysis: Do you want to perform cell type analysis?
   - This includes deconvolution or cell type annotation
   - Answer "yes" for cell type identification
   - Answer "no" to skip this step

Guidelines:
- CAREFULLY REVIEW the conversation history to identify information already provided by the user
- DO NOT ask for information that was already mentioned or can be reasonably inferred
- Examples of reasonable inference:
  * "patient" → human species
  * "breast cancer patient" → human species + breast cancer disease
  * "mouse model" → mouse species
  * "5 slides" → 5 samples
- Ask clarifying questions ONLY if information is unclear, ambiguous, or truly missing
- Be conversational and guide the user through the process efficiently
- Keep track of what you already know from the conversation

CRITICAL RULES:
- DO NOT call the tool until you have ALL 8 pieces of information with complete, valid values
- DO NOT call the tool if ANY field is missing, unclear, or needs confirmation
- DO NOT ask for information already provided in the conversation
- Use reasonable inference for obvious information (e.g., "patient" = human)
- ONLY call the tool when you are 100% certain you have all required information
- If truly uncertain about inferred information, ask for brief confirmation

After you have confirmed ALL 8 pieces of information are complete and valid, then call the STPipelineInfoExtraction tool.

EXAMPLE OF GOOD CONVERSATION:
User: "I need a pipeline for Visium data analyzing breast cancer patient"
Assistant (mentally): [Technology: Visium ✓, Disease: breast cancer ✓, Species: human (patient=human) ✓, Count: ?, OS: ?, GPU: ?]
Assistant: "Great! I have your Visium data for breast cancer analysis. How many samples do you have?"

EXAMPLE OF BAD CONVERSATION (DON'T DO THIS):
User: "I need a pipeline for Visium data analyzing breast cancer patient"
Assistant: "What disease are you studying?" ← WRONG! User already said "breast cancer"
Assistant: "What species?" ← WRONG! "patient" clearly means human

[IMPORTANT] Your conversation is in Korean. The collected data should be in English."""

    def __init__(
        self,
        model: Any,
        state_schema: Any = STPipelineBuilderState,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
    ) -> None:
        super().__init__(
            model=model,
            state_schema=state_schema,
            config_schema=config_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            checkpointer=checkpointer,
            store=store,
            max_retry_attempts=max_retry_attempts,
            agent_name=agent_name or "STPipelineBuilderAgent",
            is_debug=is_debug,
        )
        # LLM에 구조체를 바인딩
        self.llm_with_tool = self.model.bind_tools([STPipelineInfoExtraction])
        # MCP client will be initialized when needed
        self.mcp_client = None

    #############################
    ####### Helper Methods ######
    #############################

    def get_platform_type(self, st_technology: str) -> Literal["spot-based", "single-cell"]:
        """Determine platform type from ST technology name"""
        tech_lower = st_technology.lower()

        for platform in SPOT_BASED_PLATFORMS:
            if platform in tech_lower:
                return "spot-based"

        for platform in SINGLE_CELL_PLATFORMS:
            if platform in tech_lower:
                return "single-cell"

        # Default to spot-based if unknown
        if self.is_debug:
            print(f"Unknown platform '{st_technology}', defaulting to spot-based")
        return "spot-based"


    def create_default_pipeline(self, platform_type: Literal["spot-based", "single-cell"]) -> PipelineConfig:
        """Generate default pipeline configuration based on platform type"""
        if platform_type == "spot-based":
            return PipelineConfig(
                normalization="log",
                celltype_analysis="IRIS",  # deconvolution
                spatial_clustering="IRIS",
                platform_type=platform_type,
            )
        else:  # single-cell
            return PipelineConfig(
                normalization="log",
                celltype_analysis="CyteType",  # annotation
                spatial_clustering="leiden",
                platform_type=platform_type,
            )


    def extract_info_from_messages(self, messages: list) -> dict[str, Any]:
        """Extract collected information from tool calls in messages"""
        extracted_info = {}

        # Iterate through messages in reverse to find the most recent tool call
        for message in reversed(messages):
            if isinstance(message, AIMessage) and hasattr(message, "tool_calls") and message.tool_calls:
                # if self.is_debug:
                #     print(f"[DEBUG] extract_info_from_messages - Found AIMessage with tool_calls")

                for tool_call in message.tool_calls:
                    # if self.is_debug:
                    #     print(f"[DEBUG] Tool call name: {tool_call.get('name')}")

                    if tool_call.get("name") == "STPipelineInfoExtraction":
                        args = tool_call.get("args", {})
                        extracted_info = {
                            "st_technology": args.get("st_technology"),
                            "disease": args.get("disease"),
                            "species": args.get("species"),
                            "sample_count": args.get("sample_count"),
                            "os_type": args.get("os_type"),
                            "gpu_available": args.get("gpu_available"),
                            "spatial_clustering": args.get("spatial_clustering"),
                            "celltype_analysis": args.get("celltype_analysis"),
                        }

                        # if self.is_debug:
                        #     print(f"[DEBUG] Extracted info: {extracted_info}")

                        # Return first (most recent) match
                        return extracted_info

        # if self.is_debug:
        #     print(f"[DEBUG] extract_info_from_messages - No tool calls found, returning empty dict")

        return extracted_info


    # ===== Node Initialization =====


    def init_nodes(self, graph: StateGraph):
        """Initialize nodes in the graph"""
        check_state_node = self.get_node_name("CHECK_STATE")
        info_collection_node = self.get_node_name("INFO_COL")
        info_validation_node = self.get_node_name("INFO_VAL")
        pipeline_gen_node = self.get_node_name("PIPELINE_GEN")
        hitl_node = self.get_node_name("HITL")
        check_hitl_node = self.get_node_name("CHECK_HITL")
        pipeline_update_node = self.get_node_name("PIPELINE_UPDATE")
        pipeline_select_node = self.get_node_name("PIPELINE_SELECT")
        pipeline_summary_node = self.get_node_name("PIPELINE_SUMMARY")

        assert check_state_node is not None, "CHECK_STATE node name must be defined"
        assert info_collection_node is not None, "INFO_COL node name must be defined"
        assert info_validation_node is not None, "INFO_VAL node name must be defined"
        assert pipeline_gen_node is not None, "PIPELINE_GEN node name must be defined"
        assert hitl_node is not None, "HITL node name must be defined"
        assert check_hitl_node is not None, "CHECK_HITL node name must be defined"

        assert pipeline_update_node is not None, "PIPELINE_UPDATE node name must be defined"
        assert pipeline_select_node is not None, "PIPELINE_SELECT node name must be defined"
        assert pipeline_summary_node is not None, "PIPELINE_SUMMARY node name must be defined"

        graph.add_node(check_state_node, self.check_state_node)
        graph.add_node(info_collection_node, self.info_collection_node)
        graph.add_node(info_validation_node, self.info_validation_node)
        graph.add_node(pipeline_gen_node, self.pipeline_generation_node)
        graph.add_node(hitl_node, self.hitl_node)
        graph.add_node(check_hitl_node, self.check_hitl_node)
        graph.add_node(pipeline_update_node, self.pipeline_update_node)
        graph.add_node(pipeline_select_node, self.pipeline_selection_node)
        graph.add_node(pipeline_summary_node, self.pipeline_summary_node)


    def init_edges(self, graph: StateGraph):
        """Initialize edges in the graph"""

        check_state_node = self.get_node_name("CHECK_STATE")
        info_collection_node = self.get_node_name("INFO_COL")
        info_validation_node = self.get_node_name("INFO_VAL")
        pipeline_gen_node = self.get_node_name("PIPELINE_GEN")
        hitl_node = self.get_node_name("HITL")
        check_hitl_node = self.get_node_name("CHECK_HITL")
        pipeline_update_node = self.get_node_name("PIPELINE_UPDATE")
        pipeline_select_node = self.get_node_name("PIPELINE_SELECT")
        pipeline_summary_node = self.get_node_name("PIPELINE_SUMMARY")

        assert info_collection_node is not None, "INFO node name must be defined"
        assert pipeline_gen_node is not None, "PIPELINE_GEN node name must be defined"
        assert hitl_node is not None, "HITL node name must be defined"

        # Start → check_state
        graph.add_edge(START, check_state_node)

        # check_state → [END | info_collection_node | check_hitl_node]
        graph.add_conditional_edges(
            check_state_node,
            self.route_after_check,
            [END, info_collection_node, check_hitl_node]
            )

        # info_collection → [END (wait for user) | info_validation_node | pipeline_generation]
        graph.add_conditional_edges(
            info_collection_node,
            self.get_state,
            [END, info_validation_node, info_collection_node]
            )

        # info_validation_node → [END(pipeline agent END!) | pipeline_generation]
        graph.add_conditional_edges(
            info_validation_node,
            self.route_after_info_validation,
            [END, pipeline_gen_node]
        )

        # pipeline_generation → hitl
        graph.add_edge(pipeline_gen_node, hitl_node)

        # hitl → check_hitl
        graph.add_edge(hitl_node, check_hitl_node)

        # check_hitl → [pipeline_summary | pipeline_update | pipeline_selection]
        graph.add_conditional_edges(
            check_hitl_node,
            self.route_after_hitl,
            [pipeline_summary_node, pipeline_update_node, pipeline_select_node]
        )

        # pipeline_update → END
        graph.add_edge(pipeline_update_node, pipeline_summary_node)

        # pipeline_selection → END
        graph.add_edge(pipeline_select_node, pipeline_summary_node)

        # pipeline_summary → END
        graph.add_edge(pipeline_summary_node, END)


    # ===== Check State Node =====

    async def check_state_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Check state node - pass-through node for routing logic

        Note: config parameter is required by LangGraph but not used in this implementation.
        Routing logic is handled by route_after_check function.
        """
        return {}

    # 상태 결정 함수 정의
    # 상태에서 메시지 목록을 가져옴
    def route_after_check(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> Literal["__end__", "info_collection", "check_human_decision"]:
        """state check 이후 라우팅 함수 - 상태에 따라 다음 노드 결정

        Note: config parameter is required by LangGraph but not used in this implementation.

        Routing logic:
        1. If pipeline_summary is True → END (workflow complete)
        2. If info_complete is False → info_collection (need to collect info)
        3. If info_complete is True AND pipeline_generated is True → check_hitl (ready for HITL)
        4. Default → info_collection (fallback)
        """
        # Check if pipeline summary has been generated (workflow complete)
        if state.get("pipeline_summary"):
            return END

        # Check if information collection is incomplete
        if not state.get("info_complete"):
            info_collection_node = self.get_node_name("INFO_COL")
            return info_collection_node

        # Check if info is complete and pipeline is generated (ready for HITL)
        if state.get("info_complete") and state.get("pipeline_generated"):
            check_hitl_node = self.get_node_name("CHECK_HITL")
            return check_hitl_node

        # Default fallback: go to info collection
        info_collection_node = self.get_node_name("INFO_COL")
        return info_collection_node




    # ===== Information Collection Node =====

    def get_messages_with_system(
        self, messages: list[HumanMessage | AIMessage | SystemMessage]
    ) -> list[SystemMessage | HumanMessage | AIMessage]:
        """사용자 메시지 목록을 받아 시스템 메시지와 결합하여 반환"""
        return [SystemMessage(content=self.SYSTEM_TEMPLATE)] + messages

    async def info_collection_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """정보 수집 노드 - 사용자로부터 ST 파이프라인 구축에 필요한 정보 수집

        Note: config parameter is required by LangGraph but not used in this implementation.
        """
        try:
            # 상태에서 메시지 정보를 가져와 시스템 메시지와 결합
            messages = self.get_messages_with_system(state["messages"])
            # LLM을 호출하여 응답 생성
            response = await self.llm_with_tool.ainvoke(messages)

            # 생성된 응답을 메시지 목록으로 반환
            return {"messages": [response]}
        except Exception as e:
            if self.is_debug:
                print(f"Error in info_collection_node: {e}")
            raise e


    # 상태 결정 함수 정의
    # 상태에서 메시지 목록을 가져옴
    def get_state(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> Literal["__end__", "info_validation", "info_collection"]:
        messages = state["messages"]

        # 마지막 메시지가 AIMessage이고 도구 호출이 있는 경우
        if isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            # 도구 메시지를 추가해야 하는 상태 반환
            info_validation_node = self.get_node_name("INFO_VAL")
            return info_validation_node
        # 마지막 메시지가 HumanMessage가 아닌 경우
        elif not isinstance(messages[-1], HumanMessage):
            # 대화 종료 상태 반환
            return END

        # 기본적으로 정보 수집 상태 반환
        info_collection_node = self.get_node_name("INFO_COL")
        return info_collection_node


    # ===== information Validation Node =====

    def route_after_info_validation(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> Literal["__end__", "pipeline_generation"]:
        """info_validation 이후 라우팅 함수

        If both spatial_clustering and celltype_analysis are "no",
        skip pipeline generation and go to END.

        Note: config parameter is required by LangGraph but not used in this implementation.
        """
        spatial_clustering = state.get("spatial_clustering")
        celltype_analysis = state.get("celltype_analysis")

        # If both are "no", no pipeline needed - go directly to END
        if spatial_clustering == "no" and celltype_analysis == "no":
            return END

        # Otherwise, proceed to pipeline generation
        pipeline_gen_node = self.get_node_name("PIPELINE_GEN")
        return pipeline_gen_node


    async def info_validation_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """정보 검증 노드 - 수집된 정보 검증 및 조기 종료 처리

        Note: config parameter is required by LangGraph but not used in this implementation.
        """
        last_message = state["messages"][-1]

        # 검증
        if not isinstance(last_message, AIMessage):
            raise ValueError("마지막 메시지가 AIMessage가 아닙니다")

        if not last_message.tool_calls:
            raise ValueError("도구 호출이 없습니다")

        # ✅ 명확한 변수명으로 미리 추출
        tool_call = last_message.tool_calls[0]
        tool_call_id = tool_call.get("id")
        tool_args = tool_call.get("args", {})

        if not tool_call_id:
            raise ValueError("tool_call_id가 없습니다")

        # Extract collected information
        spatial_clustering = tool_args.get("spatial_clustering")
        celltype_analysis = tool_args.get("celltype_analysis")

        # Check if both are "no" (no pipeline needed - early exit case)
        if spatial_clustering == "no" and celltype_analysis == "no":
            # Set all state from tool_args and mark workflow as complete
            return {
                "messages": [
                    ToolMessage(
                        content="✅ You are ready to analyze cell-cell interaction analysis!\n",
                        tool_call_id=tool_call_id
                    )
                ],
                "st_technology": tool_args.get("st_technology"),
                "disease": tool_args.get("disease"),
                "species": tool_args.get("species"),
                "sample_count": tool_args.get("sample_count"),
                "os_type": tool_args.get("os_type"),
                "gpu_available": tool_args.get("gpu_available"),
                "spatial_clustering": spatial_clustering,
                "celltype_analysis": celltype_analysis,
                "info_complete": True,
                "pipeline_generated": True,
                "pipeline_summary": True,
            }

        # Otherwise, proceed with normal validation
        disease = tool_args.get("disease", "질병")
        technology = tool_args.get("st_technology", "기술")

        return {
            "messages": [
                ToolMessage(
                    content=f"{disease} 연구를 위한 {technology} 파이프라인 생성 준비 완료\n",
                    tool_call_id=tool_call_id
                )
            ]
        }


    # ===== Pipeline Generation Node =====

    async def pipeline_generation_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """파이프라인 생성 노드 - 플랫폼 타입에 기반한 기본 파이프라인 생성

        Note: config parameter is required by LangGraph but not used in this implementation.
        """
        try:
            # Extract collected information from messages
            info = self.extract_info_from_messages(state["messages"])

            if not info.get("st_technology"):
                raise ValueError("ST technology information is missing")

            # Determine platform type
            platform_type = self.get_platform_type(info["st_technology"])

            # Create default pipeline configuration
            pipeline_config = self.create_default_pipeline(platform_type)

            if self.is_debug:
                print(f"Generated default pipeline for {platform_type}:")
                print(f"  - Normalization: {pipeline_config.normalization}")
                print(f"  - Celltype Analysis: {pipeline_config.celltype_analysis}")
                print(f"  - Spatial Clustering: {pipeline_config.spatial_clustering}")

            # Create message to present the default pipeline to user
            pipeline_message = f"""
✅ Information Collection Complete!

Based on your inputs:
- ST Technology: {info['st_technology']} ({platform_type})
- Disease: {info['disease']}
- Species: {info['species']}
- Sample Count: {info['sample_count']}
- OS: {info['os_type']}
- Computing: {info['gpu_available']}

I've generated the following default analysis pipeline:

📊 Pipeline Configuration:
1. Normalization: `{pipeline_config.normalization}`
2. Cell Type Analysis: `{pipeline_config.celltype_analysis}` ({'deconvolution' if platform_type == 'spot-based' else 'annotation'})
3. Spatial Clustering: `{pipeline_config.spatial_clustering}`
"""

            return {
                "messages": [AIMessage(content=pipeline_message)],
                "st_technology": info["st_technology"],
                "disease": info["disease"],
                "species": info["species"],
                "sample_count": info["sample_count"],
                "os_type": info["os_type"],
                "gpu_available": info["gpu_available"],
                "spatial_clustering": info["spatial_clustering"],
                "celltype_analysis": info["celltype_analysis"],
                "pipeline_config": pipeline_config,
                "info_complete": True,
                "pipeline_generated": True,
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error in pipeline_generation_node: {e}")
            raise e


    # ===== HITL (Human-in-the-Loop) Node =====

    async def hitl_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Human-in-the-Loop node - present options and collect user choice

        Uses interrupt() to pause execution and wait for user input.
        For "update" choice, prompts user again for specific modification details.
        Parses user choice and sets hitl_decision for routing.

        Note: config parameter is required by LangGraph but not used in this implementation.
        """
        try:
            # Stage 1: Present main options and pause for user input
            prompt_message = """Please choose one of the following options:

1️⃣ Use Default Pipeline - Proceed with the suggested pipeline
   ↳ Type: "1", "default" or "proceed"

2️⃣ Customize Pipeline - Modify specific components
   ↳ Type: "2", "custom" or "update"

3️⃣ Select Reference-based Pipeline - Use RAG to find methods from literature
   ↳ Type: "3", "reference" or "select"

What would you like to do?"""

            # Wrap the prompt in a dict to ensure proper serialization
            user_choice = interrupt(value={"message": prompt_message})

            # Extract the actual user choice from response
            # Handle both string responses and dict responses for compatibility
            if isinstance(user_choice, dict):
                actual_choice = user_choice.get("response", user_choice.get("message", str(user_choice)))
            else:
                actual_choice = str(user_choice)

            # Parse user choice (case-insensitive)
            choice_lower = actual_choice.lower().strip()

            # Determine decision based on keywords or numbers
            if any(keyword in choice_lower for keyword in ["1", "default", "proceed"]):
                decision = "default"
                return {
                    "hitl_decision": decision,
                    "messages": [HumanMessage(content=f"User choice: {actual_choice}")]
                }

            elif any(keyword in choice_lower for keyword in ["2", "custom", "update", "modify"]):
                decision = "update"

                # Stage 2: Prompt for specific modifications
                current_pipeline = state.get("pipeline_config")
                if not current_pipeline:
                    raise ValueError("No pipeline configuration found in state")

                modification_prompt = f"""You selected to customize the pipeline.

Current Pipeline Configuration:
1. Normalization: `{current_pipeline.normalization}`
2. Cell Type Analysis: `{current_pipeline.celltype_analysis}`
3. Spatial Clustering: `{current_pipeline.spatial_clustering}`

Please specify which components you'd like to modify and your preferred methods.

Examples:
- "Change normalization to SCTransform"
- "Use Cell2location for cell type analysis"
- "Switch spatial clustering to BayesSpace"
- "Use SCTransform and leiden clustering"

What modifications would you like to make?"""

                # Second interrupt to collect modification details - wrap in dict
                modification_details = interrupt(value={"message": modification_prompt})

                # Handle the modification_details response
                if isinstance(modification_details, dict):
                    actual_modification = modification_details.get("response", modification_details.get("message", str(modification_details)))
                else:
                    actual_modification = str(modification_details)

                return {
                    "hitl_decision": decision,
                    "messages": [
                        HumanMessage(content=f"User choice: {actual_choice}"),
                        HumanMessage(content=actual_modification)
                    ]
                }

            elif any(keyword in choice_lower for keyword in ["3", "reference", "select", "rag"]):
                decision = "select"
                return {
                    "hitl_decision": decision,
                    "messages": [HumanMessage(content=f"User choice: {actual_choice}")]
                }

            else:
                # Fallback to default if unclear
                decision = "default"
                return {
                    "hitl_decision": decision,
                    "messages": [HumanMessage(content=f"{actual_choice} (defaulting to default pipeline)")]
                }

        except Exception as e:
            if self.is_debug:
                print(f"Error in hitl_node: {e}")
            raise e


    # ===== Check HITL Node =====

    async def check_hitl_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Check HITL node - pass-through node for routing logic

        Note: config parameter is required by LangGraph but not used in this implementation.
        Routing logic is handled by route_after_hitl function.
        """
        return {}

    def route_after_hitl(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> Literal["pipeline_summary", "pipeline_update", "pipeline_selection"]:
        """HITL 이후 라우팅 함수 - 사용자 결정에 따라 다음 노드 결정

        Note: config parameter is required by LangGraph API but not used in this implementation.
        """
        decision = state.get("hitl_decision")

        if decision == "default":
            # Route to pipeline_summary node (which will then end naturally)
            pipeline_summary_node = self.get_node_name("PIPELINE_SUMMARY")
            return pipeline_summary_node
        elif decision == "update":
            pipeline_update_node = self.get_node_name("PIPELINE_UPDATE")
            return pipeline_update_node
        elif decision == "select":
            pipeline_select_node = self.get_node_name("PIPELINE_SELECT")
            return pipeline_select_node

        # Default fallback: go to pipeline_summary
        pipeline_summary_node = self.get_node_name("PIPELINE_SUMMARY")
        return pipeline_summary_node


    # ===== Pipeline Update Node =====

    async def pipeline_update_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """파이프라인 업데이트 노드 - 사용자 지정 파이프라인 수정 적용

        Note: config parameter is required by LangGraph but not used in this implementation.
        """
        try:
            messages = state["messages"]
            current_pipeline = state.get("pipeline_config")

            if not current_pipeline:
                raise ValueError("No pipeline configuration found in state")

            # Get the last user message with update instructions
            user_message = None
            for message in reversed(messages):
                if isinstance(message, HumanMessage):
                    user_message = message.content
                    break

            if not user_message:
                raise ValueError("No user message found for pipeline update")

            # For now, use a simple parsing approach
            # In production, you might want to use LLM with structured output for better parsing
            updated_pipeline = PipelineConfig(
                normalization=current_pipeline.normalization,
                celltype_analysis=current_pipeline.celltype_analysis,
                spatial_clustering=current_pipeline.spatial_clustering,
                platform_type=current_pipeline.platform_type,
            )

            user_lower = user_message.lower()

            # Parse normalization updates
            if "sctransform" in user_lower:
                updated_pipeline.normalization = "SCTransform"
            elif "pearson" in user_lower:
                updated_pipeline.normalization = "pearson residuals"
            elif "log" in user_lower and "normalization" in user_lower:
                updated_pipeline.normalization = "log"

            # Parse celltype analysis updates
            if "cell2location" in user_lower or "cell 2 location" in user_lower:
                updated_pipeline.celltype_analysis = "Cell2location"
            elif "cytetype" in user_lower:
                updated_pipeline.celltype_analysis = "CyteType"
            elif "tangram" in user_lower:
                updated_pipeline.celltype_analysis = "Tangram"
            elif "iris" in user_lower and ("celltype" in user_lower or "cell type" in user_lower):
                updated_pipeline.celltype_analysis = "IRIS"

            # Parse spatial clustering updates
            elif "bayesspace" in user_lower or "bayes space" in user_lower:
                updated_pipeline.spatial_clustering = "BayesSpace"
            elif "leiden" in user_lower:
                updated_pipeline.spatial_clustering = "leiden"
            elif "louvain" in user_lower:
                updated_pipeline.spatial_clustering = "louvain"
            elif "iris" in user_lower and ("clustering" in user_lower or "cluster" in user_lower):
                updated_pipeline.spatial_clustering = "IRIS"

            if self.is_debug:
                print("Updated pipeline:")
                print(f"  - Normalization: {updated_pipeline.normalization}")
                print(f"  - Celltype Analysis: {updated_pipeline.celltype_analysis}")
                print(f"  - Spatial Clustering: {updated_pipeline.spatial_clustering}")

            # Create confirmation message
            confirmation_message = f"""
✅ Pipeline Updated Successfully!

Updated Pipeline Configuration:
1. Normalization: `{updated_pipeline.normalization}`
2. Cell Type Analysis: `{updated_pipeline.celltype_analysis}`
3. Spatial Clustering: `{updated_pipeline.spatial_clustering}`

Your customized pipeline is ready to use!
"""

            return {
                "messages": [AIMessage(content=confirmation_message)],
                "pipeline_config": updated_pipeline,
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error in pipeline_update_node: {e}")
            raise e


    # ===== Pipeline Selection Node (RAG-based) =====

    async def _init_mcp_client(self):

        """Initialize MCP client for langconnect-rag if not already initialized"""
        if self.mcp_client is not None:
            return self.mcp_client

        try:
            import os

            # Get langconnect paths from environment
            CCI_RAG_python = os.getenv("LANGCONNECT_PYTHON")
            CCI_RAG_server = os.getenv("LANGCONNECT_SERVER")
            CCI_RAG_base_url = os.getenv("API_BASE_URL")

            client = MultiServerMCPClient({
                "server-sequential-thinking": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
                    "transport": "stdio",
                },
                "langconnect-mcp": {
                    "command": CCI_RAG_python,
                    "args": [CCI_RAG_server],
                    "env": {
                        "API_BASE_URL": CCI_RAG_base_url
                    },
                    "transport": "stdio",
                }
            })

            self.mcp_client = client

            if self.is_debug:
                print("MCP client initialized successfully")

            return self.mcp_client

        except Exception as e:
            if self.is_debug:
                print(f"Failed to initialize MCP client: {e}")
            raise e


    async def pipeline_selection_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """파이프라인 선택 노드 - RAG 기반 reference pipeline 구축

        Note: config parameter is required by LangGraph but not used in this implementation.
        """
        try:
            # Initialize MCP client
            mcp_client = await self._init_mcp_client()

            # Get collected information
            st_technology = state.get("st_technology")
            disease = state.get("disease")
            species = state.get("species")
            current_pipeline = state.get("pipeline_config")

            if not all([st_technology, disease, current_pipeline]):
                raise ValueError("Missing required information for pipeline selection")

            if self.is_debug:
                print("Starting RAG-based pipeline selection...")

            # Step 1: List collections to find 'pipeline' collection
            tools = await mcp_client.get_tools()
            list_collections_tool = next((t for t in tools if t.name == "list_collections"), None)

            if not list_collections_tool:
                raise ValueError("list_collections tool not found in MCP server")

            collections_result = await list_collections_tool.ainvoke({})

            if self.is_debug:
                print(f"Collections result: {collections_result}")

            # Parse collections to find 'pipeline' collection ID
            # The result format might vary, so we need to handle it carefully
            collection_id = None
            if isinstance(collections_result, str):
                # Try to parse as text
                if "pipeline" in collections_result.lower():
                    # Extract collection ID from the result
                    # This is a simplified approach; adjust based on actual format
                    import re
                    match = re.search(r'pipeline.*?id["\s:]+([a-f0-9-]+)', collections_result, re.IGNORECASE)
                    if match:
                        collection_id = match.group(1)

            if not collection_id:
                if self.is_debug:
                    print("Pipeline collection not found, using default pipeline")
                # Fallback to default pipeline
                return {
                    "messages": [AIMessage(content="""
⚠️ Could not find the 'pipeline' collection in the RAG system.

Using the default pipeline instead:
1. Normalization: `{current_pipeline.normalization}`
2. Cell Type Analysis: `{current_pipeline.celltype_analysis}`
3. Spatial Clustering: `{current_pipeline.spatial_clustering}`
""")]
                }

            # Step 2: Generate multiple queries using multi_query
            multi_query_tool = next((t for t in tools if t.name == "multi_query"), None)

            if multi_query_tool:
                # Generate queries for each pipeline component
                base_question = f"Find appropriate methods for {st_technology} {disease} analysis in {species}"

                multi_query_result = await multi_query_tool.ainvoke({"question": base_question})

                if self.is_debug:
                    print(f"Generated queries: {multi_query_result}")
            else:
                # Fallback: create manual queries
                multi_query_result = [
                    f"normalization methods for {st_technology} {disease}",
                    f"cell type analysis for {st_technology} {species} {disease}",
                    f"spatial clustering for {st_technology}",
                ]

            # Step 3: Search documents for each query
            search_tool = next((t for t in tools if t.name == "search_documents"), None)

            if not search_tool:
                raise ValueError("search_documents tool not found in MCP server")

            all_results = []
            for query in multi_query_result if isinstance(multi_query_result, list) else [multi_query_result]:
                search_result = await search_tool.ainvoke({
                    "collection_id": collection_id,
                    "query": str(query),
                    "search_type": "hybrid",
                    "limit": 5,
                })
                all_results.append(search_result)

                if self.is_debug:
                    print(f"Search results for '{query}': {search_result}")

            # Step 4: Extract tool names from results
            # Tool names are stored as file names in the documents
            selected_pipeline = PipelineConfig(
                normalization=current_pipeline.normalization,
                celltype_analysis=current_pipeline.celltype_analysis,
                spatial_clustering=current_pipeline.spatial_clustering,
                platform_type=current_pipeline.platform_type,
            )

            # Parse results to extract relevant tool names
            # This is a simplified approach - in production, use LLM to parse results
            for result in all_results:
                result_str = str(result).lower()

                # Look for normalization methods
                if "sctransform" in result_str:
                    selected_pipeline.normalization = "SCTransform"
                elif "pearson" in result_str:
                    selected_pipeline.normalization = "pearson residuals"

                # Look for celltype analysis methods
                if "cell2location" in result_str:
                    selected_pipeline.celltype_analysis = "Cell2location"
                elif "tangram" in result_str:
                    selected_pipeline.celltype_analysis = "Tangram"
                elif "cytetype" in result_str:
                    selected_pipeline.celltype_analysis = "CyteType"

                # Look for spatial clustering methods
                if "bayesspace" in result_str:
                    selected_pipeline.spatial_clustering = "BayesSpace"
                elif "leiden" in result_str:
                    selected_pipeline.spatial_clustering = "leiden"
                elif "louvain" in result_str:
                    selected_pipeline.spatial_clustering = "louvain"

            if self.is_debug:
                print("Selected reference-based pipeline:")
                print(f"  - Normalization: {selected_pipeline.normalization}")
                print(f"  - Celltype Analysis: {selected_pipeline.celltype_analysis}")
                print(f"  - Spatial Clustering: {selected_pipeline.spatial_clustering}")

            # Create result message
            result_message = f"""
✅ Reference-based Pipeline Selected!

Based on relevant literature and methods in the RAG database:

Selected Pipeline Configuration:
1. Normalization: `{selected_pipeline.normalization}`
2. Cell Type Analysis: `{selected_pipeline.celltype_analysis}`
3. Spatial Clustering: `{selected_pipeline.spatial_clustering}`

This pipeline was selected based on published methods for {st_technology} analysis.
"""

            return {
                "messages": [AIMessage(content=result_message)],
                "pipeline_config": selected_pipeline,
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error in pipeline_selection_node: {e}")

            # Fallback to default pipeline on error
            current_pipeline = state.get("pipeline_config")
            if current_pipeline:
                # Handle both dict and PipelineConfig object
                if isinstance(current_pipeline, dict):
                    norm = current_pipeline.get("normalization", "unknown")
                    celltype = current_pipeline.get("celltype_analysis", "unknown")
                    spatial = current_pipeline.get("spatial_clustering", "unknown")
                else:
                    norm = current_pipeline.normalization
                    celltype = current_pipeline.celltype_analysis
                    spatial = current_pipeline.spatial_clustering

                error_message = f"""
⚠️ Error during RAG-based pipeline selection

Error: {str(e)}

Using the default pipeline instead:
1. Normalization: `{norm}`
2. Cell Type Analysis: `{celltype}`
3. Spatial Clustering: `{spatial}`
"""
                return {"messages": [AIMessage(content=error_message)]}

            raise e



    async def pipeline_summary_node(
        self, state: STPipelineBuilderState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Generate the final ST analysis pipeline based on collected information and search results.

        Note: config parameter is required by LangGraph but not used in this implementation.
        """
        pipeline_prompt = create_pipeline_prompt(state)

        response = await self.model.ainvoke([SystemMessage(content=pipeline_prompt)] + state["messages"])
        return {
            "messages": [response],
            "pipeline_summary": True,
        }
