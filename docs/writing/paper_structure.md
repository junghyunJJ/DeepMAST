# DeepMAST Paper Framing

이 문서는 DeepMAST 논문의 narrative, Introduction/Results 구조, figure framing, reference positioning을 정리한 writing blueprint입니다. 전체 Results는 MEDEA의 system-overview/benchmark/ablation 흐름, SpatialAgent의 spatial biology use-case framing, SPARK의 staged reasoning and verification logic을 참고하되, DeepMAST의 중심 contribution은 **MCP/tool access를 domain-specific control layer로 제약, 검증, 증거화하는 evidence-governed biological agent harness**로 잡습니다. 핵심 정체성은 **evidence-governed harness**이고, 구조적 작동 원리는 **validation-driven looping**입니다.

**Central thesis**

DeepMAST is built on the premise that reliable spatial transcriptomics agents require more than access to MCP servers or biological tools. MCP standardizes how tools are called, but it does not specify how tools should be selected, sequenced, validated, interpreted, or converted into therapeutic evidence. The central governance target is therefore not only tool use, but the biological and therapeutic claims that survive into the final report. DeepMAST addresses this gap through harness engineering: a non-model control layer that surrounds LLM agents with domain-specific skills, stage-specific tool constraints, structured intermediate artifacts, provenance-aware reporting, claim-level validation, deterministic rendering, fail-closed finalization, literature-grounded interpretation, explicit therapeutic target scoring, and expert-reviewable reports. In this framing, DeepMAST operationalizes harness engineering through validation-driven looping: intermediate artifacts are checked for coverage, relevance, provenance, claim support, and report readiness, and failed checks trigger bounded refinement or fail-closed withholding rather than direct finalization.

**Problem / gap / solution**

- **Problem:** Spatial transcriptomics can reveal spatially localized disease programs, but therapeutic interpretation requires selecting the right biological tools, executing them in a defensible order, validating their outputs, integrating results with literature and disease context, and deciding which claims are evidence-supported enough to report.
- **Gap:** Tool access alone does not define scientific reasoning. Without domain-specific skills, verification rules, provenance tracking, evidence-integration protocols, and claim-level governance, agents can call valid tools in inappropriate contexts or generate plausible but unsupported therapeutic claims.
- **Solution:** DeepMAST treats MCP servers and biological tools as resources inside a broader biological harness. Domain skills encode how tools should be selected and interpreted, while validation-driven loops, provenance checks, literature grounding, evidence scoring, and deterministic finalization govern whether an output can become a scientific or therapeutic conclusion.

**Positioning against prior work**

Manuscript-facing references are numbered by first appearance from the Introduction Draft onward. See the `References` section at the end.

Use a conservative claim boundary. Do not argue that prior systems lack harness engineering entirely, because general harness-oriented work already studies action constraints, runtime behavior, verification, and externalized control layers [48-50]. Instead, position prior Agent Skills work as focused on reusable procedural packages, skill selection, and evaluation [19-28]; scientific skill-library work as extending skill construction into genomics workflows such as spatial transcriptomics cell type annotation and single-cell scDRS [29]; and biomedical agent systems as emphasizing workflow automation, tool access, spatial/omics interpretation, or therapeutic reasoning [9-13,51]. DeepMAST’s gap is the integration of these directions into a **skill-inclusive, evidence-governed biological harness** for spatial transcriptomics interpretation, transparent therapeutic target prioritization, validation-driven looping, and governance over evidence-bearing claims.

**Model notation**

Use manuscript-facing model names as `Qwen3.5-35B`, `Qwen3.5-122B`, and `Qwen3.5-397B`. Avoid capability-adjective labels for model-size groups in prose. Raw runtime tags may appear only in Methods or source-artifact notes when needed for reproducibility, for example `qwen3.5:397b-cloud`.

**Operational definition**

```text
We define harness engineering as the design of the non-model control layer around an LLM agent, including domain-specific instructions, skill activation, tool-use constraints, staged execution, validation-driven loops, provenance tracking, claim-level validation, and evaluation procedures that make agent outputs auditable, reproducible, and reviewable by domain experts [48-50].
```

For DeepMAST, the harness is the domain-specific control layer surrounding the LLM: it activates task-relevant biological skills, constrains MCP tool use by analysis stage, separates biological interpretation from target scoring, routes LLM outputs through structured artifacts, verifies evidence provenance, and renders scientific or therapeutic conclusions only when they are supported by traceable sources and pass deterministic checks. Its structural operating principle is validation-driven looping: coverage checks, relevance gates, provenance validators, claim-quality checks, and finalization-readiness checks decide whether an intermediate artifact is refined, retried, withheld, or promoted to an expert-reviewable conclusion. This makes DeepMAST closer to an evidence-governed biomedical agent harness than to a tool-executing spatial transcriptomics agent.

**Defensible claim boundary**

DeepMAST should be described as applying harness engineering most strongly to its core scientific interpretation pipelines, especially the drug-target and deep-interpretation pathways. The Pipeline Builder and Pipeline Executor are important expert agents that provide the analytical substrate, HITL workflow construction, MCP readiness checks, and tool execution, but they should not be described as having the same hard finalization gates as the drug-target reporting path. Avoid broad across-all-agent claims that imply identical hard gates in every module. A safer formulation is:

```text
DeepMAST applies harness engineering to its core biomedical interpretation pipelines by routing LLM outputs through staged execution, tool constraints, structured artifacts, validation-driven loops, provenance-aware validation, deterministic rendering, and fail-closed finalization where implemented.
```

## Overall Paper Structure

### Title

최종 제목은 아래로 고정합니다. 핵심 contribution은 **evidence-governed agent harness**이고, `Spatial Transcriptomics`는 중간에 넣지 않고 제목 끝의 application-domain qualifier로 둡니다. `validation-driven looping`은 제목에 직접 넣지 않고 Abstract, Introduction, Figure 1/2, Discussion에서 harness의 구조적 작동 원리로 반복해서 설명합니다.

```text
DeepMAST: An Evidence-Governed Agent Harness for Literature-Grounded Interpretation and Therapeutic Target Prioritization in Spatial Transcriptomics
```

`DeepMAST` 이름은 유지하되, 제목에서 DeepAgents 구현 의존성을 직접 설명하지 않습니다. DeepAgents는 Introduction/Methods에서 long-horizon orchestration substrate로 설명하고, 제목은 governance/reliability 방향성과 claim-level evidence control을 전면에 둡니다. “drug target discovery”는 강한 표현이고, 실험검증이 있는 IPF에서는 가능하지만 전체 논문에서는 “therapeutic target prioritization”이 더 안전합니다.

Acronym/name-origin 설명은 제목이나 Abstract 첫 문장에 넣지 않습니다. 필요하면 Architecture 또는 Methods에서만 약하게 설명합니다:

```text
The DeepMAST name reflects its DeepAgents-based, multi-agent spatial transcriptomics architecture; however, its primary contribution is an evidence-governed harness for biological interpretation and therapeutic target prioritization, operationalized through validation-driven looping.
```

---

## Introduction Draft

Draft note. References in the manuscript-facing draft are numbered by first appearance from this Introduction Draft onward and should remain in that order when this text is moved into the final manuscript.

Spatial transcriptomics links gene expression to tissue architecture by preserving spatial coordinates during transcriptome-wide profiling of intact tissue sections [1]. This capability has transformed studies of tissue organization, development, and disease by enabling investigators to ask where molecular programs occur, how cellular neighborhoods are arranged, and how spatially localized signals relate to pathological context [2]. Integration with single-cell transcriptomics extends this framework to cell-state mapping, niche analysis, intercellular-communication inference, and tissue-dynamics reconstruction [3]. However, the same data richness that makes spatial transcriptomics powerful also creates a translation bottleneck. Spatial resolution, assay throughput, morphology, cell-type annotation, spatially variable gene detection, cell-cell interaction inference, multimodal integration, and analytical strategy must be handled together [4]. Spatial patterns become therapeutically useful only when candidate signals are linked to disease mechanism, target-disease relevance, drug mechanism-of-action reasoning, and the limits of the underlying analysis [5]. In agentic analysis settings, this challenge is not only computational but evidentiary. An agent must select biologically appropriate tools, preserve context across long-horizon analyses, retrieve relevant evidence, interpret intermediate outputs, and decide whether a biological or target-prioritization claim is sufficiently supported to enter a reviewable scientific report [6-8].

Recent biomedical, spatial-biology, pathology, and omics agents show that large language model workflows can automate tool execution, literature retrieval, multimodal interpretation, verification, and report generation [9-16]. STAgent and SpatialAgent demonstrate this shift in spatial biology, while SPARK and MEDEA extend staged verification and evidence reconciliation to pathology and omics discovery [11-13,16]. Thus, DeepMAST does not need to argue that agentic analysis is absent. The remaining question is how agent-generated outputs are governed once they begin to support biological or therapeutic claims.

We use harness to mean the non-model control layer that surrounds an LLM agent rather than the model itself. A harness maintains task state, activates skills, constrains tool use, checks intermediate artifacts, preserves provenance, and decides whether feedback should trigger refinement or finalization. DeepAgents and the Model Context Protocol provide useful orchestration and resource-access primitives for this role [17-18]. Agent Skills and recent harness studies further suggest that long-horizon performance depends less on raw context length, tool-call volume, or harness size than on reusable procedures, task-relevant state, valid feedback, and failure-derived rules that remain active across subsequent actions [19-34].

Despite this progress, spatial-transcriptomics agents and general-purpose harnesses still leave a domain-specific gap between tool execution and claim finalization. Spatial-biology agents can automate analysis and interpretation, and verification-aware omics agents can validate plans, executions, and evidence streams, but neither tool access nor general orchestration specifies how spatial-omics outputs should become evidence-bounded biological or therapeutic-prioritization claims. The unresolved need is claim governance, a domain-specific biological harness that treats candidate tool outputs and LLM-generated interpretations as provisional artifacts in a claim lifecycle. In this lifecycle, claims are refined, retried, withheld, or finalized according to evidence provenance, analytical context, and review readiness.

To address this gap, we present DeepMAST, an evidence-governed multi-agent harness for spatial transcriptomics interpretation and therapeutic target prioritization. DeepMAST uses DeepAgents as a long-horizon, file-mediated orchestration substrate and MCP-enabled tools as governed analytical resources rather than interchangeable endpoints [17-18]. Its domain-specific control layer activates task-relevant biological skills, constrains tool use by analysis stage, separates literature-grounded biological interpretation from target prioritization, verifies evidence provenance, scores target-relevant evidence, preserves failure and refinement state, and governs which biological or target-prioritization claims can survive into expert-reviewable reports. We evaluate DeepMAST in three steps. First, we define its architecture as a biological harness around agentic tool use. Second, we test retrieval-side evidence acquisition, source-grounded retrieval, and claim-governance controls spanning structured CCI interpretation and breast cancer Evidence-Grounded Follow-up Recommendations. Third, we apply the harness to complementary cancer Visium workflows and then extend the analysis to mouse Alzheimer single-cell-resolution spatial transcriptomics and human idiopathic pulmonary fibrosis target-prioritization. Across these evaluations, DeepMAST treats LLM-generated conclusions as intermediate artifacts rather than final answers. Unsupported or incomplete artifacts are routed through provenance-aware validation, bounded refinement, deterministic rendering, and fail-closed finalization. In this way, DeepMAST is designed to produce not simply more automated spatial-transcriptomics workflows, but more traceable biological and therapeutic claims.

---

## Introduction Structure

### 1. Spatial transcriptomics creates interpretation and translation bottlenecks

Draft 첫 문단과 대응합니다. 시작은 spatial transcriptomics의 장점에서 출발하되, 곧바로 interpretation and translation bottleneck으로 좁힙니다.

내용
- Spatial transcriptomics maps gene expression to tissue architecture by preserving spatial coordinates during transcriptome-wide profiling of intact tissue sections [1].
- Modern sequencing- and imaging-based spatial transcriptomics technologies enable exploratory and confirmatory analysis across development, tissue organization, and disease contexts, including cancer [2].
- Integration with single-cell transcriptomics further supports cell-state, niche, intercellular-communication, and tissue-dynamics interpretation, but it also introduces nontrivial mapping and deconvolution problems [3].
- High-throughput spatially resolved transcriptomic data create computational and interpretive bottlenecks because spatial resolution, assay throughput, morphology, cell-type annotation, spatially variable gene detection, cell-cell interaction inference, and multimodal integration must be handled jointly [4].
- Using spatial patterns for therapeutic target prioritization remains difficult because candidate signals must be connected to disease mechanism, target-disease relevance, drug mechanism-of-action reasoning, and the limitations of the underlying analytical strategy [5].

핵심 문장

```text
Spatial transcriptomics can reveal where disease programs occur by linking gene expression to tissue architecture and cellular context [1-3], but identifying which spatially localized signals are biologically meaningful, computationally robust, and therapeutically actionable remains a major bottleneck [4-5].
```

전환 문장

```text
This bottleneck becomes sharper in agentic analysis settings, where spatial signals must be routed through tool selection, evidence retrieval, biological interpretation, and target-prioritization decisions before they can support reviewable scientific claims.
```

### 2. Prior biomedical and spatial agents establish agentic capability

Draft 둘째 문단과 대응합니다. 기존 agent 성취를 길게 나열하지 않고, agentic biomedical analysis가 이미 가능하다는 점을 인정한 뒤 governance 질문으로 넘어갑니다.

내용
- Prior biomedical, spatial-biology, pathology, and omics agents already demonstrate tool execution, literature retrieval, multimodal interpretation, verification, evidence reconciliation, benchmarking, and report generation [9-16].
- STAgent and SpatialAgent should be used as the spatial biology bridge, while SPARK and MEDEA support staged verification and evidence reconciliation framing [11-13,16].
- 이 문단의 목적은 기존 agent들도 이미 많은 것을 보여주었다는 점을 인정하는 것입니다.
- DeepMAST의 질문은 agentic analysis가 가능한가가 아니라, agent-generated outputs가 biological or therapeutic claims로 승격될 때 어떻게 governance되는가입니다.

문단 구성
- Paragraph A compresses existing biomedical and spatial agents into one bridge.
- Paragraph B closes with the governance question that motivates the harness definition.

핵심 문장

```text
Recent biomedical, spatial-biology, pathology, and omics agents show that large language model workflows can automate tool execution, literature retrieval, multimodal interpretation, verification, and report generation [9-16]. Thus, DeepMAST does not need to argue that agentic analysis is absent. The remaining question is how agent-generated outputs are governed once they begin to support biological or therapeutic claims.
```

전환 문장

```text
This governance question requires defining the harness as the control layer around the model rather than treating the LLM or tool server as the full system.
```

### 3. Harness defines the non-model control layer around LLM agents

Draft 셋째 문단과 대응합니다. 여기서 harness를 처음 명시적으로 정의하고, DeepAgents, MCP, Agent Skills, recent harness studies를 한 묶음으로 연결합니다.

내용
- Harness는 LLM 자체가 아니라 LLM 주변의 non-model control layer로 정의합니다.
- Harness는 task state, skill activation, tool constraints, artifact validation, provenance, feedback retention, and finalization gates를 관리합니다.
- DeepAgents and MCP provide orchestration and resource-access primitives [17-18].
- Agent Skills and recent harness studies support the claim that long-horizon agent performance depends on reusable procedures, task-relevant state, valid feedback, and failure-derived rules rather than only raw context length, tool-call volume, or harness size [19-34].
- 이 문단에서는 아직 DeepMAST novelty를 길게 풀지 않고, 독자에게 harness terminology를 익숙하게 만드는 것이 목적입니다.

문단 구성
- Paragraph A defines harness in plain language.
- Paragraph B links general harness primitives to DeepAgents, MCP, Agent Skills, and recent harness studies.

핵심 문장

```text
We use harness to mean the non-model control layer that surrounds an LLM agent rather than the model itself. A harness maintains task state, activates skills, constrains tool use, checks intermediate artifacts, preserves provenance, and decides whether feedback should trigger refinement or finalization.
```

전환 문장

```text
These primitives are necessary for long-horizon agent execution, but they do not by themselves specify how spatial-omics outputs should become evidence-bounded biological or therapeutic-prioritization claims.
```

### 4. Domain-specific gap is claim governance, not tool access

Draft 넷째 문단과 대응합니다. 여기서는 tool access나 general-purpose orchestration의 부족이 아니라, claim finalization 직전의 domain-specific governance가 빠져 있다는 점을 강조합니다.

내용
- Spatial-biology agents can automate analysis and interpretation.
- Verification-aware omics and pathology agents can validate plans, executions, and evidence streams.
- General harnesses can support planning, state management, skills, and tool access.
- 그러나 이 조합만으로 spatial-omics outputs가 evidence-bounded biological or therapeutic-prioritization claims로 승격되는 기준이 생기지는 않습니다.
- The unresolved need is claim governance, where candidate tool outputs and LLM-generated interpretations remain provisional until evidence provenance, analytical context, and review readiness are sufficient [6-8,14-15].
- Claim outcomes should be described as refined, retried, withheld, or finalized.

문단 구성
- Paragraph A states what prior agents and general harnesses can already do.
- Paragraph B states the remaining domain-specific gap as claim governance.
- Paragraph C defines the claim lifecycle language used later in Figure 3.

핵심 문장

```text
Despite this progress, spatial-transcriptomics agents and general-purpose harnesses still leave a domain-specific gap between tool execution and claim finalization. The unresolved need is claim governance, a domain-specific biological harness that treats candidate tool outputs and LLM-generated interpretations as provisional artifacts in a claim lifecycle.
```

닫는 문장

```text
In this lifecycle, claims are refined, retried, withheld, or finalized according to evidence provenance, analytical context, and review readiness.
```

### 5. DeepMAST contribution and roadmap

Draft 마지막 문단과 대응합니다. 여기서는 DeepMAST가 무엇인지 정의하고, 이어지는 Results의 evidence 흐름을 짧게 예고합니다.

내용
- DeepMAST is an evidence-governed multi-agent harness for spatial transcriptomics interpretation and therapeutic target prioritization.
- DeepAgents is described as the long-horizon, file-mediated orchestration substrate [17-18].
- MCP-enabled tools are governed analytical resources rather than interchangeable endpoints.
- The domain-specific control layer activates skills, constrains tool use, separates biological interpretation from target prioritization, verifies provenance, scores target-relevant evidence, preserves failure and refinement state, and governs finalizable claims.
- Evaluation roadmap should follow architecture, evidence acquisition and source grounding, claim-governance controls, complementary cancer Visium workflows, Alzheimer STARmapPLUS, and IPF target-prioritization.

문단 구성
- Paragraph A presents DeepMAST and its control layer.
- Paragraph B previews the evaluation sequence.
- Paragraph C closes on traceable biological and therapeutic claims rather than more automation.

핵심 문장

```text
Here, we present DeepMAST, an evidence-governed multi-agent harness for spatial transcriptomics interpretation and therapeutic target prioritization. DeepMAST uses DeepAgents as a long-horizon, file-mediated orchestration substrate and MCP-enabled tools as governed analytical resources rather than interchangeable endpoints [17-18]. Its domain-specific control layer activates task-relevant skills, constrains tool use by analysis stage, separates literature-grounded biological interpretation from target prioritization, verifies evidence provenance, scores target-relevant evidence, preserves failure and refinement state, and governs which biological or therapeutic-prioritization claims can survive into expert-reviewable reports. We evaluate DeepMAST by first defining its architecture, then testing evidence acquisition, source-grounded retrieval, and claim-governance controls, and finally applying the harness across complementary cancer Visium workflows, mouse Alzheimer single-cell-resolution spatial transcriptomics, and human idiopathic pulmonary fibrosis target-prioritization analyses. Across these evaluations, DeepMAST treats LLM-generated conclusions as intermediate artifacts rather than final answers, routing them through provenance-aware validation, bounded refinement, deterministic rendering, and fail-closed finalization.
```

---

# Results Structure

Results는 **architecture -> evidence acquisition/source grounding -> claim governance -> biological applications -> translational application** 흐름으로 정리하는 것을 추천합니다. Section 1에서 DeepMAST의 architecture를 먼저 정의한 뒤, Section 2에서 evidence가 system 안으로 들어오는 두 control point, 즉 citable biological context coverage와 source-grounded retrieval을 보여줍니다. Section 3에서는 그 evidence가 실제 biological claim으로 바뀌는 지점의 governance를 보여주며 structured SKILL CCI benchmark와 breast cancer Evidence-Grounded Follow-up Recommendations validation을 같은 bridge figure로 묶습니다. Breast cancer Deep Target Prioritizer output은 독립 main panel이 아니라 follow-up recommendation validation에 사용된 fixed evidence package로 본문과 Supplementary Data/Table에서 설명합니다. 이후 Section 4부터 complementary cancer Visium workflows, Alzheimer STARmapPLUS, IPF target-prioritization application으로 넘어갑니다. 이 흐름은 MEDEA의 system/verified-planning 이후 benchmark 전개, SPARK의 design/verification 이후 use-case 전개, SpatialAgent/STAgent의 실제 spatial output 중심 use-case figure framing을 참고하되, DeepMAST의 중심 novelty를 **tool access가 아니라 evidence-governed biological harness control layer**로 유지합니다.

Benchmarking design을 독립 Results 섹션 여러 개로 길게 떼지는 않습니다. 대신 Section 2와 Section 3을 짧은 two-step validation bridge로 둡니다:

```text
Having defined DeepMAST as an evidence-governed biological harness, we next evaluated two stages of the control layer before applying it to disease datasets: first, whether the harness improves acquisition and retrieval of source-grounded evidence; and second, whether structured guidance constrains the biological claims generated from that evidence.
```

이 문단 뒤에 Figure 2는 evidence acquisition/source-grounding benchmark, Figure 3은 claim-governance benchmark로 이어가면 됩니다. 각 panel은 같은 논리 문법을 따릅니다:

```text
[Harness component] validates [intermediate artifact] and reduces [measurable failure point]
```

---

## 1. DeepMAST is an evidence-governed biological agent harness for spatial transcriptomics interpretation and target prioritization

이 섹션은 전체 구조는 유지하되, agent별 역할과 claim boundary를 조금 더 정밀하게 업데이트합니다. Pipeline Builder와 Pipeline Executor는 DeepMAST의 analytical substrate로 자세히 설명하되 main novelty로 과도하게 올리지 않습니다. 중심 해석 모듈은 **Deep Target Prioritizer**와 **Deep Interpreter**로 통일합니다. STAgent와 SpatialAgent가 이미 spatial-transcriptomics agent automation, tool execution, multimodal interpretation, and spatial-biology workflow automation을 강하게 보여주기 때문에, DeepMAST는 그 위에 **skills, staged constraints, Summary-Guided Chunk Promotion (SGCP), evidence scoring, provenance checks, deterministic report finalization**을 결합한 evidence-governed biological harness로 포지셔닝합니다. 가장 안전한 claim은 DeepMAST가 모든 모듈에 동일한 hard gate를 적용한다는 것이 아니라, core biomedical interpretation pipelines에서 validation-driven looping을 통해 intermediate artifacts를 refinement, withholding, finalization으로 라우팅한다는 것입니다.

DeepMAST takes as input spatial transcriptomics data together with a natural-language biological question or analysis objective. To support users with different levels of spatial-omics expertise, DeepMAST accepts either high-level biological goals or structured pipeline choices and returns an auditable, expert-reviewable report that links spatial patterns to literature-grounded interpretation and therapeutic target evidence. DeepMAST couples a central orchestrator with four expert agents shown in Figure 1a, including Pipeline Builder, Pipeline Executor, Deep Target Prioritizer, and Deep Interpreter. The system uses MCP to standardize access to external analysis tools and biological resources [18], and uses LangGraph and DeepAgents to support stateful orchestration, subagent delegation, filesystem-mediated context management, and human-in-the-loop control during long-horizon analyses [17,35].

The Pipeline Builder and Pipeline Executor form the analytical substrate. The Pipeline Builder collects study metadata, validates information completeness, and constructs analysis workflows through three user-facing modes, including a default spatial transcriptomics pipeline, a user-specified custom pipeline, or a reference-guided pipeline selected from retrieved papers. The Pipeline Executor loads spatial data, resolves the optimal single-cell reference when spot-based platforms have multiple candidate references, checks MCP readiness, executes the configured workflow through a ReAct-style execution core, and saves structured intermediate outputs. Supplementary Figure S1 provides Pipeline Builder details linked to Figure 1, and Supplementary Figure S2 provides Pipeline Executor details linked to Figure 1.

The Deep Target Prioritizer and Deep Interpreter concentrate the evidence-governed claim layer. Supplementary Figure S3 provides Deep Target Prioritizer and Deep Interpreter details linked to Figure 1. The Deep Target Prioritizer receives ligand-receptor candidates and applies a staged evidence funnel in which an evidence-assessor subagent integrates target-validation, genetic, biological-context, protein-interaction, pathway, and compound evidence before a follow-up recommendation stage renders evidence-grounded follow-up recommendations. This output separates primary interest-cell follow-up candidates from secondary spatial-niche follow-up candidates, so same-cell evidence, cross-cell spatial-niche framing, actionability evidence, and unresolved validation needs remain distinct. Downstream validation-driven looping gates check recommendation quality, cited provenance, and finalization readiness before deterministic target-prioritization reports are rendered. The Deep Interpreter integrates spatial analysis outputs, target-prioritization evidence, and literature through planner, searcher, interpreter, and reporter subagents. During retrieval, it invokes Summary-Guided Chunk Promotion (SGCP), which uses generated summaries as non-authoritative navigation memory to promote linked source chunks before relevance grading rather than injecting summaries into the answer context. Interpretation claims then pass through validation-driven looping steps that combine claim-level citation checks, full-text validation when available, quality scoring, and synthesis-level verification before final report generation. DeepMAST reports are grounded in spatial analysis outputs, SGCP-enabled literature retrieval, and biological databases used for single-cell context, genetic association, target validation, protein interactions, pathway annotation, and compound bioactivity assessment [36-41]. This modular design separates workflow construction, tool execution, target prioritization, and biological interpretation while preserving citation-grounded evidence, validation-driven looping, stage-specific resource control, and claim-level governance.

Figure 1 핵심 구성
- Orchestrator layer - central controller routing requests to four expert agents.
- Expert agents - Pipeline Builder, Pipeline Executor, Deep Target Prioritizer, Deep Interpreter.
- Harness/control layer - skill activation, stage-specific MCP/tool constraints, validation-driven looping gates, structured artifacts, claim-level checks, provenance-aware reporting, deterministic rendering, expert-reviewable artifacts, and fail-closed finalization gates.
- Resource layer - MCP-enabled spatial analysis tools, SGCP-enabled literature retrieval, and biological databases.

Figure 1-linked supplementary figures
- Supplementary Figure S1. Pipeline Builder details linked to Figure 1. Panel A shows the Pipeline Builder architecture. Panel B shows the full SGCP-RAG execution graph used for reference-guided pipeline construction and literature-grounded retrieval. Panel C shows a real user interaction in which a user requests a breast cancer Visium analysis pipeline, and Panel D shows the generated spatial transcriptomics analysis pipeline output. Source path - `docs/writing/figures/sfig1.png`.
- Supplementary Figure S2. Pipeline Executor details linked to Figure 1. Panel A shows the Pipeline Executor architecture. Panel B will show the single-cell reference selector MCP used to choose an optimal single-cell reference for spot-based platforms before deconvolution, and Panel C shows rMCPAgent, which converts R-based spatial analysis workflows into production-ready MCP servers. Source path - `docs/writing/figures/sfig2.png`.
- Supplementary Figure S3. Deep Target Prioritizer and Deep Interpreter details linked to Figure 1. Panel A shows the staged therapeutic evidence workflow from ligand-receptor candidates to target-prioritization reports. Panel B shows the Deep Interpreter workflow from spatial analysis outputs and HITL target selection to validated biological interpretation. Source path - `docs/writing/figures/sfig3.png`.
- Main Figure 1 should cite these supplementary figures as implementation details for the analytical substrate, while keeping the main novelty emphasis on Deep Target Prioritizer and Deep Interpreter.

---

## 2. Benchmarking evidence acquisition and source-grounded retrieval controls

이 섹션은 Results 원고로 사용합니다. Reference paper 구조는 MEDEA와 SPARK처럼 system overview 뒤에 validation benchmark를 배치하고, SpatialAgent와 STAgent처럼 figure 중심으로 benchmark endpoint를 먼저 설명한 뒤 claim boundary를 닫는 방식으로 맞춥니다.

Having defined DeepMAST as an evidence-governed biological harness, we next asked whether its retrieval-side control layer improved the evidence available for downstream interpretation before any biological or therapeutic claim was written. We evaluated two evidence-input controls in Figure 2. The first benchmark tested whether a literature-retrieval skill broadened citable biological context for ligand-receptor interpretation in 30 breast cancer Visium cell-cell interaction cases (GSE243280) [42,43]. The second benchmark tested whether Summary-Guided Chunk Promotion (SGCP) improved retrieval of source-bearing chunks in a 2,556-case MultiHop-RAG benchmark [44]. Together, these experiments evaluate the evidence entering the harness rather than the final biological interpretation itself.

In the ligand-receptor retrieval benchmark, DeepMAST used coverage validation to identify missing gene, pathway, and cell-type context, then routed the search back through targeted gap-filling queries before handoff to downstream interpretation (Figure 2a). Gene coverage was already saturated in both skill-off and skill-on arms after citable filtering, indicating that the benchmark was not limited by failure to retrieve ligand or receptor names. The retrieval skill instead improved cell-type context coverage, which is the evidence class needed to interpret spatially localized ligand-receptor signals in their tumor microenvironment context. In the Qwen3.5-35B setting, citable cell-type coverage increased from 27.7% to 38.7% (p = 1.44e-03). In the Qwen3.5-122B setting, citable cell-type coverage increased from 26.8% to 46.4% (p = 1.30e-04). The same pattern was visible in the all-retrieved paper analysis shown in Supplementary Figure S4A, where cell-type coverage increased from 42.6% to 63.2% for Qwen3.5-35B and from 40.4% to 65.1% for Qwen3.5-122B, while pathway coverage increased directionally but was underpowered because only 11 cases contained pathway annotations. These results show that the literature-retrieval skill primarily broadened biologically citable context rather than merely adding more direct ligand-receptor papers.

We then evaluated source-grounded retrieval at the chunk level using SGCP, a summary-guided source-navigation control that promotes linked source documents before chunk retrieval and grading (Figure 2b). The generated summaries were used only as non-authoritative navigation memory and were not injected as evidence into the answer context. In the Qwen3.5-35B model, SGCP increased exact-answer containment from 26.3% to 34.9% (+8.6 percentage points, McNemar p = 6.30e-38) and increased evidence recall from 0.155 to 0.256 (Wilcoxon p = 1.50e-78). In the Qwen3.5-122B model, SGCP increased exact-answer containment from 28.1% to 31.7% (+3.7 percentage points, McNemar p = 2.20e-06) and increased evidence recall from 0.192 to 0.258 (Wilcoxon p = 1.60e-31). After SGCP, evidence recall was nearly identical in Qwen3.5-35B and Qwen3.5-122B (0.256 versus 0.258), and exact-answer containment was higher in Qwen3.5-35B (34.9% versus 31.7%). The larger gain in Qwen3.5-35B suggests that summary-guided source navigation is especially useful when the base retriever or generator has less capacity, while the significant Qwen3.5-122B gains indicate that the control is not limited to a smaller-model rescue effect. SGCP also reduced no-relevant-context failures, although this improvement came with an approximately 29-31 s latency increase. Thus, SGCP represents an accuracy and recall tradeoff that is appropriate when source-grounded evidence is more important than minimal retrieval latency.

Figure 2 핵심 구성
- Figure 2a shows literature-retrieval skill coverage in 30 breast cancer Visium ligand-receptor cases (GSE243280) [42,43] using the citable set (direct + context), with citable cell-type context coverage as the primary endpoint. Source path - `benchmarks/lr_retrieval_relevance/figures/figure2d_lr_retrieval_citable_set.svg`.
- Figure 2b shows SGCP-enabled retrieval versus baseline retrieval across Qwen3.5-35B and Qwen3.5-122B models on MultiHop-RAG [44], with exact-answer containment and evidence recall as endpoints. Source path - `benchmarks/sgcp_accuracy_recall/figures/figure2c_sgcp_accuracy_recall.svg`.
- The compiled composite figure is `benchmarks/tot/fig2.svg`.
- Supplementary Figure S4A should show the literature-retrieval coverage supplement across Qwen3.5-35B and Qwen3.5-122B, including the all-retrieved paper view that complements the Figure 2a citable set (direct + context). Source path - `benchmarks/lr_retrieval_relevance/figures/sfigure2d_lr_retrieval_citable_set.svg`.
- The full SGCP-RAG graph remains in Supplementary Figure S1B so that the main figure can focus on the benchmark endpoint.

Figure 2 legend draft

Figure 2. Evidence acquisition and source-grounded retrieval controls. a, Literature-retrieval skill benchmark for 30 breast cancer Visium ligand-receptor cases (GSE243280) [42,43]. The workflow evaluates whether coverage validation and targeted retrieval loops broaden citable biological context before downstream interpretation. Panel a reports the interpreter-facing citable set (direct + context), rather than all retrieved papers. Bar plots compare skill-off and skill-on retrieval across Qwen3.5-35B and Qwen3.5-122B models for ligand-receptor, pathway, and cell-type context. All-retrieved paper coverage is shown in Supplementary Figure S4A. b, SGCP retrieval benchmark on the MultiHop-RAG dataset [44]. SGCP uses generated summaries as non-authoritative navigation memory to promote linked source documents before chunk retrieval and grading. Exact-answer containment and evidence recall are shown for baseline retrieval and SGCP-enabled retrieval in Qwen3.5-35B and Qwen3.5-122B models. Statistical tests use paired comparisons within the same benchmark cases.

Claim boundary
- This section supports retrieval-stage evidence acquisition and source-grounded retrieval claims.
- It does not directly claim that final biological interpretation quality improved.
- Pathway coverage should be described as directional because only 11 ligand-receptor cases had pathway annotations.
- SGCP should be described as source-navigation control, not as a method that uses generated summaries as evidence.

---

## 3. Evidence-governed claim control constrains biological interpretation and follow-up recommendations

**역할:** Figure 3은 Figure 2의 evidence-acquisition benchmark와 Figure 4 이후 real-data application 사이의 claim-governance bridge입니다. Figure 2는 "citable/source-grounded evidence가 system으로 들어오는가"를 검증하지만, 그 evidence가 final biological claim으로 바뀔 때 unsupported mechanism, causal overclaiming, premature therapeutic claim이 줄어드는지는 별도 검증하지 않습니다. 따라서 Figure 3을 Figure 4 앞에 배치해 fixed evidence substrate 아래에서 guidance effect를 비교하고, 이후 biological application이 단순한 agent narrative가 아니라 evidence-boundary를 통과한 harness output임을 보여줍니다. MEDEA, SPARK, SpatialAgent, STAgent 모두 overview/evidence system 뒤에 benchmark 또는 validation figure를 두고, 그 다음 application을 전개하는 구조를 사용하므로 DeepMAST도 "evidence input -> claim-governance benchmark -> biological application" 흐름으로 정리하는 것이 가장 자연스럽습니다.

추천 heading:

```text
Evidence-governed claim control constrains biological interpretation and follow-up recommendations
```

Section 3 시작 bridge

```text
After establishing that DeepMAST improves evidence acquisition and source-grounded retrieval, we next evaluated whether evidence artifacts remain bounded when they are converted into written biological claims. Retrieval success alone does not demonstrate evidence-governed interpretation, because retrieved sources can still be transformed into unsupported mechanisms, overstated causal links, or premature therapeutic claims. We therefore tested this claim-governance layer before the real-data applications at two claim-generation points: ligand-receptor interpretation in a CCI benchmark and downstream breast cancer follow-up recommendations under controlled guide activation.
```

Figure 3 panel 구성:

```text
Figure 3
Evidence-governed claim control benchmark.
Message: DeepMAST tests the same evidence-governance principle in two benchmark branches: upstream CCI interpretation and downstream follow-up recommendation writing.

Figure 3A
Two-branch claim-governance benchmark schematic.
Source path: benchmarks/dth/figures/Fig3A_ClaimGovernanceLifecycle.svg
Message: fixed evidence artifacts and structured guidance split into two controlled benchmark branches: CCI interpretation supporting Figure 3B and follow-up recommendations supporting Figure 3C. This panel is a schematic bridge, not a new benchmark result.

Figure 3B
Structured SKILL CCI ablation benchmark.
Source path: benchmarks/cci_skill_ablation/figures/SkillAblation.png
Linked supplement: Supplementary Figure S4B shows dimension-level scores and fabrication counts from `benchmarks/cci_skill_ablation/figures/s_SkillAblation.svg`.
Message: structured SKILL guidance reduces plausible but unsupported ligand-receptor interpretation.

Figure 3C, left
Follow-up recommendation evidence coverage.
Source path: benchmarks/dth/figures/Fig3A_DTH_EvidenceCoverage.svg
Message: guide-activated generation produced a modest/borderline increase in evidence coverage and should be treated as a secondary endpoint.

Figure 3C, right
Follow-up recommendation claim-boundary restraint.
Source path: benchmarks/dth/figures/Fig3B_DTH_BlindJudgeRigor.svg
Message: follow-up recommendation guidance primarily improves evidence-boundary behavior by increasing blinded claim-boundary restraint scores.
```

**Figure 3A: Two-branch claim-governance benchmark schematic**

Figure 3A는 결과값을 추가로 주장하는 panel이 아니라, Figure 3B-C를 읽는 방법을 정리하는 design schematic입니다. Figure 2가 "evidence를 어떻게 가져오는가"를 보여준다면, Figure 3A는 "evidence가 claim으로 바뀔 때 어떤 gate를 통과하는가"를 보여줍니다. 특히 Figure 3A는 two benchmark branches를 명확히 보여줘야 합니다. Branch 1은 breast cancer LR cases에서 structured SKILL guidance가 unsupported CCI interpretation을 줄이는지를 검증하고 Figure 3B로 이어집니다. Branch 2는 fixed breast cancer Deep Target Prioritizer evidence package에서 follow-up recommendation guide가 evidence-boundary behavior를 개선하는지를 검증하고 Figure 3C로 이어집니다.

**Figure 3B: Structured biological SKILL guidance reduces unsupported interpretation in spatial CCI analysis**

Figure 3B는 upstream interpretation-control benchmark입니다. 이 panel은 agent가 명시적으로 실패하지 않고 plausible mechanism storytelling으로 넘어가는 silent/fail-plausible failure를 줄이는지를 직접 다룹니다. Breast cancer Visium ligand-receptor cases를 사용하므로, 뒤쪽 cancer Visium workflow와 Evidence-Grounded Follow-up Recommendations validation으로 자연스럽게 연결됩니다.

사용할 결과:
- Guide-compliant structured SKILL guidance produced the highest hallucination-control composite score.
- Main three-condition ordering: no skills < unstructured prose < structured SKILLs.
- Composite score: no skills 3.14, unstructured prose 3.59, structured SKILLs 3.89.
- Structured SKILLs reduced unsupported fabrication count from 3.89 to 1.78 per interpretation.
- Improvements concentrated in faithfulness, overclaiming, uncertainty handling, and fabrication count.
- Spatial calibration was near ceiling across conditions, so the gain is not just basic reading of Moran's R.
- Supplementary Figure S4B should use `benchmarks/cci_skill_ablation/figures/s_SkillAblation.svg`: left panel for per-dimension skill-ablation scores and right panel for fabrication counts.

핵심 메시지:

```text
Structured SKILL guidance did not simply make the model more verbose or more cautious. It shifted ligand-receptor interpretation from plausible mechanism storytelling toward evidence-calibrated biological reporting, reducing unsupported mechanisms and overclaiming while preserving spatial calibration.
```

**Fixed breast cancer Deep Target Prioritizer evidence package used for follow-up recommendation validation**

Deep Target Prioritizer 결과는 main Figure 3의 독립 panel로 키우지 않고, Evidence-Grounded Follow-up Recommendations validation이 어떤 evidence package 위에서 수행됐는지 본문과 Supplementary Data/Table에서 설명합니다. `drug.md`의 핵심만 압축합니다: top-30 LR pairs에서 나온 37 unique genes, Stage 3 deep-dive로 넘어간 7 featured candidates (ERBB3, EPHB4, ERBB2, INSR, EFNB2, LAMA5, NECTIN4), Stage 1 spatial/Census evidence, Stage 2 target-disease/actionability evidence, Stage 3 druggability/deep-dive evidence, and conservative follow-up tiers.

추천 처리:
- Main Results text: fixed evidence substrate로 2-3문장 설명.
- Supplementary Table: 37 assessed genes와 7 featured candidates, stage, score/tier, evidence class를 요약.
- Supplementary Data: full `drug.md`/structured evidence artifacts를 audit bundle로 제공.

핵심 메시지:

```text
The breast cancer target-prioritization output is used here as a controlled evidence substrate for Evidence-Grounded Follow-up Recommendations, whereas the full biological therapeutic-prioritization application is reserved for the human IPF analysis.
```

**Figure 3C: Follow-up recommendation guidance improves downstream claim-boundary restraint in breast cancer Evidence-Grounded Follow-up Recommendations**

Figure 3C는 same principle이 downstream Evidence-Grounded Follow-up Recommendations output에서도 작동하는지를 보여줍니다. 여기서 중요한 점은 guide activation이 "더 많은 evidence를 언급하게 했다"보다 **claim-boundary behavior를 바꿨다**는 것입니다. 왼쪽에는 secondary endpoint인 evidence coverage를, 오른쪽에는 primary endpoint인 claim-boundary restraint를 둡니다.

Source result:
- Use `benchmarks/dth/results/dth_yes_no_qwen397b_cloud_methods_results.md` as the follow-up recommendation validation source.
- Guided and baseline conditions use the same Qwen3.5-397B generator (`qwen3.5:397b-cloud` runtime tag), fixed breast cancer evidence package, output schema, save gate, and retry policy.
- Valid-output analysis includes 20 guided and 20 baseline runs, all passing recommendation-output validation, activation-trace validation, and no-fallback filtering.
- Evidence coverage is a secondary endpoint: guided mean 78.53% versus baseline 74.41%, mean paired difference +4.12 percentage points, paired Wilcoxon P = 5.10e-02.
- Claim-boundary restraint is the primary endpoint: guided mean 4.78 versus baseline 2.88 after averaging judges within pair, mean paired difference +1.90, paired Wilcoxon P = 8.13e-05.
- Judge preference supports the same direction but is model-dependent: gpt-5.4 favored guided outputs in 18 of 20 pairs, whereas claude-sonnet-4-6 favored guided outputs in 11 of 20 pairs.

Paper-ready Results draft

```text
Having established that DeepMAST improves evidence acquisition and source-grounded retrieval, we next evaluated the point at which those evidence artifacts are converted into biological claims. This benchmark was necessary because evidence availability alone does not demonstrate evidence-bounded interpretation: retrieved sources can still be transformed into unsupported mechanisms, overstated causal links, or premature therapeutic claims. We therefore used a controlled claim-governance benchmark before turning to real-data spatial-transcriptomics applications. The evidence substrate, task interface, output checks, and evaluation criteria were held fixed while guidance structure or guide activation was varied (Fig. 3A).

We first tested whether this governance layer constrained upstream ligand-receptor interpretation. In a breast cancer ligand-receptor CCI benchmark, 30 LIANA+ interaction cases were interpreted under frozen prompting conditions. Guide-compliant structured SKILL guidance produced the strongest hallucination-control composite score among the main three conditions (3.89 versus 3.59 for unstructured prose and 3.14 without skills, Kruskal-Wallis H = 219.16, P = 2.57e-48) and reduced unsupported fabrication counts from 3.89 to 1.78 per interpretation (Fig. 3B; Fig. S4B). These gains were concentrated in faithfulness, overclaiming, uncertainty handling, and fabrication count, whereas spatial calibration was near ceiling across conditions. Thus, structured guidance primarily reduced unsupported biological interpretation rather than simply improving recognition of spatial statistics.

We then tested the same claim-governance principle at a downstream writing point that turns breast cancer drug-target evidence into follow-up recommendations. To avoid conflating guide effects with changing biological inputs, this benchmark was not run from an abstract prompt. The input evidence package came from the Deep Target Prioritizer workflow (Fig. S3A), which assessed 37 unique genes from the top-30 ligand-receptor pairs through a staged evidence funnel and selected 7 Stage 3 featured candidates for deep-dive analysis (ERBB3, EPHB4, ERBB2, INSR, EFNB2, LAMA5, and NECTIN4). We treat this package as a controlled evidence substrate for follow-up recommendation validation, with the full breast cancer target-prioritization report reserved for Supplementary Data rather than as a main figure panel.

The controlled guide-activation contrast used this same breast cancer evidence package, generator model, output schema, save gate, and retry policy in both conditions (Fig. 3A). In the baseline condition, the writer received the operational contract but no follow-up recommendation guide. In the guided condition, the writer was required to read the guide before generating recommendations. The valid-output analysis included 20 guided and 20 baseline reports, all passing recommendation-output validation, activation-trace validation, and no-fallback filtering.

Guide activation produced a modest increase in mean evidence coverage compared with baseline generation (78.53% versus 74.41%, mean paired difference, +4.12 percentage points, paired Wilcoxon P = 5.10e-02), so this result should be interpreted as a borderline secondary endpoint (Fig. 3C, left). The stronger signal was claim-boundary restraint. After averaging blinded scores across GPT-5.4 and Sonnet 4.6 within each paired comparison, guided outputs scored higher than baseline outputs on claim-boundary restraint (4.78 versus 2.88, mean paired difference, +1.90, paired Wilcoxon P = 8.13e-05, Fig. 3C, right). Thus, follow-up recommendation guidance primarily improved evidence-boundary behavior by making the writer more explicit about the distinction between observed evidence, candidate mechanisms, and unestablished causal or clinical claims. Together, the two benchmark branches show that DeepMAST's evidence-governance benefit extends beyond retrieving evidence and constrains how evidence is converted into interpretation and follow-up recommendations before the framework is applied to real spatial-transcriptomics workflows.
```

Paper-ready figure legend draft

```text
Figure 3. Evidence-governed claim control constrains biological interpretation and follow-up recommendations. (A) Two-branch claim-governance benchmark schematic showing how fixed evidence artifacts enter structured guide activation and are evaluated through CCI interpretation and follow-up recommendation branches. (B) Structured SKILL CCI ablation benchmark. Hallucination-control scores and unsupported fabrication counts compare guide-compliant structured SKILL guidance with unstructured prose and no-skill conditions. (C) Breast cancer follow-up recommendation validation. Left, evidence coverage in guided and baseline reports generated from the same fixed Deep Target Prioritizer evidence package. Right, blinded dual-judge claim-boundary restraint scores comparing guided and baseline reports.
```

주의할 claim boundary:
- Figure 3B는 CCI interpretation quality benchmark이지 full therapeutic target validation이 아닙니다.
- Figure 3C는 generated follow-up recommendation quality를 검증하지 therapeutic efficacy를 검증하지 않습니다.
- Breast cancer Deep Target Prioritizer output은 follow-up recommendation validation의 upstream evidence substrate이지 breast cancer therapeutic target validation이 아닙니다.
- Evidence coverage should be described as modest or borderline because P = 5.10e-02.
- The strongest guided-output claim is claim-boundary restraint, not universal improvement across all judging axes.
- Follow-up recommendation guidance should be described as improving scientific calibration or evidence-boundary behavior.
- Do not abbreviate Evidence-Grounded Follow-up Recommendations as EGFR because that conflicts with the EGFR gene symbol. After the first definition, use "follow-up recommendations" or "follow-up recommendation guidance."
- Detailed staged target-evidence assessment remains reserved for the IPF/Figure 6 therapeutic-prioritization section.

Linked supplement:
- Supplementary Figure S3A: Deep Target Prioritizer overview supporting the fixed evidence package used for Figure 3C.
- Supplementary Figure S4B: CCI skill-ablation supplement (`benchmarks/cci_skill_ablation/figures/s_SkillAblation.svg`).
- Supplementary Figure S4C: judge-stratified claim-boundary restraint supporting Figure 3C (`benchmarks/dth/figures/FigS3D_DTH_BlindJudgeRigorByJudge.svg`).
- Supplementary Figure S4D: blind-judge preference shares supporting Figure 3C (`benchmarks/dth/figures/FigS3E_DTH_BlindJudgeWinRate.svg`).
- Supplementary Table/Data: fixed breast cancer Deep Target Prioritizer evidence package from `final_res_bc_drugtarget/drug.md`.

---

## 4. Complementary cancer Visium workflows connect reference-guided execution with curated ligand-receptor handoff

**역할:** Evidence acquisition과 claim-governance benchmark가 끝난 뒤 첫 biological application section입니다. Breast cancer와 prostate cancer Visium을 별도 Results로 길게 분리하지 말고, 한 figure/section 안에서 **서로 다른 DeepMAST 모듈을 보여주는 complementary cancer Visium demonstration**으로 묶습니다. 이 figure는 STAgent/SpatialAgent식 use-case figure처럼 실제 spatial outputs를 보여주되, follow-up recommendation validation metric은 Figure 3에 이미 배치합니다.

Section logic:
- This section should not argue that breast cancer and prostate cancer reveal a shared cancer biology mechanism. The claim is modular: the same DeepMAST harness can consume curated spatial-analysis outputs in one setting and generate reference-guided executor outputs in another.
- This is the first application section after the evidence and claim-governance benchmark bridge, so it should show practical spatial-transcriptomics use without re-litigating benchmark metrics.
- Do not include follow-up recommendation validation metrics in Figure 4. Figure 3 is now the dedicated claim-governance bridge that contains both the CCI SKILL benchmark and Evidence-Grounded Follow-up Recommendations validation. Detailed staged target-evidence scoring remains reserved for the IPF therapeutic-prioritization section.

Prostate cancer Visium의 위치:
- Prostate cancer is the upstream execution example. The dataset is the 10x Genomics Human Prostate Cancer, Adenocarcinoma with Invasive Carcinoma (FFPE) Visium dataset analyzed with Space Ranger 1.3.0, including H&E image context and adenocarcinoma/invasive carcinoma tissue annotation [45].
- The direct executor claim is that Pipeline Executor resolved a realistic spot-based Visium preprocessing problem before downstream interpretation: choosing a single-cell reference and producing structured STworkbench outputs through MCP-mediated execution.
- The single-cell reference-selection result is concrete and can be reported in Results: the spatial query contained 4,371 spots and 17,943 genes at loading; after duplicate-gene handling and harmonization, both candidate references were compared in the same 16,385-gene feature space. GSE181294 [46] ranked ahead of GSE185344 [47] by fused Gromov-Wasserstein distance (11,353.4043 vs 11,890.1709), a 4.5% lower distance for GSE181294.
- rMCPAgent should be framed as the mechanism that made R-based deconvolution/spatial workflows available through a validated MCP interface: validated H5AD inputs, reference metadata checks, standardized output tables, recovery diagnostics, and output validation. Do not overstate rMCPAgent as a biological discovery result.
- Main Figure 4A-C should use the simplified prostate cancer STworkbench outputs: A, H&E-aligned Visium tissue and spatial cluster context; B, cluster-level cell-type enrichment/deconvolution heatmap; C, cluster-level pathway/signature enrichment heatmap. This keeps the prostate example focused on reference-guided execution and structured output inspection rather than downstream target interpretation.

Breast cancer Visium의 위치:
- Breast cancer is the curated downstream-interpretation example. The dataset should be described as a breast cancer Visium/Xenium-matched setting linked to the integrated single-cell, spatial, and in situ breast cancer study and the Starfysh spatial/histology resource, using the public accession (GSE243280) [42,43].
- Because this dataset is used elsewhere in the paper for CCI skill-ablation, literature-retrieval, and follow-up recommendation validation, main Figure 4 should not repeat Pipeline Builder or Pipeline Executor architecture. It should show that curated STworkbench outputs can be narrowed to selected ligand-receptor interactions and passed to interpretation/target-evidence modules.
- Main Figure 4D-F should use the final breast cancer handoff panels: D, NMF/factor spatial programs and cluster context; E, spatial visualization of key ligand-receptor pairs; F, quantitative analysis of ligand-receptor interactions.
- The BC analysis should focus on the selected Factor3/invasive-tumor communication program and avoid broad therapeutic claims. Interest clusters are 17, 4, and 14, interest cell type is Prolif Invasive Tumor, and selected factor is Factor3. The report identifies 19 prioritized LR pairs; CDH1-ERBB3 is the main interpreted candidate with Moran's R = 0.477 and Factor3 loading = 1.180. The displayed LR maps include AFDN-NECTIN4, CDH1-ERBB3, and EGF-ERBB2, while the remaining ranked candidates should stay in the source artifact or supplement. This is enough for a Results claim that DeepMAST can preserve spatial and quantitative evidence for selected LR candidates.
- The displayed LR pairs should not be interpreted at the same evidentiary strength. AFDN-NECTIN4 is an adhesion-context example supported by Nectin-4 breast-cancer marker evidence and Nectin/Afadin junction biology [48,49]. CDH1-ERBB3 is the main literature-grounded interpretation candidate because the local spatial evidence aligns with E-cadherin deregulation and ErbB3-associated EMT, migration, and invasion literature [50,51]. EGF-ERBB2 should be framed conservatively as an ERBB-family growth-factor signaling context because HER2/ERBB2 has no known ligand and EGF-bound EGFR can transactivate HER2 [52].
- If the text mentions ERBB3 or MAPK/PI3K, it should be bounded as an interpretation-prioritization signal from this curated analysis, not as a validated therapeutic target. Detailed target-evidence scoring belongs in the IPF therapeutic-prioritization section.

Fig. 4 panel plan:
- A: Prostate cancer H&E-aligned Visium tissue and spatial cluster context (`res_pc/1.cluster_spatial.png`) establishes tissue-level spatial domains after STworkbench MCP execution.
- B: Prostate cancer cluster-level cell-type enrichment/deconvolution heatmap (`res_pc/2.celltype_heatmap_analysis.png`) links spatial clusters to inferred cell-type composition.
- C: Prostate cancer pathway/signature enrichment heatmap (`res_pc/4.spatial_enrich_decoupler.png`) summarizes cluster-level biological programs after reference-guided execution.
- D: Breast cancer NMF/factor spatial programs (`res_bc/7.factor_spatial_NMF.png`) show Factor1-3 spatial programs, cluster context, and Factor3 selection for invasive-tumor communication.
- E: Breast cancer selected LR spatial maps (`res_bc/10.spatial_plot_interections.png`) show AFDN-NECTIN4, CDH1-ERBB3, and EGF-ERBB2 in tissue context.
- F: Breast cancer LR quantitative summaries (`res_bc/11.lr_interections.png`) compare selected LR interactions across interest and non-interest contexts and preserve the quantitative evidence used for interpretation.

Fig. S5:
- Use Supplementary Figure S5 for the Deep Interpreter/STworkbench MCP and HITL example rather than for target-prioritization details. Panels can show the STworkbench MCP call/analysis trace, human-in-the-loop selection or confirmation of interest clusters/factors/LR candidates, and the downstream Deep Interpreter report handoff. This keeps the main Figure 4 focused on spatial evidence while documenting how the user-guided execution path was controlled.
- If Supplementary Figure S5 includes logs or screenshots, phrase it as an auditable workflow example: "HITL selection and MCP execution traces document how spatial outputs were selected and handed to interpretation," not as a benchmark metric.

Paper-ready Results draft:

```text
To test whether DeepMAST could support complementary human cancer Visium workflows without collapsing execution, interpretation, and target prioritization into a single claim surface, we paired a prostate cancer analysis emphasizing upstream reference-guided execution with a breast cancer analysis emphasizing downstream interpretation from curated spatial outputs. In the prostate cancer FFPE Visium dataset [45], Pipeline Executor first resolved a spot-based reference-selection problem before downstream analysis. sc-reference-selector compared GSE181294 [46] and GSE185344 [47] after metadata-aware loading, duplicate-gene handling, stratified downsampling, and harmonization to a shared 16,385-gene feature space. GSE181294 ranked as the closer reference by fused Gromov-Wasserstein distance (11,353.4043 vs 11,890.1709; 4.5% lower distance), providing the reference used for subsequent deconvolution and STworkbench MCP execution. The resulting tissue-aligned Visium and cluster view, cluster-level cell-type enrichment heatmap, and cluster-level pathway/signature enrichment heatmap provided structured executor artifacts that could be inspected and handed to Deep Interpreter rather than treated as final biological conclusions (Figure 4A-C; Supplementary Figure S5).

In the breast cancer Visium setting linked to integrated single-cell, spatial, in situ, and histology resources (GSE243280) [42,43], the analysis instead began from curated spatial annotations and focused on whether DeepMAST preserved quantitative evidence for selected ligand-receptor candidates. STworkbench MCP narrowed the curated output to a Factor3 invasive-tumor communication program across interest clusters 17, 4, and 14, then generated factor-level, spatial, and quantitative views for selected ligand-receptor interactions. The displayed interactions include AFDN-NECTIN4, CDH1-ERBB3, and EGF-ERBB2, with CDH1-ERBB3 retained as the main interpreted candidate based on spatial co-localization (Moran's R = 0.477) and high Factor3 loading (1.180) (Figure 4D-F). The three displayed pairs were interpreted with different evidence boundaries. AFDN-NECTIN4 was treated as an adhesion-context example because Nectin-4 is a breast tumor-associated antigen and Nectin/Afadin junction biology links this pair to cell-cell contact rather than a validated signaling axis [48,49]. CDH1-ERBB3 was emphasized because the local spatial signal matched literature linking E-cadherin deregulation with breast-cancer invasion and ErbB3 signaling with EMT, migration, and invasion [50,51]. EGF-ERBB2 was retained only as ERBB-family signaling context, since HER2/ERBB2 has no known ligand and EGF-bound EGFR can transactivate HER2 [52]. These results support a bounded handoff claim: DeepMAST can carry selected spatial LR evidence into literature-grounded interpretation and later target-evidence assessment, while output-level claim-governance validation is evaluated separately in Figure 3.
```

Paper-ready figure legend draft:

```text
Figure 4. Complementary human cancer Visium workflows connect reference-guided execution with curated ligand-receptor handoff. (A) H&E-aligned Visium tissue and spatial cluster context for the prostate cancer FFPE sample after STworkbench MCP execution. (B) Cluster-level cell-type enrichment/deconvolution heatmap for the prostate cancer sample following single-cell reference selection. (C) Cluster-level pathway/signature enrichment heatmap for the prostate cancer sample following MCP-mediated workflow execution. (D) Breast cancer NMF factor maps showing Factor1-3 spatial programs, cluster context, and factor-loading summaries, with Factor3 used as the focused invasive-tumor communication program. (E) Spatial visualization of selected breast cancer ligand-receptor interactions, including AFDN-NECTIN4, CDH1-ERBB3, and EGF-ERBB2. AFDN-NECTIN4 is shown as an adhesion-context example, CDH1-ERBB3 as the main literature-grounded interpretation candidate, and EGF-ERBB2 as ERBB-family signaling context rather than direct EGF-to-HER2 ligand binding. (F) Quantitative summaries of selected breast cancer LR interactions, including mean cosine similarity and Cauchy-combined P-value summaries across interest and non-interest contexts. Prostate cancer panels emphasize upstream reference selection and MCP-mediated executor output; breast cancer panels emphasize preservation of selected LR evidence for downstream interpretation without making therapeutic-efficacy claims.

Supplementary Figure S5. STworkbench MCP and HITL trace for cancer Visium interpretation. The supplementary workflow example shows the MCP execution trace, user or HITL confirmation of interest clusters/factors/LR candidates, and the handoff from STworkbench outputs to Deep Interpreter report generation. This figure documents auditability and user-controlled selection rather than serving as target-prioritization or therapeutic-evidence scoring.
```

추천 heading:

```text
DeepMAST connects reference-guided cancer Visium execution with curated breast cancer LR interpretation
```

핵심 메시지:

```text
The paired cancer Visium analyses use complementary datasets to exercise different parts of the DeepMAST harness: prostate cancer tests upstream single-cell reference selection and MCP-mediated Pipeline Executor output, whereas breast cancer tests downstream evidence-governed interpretation of selected ligand-receptor candidates.
```

주의할 claim boundary:
- 이 섹션은 breast cancer와 prostate cancer의 biological contrast를 주장하는 comparative oncology section이 아닙니다.
- Breast cancer에서 Pipeline Builder/Executor를 생략하는 이유를 "누락"이 아니라 "curated benchmark setting에서는 downstream harness를 평가하는 것이 더 적절함"으로 설명합니다.
- Prostate cancer에서 reference selector 자체를 main novelty로 과장하지 않습니다.
- "reference selection improves target ranking"은 실제 evidence가 있을 때만 씁니다.
- STAgent/SpatialAgent가 이미 spatial biology agent automation을 보여주므로, DeepMAST의 claim은 **modular, auditable, evidence-governed interpretation and target-prioritization handoff**입니다.

---

## 5. DeepMAST generalizes to single-cell-resolution spatial transcriptomics in mouse Alzheimer’s disease

**역할:** Single-cell-resolution spatial technology로의 generalization section입니다. SpatialAgent/STAgent가 spatial biology agent use cases를 이미 보여주므로, 여기서는 "DeepMAST는 특정 Visium pipeline이 아니라 harnessed biological reasoning layer"라는 점을 보여주는 용도입니다.

Dataset:
- Mouse Alzheimer disease.
- STARmapPLUS.
- Single-cell resolution.

보여줄 내용:
- Visium spot-level에서 STARmapPLUS single-cell-resolution data로 input modality/resolution generalization.
- Brain cell types: microglia, astrocytes, neurons, oligodendrocytes, vascular cells 등.
- Mouse disease biology와 human therapeutic relevance를 분리해서 해석했는지.
- Literature grounding and uncertainty calibration.

추천 heading:

```text
DeepMAST generalizes from spot-level Visium to single-cell-resolution STARmapPLUS in mouse Alzheimer’s disease
```

핵심 메시지:

```text
The Alzheimer STARmapPLUS analysis tests whether the DeepMAST harness can preserve cell-type-specific and literature-grounded interpretation when the input shifts from spot-level Visium to single-cell-resolution spatial transcriptomics.
```

주의할 claim boundary:
- Mouse result에서 human therapeutic claim을 바로 강하게 연결하지 않습니다.
- Human relevance는 "exploratory" 또는 "translation-aware interpretation"로 제한합니다.

---

## 6. DeepMAST prioritizes candidate therapeutic targets in human idiopathic pulmonary fibrosis Visium data

**역할:** Results의 biological climax로 두는 것이 좋습니다. IPF는 human disease, Visium spot-level, therapeutic target prioritization, and possible experimental validation을 연결할 수 있어서 가장 마지막 substantive Results section에 적합합니다.

Dataset:
- Human idiopathic pulmonary fibrosis.
- Visium spot-level resolution.

구조:
1. IPF spatial disease niche 해석.
2. Disease-associated ligand-receptor/pathway/cell-type signals.
3. Deep Target Prioritizer evidence scoring.
4. Top target evidence decomposition.
5. Experimental validation이 있으면 여기서만 "validated candidate" 수준의 강한 표현 사용.

추천 heading:

```text
DeepMAST prioritizes evidence-supported therapeutic targets in human idiopathic pulmonary fibrosis
```

핵심 메시지:

```text
The IPF analysis provides the strongest therapeutic-prioritization demonstration, linking human disease spatial localization, literature support, database-derived evidence, druggability context, and experimental validation when available.
```

주의할 claim boundary:
- 전체 논문 제목과 abstract에서는 "therapeutic target prioritization"을 기본으로 유지합니다.
- "target discovery"는 IPF에서 실험검증이 충분히 있을 때 해당 result에만 제한적으로 씁니다.

---

## 7. Cross-dataset analysis demonstrates evidence traceability across spatial platforms and disease contexts

선택적이지만 있으면 Discussion 직전의 clean closing으로 좋습니다.

역할:
- Breast/prostate cancer Visium: complementary curated interpretation and reference-guided execution.
- Alzheimer mouse: single-cell-resolution generalization.
- IPF human: therapeutic prioritization and validation.

측정:
- number of generated reports or interpretations.
- number/proportion of literature-supported claims.
- citation/provenance completeness.
- number of prioritized targets and evidence categories available.
- validation status.
- unsupported claim or finalization failure rate if measured.

추천 heading:

```text
Cross-dataset analyses preserve evidence traceability across spatial platforms and disease contexts
```

핵심 메시지:

```text
Across benchmark and disease analyses, DeepMAST should be evaluated not only by whether it produces plausible biological narratives, but by whether each conclusion remains traceable to spatial outputs, retrieved literature, database evidence, and validation artifacts.
```

---

# Final Recommended Results Order

```text
Results

1. DeepMAST is an evidence-governed biological agent harness for spatial transcriptomics interpretation and target prioritization

2. Benchmarking evidence acquisition and source-grounded retrieval controls

   2a. Coverage validation and retrieval looping broaden citable biological context for ligand-receptor interpretation across model scales

   2b. Summary-Guided Chunk Promotion strengthens source-grounded retrieval through a retrieval-validation loop

3. Evidence-governed claim control constrains biological interpretation and Evidence-Grounded Follow-up Recommendations

4. DeepMAST connects reference-guided cancer Visium execution with curated breast cancer LR interpretation

5. DeepMAST generalizes from spot-level Visium to single-cell-resolution STARmapPLUS in mouse Alzheimer’s disease

6. DeepMAST prioritizes evidence-supported therapeutic targets in human idiopathic pulmonary fibrosis

7. Cross-dataset analyses preserve evidence traceability across spatial platforms and disease contexts
```

---

# Figure Plan

## Main figures

```text
Figure 1
DeepMAST architecture: workflow layer, expert agents, harness/control layer, MCP-enabled resource layer, outputs.
Linked supplements: Supplementary Figure S1 expands Pipeline Builder, Supplementary Figure S2 expands Pipeline Executor, and Supplementary Figure S3 expands Deep Target Prioritizer and Deep Interpreter.

Figure 2
Evidence acquisition and source-grounded retrieval controls.
Compiled target path after refresh: benchmarks/tot/fig2.svg
Message: DeepMAST improves the evidence entering downstream interpretation by broadening citable biological context and improving source-grounded retrieval.

Figure 2A
Literature-retrieval skill citable-context coverage.
Upper subpanel: literature-retrieval workflow.
Lower subpanel: citable set (direct + context) coverage for Qwen3.5-35B and Qwen3.5-122B.
Source path: benchmarks/lr_retrieval_relevance/figures/figure2d_lr_retrieval_citable_set.svg
Linked supplement: Supplementary Figure S4A, source `benchmarks/lr_retrieval_relevance/figures/sfigure2d_lr_retrieval_citable_set.svg`.
Main message: literature-search skill improves citable biological context coverage, especially cell-type context, across model scales.

Figure 2B
SGCP mechanism and retrieval benchmark.
Upper subpanel: simplified SGCP flow.
Lower subpanel: exact-answer accuracy and evidence recall for Qwen3.5-35B and Qwen3.5-122B.
Source path: benchmarks/sgcp_accuracy_recall/figures/figure2c_sgcp_accuracy_recall.svg
Main message: SGCP-enabled retrieval improves exact-answer accuracy and evidence recall in both model settings, with larger gains in the smaller Qwen3.5-35B model.

Figure 3
Evidence-governed claim control benchmark.
Panels: (A) two-branch claim-governance benchmark schematic; (B) structured SKILL CCI ablation benchmark; (C, left) follow-up recommendation evidence coverage; (C, right) follow-up recommendation claim-boundary restraint.
Source paths/data: A, `benchmarks/dth/figures/Fig3A_ClaimGovernanceLifecycle.svg`; B, `benchmarks/cci_skill_ablation/figures/SkillAblation.png`; C left, `benchmarks/dth/figures/Fig3A_DTH_EvidenceCoverage.svg`; C right, `benchmarks/dth/figures/Fig3B_DTH_BlindJudgeRigor.svg`.
Linked supplements: Supplementary Figure S4B supports Figure 3B; Supplementary Figure S4C-D support Figure 3C right; Supplementary Table/Data contains the fixed breast cancer Deep Target Prioritizer evidence package from `final_res_bc_drugtarget/drug.md`.
Main message: structured guidance reduces unsupported CCI interpretation upstream, the fixed breast cancer Deep Target Prioritizer evidence package defines the controlled substrate for follow-up recommendation validation, and guide activation improves downstream claim-boundary restraint in breast cancer follow-up recommendation outputs.
```

## Main application figures to build or select

```text
Figure 4
Complementary human cancer Visium workflows.
Panels: (A) prostate cancer H&E-aligned Visium tissue and spatial cluster context; (B) prostate cancer cluster-level cell-type enrichment/deconvolution heatmap; (C) prostate cancer pathway/signature enrichment heatmap after single-cell reference selection and STworkbench MCP execution; (D) breast cancer NMF/factor spatial programs with Factor3 selection context; (E) breast cancer spatial visualization of selected ligand-receptor pairs; (F) breast cancer quantitative ligand-receptor interaction summaries.
Linked supplements: Supplementary Figure S4A documents the LR citable-context bridge, and Supplementary Figure S5 documents MCP/HITL handoff for the Figure 4 cancer Visium interpretation thread.
Message: prostate cancer demonstrates reference-guided Pipeline Executor output after sc-reference-selector and rMCP/MCP-mediated workflow execution, whereas breast cancer demonstrates downstream interpretation of selected LR candidates from curated spatial outputs. Keep follow-up recommendation validation in Figure 3 and reserve detailed target-prioritization evidence for the IPF/Figure 6 section.

Figure 5
Mouse Alzheimer STARmapPLUS generalization.
Panels: single-cell-resolution spatial domains/cell types, disease-relevant programs, literature-grounded interpretation, uncertainty/translation boundary.

Figure 6
Human IPF Visium therapeutic target prioritization.
Panels: disease niche, candidate targets, evidence decomposition, druggability/database support, experimental validation if available.

Figure 7 or Supplementary Overview
Cross-dataset evidence traceability summary.
Panels/table: datasets, platform/resolution, analysis goal, main outputs, evidence sources, validation status.
```

## Supplementary figure policy

```text
Supplementary Figure S1
Pipeline Builder details linked to Figure 1.
Source path: docs/writing/figures/sfig1.png
Panels: (A) Pipeline Builder agent architecture; (B) full SGCP-RAG execution graph, with the Figure 2B upper panel retaining only the simplified SGCP flow; (C) real user interaction example for breast cancer Visium pipeline generation; (D) generated Pipeline Builder output example.
Message: Pipeline Builder provides HITL workflow construction and reference-guided pipeline selection as part of the analytical substrate, without becoming the central biological interpretation novelty.

Supplementary Figure S2
Pipeline Executor details linked to Figure 1.
Source path: docs/writing/figures/sfig2.png
Panels: (A) Pipeline Executor agent architecture; (B) single-cell reference selector MCP concept for spot-based platforms requiring deconvolution; (C) rMCPAgent concept for converting R-based spatial analysis workflows into MCP servers.
Message: Pipeline Executor operationalizes configured workflows through platform checks, reference selection, MCP readiness checks, dynamic MCP generation, and tool execution.

Supplementary Figure S3
Deep Target Prioritizer and Deep Interpreter details linked to Figure 1.
Source path: docs/writing/figures/sfig3.png
Legend: Supplementary Figure S3. Deep Target Prioritizer and Deep Interpreter workflow details linked to Figure 1. (A) The Deep Target Prioritizer receives top-ranked ligand-receptor pairs and a ligand-receptor network from spatial transcriptomics analysis, evaluates candidate targets through staged evidence assessment using OpenTargets, GWAS Catalog, Ensembl VEP, STRING, CellxGene Census, and ChEMBL, ranks follow-up candidates, and passes outputs through report-writing, critic, citation-gate, anti-fabrication, and finalization checks to generate `drug.md` and `target_assessment.json`. (B) The Deep Interpreter receives spatial transcriptomics analysis results and human-in-the-loop target selections, plans interpretation targets, retrieves literature and biological context through PubMed, BioMCP, dynamic search, and BI-RAG, validates claim-level citations and quality, and renders a comprehensive HTML report with validated interpretation. The STworkbench MCP layer supplies clustering, neighborhood enrichment, pathway, CCI, MISTy, and LIANA plus NMF outputs used for interpretation.

Supplementary Figure S4
Shared benchmark/application supplement linked to Figures 2 and 3, with optional support for the Figure 4 breast-cancer interpretation thread.
Source path: docs/writing/figures/sfig4.png
Panels:
- (A) Literature-retrieval citable-context coverage across Qwen3.5-35B and Qwen3.5-122B. This panel includes the all-retrieved paper coverage view that complements the Figure 2A citable set (direct + context) benchmark.
- (B) CCI skill-ablation supplement. Left, per-dimension scores across Faithfulness, Overclaiming, Spatial Calibration, and Uncertainty Handling. Right, fabrication counts across Structured SKILLs, Structured SKILLs (Basic), Unstructured Prose, and No Skills.
- (C) Breast cancer Evidence-Grounded Follow-up Recommendations judge-stratified claim-boundary restraint.
- (D) Breast cancer Evidence-Grounded Follow-up Recommendations blind-judge preference shares.
Panel source paths:
- S4A uses `benchmarks/lr_retrieval_relevance/figures/sfigure2d_lr_retrieval_citable_set.svg`.
- S4B uses `benchmarks/cci_skill_ablation/figures/s_SkillAblation.svg`.
- S4C uses `benchmarks/dth/figures/FigS3D_DTH_BlindJudgeRigorByJudge.svg`.
- S4D uses `benchmarks/dth/figures/FigS3E_DTH_BlindJudgeWinRate.svg`.
Linking logic: S4A supports Figure 2A and can be cited as the compact LR citable-context bridge for the Figure 4 breast-cancer interpretation thread. S4B supports Figure 3B. S4C-D support Figure 3C right.

Supplementary Figure S5
Deep Interpreter use of STworkbench MCP with HITL.
Panels: STworkbench MCP execution trace, user/HITL selection or confirmation of interest clusters/factors/LR candidates, Deep Interpreter handoff/report trace, and optional source-output provenance snapshot.
Message: Supplementary Figure S5 documents how the cancer Visium spatial outputs in Figure 4 were selected, controlled, and handed to interpretation through an auditable MCP/HITL workflow. It should not be used as the main target-prioritization evidence figure.

Supplementary Figure S6
Reserved only if additional CCI overflow panels beyond Supplementary Figure S4B are needed. Otherwise, do not duplicate the skill-ablation supplement here.

Supplementary Figure S7
Reserved only if all-retrieved literature-coverage views need a separate display beyond Supplementary Figure S4A. Otherwise, keep the literature-retrieval coverage supplement as Supplementary Figure S4A and report additional all-retrieved analyses in tables or methods artifacts.

Supplementary Figure S8
Full SGCP retrieval benchmark across Qwen3.5-35B and Qwen3.5-122B model settings, including exact-answer accuracy, evidence recall, no-context failures, latency, and static-reference ablation.
```

## Table policy

기본은 tables를 supplement로 보냅니다.

Main text에 넣을 수 있는 예외:
- 아주 compact한 "benchmark summary table" 하나: Figure 2A-B와 Figure 3B-C의 primary endpoint와 claim boundary를 한 줄씩 정리.
- Cross-dataset summary table: disease/platform/application/validation status를 한눈에 보여주는 경우.

그 외 detailed metric tables는 supplement가 더 좋습니다.

---

# Methods Structure

Methods는 Results 순서와 맞추되, system architecture, benchmark methods, biological application methods를 분리합니다. 아래는 paper-ready prose draft로 사용할 수 있는 Methods skeleton입니다. 세부 숫자와 artifact path는 각 standalone methods 파일에서 최종 manuscript table/legend로 끌어오면 됩니다.

## Methods Draft

### DeepMAST system overview and claim-governed architecture

DeepMAST was implemented as a multi-agent harness for spatial transcriptomics interpretation and therapeutic target prioritization. The system accepts spatial transcriptomics inputs together with either a natural-language biological objective or a structured analysis request. A supervisor agent routes the request across four expert agents: Pipeline Builder, Pipeline Executor, Deep Target Prioritizer, and Deep Interpreter. Pipeline Builder and Pipeline Executor provide the analytical substrate by constructing and executing spatial transcriptomics workflows. Deep Target Prioritizer and Deep Interpreter provide the core evidence-governed claim layer by converting spatial outputs, ligand-receptor candidates, literature evidence, and database evidence into auditable biological interpretation and target-prioritization reports.

The orchestration layer uses LangGraph and DeepAgents for stateful execution, file-mediated context management, subagent delegation, and human-in-the-loop control [17,35]. Model Context Protocol (MCP) is used as the standardized interface between agent workflows and external analysis resources [18]. In DeepMAST, MCP servers standardize calls to external tools and biological resources, whereas the harness controls analysis-step selection, intermediate-output validation, evidence-retrieval constraints, and promotion of supported claims. The servers expose validated computational resources, skill-guided workflows define how evidence is retrieved and constrained, and validation-driven loops decide whether intermediate artifacts should be refined, retried, withheld, or promoted into final reports.

The DeepMAST harness is defined as the non-model control layer around the LLM agents, including MCP-mediated resource access, structured workflow contracts, source-provenance handling, claim-level validation, deterministic rendering, and evaluation procedures. The strongest claim-governance and fail-closed finalization gates are implemented in the Deep Target Prioritizer and Deep Interpreter paths. Pipeline Builder and Pipeline Executor should be described as workflow-control and analytical-execution modules rather than as evidence-finalization modules with identical hard gates.

### Study-specific MCP resources and skill-guided evidence workflows

DeepMAST used four study-specific MCP resources and three skill-guided evidence workflows. This block should appear early in Methods, before benchmark and dataset descriptions, because these resources are the operational layer that made the Results analyses reproducible. The MCP resources were Summary-Guided Chunk Promotion (SGCP), STworkbench MCP, visium_reference_selector_mcp, and rMCPAgent. The skill-guided workflows were biomedical-literature-search, compare-census-gene-pair-by-cell-type, and drug-target-hypothesis.

#### Summary-Guided Chunk Promotion MCP for source-grounded retrieval

Summary-Guided Chunk Promotion (SGCP) was used as a retrieval-control method for source-grounded biological interpretation. The base retrieval system extended LangConnect Client and LangChain LangConnect infrastructure for collection management, document ingestion, hybrid retrieval, and PostgreSQL/pgvector-backed storage. The methodological contribution was the SGCP promotion layer, not the base RAG service.

SGCP constructs a persistent SGCP index containing generated summaries and explicit source back-references to documents and chunks. The summaries are non-authoritative navigation memory: they guide retrieval toward likely source regions of the corpus, but they are not injected into the answer context as evidence. At query time, selected SGCP pages either promote exact referenced chunks in a static-reference ablation or route retrieval to likely source documents for query-conditioned hybrid search. Promoted chunks are deduplicated and passed through the same LLM relevance grading, answer generation, hallucination grading, and answer-quality grading steps as ordinarily retrieved chunks. Summary injection was disabled in the benchmark, so SGCP was evaluated only as bounded retrieval-time chunk promotion.

The SGCP benchmark used 2,556 MultiHop-RAG cases [44] under paired retrieval conditions for Qwen3.5-35B and Qwen3.5-122B. The primary comparison was baseline retrieval versus SGCP-enabled document-routed retrieval; static-reference promotion was treated as a supplementary ablation. Primary endpoints were normalized exact-answer containment and evidence recall among LLM-graded relevant documents. Token F1, no-relevant-context failure rate, retrieved chunk count, and latency were secondary endpoints.

#### STworkbench MCP for spatial transcriptomics analysis

STworkbench MCP was developed as a FastMCP-based spatial transcriptomics analysis framework for exploratory spatial characterization, ligand-receptor program discovery, and focused evaluation of candidate ligand-receptor interactions. The workflow accepted AnnData inputs containing expression matrices, spatial coordinates, cluster annotations, and either spot-level cell-type compositions or single-cell cell-type labels. For 10x Visium inputs, raw feature-barcode matrices were read with Squidpy, genes detected in fewer than five observations were removed, counts were normalized to 10,000 per observation, and expression values were log-transformed using Scanpy.

Spatial neighbor graphs were constructed according to platform geometry. Visium analyses used grid-based spatial neighbors with six nearest neighbors and two neighbor rings. Single-cell-resolution spatial datasets used Delaunay triangulation, with long edges removed at the 99th percentile by default. Multi-sample graphs were constructed independently within each sample to prevent cells or spots from different tissue sections, fields of view, or slides from being treated as spatial neighbors.

Exploratory STworkbench analyses visualized spatial clusters, quantified cluster-cell-type enrichment with one-sided Mann-Whitney U tests followed by Benjamini-Hochberg FDR correction, estimated spatial neighborhood enrichment with Squidpy permutation tests, and inferred pathway activity with decoupleR using PROGENy and MSigDB Hallmark signatures. Where pathway-cell-type relationships were evaluated, MISTy modeled local and broader spatial relationships between pathway activity scores and cell-type compositions or single-cell summaries.

Ligand-receptor interactions were inferred with LIANA+ using OmniPath-derived intercellular resources, including CellChatDB, CellPhoneDB, connectomeDB2020, and CellTalkDB annotations. Spatial co-localization was quantified with LIANA+ bivariate analysis using local cosine similarity and global bivariate Moran's R with 100 permutations and a fixed random seed. Positive Moran's R ligand-receptor pairs with p < 0.05 were carried into NMF. Candidate NMF ranks from 1 to 10 were evaluated by reconstruction error when the rank was not specified; an elbow detector selected the factor number, with five factors used as the fallback.

Ligand-receptor pairs contributing to the selected NMF factor were prioritized by integrating selected factor loading, Moran's R, and GenePT functional similarity. Each component was min-max normalized, and the primary score was computed as 0.4 times normalized factor loading plus 0.4 times normalized Moran's R plus 0.2 times normalized GenePT score. User-selected interest clusters focused the candidate set. Observation-level p values were aggregated separately across pooled interest and non-interest clusters using ACAT, followed by Benjamini-Hochberg FDR correction. Interactions with FDR-adjusted p < 0.05 in the interest-cluster group were retained, and additional candidates were added by Moran's R and factor loading when needed to reach the requested minimum set.

#### Visium reference selector MCP

The visium_reference_selector_mcp workflow compared candidate single-cell references for spot-based Visium analyses. The method was used in the prostate cancer reference-selection case study, where the spatial query was the 10x Genomics Human Prostate Cancer, Adenocarcinoma with Invasive Carcinoma (FFPE) Visium Spatial Gene Expression dataset [45]. Two candidate references, GSE181294 [46] and GSE185344 [47], were compared after metadata-aware loading, duplicate-gene resolution, stratified downsampling, common-gene harmonization, normalization, and fused Gromov-Wasserstein (FGW) distance calculation.

The prostate cancer spatial input contained 4,371 spots and 17,943 genes at loading. Duplicate-gene handling left 17,941 spatial genes. GSE181294 was downsampled from 156,301 to 9,991 cells, and GSE185344 from 57,697 to 9,995 cells. After harmonization, the spatial query and both references were restricted to the same 16,385-gene feature space. Spatial and reference data were normalized to 10,000 counts per observation and log-transformed using Scanpy. Reference similarity was measured with FGW distance using a fused-distance mixing parameter of 0.5 and entropic regularization of 0.1. Lower distances were interpreted as stronger agreement between the spatial query and a candidate reference.

#### rMCPAgent for converting R workflows into MCP-compatible services

rMCPAgent was used as the R-workflow MCP generation layer for deconvolution-ready spatial analysis. The framework converted R-based bioinformatics functions into MCP-compatible services through four layers: function discovery and schema construction, workflow template standardization, production enhancement, and validation. This design follows the Methods pattern in SPARK, where agentic workflow modules are described together with their preprocessing, validation, and reproducibility boundaries.

Workflow templates specified required inputs, analysis parameters, output files, and validation rules, allowing package-specific R implementations to be wrapped behind a stable agent-facing contract. For deconvolution, templates required H5AD spatial inputs with expression matrices and spatial coordinates, single-cell reference inputs with expression and cell-type/sample metadata, and count-based filtering parameters. The primary deconvolution output was a table with one row per spatial barcode and numeric cell-type proportion columns.

The production workflow applied five stages before exposing an R workflow to Pipeline Executor: input validation, data loading, workflow integration, recovery diagnostics, and output validation with MCP registration. Input validation checked file existence, file type, readability, required assays, spatial coordinates, metadata fields, and compatibility between spatial and reference datasets. Data loading converted validated H5AD inputs into R-compatible objects through zellkonverter. Recovery diagnostics converted file-access failures, missing metadata, unsupported assays, invalid parameters, package execution failures, output-write failures, and malformed outputs into structured messages. Deconvolution outputs were accepted only when they contained barcode identifiers, at least one numeric proportion column, no missing values, values bounded between 0 and 1, and row-wise proportions summing to 1.0 within a tolerance of 0.01.

#### Biomedical literature search skill

The biomedical-literature-search skill was used as a reusable PubMed literature workflow for ligand-receptor and disease-context evidence. The skill is not a new retrieval backend and should not be described as improving PubMed search itself. It is a protocol for tool use, evidence grading, citation selection, and handoff artifact construction.

In SEARCHER production mode, the skill retrieves a broad disease-anchored raw paper pool for one or more ligand-receptor pairs, saves the complete raw retrieval set, grades title and abstract evidence into citation buckets, and writes the canonical SEARCHER-to-INTERPRETER handoff artifact. Direct ligand-receptor evidence and receptor/pathway context evidence are passed to the Interpreter by default, whereas disease-only background and weak evidence are retained for audit but excluded from interpreter-facing context. In retrieval-only benchmark mode, the skill uses the same broad retrieval strategy but skips the filtered handoff step so that retrieval effects can be isolated.

#### Compare Census gene-pair-by-cell-type skill

The compare-census-gene-pair-by-cell-type skill was used for disease-focused CELLxGENE Census analysis of ligand-receptor or gene-pair evidence. The workflow computes gene A-positive, gene B-positive, and co-expression rates across cell types in a disease subset, then tests enrichment or depletion in a target cell type versus all remaining cells. The command interface requires disease, gene A, gene B, target cell type, organism, Census version, and cell-count thresholds. Pinned Census versions are preferred for reproducibility.

Outputs include an overall summary, a target-versus-rest comparison, and a cell-type summary table. Target-versus-rest comparisons report positive rates, absolute difference, risk ratio, z statistic, and two-proportion z-test p value. Full per-cell-type metrics can be exported as CSV for downstream target-prioritization or claim-validation steps. Small cell counts are treated cautiously even when nominal p values are small.

#### Drug-target hypothesis skill

The drug-target-hypothesis skill generated conservative evidence-grounded follow-up recommendations from completed Stage 1-3 drug-target assessment evidence. It was not used as a free-form hypothesis-generation workflow. The skill reads hypothesis-scope evidence, classifies evidence support, enforces claim boundaries, validates every cited filename, and persists a structured hypothesis artifact for downstream report writing.

The workflow requires a completed evidence bundle with non-empty Stage 3 candidates. Phase 1 ingests evidence and categorizes targets. A deterministic Stage 1 eligibility gate separates interest-cell intrinsic support, secondary spatial-niche or cross-cell support, and gene-level/actionability-only support. Phase 2 generates follow-up recommendations using class-specific language so that same-cell, cross-cell, spatial-niche, and gene-level claims remain distinct. Phase 3 detects evidence gaps. Phase 4 applies UCB-style scoring and filtering. Later gates validate evidence references, enforce top-N coverage, save the hypothesis artifact, and retry only changed fields when deterministic rejection identifies invalid references, unsupported direct pair axes, failed Stage 1 pair evidence, or missing featured-gene coverage.

### Data inputs, benchmark artifacts, and source evidence

DeepMAST analyses used spatial transcriptomics datasets, ligand-receptor candidate tables, target-prioritization evidence bundles, literature retrieval collections, and frozen benchmark artifacts. The human cancer Visium analyses were designed as complementary modularity demonstrations rather than as a comparative oncology study. The breast cancer arm used preprocessed Visium/Xenium-matched breast cancer annotations and spatial clustering as a curated downstream-interpretation setting linked to the integrated single-cell, spatial, and in situ breast cancer study, the Starfysh spatial/histology analysis, and the public accession GSE243280 [42,43]. The prostate cancer arm used the 10x Genomics Human Prostate Cancer, Adenocarcinoma with Invasive Carcinoma (FFPE) Visium dataset and emphasized upstream reference selection, MCP-mediated execution, and downstream biological interpretation [45].

The fixed breast cancer Deep Target Prioritizer evidence package was used for Evidence-Grounded Follow-up Recommendations validation. This package assessed 37 unique genes from the top-30 ligand-receptor pairs, selected 7 Stage 3 featured candidates, and contained prioritized target candidates, ligand-receptor candidates, malignant-cell pair evidence, gene-level target evidence, Open Targets target-disease evidence, known-drug annotations, and recommendation-validation metadata. Featured target genes included ERBB3, EPHB4, ERBB2, INSR, EFNB2, NECTIN4, and LAMA5.

The mouse Alzheimer STARmapPLUS analysis should be described as a cross-platform spatial transcriptomics application rather than as therapeutic validation. Methods should specify the dataset, preprocessing status, spatial analysis outputs supplied to DeepMAST, disease/cell-type context, and which downstream modules were activated. The human idiopathic pulmonary fibrosis Visium analysis is the strongest therapeutic target-prioritization application and should describe the Visium input, ligand-receptor candidate generation, target-prioritization run, database evidence sources, featured and novel candidate selection, and any experimental or external validation used in the manuscript.

Frozen reproducibility bundles should be cited in Methods as source artifacts rather than as manuscript references. Relevant bundles include CCI skill-ablation outputs under `docs/benchmarks/cci_skill_ablation/`, literature-retrieval coverage artifacts under `benchmarks/lr_retrieval_relevance/`, SGCP accuracy/recall artifacts under `benchmarks/sgcp_accuracy_recall/`, and follow-up recommendation validation artifacts under `benchmarks/dth/`. Offline reproduction scripts are preferred as stable manuscript references because they regenerate summary tables and figures from committed artifacts without calling live model endpoints or external retrieval services.

### Benchmark design and evaluation

The benchmark suite was designed to separate evidence acquisition, source-grounded retrieval, and claim generation. This separation follows the reference-paper pattern in which system modules are first defined, then evaluated through bounded benchmarks with direct endpoints. Each panel should have a narrow endpoint and should not be overinterpreted as a generic measure of full-system performance.

The evidence acquisition benchmark tested whether the biomedical-literature-search skill broadened retrieval-stage citable biological context coverage before downstream interpretation. The same 30 ligand-receptor cases from the CCI benchmark were evaluated under paired skill ON and skill OFF conditions for Qwen3.5-35B and Qwen3.5-122B. Coverage was computed over all retrieved papers and over the interpreter-facing citable set, defined as direct ligand-receptor evidence or receptor/pathway context evidence after applying the same handoff policy to both arms. Main Figure 2A should use the citable set for both Qwen3.5-35B and Qwen3.5-122B, with all-retrieved analyses reported as supplementary evidence.

The SGCP source-grounded retrieval benchmark evaluated baseline retrieval, static-reference SGCP, and SGCP-enabled document-routed retrieval on the same 2,556 MultiHop-RAG cases [44]. The primary comparison was baseline retrieval versus SGCP-enabled retrieval. Static-reference promotion was retained as a supplementary ablation. Main Figure 2B should present Qwen3.5-35B and Qwen3.5-122B together to show both model-scale robustness and the larger gain in the 35B setting.

The structured CCI interpretation benchmark tested whether structured biological SKILL guidance reduced unsupported free-text interpretation of ligand-receptor pairs from breast cancer Visium data. The benchmark used 30 ligand-receptor cases sampled from LIANA+ outputs using a 3 x 2 stratified design over Moran's R magnitude and literature/pathway annotation status. Each case included the interaction identifier, spatial co-localization statistics, ligand and receptor expression metrics, pathway and disease annotations, cell-type expression patterns, and tissue context. The main comparison used no skill guidance, unstructured prose guidance, and guide-compliant structured SKILL guidance; a fourth basic structured-SKILL condition was retained for supplementary analysis.

The Evidence-Grounded Follow-up Recommendations validation tested whether the drug-target-hypothesis workflow improved recommendation quality after spatial ligand-receptor evidence had been curated. Guided and baseline prompts used the same generator model, source evidence, schema contract, save gate, and retry policy. In the baseline condition, the writer received the operational contract but no follow-up recommendation guide. In the guided condition, the writer was required to use the recommendation guide before generating recommendations. Valid-output analysis included 20 guided and 20 baseline runs generated with Qwen3.5-397B (`qwen3.5:397b-cloud`). The primary endpoint should be Figure 3C right, claim-boundary restraint; Figure 3C left should be treated as a secondary coverage summary.

LLM judging and automated auditing were used only for bounded evaluation targets. Automated auditing recorded evidence coverage, retained recommendations, evidence references, retry counts, and lexical evidence-use indicators. Blind judging compared anonymized guided and baseline outputs for evidence grounding, biological plausibility, therapeutic relevance, claim-boundary restraint, and specificity/testability, with unsupported-claim penalties and major-error flags.

### Biological application workflows

The complementary human cancer Visium analyses were used to demonstrate modularity across upstream execution and curated downstream interpretation. In the prostate cancer arm, Pipeline Executor first selected a single-cell reference for deconvolution, then exposed downstream spatial analysis through MCP-mediated execution before outputs were passed to Deep Interpreter. In the breast cancer arm, curated HITL selection used interest clusters 17, 4, and 14, the Prolif Invasive Tumor cell type, and Factor3. STworkbench MCP generated the NMF/factor spatial program summary, selected ligand-receptor spatial maps, and quantitative interaction summaries. Deep Interpreter then generated literature-grounded disease-context interpretation from these selected outputs.

The breast cancer follow-up recommendation workflow used the fixed Deep Target Prioritizer evidence package described above as the controlled evidence substrate for Figure 3C. The full staged target-evidence assessment, druggability evidence, and deterministic report finalization should be described as biological application results in the later IPF/Figure 6 target-prioritization analysis rather than as an additional main Figure 3 panel.

The mouse Alzheimer STARmapPLUS analysis should test whether DeepMAST generalizes beyond Visium spot-level data to single-cell-resolution spatial transcriptomics. The Methods should specify the input data type, preprocessing status, spatial analysis outputs supplied to DeepMAST, disease/cell-type context, and downstream modules activated. The direct claim should remain cross-platform interpretability and evidence traceability, not therapeutic validation.

The human IPF Visium analysis should be presented as the strongest therapeutic target-prioritization application. Methods should describe the Visium input, CCI or ligand-receptor candidate generation, Deep Target Prioritizer run, CELLxGENE/OpenTargets/GWAS/DrugBank/ChEMBL-style evidence sources when used, featured and novel candidate selection, and any experimental or external validation included in the manuscript. Therapeutic language should remain conservative: DeepMAST prioritizes candidate therapeutic targets and generates Evidence-Grounded Follow-up Recommendations; it does not establish clinical efficacy without downstream experimental validation.

### Statistical analysis, software, and reproducibility

All benchmark analyses should use paired designs when the same prompt, case, or question is evaluated under multiple conditions. The CCI hallucination benchmark uses Kruskal-Wallis tests for omnibus condition differences, Mann-Whitney U tests with Bonferroni correction for post-hoc comparisons, and quadratic weighted kappa for inter-rater agreement. Literature-retrieval coverage uses paired case-level differences, bootstrap confidence intervals, and paired Wilcoxon signed-rank tests. SGCP uses exact McNemar tests for answer containment and paired Wilcoxon signed-rank tests for evidence recall, token F1, chunk count, and latency. Follow-up recommendation evidence-coverage comparisons use paired Wilcoxon signed-rank tests over matched valid runs. Blind-judge preferences use exact two-sided sign tests over non-tie pairs, and claim-boundary restraint uses paired Wilcoxon signed-rank tests after averaging judge scores within each pair, with judge-stratified tests as sensitivity analyses.

Software environments were recorded for reproducibility. STworkbench MCP used Python >=3.10 with Scanpy, Squidpy, LIANA, decoupleR, OmniPath, scikit-learn, statsmodels, Plotly, FastMCP, and MCP. rMCPAgent was implemented in R >=4.0.0 with ellmer, mcptools, zellkonverter, Bioconductor containers, sparse matrix support, workflow templates, JSON/HTTP utilities, and package-development/test dependencies. visium_reference_selector_mcp used FastMCP, AnnData/Scanpy, optimal transport and JAX-compatible computation when available, and Plotly report generation. SGCP benchmarks used the frozen raw provenance files and offline regeneration scripts in the SGCP reproducibility bundle.

Data availability and code availability should be reported separately from manuscript references. Public dataset accessions, public tool repositories, software versions, and archived benchmark bundles belong in Methods or Source Artifacts. Local file paths, generated CSV/JSON/JSONL artifacts, notebook paths, and repository-internal implementation files should not be added to the manuscript References section unless they are replaced by public URLs, DOIs, or archival repository identifiers.

Methods에서 중요한 원칙:
- 4개 MCP와 3개 Skill은 Methods 앞부분에서 study-specific resources로 먼저 설명합니다. 이 블록은 DeepMAST가 단순 agent wrapper가 아니라 실행 가능한 분석 리소스와 evidence workflow를 함께 구축했다는 점을 보여줍니다.
- Skill 관련 하위제목은 activation 중심으로 쓰지 않습니다. 대신 `skill-guided evidence workflows`로 쓰고, 각 skill은 활성화 메커니즘이 아니라 재현 가능한 evidence protocol로 설명합니다.
- Pipeline Builder/Executor는 자세히 쓰되 novelty를 과장하지 않습니다. 이들은 DeepMAST의 analytical substrate입니다.
- Complementary cancer Visium Methods에서는 prostate cancer가 visium_reference_selector_mcp와 rMCPAgent/Pipeline Executor를 보여주는 reference-guided execution setting이고, breast cancer가 preprocessed annotations/spatial clustering을 사용하는 curated downstream-interpretation setting이면서 Figure 3의 Evidence-Grounded Follow-up Recommendations validation으로 이어진다는 점을 명시합니다.
- Deep Target Prioritizer와 Deep Interpreter는 core biological harness modules로 더 자세히 씁니다.
- HITL과 expert review는 "사용자가 알아서 확인한다"는 disclaimer가 아니라, DeepMAST가 auditable artifacts, provenance, and claim-level checks를 제공하는 이유로 Methods에 명시합니다.
- DeepMAST를 formal acronym으로 강하게 풀어쓰지 않습니다. 이름 유래를 설명해야 할 때만 "DeepAgents-based, multi-agent spatial transcriptomics architecture"를 반영한 이름이라고 약하게 쓰고, 곧바로 primary contribution이 evidence-governed harness이고 구조적 작동 원리가 validation-driven looping임을 명시합니다.
- SGCP는 method = **Summary-Guided Chunk Promotion**, artifact = **the SGCP index**로 명확히 씁니다.
- Benchmark methods는 각 benchmark의 direct endpoint를 분명히 제한합니다.
- Main Figure 2A는 citable set(direct + context)만 main에 두되 Qwen3.5-35B와 Qwen3.5-122B를 함께 제시하고, all-retrieved analyses는 supplement에 둡니다.
- Main Figure 2B는 Qwen3.5-35B와 Qwen3.5-122B를 함께 제시해서 model-scale robustness와 Qwen3.5-35B의 larger gain을 동시에 보여줍니다.

---

# Discussion Structure

#35 vd 122

Discussion은 "more tools"가 아니라 "better biological control layer", "evidence-governed claims", and "validation-driven looping"으로 닫습니다.

```text
Discussion

DeepMAST extends harness engineering from tool execution to evidence-grounded biological reasoning through validation-driven looping

Tool access, MCP standardization, and spatial-agent automation are necessary but insufficient for biological conclusion generation

The governance target is not only tool access but which biological and therapeutic claims are allowed to survive into the final report

Recent harness and long-horizon agent studies support the same framing: useful control comes from preserving task-relevant state, retaining valid feedback, and carrying failure-derived rules into subsequent actions, not from adding raw context, tool calls, or larger harnesses alone

Structured SKILL guidance reduces unsupported CCI interpretation, and follow-up recommendation guidance extends the same evidence-governance principle to breast cancer follow-up recommendation claim-boundary restraint

The Figure 2/3 validation bridge should be framed as a staged evidence-governance argument: Figure 2 tests evidence acquisition and source-grounded retrieval, whereas Figure 3 tests whether structured guidance constrains the claims generated from that evidence

Literature-search skills and SGCP improve evidence entry points across model scales by converting coverage, relevance, and quality checks into bounded retrieval loops. The model-size pattern should be framed as task fit rather than model ranking. Figure 2a supports a balanced interpretation because Qwen3.5-122B showed the larger absolute citable cell-type coverage gain, whereas Figure 2b shows that SGCP produced the larger retrieval-control gain in Qwen3.5-35B. This is consistent with internal constrained-generation and selective-activation notes in which Qwen3.5-35B was more reproducible under literal schema adherence, conservative evidence attribution, deterministic candidate coverage, and traceable activation contracts, while Qwen3.5-122B more often synthesized, compressed, or bypassed soft protocol steps. The Discussion should therefore treat Qwen3.5-35B advantages as stage-specific reliability signals, not as evidence of superior general scientific reasoning. A cautious framing is that DeepMAST performance depends on matching model behavior to the stage objective, with Qwen3.5-35B sometimes serving as a more reliable contract-following generator and Qwen3.5-122B remaining useful for reviewer, critic, or higher-level synthesis roles after evidence-grounded artifacts pass validation.

Internal source notes for this Discussion point:
- `docs/benchmarks/harness_x_model/REV6_4ERA_RESULTS.md` reports stable Qwen3.5-122B retrieval-skill gains and content-sensitive, partially recoverable Qwen3.5-35B behavior after skill recalibration.
- `docs/benchmarks/hypothesis_generation_consistency/smaller_vs_larger_model_activation_interpretation.md` reports stronger selective skill-activation compliance for Qwen3.5-35B under the Governor protocol.
- `docs/benchmarks/drugtarget_skill_ablation/results/ipf_hypothesis_generation_qwen35_vs_122b_20260609.md` reports higher operational reproducibility for Qwen3.5-35B in constrained IPF recommendation generation, while cautioning against interpreting this as superior general scientific reasoning.

The paired cancer Visium application should be framed as a modularity demonstration rather than a comparative oncology claim: prostate cancer exercises upstream reference-guided execution before downstream interpretation, whereas breast cancer exercises downstream curated interpretation and selected ligand-receptor handoff after the Figure 3 claim-governance bridge

Separating biological interpretation from target prioritization improves traceability of therapeutic follow-up recommendations

DeepMAST complements rather than replaces human biological expertise by producing auditable, provenance-linked, expert-reviewable artifacts rather than autonomous therapeutic decisions

DeepMAST should not be described as self-evolving; the safer future-facing claim is that validated failure traces could later support curated biological skill updates after regression testing and expert review

Limitations: benchmark scope, model dependence, literature bias, database incompleteness, pathway benchmark power, latency cost, dataset coverage, and experimental validation scale

Future directions: larger multi-disease benchmarks, expert adjudication, adaptive retrieval budgets, prospective validation, failure-trace mining for validated skill updates, closed-loop experimental design, and community biological skill libraries
```

가장 중요한 Discussion 메시지:

```text
DeepMAST suggests that the next stage of biomedical agent development will not be defined by adding more tools, longer context, or larger harnesses alone, but by building biological harnesses that preserve task-relevant state, convert valid feedback into subsequent actions, govern when retrieved evidence should enter context, decide which claims are sufficiently supported, and make therapeutic conclusions fail closed when evidence remains insufficient.
```

이 구조로 가면 DeepMAST는 단순한 spatial transcriptomics automation agent가 아니라, **MCP-enabled tools를 domain skills, SGCP, staged evidence assessment, provenance checks, claim-level validation, validation-driven looping, and deterministic reporting으로 통제하는 evidence-governed biomedical agent harness**로 보입니다.

---

# References

[1] DOI: 10.1126/science.aaf2403. "Visualization and analysis of gene expression in tissue sections by spatial transcriptomics."

[2] DOI: 10.1038/s41586-021-03634-9. "Exploring tissue architecture using spatial transcriptomics."

[3] DOI: 10.1038/s41576-021-00370-8. "Integrating single-cell and spatial transcriptomics to elucidate intercellular tissue dynamics."

[4] DOI: 10.1038/s41467-021-25557-9. "Computational challenges and opportunities in spatially resolved transcriptomic data analysis."

[5] DOI: 10.7150/thno.95908. "Spatial Transcriptomics: A Powerful Tool in Disease Understanding and Drug Discovery."

[6] DOI: 10.48550/arXiv.2305.11738. "CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing."

[7] DOI: 10.48550/arXiv.2510.09901. "Autonomous Agents for Scientific Discovery: Orchestrating Scientists, Language, Code, and Physics."

[8] arXiv: 2508.14111. "From AI for Science to Agentic Science: A Survey on Autonomous Scientific Discovery." https://arxiv.org/abs/2508.14111

[9] "BioMaster." Source in `agentpaper` collection: `BioMaster.pdf`; bioRxiv DOI reported in the paper: https://doi.org/10.1101/2025.01.23.634608

[10] "GenoMAS." Source in `agentpaper` collection: `GenoMAS.pdf`; code URL reported in the paper: https://github.com/Liu-Hy/GenoMAS

[11] "STAgent / Spatial Transcriptomics AI Agent." Source in `agentpaper` collection: `STAgent.pdf`

[12] "SpatialAgent: An autonomous AI agent for spatial biology." Source in `agentpaper` collection: `SpatialAgent.pdf`

[13] DOI: 10.64898/2026.01.16.696667. "Medea: An omics AI agent for therapeutic discovery." Public full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC12871667

[14] DOI: 10.1093/bib/bbag075. "Artificial Intelligence agents for biological research: a survey." Public full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC12936789

[15] DOI: 10.1093/bib/bbaf505. "Streamline automated biomedical discoveries with agentic bioinformatics." Public full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC12476841

[16] DOI: 10.1038/s41591-026-04357-y. "An agentic framework for autonomous scientific discovery in cancer pathology."

[17] "Deep Agents overview." LangChain documentation. https://docs.langchain.com/oss/python/deepagents/overview

[18] "Model Context Protocol Specification." https://modelcontextprotocol.io/specification/2025-11-25

[19] "SkillsBench: How Agent Skills Improve Performance Across Diverse Tasks." https://citations.gxl.ai/papers/arx_2602.12670#L4-L12

[20] "SkillTester: Holistic Evaluation of Utility and Security for Agent Skills." https://citations.gxl.ai/papers/arx_2603.28815#L10-L18

[21] "Trace2Skill: Generating Agent Skills from Execution Data." https://citations.gxl.ai/papers/arx_2603.25158#L5-L32

[22] "SWE-Skills-Bench: Measuring the Impact of Agent Skills on Software Engineering Tasks." https://citations.gxl.ai/papers/arx_2603.15401#L17-L31

[23] "Agent Skills for Large Language Models." https://citations.gxl.ai/papers/arx_2602.12430#L5-L13

[24] "SkillWeaver: Web Agents can Self-Improve by Discovering and Honing Skills." https://citations.gxl.ai/papers/arx_2504.07079#L7-L21

[25] "SkillNet: Towards Open Infrastructure and General Evaluation for AI Skills." https://citations.gxl.ai/papers/arx_2603.04448#L10-L33

[26] "AgentSkillOS: Towards Automatic Skill Selection, Orchestration, and Ecosystem Management." https://citations.gxl.ai/papers/arx_2603.02176#L4-L37

[27] "Memento-Skills: How to Continuously Learn and Adapt as a Language Agent." https://citations.gxl.ai/papers/arx_2603.18743#L4-L32

[28] "XSkill: Cross-Embodiment Skill Discovery for Visual-Language Agents." https://citations.gxl.ai/papers/arx_2603.12056#L6-L28

[29] "SKILLFOUNDRY: Building Self-Evolving Agent Skill Libraries from Heterogeneous Scientific Resources." Source in `agentpaper` collection: `skillfoundry.pdf`; project URLs reported in the paper: https://github.com/ma-compbio-lab/SkillFoundry and https://ma-compbio-lab.github.io/SkillFoundry/

[30] arXiv: 2605.30785. "Learning Agent-Compatible Context Management for Long-Horizon Tasks." https://arxiv.org/html/2605.30785v1

[31] arXiv: 2605.29682. "Scaling Laws for Agent Harnesses via Effective Feedback Compute." https://arxiv.org/abs/2605.29682

[32] arXiv: 2605.30621. "Harness Updating Is Not Harness Benefit: Disentangling Evolution Capabilities in Self-Evolving LLM Agents." https://arxiv.org/abs/2605.30621

[33] arXiv: 2606.09498. "Self-Harness: Harnesses That Improve Themselves." https://arxiv.org/abs/2606.09498

[34] arXiv: 2606.05080. "AutoLab: Can Frontier Models Solve Long-Horizon Auto Research and Engineering Tasks?" https://arxiv.org/abs/2606.05080

[35] "LangGraph overview." LangChain documentation. https://docs.langchain.com/oss/python/langgraph/overview

[36] "CZ CELLxGENE Discover: A single-cell data platform for scalable exploration, analysis and modeling of aggregated data." CZ CELLxGENE citation page and bioRxiv DOI. https://cellxgene.cziscience.com/docs/08__Cite%20cellxgene%20in%20your%20publications

[37] "Open Targets Platform: facilitating therapeutic hypotheses building in drug discovery." Open Targets Platform citation page. https://platform-docs.opentargets.org/citation

[38] "GWAS Catalog current citation." NHGRI-EBI GWAS Catalog related resources. https://www.ebi.ac.uk/gwas/docs/related-resources

[39] "The STRING database in 2025: protein networks with directionality of regulation." Nucleic Acids Research. https://academic.oup.com/nar/article/53/D1/D730/7903368

[40] "The Reactome Pathway Knowledgebase 2024." Nucleic Acids Research. https://academic.oup.com/nar/article/52/D1/D672/7369850

[41] "The ChEMBL Database in 2023: a drug discovery platform spanning multiple bioactivity data types and time periods." Nucleic Acids Research. https://academic.oup.com/nar/article/52/D1/D1180/7337608

[42] DOI: 10.1038/s41467-023-43458-x. "High resolution mapping of the tumor microenvironment using integrated single-cell, spatial and in situ analysis."

[43] DOI: 10.1038/s41587-024-02173-8. "Starfysh integrates spatial transcriptomic and histologic data to reveal heterogeneous tumor-immune hubs."

[44] DOI: 10.48550/arXiv.2401.15391. "MultiHop-RAG: Benchmarking Retrieval-Augmented Generation for Multi-Hop Queries."

[45] URL: https://www.10xgenomics.com/datasets/human-prostate-cancer-adenocarcinoma-with-invasive-carcinoma-ffpe-1-standard-1-3-0. "Human Prostate Cancer, Adenocarcinoma with Invasive Carcinoma (FFPE)." 10x Genomics Spatial Gene Expression dataset analyzed using Space Ranger 1.3.0.

[46] DOI: 10.1038/s41467-023-36325-2. "Dissecting the immune suppressive human prostate tumor microenvironment via integrated single-cell and spatial transcriptomic analyses." GEO accession: GSE181294; PMID: 36750562.

[47] DOI: 10.1038/s41467-022-33780-1. "Single cell analysis of cribriform prostate cancer reveals cell intrinsic and tumor microenvironmental pathways of aggressive disease." GEO accession: GSE185344; PMID: 36229464.

[48] DOI: 10.1186/1471-2407-7-73. "Nectin-4 is a new histological and serological tumor associated marker for breast cancer."

[49] DOI: 10.1002/path.6394. "Afadin loss induces breast cancer metastasis through destabilisation of E-cadherin to F-actin linkage."

[50] DOI: 10.1111/jcmm.15140. "E-cadherin deregulation in breast cancer."

[51] DOI: 10.1186/1471-2407-13-383. "HRG-beta1-driven ErbB3 signaling induces epithelial-mesenchymal transition in breast cancer cells."

[52] DOI: 10.3390/ijms25115978. "Disrupting EGFR-HER2 Transactivation by Pertuzumab in HER2-Positive Cancer: Quantitative Analysis Reveals EGFR Signal Input as Potential Predictor of Therapeutic Outcome."

[53] "Natural-Language Agent Harnesses." https://arxiv.org/abs/2603.25723

[54] "AutoHarness: Automatic Generation of Agent Harnesses." https://citations.gxl.ai/papers/arx_2603.03329#L6-L21

[55] "Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering." https://arxiv.org/abs/2604.08224

[56] "CRISPR-GPT: An LLM Agent for Automated Design of Gene-Editing Experiments." https://citations.gxl.ai/papers/bio_ea67019d70c5#L17-L45
