# DeepMAST Paper Framing

이 문서는 DeepMAST 논문의 narrative, Introduction/Results 구조, figure framing, reference positioning을 정리한 writing blueprint입니다. 전체 Results는 MEDEA의 system-overview/benchmark/ablation 흐름, SpatialAgent와 STAgent의 spatial biology use-case framing, SPARK의 staged reasoning and verification logic, twasis의 discovery-to-prioritization evidence progression을 참고하되, DeepMAST의 중심 contribution은 **MCP/tool access를 domain-specific control layer로 제약, 검증, 증거화하는 evidence-governed biological agent harness**로 잡습니다. 핵심 정체성은 **evidence-governed harness**이고, 구조적 작동 원리는 **validation-driven looping**입니다.

**Central thesis**

DeepMAST is built on the premise that reliable spatial transcriptomics agents require more than access to MCP servers or biological tools. MCP standardizes how tools are called, but it does not specify how tools should be selected, sequenced, validated, interpreted, or converted into target-prioritization evidence. The central governance target is therefore not only tool use, but the biological and drug-target claims that survive into the final report. DeepMAST addresses this gap through harness engineering: a non-model control layer that surrounds LLM agents with domain-specific skills, stage-specific tool constraints, structured intermediate artifacts, provenance-aware reporting, claim-level validation, deterministic rendering, fail-closed finalization, literature-grounded interpretation, explicit drug-target evidence scoring, and expert-reviewable reports. In this framing, DeepMAST operationalizes harness engineering through validation-driven looping: intermediate artifacts are checked for coverage, relevance, provenance, claim support, and report readiness, and failed checks trigger bounded refinement or fail-closed withholding rather than direct finalization.

**Problem / gap / solution**

- **Problem:** Spatial transcriptomics can reveal spatially localized disease programs, but therapeutic interpretation requires selecting the right biological tools, executing them in a defensible order, validating their outputs, integrating results with literature and disease context, and deciding which claims are evidence-supported enough to report.
- **Gap:** Tool access alone does not define scientific reasoning. Without domain-specific skills, verification rules, provenance tracking, evidence-integration protocols, and claim-level governance, agents can call valid tools in inappropriate contexts or generate plausible but unsupported therapeutic claims.
- **Solution:** DeepMAST treats MCP servers and biological tools as resources inside a broader biological harness. Domain skills encode how tools should be selected and interpreted, while validation-driven loops, provenance checks, literature grounding, evidence scoring, and deterministic finalization govern whether an output can become a scientific or therapeutic conclusion.

**Positioning against prior work**

Manuscript-facing references are numbered by first appearance from the Introduction Draft onward. See the `References` section at the end.

Use a conservative claim boundary. Do not argue that prior systems lack harness engineering entirely, because general harness-oriented work already studies action constraints, runtime behavior, verification, and externalized control layers [71-73]. Instead, position prior Agent Skills work as focused on reusable procedural packages, skill selection, and evaluation [23-32]; scientific skill-library work as extending skill construction into genomics workflows such as spatial transcriptomics cell type annotation and single-cell scDRS [33]; and biomedical agent systems as emphasizing workflow automation, tool access, spatial/omics interpretation, or therapeutic reasoning [9-13,74]. DeepMAST’s gap is the integration of these directions into a **skill-inclusive, evidence-governed biological harness** for spatial transcriptomics interpretation, transparent drug-target prioritization, validation-driven looping, and governance over evidence-bearing claims.

**Model notation**

Use manuscript-facing model names as `Qwen3.5-9B`, `Qwen3.5-35B`, and `Qwen3.5-122B` where each appears. Avoid capability-adjective labels for model-size groups in prose. Raw runtime tags should not be used in manuscript-facing prose.

**Operational definition**

```text
We define harness engineering as the design of the non-model control layer around an LLM agent, including domain-specific instructions, skill-guided evidence workflows, tool-use constraints, staged execution, validation-driven loops, provenance tracking, claim-level validation, and evaluation procedures that make agent outputs auditable, reproducible, and reviewable by domain experts [71-73].
```

For DeepMAST, the harness is the domain-specific control layer surrounding the LLM: it uses task-relevant biological skills, constrains MCP tool use by analysis stage, separates biological interpretation from target scoring, routes LLM outputs through structured artifacts, verifies evidence provenance, and renders scientific or therapeutic conclusions only when they are supported by traceable sources and pass deterministic checks. Its structural operating principle is validation-driven looping: coverage checks, relevance gates, provenance validators, claim-quality checks, and finalization-readiness checks decide whether an intermediate artifact is refined, retried, withheld, or promoted to an expert-reviewable conclusion. This makes DeepMAST closer to an evidence-governed biomedical agent harness than to a tool-executing spatial transcriptomics agent.

**Defensible claim boundary**

DeepMAST should be described as applying harness engineering most strongly to its core scientific interpretation pipelines, especially the drug-target and deep-interpretation pathways. The Pipeline Builder and Pipeline Executor are important expert agents that provide the analytical substrate, HITL workflow construction, MCP readiness checks, and tool execution, but they should not be described as having the same hard finalization gates as the drug-target reporting path. Avoid broad across-all-agent claims that imply identical hard gates in every module. A safer formulation is:

```text
DeepMAST applies harness engineering to its core biomedical interpretation pipelines by routing LLM outputs through staged execution, tool constraints, structured artifacts, validation-driven loops, provenance-aware validation, deterministic rendering, and fail-closed finalization where implemented.
```

## Overall Paper Structure

### Title

최종 제목은 아래로 고정합니다. 핵심 contribution은 **evidence-governed agent harness**이고, `Spatial Transcriptomics`는 중간에 넣지 않고 제목 끝의 application-domain qualifier로 둡니다. `validation-driven looping`은 제목에 직접 넣지 않고 Abstract, Introduction, Figure 1/2, Discussion에서 harness의 구조적 작동 원리로 반복해서 설명합니다.

```text
DeepMAST: An Evidence-Governed Agent Harness for Literature-Grounded Interpretation and Drug-Target Prioritization in Spatial Transcriptomics
```

`DeepMAST` 이름은 유지하되, 제목에서 DeepAgents 구현 의존성을 직접 설명하지 않습니다. DeepAgents는 Introduction/Methods에서 long-horizon orchestration substrate로 설명하고, 제목은 governance/reliability 방향성과 claim-level evidence control을 전면에 둡니다. “drug target discovery”는 강한 표현이고, 임상 효능이나 검증된 치료 효과를 암시할 수 있으므로 전체 논문 제목에서는 “Drug-Target Prioritization”을 사용합니다.

Acronym/name-origin 설명은 제목이나 Abstract 첫 문장에 넣지 않습니다. 필요하면 Architecture 또는 Methods에서만 약하게 설명합니다:

```text
The DeepMAST name reflects its DeepAgents-based, multi-agent spatial transcriptomics architecture; however, its primary contribution is an evidence-governed harness for biological interpretation and drug-target prioritization, operationalized through validation-driven looping.
```

---

## Introduction Draft

Draft note. References in the manuscript-facing draft are numbered by first appearance from this Introduction Draft onward and should remain in that order when this text is moved into the final manuscript.

Spatial transcriptomics links gene expression to tissue architecture by preserving spatial coordinates during transcriptome-wide profiling of intact tissue sections [1]. This capability has transformed studies of tissue organization, development, and disease by enabling investigators to ask where molecular programs occur, how cellular neighborhoods are arranged, and how spatially localized signals relate to pathological context [2]. Integration with single-cell transcriptomics extends this framework to cell-state mapping, niche analysis, intercellular-communication inference, and tissue-dynamics reconstruction [3]. However, the same data richness that makes spatial transcriptomics powerful also creates a translation bottleneck. Spatial resolution, assay throughput, morphology, cell-type annotation, spatially variable gene detection, cell-cell interaction inference, multimodal integration, and analytical strategy must be handled together [4]. Spatial patterns become therapeutically useful only when candidate signals are linked to disease mechanism, target-disease relevance, drug mechanism-of-action reasoning, and the limits of the underlying analysis [5]. In agentic analysis settings, this challenge is not only computational but evidentiary. An agent must select biologically appropriate tools, preserve context across long-horizon analyses, retrieve relevant evidence, interpret intermediate outputs, and decide whether a biological or target-prioritization claim is sufficiently supported to enter a reviewable scientific report [6-8].

Recent biomedical, spatial-biology, pathology, and omics agents have shown that large language model (LLM)-based systems can support executable scientific workflows rather than only text generation [9-12,14-16]. STAgent [11] uses multimodal LLMs with specialized computational tools to automate spatial-transcriptomics analysis, including visual reasoning, code generation, literature retrieval, and report generation. SpatialAgent [12] frames spatial biology as an LLM-equipped autonomous workflow that combines planning, memory, dynamic tool execution, multimodal inputs, external databases, and human-in-the-loop interaction across experimental design, spatial annotation, and cell-cell communication analysis. SPARK [16] extends this agentic framing in cancer pathology by coordinating specialized modules for biological concept generation, implementation, parameter verification, and human interaction. These systems establish that agentic analysis can automate important parts of biological-data analysis, but they leave open how automated tool execution and LLM-generated interpretations should be governed once they begin to support evidence-bearing biological or drug-target-prioritization claims.

In spatial omics, this question becomes practical because sensitive data, retrieved evidence, intermediate analyses, and provisional biological interpretations may pass through multiple agent steps before any final report is produced [17]. At the same time, many repeated agent steps do not require the largest available model. Recent work on small language models and task-level model selection shows that simpler steps can often be assigned to smaller local models, while larger models are reserved for difficult reasoning or synthesis [18-20]. For spatial omics, this practical constraint connects directly to scientific reliability. A useful agent must keep sensitive data local when needed, avoid unnecessary use of expensive large models, maintain low-latency execution for routine steps, and place each model call inside a harness that validates intermediate artifacts before biological or therapeutic claims enter the final report.

Addressing this governance problem requires a harness that makes multi-step agent execution controllable, including when inference is served by locally deployed open-weight LLMs, rather than treating the LLM or tool interface as the system itself. LangChain's Deep Agents [21] provide the long-horizon orchestration substrate for this role, standardized tool interfaces [22] expose analytical resources, and domain Skills [23-33] encode reusable procedures for evidence retrieval, tool constraints, provenance checks, and claim finalization. Recent harness studies further suggest that long-horizon performance depends less on raw context length, tool-call volume, or harness size than on valid feedback, persistent state, and controlled updates to the procedures surrounding the model [34-38].

Here, we present DeepMAST, an evidence-governed multi-agent harness that operationalizes claim governance for spatial transcriptomics interpretation and drug-target prioritization. DeepMAST uses LangChain's Deep Agents [21] as a long-horizon, file-mediated orchestration substrate and pairs this substrate with domain-specific Skills that encode how biological evidence should be retrieved, constrained, validated, and converted into reviewable claims [23-33]. Rather than treating tool execution as the endpoint of analysis, DeepMAST surrounds agentic workflows with skill-guided evidence acquisition, stage-specific tool constraints, provenance-aware retrieval, claim-level validation, target-relevant evidence scoring, and fail-closed report finalization. To support local, cost-aware, and privacy-conscious deployment, Qwen3.5, a locally deployed open-weight large language model (LLM), was served through Ollama for core DeepMAST inference tasks [39-40]. We evaluated DeepMAST by first defining its architecture, then testing skill-guided evidence acquisition, source-grounded retrieval, and claim-governance controls, and finally applying the harness across complementary cancer Visium workflows and human idiopathic pulmonary fibrosis target-prioritization analyses. Across these evaluations, DeepMAST routed LLM-generated conclusions through provenance checks, structured output constraints, and claim-support validation before report generation. Together, these evaluations show that DeepMAST extends spatial-transcriptomics automation toward biological interpretation and drug-target-prioritization claims that are more traceable, bounded, and auditable.

---

## Introduction Structure

### 1. Spatial transcriptomics creates interpretation and translation bottlenecks

Draft 첫 문단과 대응합니다. 시작은 spatial transcriptomics의 장점에서 출발하되, 곧바로 interpretation and translation bottleneck으로 좁힙니다.

내용
- Spatial transcriptomics maps gene expression to tissue architecture by preserving spatial coordinates during transcriptome-wide profiling of intact tissue sections [1].
- Modern sequencing- and imaging-based spatial transcriptomics technologies enable exploratory and confirmatory analysis across development, tissue organization, and disease contexts, including cancer [2].
- Integration with single-cell transcriptomics further supports cell-state, niche, intercellular-communication, and tissue-dynamics interpretation, but it also introduces nontrivial mapping and deconvolution problems [3].
- High-throughput spatially resolved transcriptomic data create computational and interpretive bottlenecks because spatial resolution, assay throughput, morphology, cell-type annotation, spatially variable gene detection, cell-cell interaction inference, and multimodal integration must be handled jointly [4].
- Using spatial patterns for drug-target prioritization remains difficult because candidate signals must be connected to disease mechanism, target-disease relevance, drug mechanism-of-action reasoning, and the limitations of the underlying analytical strategy [5].

핵심 문장

```text
Spatial transcriptomics can reveal where disease programs occur by linking gene expression to tissue architecture and cellular context [1-3], but identifying which spatially localized signals are biologically meaningful, computationally robust, and therapeutically actionable remains a major bottleneck [4-5].
```

전환 문장

```text
This bottleneck becomes sharper in agentic analysis settings, where spatial signals must be routed through tool selection, evidence retrieval, biological interpretation, and target-prioritization decisions before they can support reviewable scientific claims.
```

### 2. Prior biomedical and spatial agents establish agentic capability, but leave claim governance open

Draft 둘째 문단과 대응합니다. 기존 agent 성취를 길게 나열하지 않고, agentic biomedical analysis가 이미 가능하다는 점을 인정한 뒤 automated tool execution과 LLM-generated interpretation이 evidence-bearing claims로 이어질 때 필요한 governance problem으로 넘어갑니다.

내용
- Prior biomedical, spatial-biology, pathology, and omics agents already demonstrate executable scientific workflows, tool execution, literature retrieval, multimodal interpretation, verification, benchmarking, and report generation [9-16].
- STAgent [11], SpatialAgent [12], and SPARK [16] should be named directly as representative systems, with citations attached immediately after the system names.
- MEDEA는 이 문단에서 제외합니다. MEDEA의 verification-aware structure는 전체 논문 framing과 Results structure 참고에는 남길 수 있지만, paragraph 2에서는 DeepMAST의 local-model and harness-governance gap을 흐리지 않도록 쓰지 않습니다.
- 이 문단의 목적은 기존 agent들도 이미 많은 것을 보여주었다는 점을 인정하되, automated tool execution과 LLM-generated interpretation이 evidence-bearing biological or drug-target-prioritization claims로 이어질 때 필요한 claim governance는 아직 충분히 해결되지 않았다는 점을 제시하는 것입니다.
- Specialization은 별도 이유로 분리하지 않고 task-level model selection 안에 포함합니다.

문단 구성
- Paragraph A names STAgent [11], SpatialAgent [12], and SPARK [16] as capability examples.
- Paragraph A closes by stating the unresolved claim-governance problem.
- Paragraph B explains why this question becomes practical in spatial omics and links privacy, cost, latency, local model use, and harness validation to scientific reliability.

핵심 문장

```text
These systems establish that agentic analysis can automate important parts of biological-data analysis, but they leave open how automated tool execution and LLM-generated interpretations should be governed once they begin to support evidence-bearing biological or drug-target-prioritization claims.
```

전환 문장

```text
In spatial omics, this question becomes practical because sensitive data, retrieved evidence, intermediate analyses, and provisional biological interpretations may pass through multiple agent steps before any final report is produced [17].
```

### 3. Harness makes multi-step agent execution governable

Draft 셋째 문단과 대응합니다. 여기서 앞 문단의 governance problem을 받아 harness가 왜 필요한지 먼저 말한 뒤, Deep Agents, standardized tool interfaces, domain Skills, recent harness studies를 연결합니다.

내용
- Harness는 multi-step agent execution을 controllable하게 만들기 위해 필요하다고 시작합니다.
- LangChain's Deep Agents provide the long-horizon orchestration substrate [21].
- Standardized tool interfaces expose analytical resources [22], but domain Skills specify how evidence should be retrieved, constrained, checked, and finalized [23-33].
- Recent harness studies support the claim that long-horizon performance depends on valid feedback, persistent state, and controlled procedural updates rather than only raw context length, tool-call volume, or harness size [34-38].
- 이 문단에서는 아직 DeepMAST novelty를 길게 풀지 않고, 독자에게 harness 필요성과 관련 primitives를 익숙하게 만드는 것이 목적입니다.

문단 구성
- Paragraph A links the governance problem to the need for a harness.
- Paragraph B links long-horizon orchestration, resource access, domain Skills, and recent harness studies.

핵심 문장

```text
Addressing this governance problem requires a harness that makes multi-step agent execution controllable, including when inference is served by locally deployed open-weight LLMs, rather than treating the LLM or tool interface as the system itself.
```

전환 문장

```text
Standardized tool interfaces expose analytical resources, but domain Skills specify how evidence should be retrieved, constrained, checked, and finalized.
```

### 4. DeepMAST contribution and roadmap

Draft 마지막 문단과 대응합니다. 여기서는 앞 문단의 governance problem을 받아 DeepMAST가 claim governance를 operationalize하는 evidence-governed harness임을 정의하고, 이어지는 Results의 evidence 흐름을 짧게 예고합니다.

내용
- DeepMAST is an evidence-governed multi-agent harness that operationalizes claim governance for spatial transcriptomics interpretation and drug-target prioritization.
- LangChain's Deep Agents are described as the long-horizon, file-mediated orchestration substrate [21].
- Domain-specific Skills encode how biological evidence should be retrieved, constrained, validated, and converted into reviewable claims [23-33].
- The domain-specific control layer uses skill-guided evidence workflows, constrains tool use, separates biological interpretation from target prioritization, verifies provenance, scores target-relevant evidence, preserves failure and refinement state, and governs finalizable claims.
- Evaluation roadmap should follow architecture, evidence acquisition and source grounding, claim-governance controls, complementary cancer Visium workflows, and IPF target-prioritization.

문단 구성
- Paragraph A presents DeepMAST and its control layer.
- Paragraph B previews the evaluation sequence.
- Paragraph C closes on traceable biological and therapeutic claims rather than more automation.

핵심 문장

```text
Here, we present DeepMAST, an evidence-governed multi-agent harness that operationalizes claim governance for spatial transcriptomics interpretation and drug-target prioritization. DeepMAST uses LangChain's Deep Agents [21] as a long-horizon, file-mediated orchestration substrate and pairs this substrate with domain-specific Skills that encode how biological evidence should be retrieved, constrained, validated, and converted into reviewable claims [23-33]. Rather than treating tool execution as the endpoint of analysis, DeepMAST surrounds agentic workflows with skill-guided evidence acquisition, stage-specific tool constraints, provenance-aware retrieval, claim-level validation, target-relevant evidence scoring, and fail-closed report finalization. To support local, cost-aware, and privacy-conscious deployment, Qwen3.5, a locally deployed open-weight large language model (LLM), was served through Ollama for core DeepMAST inference tasks [39-40]. We evaluated DeepMAST by first defining its architecture, then testing skill-guided evidence acquisition, source-grounded retrieval, and claim-governance controls, and finally applying the harness across complementary cancer Visium workflows and human idiopathic pulmonary fibrosis target-prioritization analyses. Across these evaluations, DeepMAST routed LLM-generated conclusions through provenance checks, structured output constraints, and claim-support validation before report generation. Together, these evaluations show that DeepMAST extends spatial-transcriptomics automation toward biological interpretation and drug-target-prioritization claims that are more traceable, bounded, and auditable.
```

---

# Results Structure

Results는 **architecture -> evidence acquisition/source grounding -> claim governance -> biological applications -> translational application** 흐름으로 정리하는 것을 추천합니다. Section 1에서 DeepMAST의 architecture를 먼저 정의한 뒤, Section 2에서 evidence가 system 안으로 들어오는 두 control point, 즉 citable biological context coverage와 source-grounded retrieval을 보여줍니다. Section 3에서는 그 evidence가 실제 biological claim으로 바뀌는 지점의 governance를 보여주며 structured SKILL CCI benchmark와 breast cancer Evidence-Grounded Follow-up Recommendations validation을 같은 bridge figure로 묶습니다. Breast cancer follow-up recommendation substrate는 독립 main panel이 아니라 Figure 3C validation input으로 본문과 Supplementary Data/Table에서 설명합니다. 이후 Section 4는 complementary cancer Visium workflows, Section 5는 IPF target-prioritization application으로 이어집니다. 이 흐름은 MEDEA의 system/verified-planning 이후 benchmark 전개, SPARK의 design/verification 이후 use-case 전개, SpatialAgent/STAgent의 실제 spatial output 중심 use-case figure framing을 참고하되, DeepMAST의 중심 novelty를 **tool access가 아니라 evidence-governed biological harness control layer**로 유지합니다.

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

이 섹션은 전체 구조는 유지하되, agent별 역할과 claim boundary를 조금 더 정밀하게 업데이트합니다. Pipeline Builder와 Pipeline Executor는 DeepMAST의 analytical substrate로 자세히 설명하되 main novelty로 과도하게 올리지 않습니다. 중심 해석 모듈은 **Deep Drug Target Prioritizer**와 **Deep Interpreter**로 통일합니다. STAgent와 SpatialAgent가 이미 spatial-transcriptomics agent automation, tool execution, multimodal interpretation, and spatial-biology workflow automation을 강하게 보여주기 때문에, DeepMAST는 그 위에 **skills, staged constraints, Summary-Guided Chunk Promotion RAG (SGCP-RAG), evidence scoring, provenance checks, deterministic report finalization**을 결합한 evidence-governed biological harness로 포지셔닝합니다. 가장 안전한 claim은 DeepMAST가 모든 모듈에 동일한 hard gate를 적용한다는 것이 아니라, core biomedical interpretation pipelines에서 validation-driven looping을 통해 intermediate artifacts를 refinement, withholding, finalization으로 라우팅한다는 것입니다.

Figure 1 핵심 구성
- Orchestrator layer - central controller routing requests to four expert agents.
- Expert agents - Pipeline Builder, Pipeline Executor, Deep Drug Target Prioritizer, Deep Interpreter.
- Harness/control layer - skill-guided evidence workflows, stage-specific MCP/tool constraints, validation-driven looping gates, structured artifacts, claim-level checks, provenance-aware reporting, deterministic rendering, expert-reviewable artifacts, and fail-closed finalization gates.
- Resource layer - MCP-enabled spatial analysis tools, SGCP-RAG-enabled literature retrieval, and biological databases.

Figure 1-linked supplementary figures
- Supplementary Figure S1. Pipeline Builder and Pipeline Executor details linked to Figure 1. Panel A shows the Pipeline Builder architecture. Panel B shows a real user interaction in which a user requests a breast cancer Visium analysis pipeline. Panel C shows the generated spatial transcriptomics analysis pipeline output. Panel D shows the Pipeline Executor architecture. Source path - `docs/writing/figures/sfig1.png`.
- Supplementary Figure S2. Deep Drug Target Prioritizer and Deep Interpreter details linked to Figure 1. Panel A shows the staged drug-target evidence workflow from ligand-receptor candidates to target-prioritization reports. Panel B shows the Deep Interpreter workflow from spatial analysis outputs and HITL target selection to validated biological interpretation. Source path - `docs/writing/figures/sfig2.png`.
- Supplementary Figure S3. Full SGCP-RAG execution graph used for reference-guided pipeline construction and literature-grounded retrieval, with the Figure 2B upper panel retaining only the simplified SGCP-RAG flow. Source path - `docs/writing/figures/sfig3.png`.
- Main Figure 1 should cite these supplementary figures as implementation details for the analytical substrate, while keeping the main novelty emphasis on Deep Drug Target Prioritizer and Deep Interpreter.


Paper-ready Results draft

```text
DeepMAST takes as input spatial transcriptomics data together with a natural-language biological question or structured analysis objective. To support users with different levels of spatial-omics expertise, DeepMAST accepts either high-level biological goals or explicit pipeline choices and returns an auditable, expert-reviewable report linking spatial patterns to literature-grounded interpretation and drug-target evidence. Unlike spatial-biology agents that primarily emphasize autonomous workflow execution, DeepMAST treats biological interpretation and target prioritization as a claim lifecycle in which spatial outputs, retrieved sources, and database evidence are routed toward refinement, withholding, or finalization by provenance and claim-boundary checks. Figure 1 maps this design across a central orchestrator, four expert agents, a harness/control layer, and MCP-enabled analytical, retrieval, and biological resource layers. DeepMAST also uses a task-matched local-model design, assigning locally deployed open-weight Qwen3.5 models [39,40] by stage, with smaller local models supporting constrained routing, query expansion, retrieval triage, and evidence assessment, and larger local models reserved for synthesis-heavy interpretation, reporting, and target-prioritization writing.

The Pipeline Builder and Pipeline Executor form the analytical substrate. The Pipeline Builder collects study metadata, validates information completeness, and constructs analysis workflows through three user-facing modes, including a default spatial transcriptomics pipeline, a user-specified custom pipeline, or a reference-guided pipeline selected from retrieved papers (Fig. S1A-C). The Pipeline Executor loads spatial data, resolves the optimal single-cell reference when spot-based platforms have multiple candidate references, checks resource readiness, and executes the configured workflow through MCP-enabled analytical tools (Fig. S1D). These modules generate structured spatial-analysis outputs, including spatial clusters, pathway summaries, ligand-receptor maps, and quantitative interaction evidence, before target-prioritization or interpretation claims are written.

The Deep Drug Target Prioritizer (Fig. S2A) and Deep Interpreter (Fig. S2B) concentrate the evidence-governed claim layer. Skill-guided evidence workflows define how biological evidence is searched, scored, constrained, and converted into auditable target-prioritization recommendations and biological interpretation statements. The Deep Drug Target Prioritizer receives ligand-receptor candidates and applies a staged evidence funnel with target-prioritization and database-query skills before rendering evidence-grounded follow-up recommendations. This output separates primary interest-cell follow-up candidates from secondary spatial-niche follow-up candidates, so same-cell evidence, cross-cell spatial-niche framing, actionability evidence, and unresolved validation needs remain distinct (see Methods). Downstream validation-driven looping gates check recommendation quality, cited provenance, and finalization readiness before deterministic target-prioritization reports are rendered.

The Deep Interpreter integrates STworkbench MCP spatial-analysis outputs, target-prioritization evidence, and literature through planner, searcher, interpreter, and reporter subagents. During retrieval, it invokes Summary-Guided Chunk Promotion RAG (SGCP-RAG), which uses generated summaries as non-authoritative navigation memory to promote linked source chunks before relevance grading rather than injecting summaries into the answer context (Fig. S3). Interpretation claims then pass through validation-driven looping steps that combine claim-level citation checks, full-text validation when available, quality scoring, and synthesis-level verification before final report generation. Together, this architecture separates workflow construction, tool execution, target prioritization, and biological interpretation, providing the organizational basis for the subsequent evidence-acquisition benchmarks, claim-governance tests, cancer Visium applications, and idiopathic pulmonary fibrosis (IPF) target-prioritization analysis with biological interpretation.
```

Paper-ready figure legend draft

```text
Figure 1. DeepMAST architecture for evidence-governed spatial transcriptomics interpretation and target prioritization. DeepMAST accepts spatial transcriptomics data together with a natural-language biological question or structured analysis objective and routes the request through a central orchestrator to four expert agents. The Pipeline Builder constructs default, custom, or reference-guided spatial transcriptomics workflows, and the Pipeline Executor runs configured workflows through MCP-enabled analytical resources, including STworkbench MCP outputs that supply spatial clusters, pathway summaries, ligand-receptor maps, and quantitative interaction evidence for downstream modules. The Deep Drug Target Prioritizer and Deep Interpreter form the evidence-governed claim layer, using skill-guided evidence workflows to convert spatial outputs, ligand-receptor candidates, literature, and biological database evidence into auditable target-prioritization and interpretation reports. The harness/control layer links skill-guided evidence workflows, stage-specific tool constraints, validation-driven looping, structured artifacts, provenance checks, claim-level validation, and deterministic report rendering.
```

---

이 섹션은 Results 원고로 사용합니다. Reference paper 구조는 MEDEA와 SPARK처럼 system overview 뒤에 validation benchmark를 배치하고, SpatialAgent와 STAgent처럼 figure 중심으로 benchmark endpoint를 먼저 설명한 뒤 claim boundary를 닫는 방식으로 맞춥니다.

## 2. Benchmarking evidence acquisition and source-grounded retrieval controls

Having defined DeepMAST as an evidence-governed biological harness, we next asked whether its retrieval-side control layer improved the evidence available for downstream interpretation before any biological or therapeutic claim was written. We evaluated two evidence-input controls in Figure 2. The first benchmark tested whether a literature-retrieval skill broadened citable biological context for ligand-receptor interpretation in 30 breast cancer Visium cell-cell interaction cases (GSE243280) [48,49]. The second benchmark tested whether Summary-Guided Chunk Promotion RAG (SGCP-RAG) improved retrieval of source-bearing chunks in a 2,556-case MultiHop-RAG benchmark [62]. Because MultiHop-RAG organizes English news articles into a topic- and entity-overlapping multi-document evidence graph rather than duplicated article copies, it provided a direct stress test of whether SGCP-RAG could navigate related source documents while preserving chunk-level grounding. Together, these experiments evaluate the evidence entering the harness rather than the final biological interpretation itself.

In the ligand-receptor retrieval benchmark, DeepMAST used coverage validation to identify missing gene, pathway, and cell-type context, then routed the search back through targeted gap-filling queries before handoff to downstream interpretation (Figure 2a). Gene coverage was already saturated in both skill-off and skill-on arms after citable filtering, indicating that the benchmark was not limited by failure to retrieve ligand or receptor names. The retrieval skill instead improved cell-type context coverage, which is the evidence class needed to interpret spatially localized ligand-receptor signals in their tumor microenvironment context. In the Qwen3.5-35B setting, citable cell-type coverage increased from 27.7% to 38.7% (p = 1.44e-03). In the Qwen3.5-122B setting, citable cell-type coverage increased from 26.8% to 46.4% (p = 1.30e-04). The same pattern was visible in the all-retrieved paper analysis shown in Supplementary Figure S4A, where cell-type coverage increased from 42.6% to 63.2% for Qwen3.5-35B and from 40.4% to 65.1% for Qwen3.5-122B, while pathway coverage increased directionally but was underpowered because only 11 cases contained pathway annotations. These results show that the literature-retrieval skill primarily broadened biologically citable context rather than merely adding more direct ligand-receptor papers.

We then evaluated source-grounded retrieval at the chunk level using SGCP-RAG, a summary-guided source-navigation control that promotes linked source documents before chunk retrieval and grading (Figure 2b). The generated summaries were used only as non-authoritative navigation memory and were not injected as evidence into the answer context. In the Qwen3.5-35B model, SGCP-RAG increased exact-answer containment from 26.3% to 34.9% (+8.6 percentage points, McNemar p = 6.30e-38) and increased evidence recall from 0.155 to 0.256 (Wilcoxon p = 1.50e-78). In the Qwen3.5-122B model, SGCP-RAG increased exact-answer containment from 28.1% to 31.7% (+3.7 percentage points, McNemar p = 2.20e-06) and increased evidence recall from 0.192 to 0.258 (Wilcoxon p = 1.60e-31). After SGCP-RAG, evidence recall was nearly identical in Qwen3.5-35B and Qwen3.5-122B (0.256 versus 0.258), and exact-answer containment was higher in Qwen3.5-35B (34.9% versus 31.7%). The larger gain in Qwen3.5-35B suggests that summary-guided source navigation is especially useful when the base retriever or generator has less capacity, while the significant Qwen3.5-122B gains indicate that the control is not limited to a smaller-model rescue effect. SGCP-RAG also reduced no-relevant-context failures, although this improvement came with an approximately 29-31 s latency increase. Thus, SGCP-RAG represents an accuracy and recall tradeoff that is appropriate when source-grounded evidence is more important than minimal retrieval latency.

Figure 2 핵심 구성
- Figure 2a shows literature-retrieval skill coverage in 30 breast cancer Visium ligand-receptor cases (GSE243280) [48,49] using the citable set (direct + context), with citable cell-type context coverage as the primary endpoint. Source path - `benchmarks/lr_retrieval_relevance/figures/figure2d_lr_retrieval_citable_set.svg`.
- Figure 2b shows SGCP-RAG-enabled retrieval versus baseline retrieval across Qwen3.5-35B and Qwen3.5-122B models on MultiHop-RAG [62], with exact-answer containment and evidence recall as endpoints. Source path - `benchmarks/sgcp_accuracy_recall/figures/figure2c_sgcp_accuracy_recall.svg`.
- The compiled composite figure is `benchmarks/tot/fig2.svg`.
- Supplementary Figure S4A should show the literature-retrieval coverage supplement across Qwen3.5-35B and Qwen3.5-122B, including the all-retrieved paper view that complements the Figure 2a citable set (direct + context). Source path - `benchmarks/lr_retrieval_relevance/figures/sfigure2d_lr_retrieval_citable_set.svg`.
- The full SGCP-RAG graph remains in Supplementary Figure S3 so that the main figure can focus on the benchmark endpoint.

Figure 2 legend draft

Figure 2. Evidence acquisition and source-grounded retrieval controls. a, Literature-retrieval skill benchmark for 30 breast cancer Visium ligand-receptor cases (GSE243280) [48,49]. The workflow evaluates whether coverage validation and targeted retrieval loops broaden citable biological context before downstream interpretation. Panel a reports the interpreter-facing citable set (direct + context), rather than all retrieved papers. Bar plots compare skill-off and skill-on retrieval across Qwen3.5-35B and Qwen3.5-122B models for ligand-receptor, pathway, and cell-type context. All-retrieved paper coverage is shown in Supplementary Figure S4A. b, SGCP-RAG retrieval benchmark on the MultiHop-RAG dataset [62]. SGCP-RAG uses generated summaries as non-authoritative navigation memory to promote linked source documents before chunk retrieval and grading. Exact-answer containment and evidence recall are shown for baseline retrieval and SGCP-RAG-enabled retrieval in Qwen3.5-35B and Qwen3.5-122B models. Statistical tests use paired comparisons within the same benchmark cases.

Claim boundary
- This section supports retrieval-stage evidence acquisition and source-grounded retrieval claims.
- It does not directly claim that final biological interpretation quality improved.
- Pathway coverage should be described as directional because only 11 ligand-receptor cases had pathway annotations.
- SGCP-RAG should be described as source-navigation control, not as a method that uses generated summaries as evidence.

---

## 3. Evidence-governed claim control constrains biological interpretation and follow-up recommendations

**역할:** Figure 3은 Figure 2의 evidence-acquisition benchmark와 Figure 4 이후 real-data application 사이의 claim-governance bridge입니다. Figure 2는 "citable/source-grounded evidence가 system으로 들어오는가"를 검증하지만, 그 evidence가 final biological claim으로 바뀔 때 unsupported mechanism, causal overclaiming, premature therapeutic claim이 줄어드는지는 별도 검증하지 않습니다. 따라서 Figure 3을 Figure 4 앞에 배치해 controlled evidence substrate 아래에서 guidance effect를 비교하고, 이후 biological application이 단순한 agent narrative가 아니라 evidence-boundary를 통과한 harness output임을 보여줍니다. MEDEA, SPARK, SpatialAgent, STAgent 모두 overview/evidence system 뒤에 benchmark 또는 validation figure를 두고, 그 다음 application을 전개하는 구조를 사용하므로 DeepMAST도 "evidence input -> claim-governance benchmark -> biological application" 흐름으로 정리하는 것이 가장 자연스럽습니다.

추천 heading:

```text
Evidence-governed claim control constrains biological interpretation and follow-up recommendations
```

Section 3 시작 bridge

```text
After establishing that DeepMAST improves evidence acquisition and source-grounded retrieval, we next evaluated whether evidence artifacts remain bounded when they are converted into written biological claims. Retrieval success alone does not demonstrate evidence-governed interpretation, because retrieved sources can still be transformed into unsupported mechanisms, overstated causal links, or premature therapeutic claims. We therefore tested this claim-governance layer before the real-data applications at two claim-generation points: ligand-receptor interpretation in a CCI benchmark and downstream breast cancer follow-up recommendations under controlled guidance conditions.
```

Figure 3 panel 구성:

```text
Figure 3
Evidence-governed claim control benchmark.
Message: DeepMAST tests the same evidence-governance principle in two benchmark branches: upstream CCI interpretation and downstream follow-up recommendation writing.

Figure 3A
Two-branch claim-governance benchmark schematic.
Source path: benchmarks/dth/figures/Fig3A_ClaimGovernanceLifecycle.svg
Message: controlled evidence artifacts and structured guidance split into two benchmark branches: CCI interpretation supporting Figure 3B and follow-up recommendations supporting Figure 3C. This panel is a schematic bridge, not a new benchmark result.

Figure 3B
Structured SKILL CCI ablation benchmark.
Source path: benchmarks/cci_skill_ablation/figures/SkillAblation.png
Linked supplement: Supplementary Figure S4B shows dimension-level scores and fabrication counts from `benchmarks/cci_skill_ablation/figures/s_SkillAblation.svg`.
Message: structured SKILL guidance reduces plausible but unsupported ligand-receptor interpretation.

Figure 3C, left
Follow-up recommendation evidence coverage.
Source path: benchmarks/dth/figures/Fig3A_DTH_EvidenceCoverage.svg
Message: guided generation produced a modest/borderline increase in evidence coverage and should be treated as a secondary endpoint.

Figure 3C, right
Follow-up recommendation claim-boundary restraint.
Source path: benchmarks/dth/figures/Fig3B_DTH_BlindJudgeRigor.svg
Message: follow-up recommendation guidance primarily improves evidence-boundary behavior by increasing blinded claim-boundary restraint scores.
```

**Figure 3A: Two-branch claim-governance benchmark schematic**

Figure 3A는 결과값을 추가로 주장하는 panel이 아니라, Figure 3B-C를 읽는 방법을 정리하는 design schematic입니다. Figure 2가 "evidence를 어떻게 가져오는가"를 보여준다면, Figure 3A는 "evidence가 claim으로 바뀔 때 어떤 gate를 통과하는가"를 보여줍니다. 특히 Figure 3A는 two benchmark branches를 명확히 보여줘야 합니다. Branch 1은 breast cancer LR cases에서 structured SKILL guidance가 unsupported CCI interpretation을 줄이는지를 검증하고 Figure 3B로 이어집니다. Branch 2는 breast cancer follow-up recommendation validation substrate에서 recommendation guide가 evidence-boundary behavior를 개선하는지를 검증하고 Figure 3C로 이어집니다.

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

**Controlled breast cancer Deep Drug Target Prioritizer evidence substrate used for follow-up recommendation validation**

Deep Drug Target Prioritizer 결과는 main Figure 3의 독립 panel로 키우지 않고, Evidence-Grounded Follow-up Recommendations validation이 어떤 evidence package 위에서 수행됐는지 본문과 Supplementary Data/Table에서 설명합니다. `drug.md`의 핵심만 압축합니다: top-30 LR pairs에서 나온 37 unique genes, Stage 3 deep-dive로 넘어간 7 featured candidates (ERBB3, EPHB4, ERBB2, INSR, EFNB2, LAMA5, NECTIN4), Stage 1 spatial/Census evidence, Stage 2 target-disease/actionability evidence, Stage 3 druggability/deep-dive evidence, and conservative follow-up tiers.

추천 처리:
- Main Results text: controlled evidence substrate로 2-3문장 설명.
- Supplementary Table: 37 assessed genes와 7 featured candidates, stage, score/tier, evidence class를 요약.
- Supplementary Data: full `drug.md`/structured evidence artifacts를 audit bundle로 제공.

핵심 메시지:

```text
The breast cancer target-prioritization output is used here as a controlled evidence substrate for Evidence-Grounded Follow-up Recommendations, whereas the full biological drug-target-prioritization application is reserved for the human IPF analysis.
```

**Figure 3C: Follow-up recommendation guidance improves downstream claim-boundary restraint in breast cancer Evidence-Grounded Follow-up Recommendations**

Figure 3C는 same principle이 downstream Evidence-Grounded Follow-up Recommendations output에서도 작동하는지를 보여줍니다. 여기서 중요한 점은 structured guidance가 "더 많은 evidence를 언급하게 했다"보다 **claim-boundary behavior를 바꿨다**는 것입니다. 왼쪽에는 secondary endpoint인 evidence coverage를, 오른쪽에는 primary endpoint인 claim-boundary restraint를 둡니다.

Source result:
- Use the follow-up recommendation validation bundle under `benchmarks/dth/results/` as the source for the valid-run summary and blinded-judge results.
- Guided and baseline conditions use the same Qwen3.5-122B generator, controlled breast cancer evidence substrate, output schema, save gate, and retry policy.
- Valid-output analysis includes 20 guided and 20 baseline runs, all passing recommendation-output validation, guide-use trace validation, and no-fallback filtering.
- Evidence coverage is a secondary endpoint: guided mean 78.53% versus baseline 74.41%, mean paired difference +4.12 percentage points, paired Wilcoxon P = 5.10e-02.
- Claim-boundary restraint is the primary endpoint: guided mean 4.78 versus baseline 2.88 after averaging judges within pair, mean paired difference +1.90, paired Wilcoxon P = 8.13e-05.
- Judge preference supports the same direction but is model-dependent: gpt-5.4 favored guided outputs in 18 of 20 pairs, whereas claude-sonnet-4-6 favored guided outputs in 11 of 20 pairs.

Paper-ready Results draft

```text
Having established that DeepMAST improves evidence acquisition and source-grounded retrieval, we next evaluated the point at which those evidence artifacts are converted into biological claims. This benchmark was necessary because evidence availability alone does not demonstrate evidence-bounded interpretation: retrieved sources can still be transformed into unsupported mechanisms, overstated causal links, or premature therapeutic claims. We therefore used a controlled claim-governance benchmark before turning to real-data spatial-transcriptomics applications. The evidence substrate, task interface, output checks, and evaluation criteria were held fixed while guidance structure or guide use was varied (Fig. 3A).

We first tested whether this governance layer constrained upstream ligand-receptor interpretation. In a breast cancer ligand-receptor CCI benchmark, 30 LIANA+ interaction cases were interpreted under frozen prompting conditions. Guide-compliant structured SKILL guidance produced the strongest hallucination-control composite score among the main three conditions (3.89 versus 3.59 for unstructured prose and 3.14 without skills, Kruskal-Wallis H = 219.16, P = 2.57e-48) and reduced unsupported fabrication counts from 3.89 to 1.78 per interpretation (Fig. 3B; Fig. S4B). These gains were concentrated in faithfulness, overclaiming, uncertainty handling, and fabrication count, whereas spatial calibration was near ceiling across conditions. Thus, structured guidance primarily reduced unsupported biological interpretation rather than simply improving recognition of spatial statistics.

We then tested the same claim-governance principle at a downstream writing point that turns breast cancer drug-target evidence into follow-up recommendations. To avoid conflating guide effects with changing biological inputs, this benchmark was not run from an abstract prompt. The input evidence package came from the Deep Drug Target Prioritizer workflow (Fig. S2A), which assessed 37 unique genes from the top-30 ligand-receptor pairs through a staged evidence funnel and selected 7 Stage 3 featured candidates for deep-dive analysis (ERBB3, EPHB4, ERBB2, INSR, EFNB2, LAMA5, and NECTIN4). We treat this package as a controlled evidence substrate for follow-up recommendation validation, with the full breast cancer target-prioritization report reserved for Supplementary Data rather than as a main figure panel.

The controlled Target Recommender guidance contrast used this same breast cancer evidence package, generator model, output schema, save gate, and retry policy in both conditions (Fig. 3A). In the baseline condition, the Target Recommender received the operational contract but no follow-up recommendation guide. In the guided condition, the Target Recommender was required to read the guide before generating recommendations. The valid-output analysis included 20 guided and 20 baseline reports, all passing recommendation-output validation, guide-use trace validation, and no-fallback filtering.

Structured guidance produced a modest increase in mean evidence coverage compared with baseline generation (78.53% versus 74.41%, mean paired difference, +4.12 percentage points, paired Wilcoxon P = 5.10e-02), so this result should be interpreted as a borderline secondary endpoint (Fig. 3C, left). The stronger signal was claim-boundary restraint. After averaging blinded scores across GPT-5.4 and Sonnet 4.6 within each paired comparison, guided outputs scored higher than baseline outputs on claim-boundary restraint (4.78 versus 2.88, mean paired difference, +1.90, paired Wilcoxon P = 8.13e-05, Fig. 3C, right). Thus, follow-up recommendation guidance primarily improved evidence-boundary behavior by making the Target Recommender more explicit about the distinction between observed evidence, candidate mechanisms, and unestablished causal or clinical claims. Together, the two benchmark branches show that DeepMAST's evidence-governance benefit extends beyond retrieving evidence and constrains how evidence is converted into interpretation and follow-up recommendations before the framework is applied to real spatial-transcriptomics workflows.
```

Paper-ready figure legend draft

```text
Figure 3. Evidence-governed claim control constrains biological interpretation and follow-up recommendations. (A) Two-branch claim-governance benchmark schematic showing how controlled evidence artifacts enter structured guidance and are evaluated through CCI interpretation and follow-up recommendation branches. (B) Structured SKILL CCI ablation benchmark. Hallucination-control scores and unsupported fabrication counts compare guide-compliant structured SKILL guidance with unstructured prose and no-skill conditions. (C) Breast cancer follow-up recommendation validation. Left, evidence coverage in guided and baseline reports generated from the same controlled breast cancer evidence substrate. Right, blinded dual-judge claim-boundary restraint scores comparing guided and baseline reports.
```

주의할 claim boundary:
- Figure 3B는 CCI interpretation quality benchmark이지 full drug target validation이 아닙니다.
- Figure 3C는 generated follow-up recommendation quality를 검증하지 therapeutic efficacy를 검증하지 않습니다.
- Breast cancer Deep Drug Target Prioritizer output은 follow-up recommendation validation의 upstream evidence substrate이지 breast cancer drug target validation이 아닙니다.
- Evidence coverage should be described as modest or borderline because P = 5.10e-02.
- The strongest guided-output claim is claim-boundary restraint, not universal improvement across all judging axes.
- Follow-up recommendation guidance should be described as improving scientific calibration or evidence-boundary behavior.
- Do not abbreviate Evidence-Grounded Follow-up Recommendations as EGFR because that conflicts with the EGFR gene symbol. After the first definition, use "follow-up recommendations" or "follow-up recommendation guidance."
- Detailed staged target-evidence assessment remains reserved for the IPF/Figure 5 drug-target-prioritization section.

Linked supplement:
- Supplementary Figure S2A: Deep Drug Target Prioritizer overview supporting the controlled validation substrate used for Figure 3C.
- Supplementary Figure S4B: CCI skill-ablation supplement (`benchmarks/cci_skill_ablation/figures/s_SkillAblation.svg`).
- Supplementary Figure S4C: judge-stratified claim-boundary restraint supporting Figure 3C (`benchmarks/dth/figures/FigS3D_DTH_BlindJudgeRigorByJudge.svg`).
- Supplementary Figure S4D: blind-judge preference shares supporting Figure 3C (`benchmarks/dth/figures/FigS3E_DTH_BlindJudgeWinRate.svg`).
- Supplementary Table/Data: breast cancer follow-up recommendation validation substrate from `final_res_bc_drugtarget/drug.md`.

---

## 4. Complementary cancer Visium workflows connect reference-guided execution with curated ligand-receptor handoff

**역할:** Evidence acquisition과 claim-governance benchmark가 끝난 뒤 첫 biological application section입니다. Breast cancer와 prostate cancer Visium을 별도 Results로 길게 분리하지 말고, 한 figure/section 안에서 **서로 다른 DeepMAST 모듈을 보여주는 complementary cancer Visium demonstration**으로 묶습니다. 이 figure는 STAgent/SpatialAgent식 use-case figure처럼 실제 spatial outputs를 보여주되, follow-up recommendation validation metric은 Figure 3에 이미 배치합니다.

Section logic:
- This section should not argue that breast cancer and prostate cancer reveal a shared cancer biology mechanism. The claim is modular: the same DeepMAST harness can consume curated spatial-analysis outputs in one setting and generate reference-guided executor outputs in another.
- This is the first application section after the evidence and claim-governance benchmark bridge, so it should show practical spatial-transcriptomics use without re-litigating benchmark metrics.
- Do not include follow-up recommendation validation metrics in Figure 4. Figure 3 is now the dedicated claim-governance bridge that contains both the CCI SKILL benchmark and Evidence-Grounded Follow-up Recommendations validation. Detailed staged target-evidence scoring remains reserved for the IPF drug-target-prioritization section.

Prostate cancer Visium의 위치:
- Prostate cancer is the upstream execution example. The dataset is the 10x Genomics Human Prostate Cancer, Adenocarcinoma with Invasive Carcinoma (FFPE) Visium dataset analyzed with Space Ranger 1.3.0, including H&E image context and adenocarcinoma/invasive carcinoma tissue annotation [63].
- The direct executor claim is that Pipeline Executor resolved a realistic spot-based Visium preprocessing problem before downstream interpretation: choosing a single-cell reference and producing structured STworkbench outputs through MCP-mediated execution.
- The single-cell reference-selection result is concrete and can be reported in Results: the spatial query contained 4,371 spots and 17,943 genes at loading; after duplicate-gene handling and harmonization, both candidate references were compared in the same 16,385-gene feature space. GSE181294 [64] ranked ahead of GSE185344 [65] by fused Gromov-Wasserstein distance (11,353.4043 vs 11,890.1709), a 4.5% lower distance for GSE181294.
- rMCPAgent should be framed as the mechanism that made R-based deconvolution/spatial workflows available through a validated MCP interface: validated H5AD inputs, reference metadata checks, standardized output tables, recovery diagnostics, and output validation. Do not overstate rMCPAgent as a biological discovery result.
- Main Figure 4A-C should use the simplified prostate cancer STworkbench outputs: A, H&E-aligned Visium tissue and spatial cluster context; B, cluster-level cell-type enrichment/deconvolution heatmap; C, cluster-level pathway/signature enrichment heatmap. This keeps the prostate example focused on reference-guided execution and structured output inspection rather than downstream target interpretation.

Breast cancer Visium의 위치:
- Breast cancer is the curated downstream-interpretation example. The dataset should be described as a breast cancer Visium/Xenium-matched setting linked to the integrated single-cell, spatial, and in situ breast cancer study and the Starfysh spatial/histology resource, using the public accession (GSE243280) [48,49].
- Because this dataset is used elsewhere in the paper for CCI skill-ablation, literature-retrieval, and follow-up recommendation validation, main Figure 4 should not repeat Pipeline Builder or Pipeline Executor architecture. It should show that curated STworkbench outputs can be narrowed to selected ligand-receptor interactions and passed to interpretation/target-evidence modules.
- Main Figure 4D-F should use the final breast cancer handoff panels: D, NMF/factor spatial programs and cluster context; E, spatial visualization of key ligand-receptor pairs; F, quantitative analysis of ligand-receptor interactions.
- The BC analysis should focus on the selected Factor3/invasive-tumor communication program and avoid broad therapeutic claims. Interest clusters are 17, 4, and 14, interest cell type is Prolif Invasive Tumor, and selected factor is Factor3. The report identifies 19 prioritized LR pairs; CDH1-ERBB3 is the main interpreted candidate with Moran's R = 0.477 and Factor3 loading = 1.180. The displayed LR maps include AFDN-NECTIN4, CDH1-ERBB3, and EGF-ERBB2, while the remaining ranked candidates should stay in the source artifact or supplement. This is enough for a Results claim that DeepMAST can preserve spatial and quantitative evidence for selected LR candidates.
- The displayed LR pairs should not be interpreted at the same evidentiary strength. AFDN-NECTIN4 is an adhesion-context example supported by Nectin-4 breast-cancer marker evidence and Nectin/Afadin junction biology [66,67]. CDH1-ERBB3 is the main literature-grounded interpretation candidate because the local spatial evidence aligns with E-cadherin deregulation and ErbB3-associated EMT, migration, and invasion literature [68,69]. EGF-ERBB2 should be framed conservatively as an ERBB-family growth-factor signaling context because HER2/ERBB2 has no known ligand and EGF-bound EGFR can transactivate HER2 [70].
- If the text mentions ERBB3 or MAPK/PI3K, it should be bounded as an interpretation-prioritization signal from this curated analysis, not as a validated drug target. Detailed target-evidence scoring belongs in the IPF drug-target-prioritization section.

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
To test whether DeepMAST could support complementary human cancer Visium workflows without collapsing execution, interpretation, and target prioritization into a single claim surface, we paired a prostate cancer analysis emphasizing upstream reference-guided execution with a breast cancer analysis emphasizing downstream interpretation from curated spatial outputs. In the prostate cancer FFPE Visium dataset [63], Pipeline Executor first resolved a spot-based reference-selection problem before downstream analysis. sc-reference-selector compared GSE181294 [64] and GSE185344 [65] after metadata-aware loading, duplicate-gene handling, stratified downsampling, and harmonization to a shared 16,385-gene feature space. GSE181294 ranked as the closer reference by fused Gromov-Wasserstein distance (11,353.4043 vs 11,890.1709; 4.5% lower distance), providing the reference used for subsequent deconvolution and STworkbench MCP execution. The resulting tissue-aligned Visium and cluster view, cluster-level cell-type enrichment heatmap, and cluster-level pathway/signature enrichment heatmap provided structured executor artifacts that could be inspected and handed to Deep Interpreter rather than treated as final biological conclusions (Figure 4A-C; Supplementary Figure S5).

In the breast cancer Visium setting linked to integrated single-cell, spatial, in situ, and histology resources (GSE243280) [48,49], the analysis instead began from curated spatial annotations and focused on whether DeepMAST preserved quantitative evidence for selected ligand-receptor candidates. STworkbench MCP narrowed the curated output to a Factor3 invasive-tumor communication program across interest clusters 17, 4, and 14, then generated factor-level, spatial, and quantitative views for selected ligand-receptor interactions. The displayed interactions include AFDN-NECTIN4, CDH1-ERBB3, and EGF-ERBB2, with CDH1-ERBB3 retained as the main interpreted candidate based on spatial co-localization (Moran's R = 0.477) and high Factor3 loading (1.180) (Figure 4D-F). The three displayed pairs were interpreted with different evidence boundaries. AFDN-NECTIN4 was treated as an adhesion-context example because Nectin-4 is a breast tumor-associated antigen and Nectin/Afadin junction biology links this pair to cell-cell contact rather than a validated signaling axis [66,67]. CDH1-ERBB3 was emphasized because the local spatial signal matched literature linking E-cadherin deregulation with breast-cancer invasion and ErbB3 signaling with EMT, migration, and invasion [68,69]. EGF-ERBB2 was retained only as ERBB-family signaling context, since HER2/ERBB2 has no known ligand and EGF-bound EGFR can transactivate HER2 [70]. These results support a bounded handoff claim: DeepMAST can carry selected spatial LR evidence into literature-grounded interpretation and later target-evidence assessment, while output-level claim-governance validation is evaluated separately in Figure 3.
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

## 5. DeepMAST prioritizes candidate drug targets in human idiopathic pulmonary fibrosis Visium data

**역할:** Results의 biological climax로 두는 것이 좋습니다. IPF는 human disease, Visium spot-level, drug target prioritization, and possible experimental validation을 연결할 수 있어서 가장 마지막 substantive Results section에 적합합니다.

Dataset
- Human idiopathic pulmonary fibrosis.
- Visium spot-level resolution.
- Data source: Franzén et al. [76].
- IRIS domain maps show strong sample-to-sample heterogeneity across control and IPF sections (Supplementary Figure S6).

구조
1. IPF dataset and sample heterogeneity rationale.
2. Clinical and epithelial biology rationale for focusing on mild IPF and AT2/transitional AT2 compartments.
3. Mild IPF AT2/transitional AT2 niche focusing using IRIS domains 9, 11, 10, 13, and 5 from Figure 5A.
4. Index-section selection of (V19S23-092-B1) based on interest-domain composition, not candidate target expression.
5. Disease-associated ligand-receptor/pathway/cell-type signals.
6. Spatial ligand-receptor quadrant handoff using Moran's R, NMF Factor1 loading, and GenePT functional-semantic score.
7. Deep Drug Target Prioritizer evidence scoring.
8. Top target evidence decomposition.
9. Experimental validation이 있으면 여기서만 "validated candidate" 수준의 강한 표현 사용.

추천 heading

```text
DeepMAST prioritizes evidence-supported drug targets in human idiopathic pulmonary fibrosis
```

핵심 메시지

```text
The IPF analysis provides the strongest drug target-prioritization demonstration, linking human disease spatial localization, literature support, database-derived evidence, druggability context, and experimental validation when available.
```

추천 Results opening

```text
For the final disease application, DeepMAST was applied to the human idiopathic pulmonary fibrosis Visium atlas from Franzén et al. [76]. IRIS domain maps showed strong sample-to-sample heterogeneity in spatial domain composition across control and IPF sections (Supplementary Figure S6), motivating an index-section analysis focused on the disease niche most relevant to the biological question. Clinical studies support this focus because IPF can progress even when lung function is still relatively preserved, and prompt antifibrotic treatment is recommended to preserve lung function rather than waiting for advanced decline [77-79]. In parallel, epithelial biology studies link AT2-derived transitional cell states to fibrotic repair and persistence in human lung fibrosis, placing AT2 and transitional AT2 compartments at a plausible early epithelial-fibrotic interface [80,81]. This clinical and cellular context motivated the mild IPF, AT2/transitional AT2-centered analysis, while index-section selection itself remained based on IRIS-domain composition rather than candidate target expression. Interest domains were defined from the cell-type analysis as IRIS domains 9, 11, 10, 13, and 5 (Figure 5A). Among mild IPF sections, (V19S23-092-B1) showed the strongest representation of this pre-specified niche without using candidate target expression as a selection criterion, with 4,113 of 4,116 spots assigned to the interest domains (99.93%) and the highest AT2/transitional AT2 weighted domain score. DeepMAST therefore used (V19S23-092-B1) as the index section for spatial ligand-receptor ranking, followed by staged drug target evidence scoring.
```

주의할 claim boundary
- 전체 논문 제목과 abstract에서는 "drug-target prioritization"을 기본으로 유지합니다.
- "target discovery"는 IPF에서 실험검증이 충분히 있을 때 해당 result에만 제한적으로 씁니다.

---

## 6. Cross-dataset analysis demonstrates evidence traceability across disease contexts and workflow types

선택적이지만 있으면 Discussion 직전의 clean closing으로 좋습니다.

역할:
- Breast/prostate cancer Visium: complementary curated interpretation and reference-guided execution.
- IPF human: drug target prioritization and validation.

측정:
- number of generated reports or interpretations.
- number/proportion of literature-supported claims.
- citation/provenance completeness.
- number of prioritized targets and evidence categories available.
- validation status.
- unsupported claim or finalization failure rate if measured.

추천 heading:

```text
Cross-dataset analyses preserve evidence traceability across disease contexts and workflow types
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

   2b. SGCP-RAG strengthens source-grounded retrieval through a retrieval-validation loop

3. Evidence-governed claim control constrains biological interpretation and Evidence-Grounded Follow-up Recommendations

4. DeepMAST connects reference-guided cancer Visium execution with curated breast cancer LR interpretation

5. DeepMAST prioritizes evidence-supported drug targets in human idiopathic pulmonary fibrosis

6. Cross-dataset analyses preserve evidence traceability across disease contexts and workflow types
```

---

# Figure Plan

## Main figures

```text
Figure 1
DeepMAST architecture: workflow layer, expert agents, harness/control layer, MCP-enabled resource layer, outputs.
Linked supplements: Supplementary Figure S1 expands Pipeline Builder and Pipeline Executor architecture, Supplementary Figure S2 expands Deep Drug Target Prioritizer and Deep Interpreter, and Supplementary Figure S3 expands the full SGCP-RAG execution graph.

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
SGCP-RAG mechanism and retrieval benchmark.
Upper subpanel: simplified SGCP-RAG flow.
Lower subpanel: exact-answer accuracy and evidence recall for Qwen3.5-35B and Qwen3.5-122B.
Source path: benchmarks/sgcp_accuracy_recall/figures/figure2c_sgcp_accuracy_recall.svg
Main message: SGCP-RAG-enabled retrieval improves exact-answer accuracy and evidence recall in both model settings, with larger gains in the smaller Qwen3.5-35B model.

Figure 3
Evidence-governed claim control benchmark.
Panels: (A) two-branch claim-governance benchmark schematic; (B) structured SKILL CCI ablation benchmark; (C, left) follow-up recommendation evidence coverage; (C, right) follow-up recommendation claim-boundary restraint.
Source paths/data: A, `benchmarks/dth/figures/Fig3A_ClaimGovernanceLifecycle.svg`; B, `benchmarks/cci_skill_ablation/figures/SkillAblation.png`; C left, `benchmarks/dth/figures/Fig3A_DTH_EvidenceCoverage.svg`; C right, `benchmarks/dth/figures/Fig3B_DTH_BlindJudgeRigor.svg`.
Linked supplements: Supplementary Figure S4B supports Figure 3B; Supplementary Figure S4C-D support Figure 3C right; Supplementary Table/Data contains the breast cancer follow-up recommendation validation substrate from `final_res_bc_drugtarget/drug.md`.
Main message: structured guidance reduces unsupported CCI interpretation upstream, the controlled breast cancer substrate supports follow-up recommendation validation, and structured guidance improves downstream claim-boundary restraint in breast cancer follow-up recommendation outputs.
```

## Main application figures to build or select

```text
Figure 4
Complementary human cancer Visium workflows.
Panels: (A) prostate cancer H&E-aligned Visium tissue and spatial cluster context; (B) prostate cancer cluster-level cell-type enrichment/deconvolution heatmap; (C) prostate cancer pathway/signature enrichment heatmap after single-cell reference selection and STworkbench MCP execution; (D) breast cancer NMF/factor spatial programs with Factor3 selection context; (E) breast cancer spatial visualization of selected ligand-receptor pairs; (F) breast cancer quantitative ligand-receptor interaction summaries.
Linked supplements: Supplementary Figure S4A documents the LR citable-context bridge, and Supplementary Figure S5 documents MCP/HITL handoff for the Figure 4 cancer Visium interpretation thread.
Message: prostate cancer demonstrates reference-guided Pipeline Executor output after sc-reference-selector and rMCP/MCP-mediated workflow execution, whereas breast cancer demonstrates downstream interpretation of selected LR candidates from curated spatial outputs. Keep follow-up recommendation validation in Figure 3 and reserve detailed target-prioritization evidence for the IPF/Figure 5 section.

Figure 5
Human IPF Visium drug target prioritization.
Panels: (A) quadrant analysis of IPF ligand-receptor candidates showing Moran's R, Factor1 NMF loading, and GenePT functional-semantic score for interest-cluster and other ligand-receptor pairs; (B) staged Deep Drug Target Prioritizer evidence funnel from ligand-receptor-derived genes to Stage 3 featured candidates; (C) candidate target evidence matrix; (D) interest-cell intrinsic versus secondary spatial-niche interpretation tiers; (E) representative Evidence-Grounded Follow-up Recommendations; (F) druggability/database support or experimental validation if available.

Figure 6 or Supplementary Overview
Cross-dataset evidence traceability summary.
Panels/table: datasets, platform/resolution, analysis goal, main outputs, evidence sources, validation status.
```

## Supplementary figure policy

```text
Supplementary Figure S1
Pipeline Builder and Pipeline Executor details linked to Figure 1.
Source path: docs/writing/figures/sfig1.png
Panels: (A) Pipeline Builder agent architecture; (B) real user interaction example for breast cancer Visium pipeline generation; (C) generated Pipeline Builder output example; (D) Pipeline Executor agent architecture.
Message: Pipeline Builder provides HITL workflow construction and reference-guided pipeline selection as part of the analytical substrate, without becoming the central biological interpretation novelty.

Supplementary Figure S2
Deep Drug Target Prioritizer and Deep Interpreter details linked to Figure 1.
Source path: docs/writing/figures/sfig2.png
Legend: Supplementary Figure S2. Deep Drug Target Prioritizer and Deep Interpreter workflow details linked to Figure 1. (A) The Deep Drug Target Prioritizer receives top-ranked ligand-receptor pairs and a ligand-receptor network from spatial transcriptomics analysis, evaluates candidate targets through staged evidence assessment using OpenTargets, GWAS Catalog, Ensembl VEP, STRING, CellxGene Census, and ChEMBL, ranks follow-up candidates, and passes outputs through the Target Recommender, critic, citation-gate, anti-fabrication, and finalization checks to generate `drug.md` and `target_assessment.json`. (B) The Deep Interpreter receives spatial transcriptomics analysis results and human-in-the-loop target selections, plans interpretation targets, retrieves literature and biological context through PubMed, BioMCP, dynamic search, and BI-RAG, validates claim-level citations and quality, and renders a comprehensive HTML report with validated interpretation. The STworkbench MCP layer supplies clustering, neighborhood enrichment, pathway, CCI, MISTy, and LIANA plus NMF outputs used for interpretation.

Supplementary Figure S3
Full SGCP-RAG execution graph.
Source path: docs/writing/figures/sfig3.png
Message: Supplementary Figure S3 shows the full SGCP-RAG execution graph used for reference-guided pipeline construction and literature-grounded retrieval, while Figure 2B retains only the simplified SGCP-RAG flow in the main display.

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
IRIS domain maps across control and IPF Visium sections from Franzén et al. [76].
Source path: docs/writing/figures/sfig6.png
Message: IRIS domain composition varies substantially across samples, supporting a focused index-section strategy for the mild IPF AT2/transitional AT2 niche.

Supplementary Figure S7
Reserved only if all-retrieved literature-coverage views need a separate display beyond Supplementary Figure S4A. Otherwise, keep the literature-retrieval coverage supplement as Supplementary Figure S4A and report additional all-retrieved analyses in tables or methods artifacts.

Supplementary Figure S8
Full SGCP-RAG retrieval benchmark across Qwen3.5-35B and Qwen3.5-122B model settings, including exact-answer accuracy, evidence recall, no-context failures, latency, and static-reference ablation.
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

DeepMAST was implemented as a multi-agent harness for spatial transcriptomics interpretation and drug-target prioritization. The system accepts spatial transcriptomics inputs together with either a natural-language biological objective or a structured analysis request. A supervisor agent routes the request across four expert agents: Pipeline Builder, Pipeline Executor, Deep Drug Target Prioritizer, and Deep Interpreter. Pipeline Builder and Pipeline Executor provide the analytical substrate by constructing and executing spatial transcriptomics workflows. Deep Drug Target Prioritizer and Deep Interpreter provide the core evidence-governed claim layer by converting spatial outputs, ligand-receptor candidates, literature evidence, and database evidence into auditable biological interpretation and target-prioritization reports.

The orchestration layer uses LangGraph and DeepAgents for stateful execution, file-mediated context management, subagent delegation, and human-in-the-loop control [21,41]. Model Context Protocol (MCP) is used as the standardized interface between agent workflows and external analysis resources [22]. In DeepMAST, MCP servers standardize calls to external tools and biological resources, whereas the harness controls analysis-step selection, intermediate-output validation, evidence-retrieval constraints, and promotion of supported claims. The servers expose validated computational resources, skill-guided workflows define how evidence is retrieved and constrained, and validation-driven loops decide whether intermediate artifacts should be refined, retried, withheld, or promoted into final reports.

The DeepMAST harness is defined as the non-model control layer around the LLM agents, including MCP-mediated resource access, structured workflow contracts, source-provenance handling, claim-level validation, deterministic rendering, and evaluation procedures. The strongest claim-governance and fail-closed finalization gates are implemented in the Deep Drug Target Prioritizer and Deep Interpreter paths. Pipeline Builder and Pipeline Executor should be described as workflow-control and analytical-execution modules rather than as evidence-finalization modules with identical hard gates.

### DeepMAST expert agents and workflow responsibilities

The four expert agents were defined by workflow responsibility rather than by shared tool access. Pipeline Builder and Pipeline Executor control workflow construction and analytical execution, whereas Deep Drug Target Prioritizer and Deep Interpreter control evidence assessment, source grounding, and report finalization.

#### Pipeline Builder

The Pipeline Builder converts user-provided metadata and analysis goals into executable spatial transcriptomics workflows. The module records the platform, species, tissue or disease context, available spatial data, requested analysis type, and optional reference papers. An information-completeness check determines whether the collected metadata are sufficient to generate an executable pipeline; incomplete requests are routed back to information collection rather than finalized prematurely.

The Pipeline Builder supports default, custom, and reference-guided workflow modes. In the default mode, the module proposes a standard spatial transcriptomics pipeline for common analysis objectives. In the custom mode, it updates the workflow according to user-specified analysis choices. In the reference-guided mode, a ReAct-style agent uses sequential reasoning and SGCP-RAG-enabled retrieval to identify paper-derived workflow examples and select or synthesize a pipeline suitable for the requested dataset [42]. Human-in-the-loop decision points allow the user to accept the default workflow, request updates, or select a reference-guided plan. The output is a structured pipeline summary that is passed to the Pipeline Executor.

#### Pipeline Executor

The Pipeline Executor runs the configured workflow and writes structured intermediate outputs for downstream interpretation. The executor loads the workflow configuration and spatial data, validates the setup, performs platform-specific preparation, and resolves preprocessing requirements such as single-cell reference selection when spot-based spatial transcriptomics platforms have multiple plausible references for deconvolution or annotation.

Before execution, the module performs an MCP readiness check. If a required analysis tool is not available as an MCP server, the workflow can generate or expose the missing MCP interface before continuing. Python tools can be exposed through MCP-compatible wrappers, and R-based workflows can be converted through rMCPAgent so that R analyses are invoked through the same MCP-mediated execution contract. Once required tools are available, a ReAct [42] execution core alternates between pipeline reasoning, tool invocation, observation, and structured execution summarization . The executor saves results and intermediate artifacts for later Deep Interpreter and Deep Drug Target Prioritizer stages.

#### Deep Drug Target Prioritizer

The Deep Drug Target Prioritizer prioritizes candidate drug targets from ligand-receptor candidates identified by spatial transcriptomics cell-cell interaction analysis. Inputs include ligand-receptor candidate files, optional user-selected target cell types, disease context, and spatial analysis outputs. Outputs include per-stage evidence files, a structured target-assessment contract, and a publication-style target-prioritization report.

The agent applies a staged evidence funnel. An initial mapping step resolves user-provided disease and cell-type names to database-compatible vocabulary when available. Stage 1 evaluates ligand-receptor pair context using single-cell expression and disease-context evidence from CELLxGENE Census [43] and protein-interaction evidence from STRING [46]. Stage 2 evaluates unique genes from the ligand-receptor candidate set using target-validation, tractability, safety, disease-evidence, and known-drug annotations from Open Targets Platform [44] together with genetic-association evidence from GWAS Catalog [45]. Stage 3 performs focused druggability assessment for selected featured or novel candidates, using ChEMBL [47] as the default source for target search, bioactivity, indications, and mechanism-of-action evidence. Follow-up recommendations preserve claim boundaries by separating primary interest-cell follow-up candidates from secondary spatial-niche follow-up candidates. Primary interest-cell candidates require eligible interest-cell or same-cell support, whereas secondary spatial-niche candidates can be supported by cross-cell, spatial-niche, or gene-level actionability evidence without implying cell-autonomous target support.

After staged evidence collection, candidate genes were scored with a deterministic two-track rubric to separate established drug-development evidence from exploratory biological evidence. The validated-evidence track captured clinical and drug-development support. Existing drug evidence was scored from -5 to +5 as the clamped difference between gene-level drug counts and disease-level drug counts from Open Targets Platform [44]. Clinical-trial activity was scored from -5 to +5 as the clamped difference between gene-level clinical-development programs and disease-level trial evidence from Open Targets Platform [44] and ChEMBL [47]. Safety was applied as a penalty from -3 to 0 using curated safety-liability metadata, where larger penalties indicated stronger clinical or preclinical safety concerns. The validated total was calculated as the sum of existing drug evidence, clinical-trial activity, and safety.

The exploratory-evidence track captured genetic support, tractability, biological plausibility, and novelty opportunity. GWAS support was scored from 0 to 3 using disease-specific GWAS Catalog [45] evidence, with the maximum score assigned to direct genome-wide significant overlap. Tractability was scored from 0 to 3 using Open Targets Platform [44] tractability annotations, with higher scores assigned to clinical or approved-modality precedent. Biological plausibility was scored from 0 to 5 using qualifying disease-evidence types, high-confidence disease evidence, available variant-effect annotations, and a bounded bonus for membership in a Stage 1-passed ligand-receptor pair. Novelty opportunity was scored from 0 to 5 as an inverse function of the number of Open Targets Platform [44] disease associations, with higher scores assigned to less characterized targets. The exploratory total was calculated as the sum of GWAS support, tractability, biological plausibility, and novelty opportunity.

The combined total was calculated as the sum of the validated and exploratory totals. A separate rank score was used only for ordering candidates; this score normalized GWAS support and tractability to 0-5 rank contributions and added biological plausibility, novelty opportunity, and the validated total. Candidate classes were assigned by rule. Genes were labeled as validated targets when they had strong existing drug evidence or positive drug evidence with a sufficient validated total, exploratory targets when they had GWAS, tractability, or biological-plausibility support, novel candidates when they had biological-plausibility or novelty support without stronger validation, and insufficient-evidence candidates otherwise. Validated targets were prioritized by combined total, whereas exploratory and novel targets were prioritized by exploratory total. Genes with a combined total of at least 10 that also appeared in Stage 1-passed ligand-receptor pairs were selected as featured candidates for Stage 3 ChEMBL [47] druggability profiling.

Report finalization is handled as a validation-gated step rather than as unrestricted free-form writing. The finalization path loads the staged evidence bundle, checks schema conformance, validates cited provenance against available evidence records, and renders report artifacts only after validation passes. If the evidence package exceeds the allowed context, schema validation fails, cited-only provenance cannot be verified, or final workspace checks fail, the workflow records an explicit finalization error and withholds report artifacts.

#### Deep Interpreter

The Deep Interpreter converts spatial analysis outputs and target-prioritization evidence into literature-grounded biological interpretation reports. The agent uses planner, searcher, interpreter, and reporter subagents. The planner decomposes the interpretation objective and identifies required evidence types. The searcher retrieves relevant literature and biological context through dynamic paper search, full-text retrieval, and SGCP-RAG-enabled source navigation. The interpreter synthesizes spatial outputs, ligand-receptor evidence, target-prioritization outputs, and retrieved literature. The reporter renders an expert-reviewable biological interpretation report.

Deep Interpreter outputs pass through validation-driven checks before final reporting. These checks include relevance grading, claim-level citation checks, full-text validation when available, quality scoring, and synthesis-level verification. If literature coverage is insufficient, retrieval can be refined through targeted query loops. If source grounding is weak or a biological claim is not sufficiently supported, the claim is revised or withheld rather than promoted into the final report.

### Study-specific MCP resources and skill-guided evidence workflows

DeepMAST used four study-specific MCP resources and seven skill-guided evidence workflows. The MCP resources defined the executable tool layer, whereas the skills defined task-specific evidence-seeking, database-query, and claim-boundary protocols. The MCP resources developed for this study were Summary-Guided Chunk Promotion RAG (SGCP-RAG), STworkbench MCP, sc_reference_selector, and rMCPAgent. The skills developed within DeepMAST were biomedical-literature-search, compare-census-gene-pair-by-cell-type, and the Target Recommender guide (`drug-target-hypothesis` in benchmark artifacts). The database-query skills chembl-database, gwas-database, opentargets-database, and string-database were adapted from the K-Dense-AI scientific-agent-skills collection [75] for DeepMAST-specific target-prioritization evidence workflows.

#### SGCP-RAG MCP for source-grounded retrieval

Summary-Guided Chunk Promotion RAG (SGCP-RAG) was used as a retrieval-control method for source-grounded biological interpretation. The base retrieval system extended LangConnect Client and LangChain LangConnect infrastructure for collection management, document ingestion, hybrid retrieval, and PostgreSQL/pgvector-backed storage. The methodological contribution was the SGCP-RAG promotion layer, not the base RAG service.

SGCP-RAG constructs a per-collection Summary Navigation Index (SNI), implemented as generated navigation artifacts and a runtime pack containing source pages, concept pages, summaries, keywords, and explicit back-references to source documents and chunks. Source documents were chunked with the default SGCP-RAG MCP settings (chunk_size = 3000; chunk_overlap = 200). For the MultiHop-RAG benchmark, chunk_size was reduced to 1000 while chunk_overlap remained 200 because the corpus contained many short news articles. The SNI is non-authoritative navigation metadata. It guides retrieval toward likely source regions of the corpus, but its generated summaries, titles, and concept labels are not treated as evidence and are not injected into answer generation. At query time, selected SNI pages either promote exact referenced chunks in a static-reference ablation or route retrieval to likely source documents for query-conditioned hybrid search. Promoted chunks are deduplicated and passed through the same LLM relevance grading, answer generation, hallucination grading, and answer-quality grading steps as ordinarily retrieved chunks. Thus, SGCP-RAG was evaluated as bounded retrieval-time source navigation and chunk promotion, not as summary injection.

The SGCP-RAG benchmark used 2,556 MultiHop-RAG cases [62] under paired retrieval conditions for Qwen3.5-35B and Qwen3.5-122B. MultiHop-RAG was selected as a source-grounded multi-hop retrieval benchmark because its English news corpus was curated around documents with overlapping keywords, bridge entities, and bridge topics, rather than duplicated article copies [62]. This design creates a dense multi-document evidence graph in which successful retrieval requires locating source-bearing chunks across topically related news articles. The primary comparison was baseline retrieval versus SNI-enabled document-routed retrieval. Static-reference promotion was treated as a supplementary ablation. Primary endpoints were normalized exact-answer containment and evidence recall among LLM-graded relevant documents. Token F1, no-relevant-context failure rate, retrieved chunk count, and latency were secondary endpoints.

#### STworkbench MCP for spatial transcriptomics analysis

STworkbench MCP was developed as a spatial transcriptomics analysis framework implemented with FastMCP [50] for exploratory spatial characterization, ligand-receptor program discovery, and focused evaluation of candidate ligand-receptor interactions. The workflow accepted AnnData [83] inputs containing expression matrices, spatial coordinates, cluster annotations, and either spot-level cell-type compositions or single-cell cell-type labels. For 10x Visium inputs, raw feature-barcode matrices were read with Squidpy [51], genes detected in fewer than five observations were removed, counts were normalized to 10,000 per observation, and expression values were log-transformed using Scanpy [84].

Spatial neighbor graphs were constructed according to platform geometry. Visium analyses used grid-based spatial neighbors with six nearest neighbors and two neighbor rings. Single-cell-resolution spatial datasets used Delaunay triangulation, with long edges removed at the 99th percentile by default. Multi-sample graphs were constructed independently within each sample to prevent cells or spots from different tissue sections, fields of view, or slides from being treated as spatial neighbors.

Exploratory STworkbench analyses visualized spatial clusters, quantified cluster-cell-type enrichment with one-sided Mann-Whitney U tests followed by Benjamini-Hochberg FDR correction, estimated spatial neighborhood enrichment with Squidpy [51] permutation tests, and inferred pathway activity with decoupleR [85] using PROGENy [52] signaling signatures. Where pathway-cell-type relationships were evaluated, MISTy [53] modeled local and broader spatial relationships between pathway activity scores and cell-type compositions or single-cell summaries.

Ligand-receptor interactions were inferred with LIANA+ [54] using intercellular resources derived from OmniPath [55], including CellChatDB [56], CellPhoneDB [57], connectomeDB2020 [58], and CellTalkDB [59] annotations. Spatial co-localization was quantified with LIANA+ bivariate analysis using local cosine similarity and global bivariate Moran's R with 100 permutations and a fixed random seed. Positive Moran's R ligand-receptor pairs with p < 0.05 were carried into non-negative matrix factorization (NMF). Candidate NMF ranks from 1 to 10 were evaluated by reconstruction error when the rank was not specified; an elbow detector selected the factor number, with five factors used as the fallback.

Ligand-receptor pairs contributing to the selected NMF factor were prioritized by integrating selected factor loading, Moran's R, and GenePT [60] functional similarity. GenePT was used to add a functional-semantic prioritization layer after ligand-receptor filtering by LIANA+ evidence, spatial co-localization, and NMF factor loading. This term was intended to help rank candidate ligand-receptor pairs whose genes were not only spatially co-organized but also close in gene-description embedding space, thereby reducing reliance on spatial statistics alone when multiple positive-Moran's R candidates contributed to the same communication factor. GenePT was not used to infer new ligand-receptor interactions, validate physical ligand-receptor binding, or replace curated intercellular resources. Each component was min-max normalized, and the primary score was computed as 0.4 times normalized factor loading plus 0.4 times normalized Moran's R plus 0.2 times normalized GenePT score. User-selected interest clusters focused the candidate set. Observation-level p values were aggregated separately across pooled interest and non-interest clusters using the aggregated Cauchy association test (ACAT) [61], followed by Benjamini-Hochberg FDR correction. Interactions with FDR-adjusted p < 0.05 in the interest-cluster group were retained, and additional candidates were added by Moran's R and factor loading when needed to reach the requested minimum set.

#### sc_reference_selector MCP for single-cell reference selection

The sc_reference_selector workflow compared candidate single-cell references for spot-based Visium analyses. The method was used in the prostate cancer reference-selection case study, where the spatial query was the 10x Genomics Human Prostate Cancer, Adenocarcinoma with Invasive Carcinoma (FFPE) Visium Spatial Gene Expression dataset [63]. Two candidate references, GSE181294 [64] and GSE185344 [65], were compared after metadata-aware loading, duplicate-gene resolution, stratified downsampling, common-gene harmonization, normalization, and fused Gromov-Wasserstein (FGW) distance calculation.

The prostate cancer spatial input contained 4,371 spots and 17,943 genes at loading. Duplicate-gene handling left 17,941 spatial genes. GSE181294 was downsampled from 156,301 to 9,991 cells, and GSE185344 from 57,697 to 9,995 cells. After harmonization, the spatial query and both references were restricted to the same 16,385-gene feature space. Spatial and reference data were normalized to 10,000 counts per observation and log-transformed using Scanpy [84]. Reference similarity was measured with FGW distance using a fused-distance mixing parameter of 0.5 and entropic regularization of 0.1. Lower distances were interpreted as stronger agreement between the spatial query and a candidate reference.

#### rMCPAgent for converting R workflows into MCP-compatible services

rMCPAgent was used as the R-workflow MCP generation layer for deconvolution-ready spatial analysis. The framework converted R-based bioinformatics functions into MCP-compatible services through four layers consisting of function discovery and schema construction, workflow template standardization, production enhancement, and validation. This design follows the Methods pattern in SPARK, where agentic workflow modules are described together with their preprocessing, validation, and reproducibility boundaries.

Workflow templates specified required inputs, analysis parameters, output files, and validation rules, allowing package-specific R implementations to be wrapped behind a stable agent-facing contract. For deconvolution, templates required H5AD spatial inputs with expression matrices and spatial coordinates, single-cell reference inputs with expression and cell-type/sample metadata, and count-based filtering parameters. The primary deconvolution output was a table with one row per spatial barcode and numeric cell-type proportion columns.

The production workflow applied five stages before exposing an R workflow to Pipeline Executor, including input validation, data loading, workflow integration, recovery diagnostics, and output validation with MCP registration. Input validation checked file existence, file type, readability, required assays, spatial coordinates, metadata fields, and compatibility between spatial and reference datasets. Data loading converted validated H5AD inputs into R-compatible objects through zellkonverter [86]. Recovery diagnostics converted file-access failures, missing metadata, unsupported assays, invalid parameters, package execution failures, output-write failures, and malformed outputs into structured messages. Deconvolution outputs were accepted only when they contained barcode identifiers, at least one numeric proportion column, no missing values, values bounded between 0 and 1, and row-wise proportions summing to 1.0 within a tolerance of 0.01.

#### Biomedical literature search skill

The biomedical-literature-search skill was used as a PubMed evidence-control workflow for ligand-receptor and disease-context interpretation. The skill did not modify PubMed retrieval itself; instead, it standardized how ligand-receptor pairs, disease terms, pathway modifiers, and cell-type modifiers were converted into auditable literature evidence.

In production SEARCHER mode, the workflow retrieved a broad disease-anchored raw paper pool, saved the complete retrieval set for audit, graded title and abstract evidence into predefined buckets, and generated the canonical SEARCHER-to-INTERPRETER handoff artifact. Direct ligand-receptor evidence and receptor/pathway context evidence were passed to downstream interpretation, whereas disease-only background and weak evidence were retained as audit records but excluded from interpreter-facing context by default. Retrieval-only benchmark mode used the same broad retrieval strategy while omitting filtered handoff generation, allowing retrieval effects to be evaluated independently from evidence selection.

#### Compare Census gene-pair-by-cell-type skill

The compare-census-gene-pair-by-cell-type skill was used to quantify disease-context expression and co-expression evidence from CELLxGENE Census [43]. For a specified disease, organism, gene pair, and target cell type, the workflow computed the fraction of cells expressing gene A, gene B, and both genes across cell types. The target cell type was then compared with all remaining cells using a two-proportion z-test.

The workflow reported overall expression summaries, target-versus-rest comparisons, and per-cell-type tables. Target-versus-rest outputs included positive rates, absolute rate differences, risk ratios, z statistics, and p values. Pinned Census versions and minimum cell-count thresholds were used to support reproducibility. Full per-cell-type outputs could be exported as CSV artifacts for downstream target-prioritization and claim-validation steps. Results from low-count cell types were treated as exploratory even when nominal p values were small.

#### Target Recommender guide

The Target Recommender generated evidence-grounded follow-up recommendations from completed Stage 1-3 drug-target assessment evidence. It was not used for unconstrained recommendation ideation. The workflow required a completed evidence bundle with non-empty Stage 3 candidates and used only recommendation-scope evidence made available by the target-prioritization runtime.

The Target Recommender separated recommendation support into interest-cell intrinsic, secondary spatial-niche or cross-cell, and gene-level/actionability-only evidence classes. This separation constrained the language used for follow-up claims: same-cell and cell-autonomous wording required direct eligible Stage 1 support, whereas spatial-only or depleted pair evidence was limited to secondary niche framing. Gene-level Open Targets Platform [44], GWAS Catalog [45], STRING [46], and ChEMBL [47] evidence supported actionability or prioritization claims only within their evidence boundaries.

Candidate recommendations were scored and filtered using evidence coverage, specificity, novelty, and actionability criteria. Before persistence, cited evidence filenames and direct pair axes were validated against the loaded evidence bundle, featured-gene coverage was checked, and deterministic rejection conditions triggered targeted repair rather than unrestricted rewriting. The final output was a structured recommendation artifact used for downstream report rendering.

#### Adapted database-query skills

The chembl-database, gwas-database, opentargets-database, and string-database skills were adapted from the K-Dense-AI scientific-agent-skills collection [75] for DeepMAST-specific target-prioritization workflows. These skills provided database-query protocols rather than new database resources. ChEMBL [47] was used for compound, bioactivity, mechanism-of-action, indication, and druggability evidence; the GWAS Catalog [45] was used for trait and variant association evidence; the Open Targets Platform [44] was used for target-disease, tractability, safety, and known-drug evidence; and STRING [46] was used for protein-interaction and functional-network evidence.

Within DeepMAST, the adapted skills constrained entity resolution, query selection, confidence-threshold interpretation, and evidence summarization before database-derived evidence was passed into target scoring, Target Recommender output generation, and claim-boundary checks.

### Data inputs, benchmark artifacts, and source evidence

DeepMAST analyses used spatial transcriptomics datasets, ligand-receptor candidate tables, target-prioritization evidence bundles, literature retrieval collections, and frozen benchmark artifacts. The human cancer Visium analyses were designed as complementary modularity demonstrations rather than as a comparative oncology study. The breast cancer arm used preprocessed Visium/Xenium-matched breast cancer annotations and spatial clustering as a curated downstream-interpretation setting linked to the integrated single-cell, spatial, and in situ breast cancer study, the Starfysh spatial/histology analysis, and the public accession GSE243280 [48,49]. The prostate cancer arm used the 10x Genomics Human Prostate Cancer, Adenocarcinoma with Invasive Carcinoma (FFPE) Visium dataset and emphasized upstream reference selection, MCP-mediated execution, and downstream biological interpretation [63].

The human idiopathic pulmonary fibrosis (IPF) analysis used the Visium spatial transcriptomics atlas of human pulmonary fibrosis from Franzén et al. [76]. The source study profiled human IPF lung tissue and healthy lung controls across sections spanning mild to more advanced fibrotic remodeling. DeepMAST treated this dataset as the drug target-prioritization application and focused on AT2 and transitional AT2 compartments to identify early disease-associated markers, ligand-receptor axes, and candidate genes. For spot-based analysis, the Pipeline Executor defaulted to IRIS, which supports cell-type deconvolution and spatial clustering within the same multi-slide workflow, before downstream ligand-receptor selection and Deep Drug Target Prioritizer evidence scoring.

Index-section selection for the IPF application was defined before target prioritization and was based on IRIS-domain composition rather than candidate target expression. Candidate sections were restricted to mild IPF tissue. Interest domains were defined as IRIS domains 9, 11, 10, 13, and 5, corresponding to AT2 and transitional AT2-enriched domains from the cell-type analysis. For each eligible section, the analysis computed the spot count and fraction assigned to the interest domains and a secondary AT2/transitional AT2 weighted score, calculated as the sum across interest-domain fractions weighted by the corresponding AT2 and transitional AT2 cluster-median enrichment values. The resulting section-selection table should be reported as supplementary data; repository-local CSV artifacts should remain in source-artifact notes rather than the main Methods prose.

### Benchmark design and evaluation

The benchmark suite was designed to separate evidence acquisition, source-grounded retrieval, and claim generation. This separation follows the reference-paper pattern in which system modules are first defined, then evaluated through bounded benchmarks with direct endpoints. Each panel should have a narrow endpoint and should not be overinterpreted as a generic measure of full-system performance.

#### Literature evidence acquisition benchmark

The literature evidence acquisition benchmark tested whether the biomedical-literature-search skill broadened retrieval-stage citable biological context before downstream interpretation. The benchmark used the same 30 breast cancer Visium ligand-receptor cases as the structured CCI benchmark, sampled across Moran's R magnitude and literature/pathway annotation status. Each case supplied a ligand-receptor pair, breast cancer disease context, ligand and receptor genes, available pathway annotations, and ligand- and receptor-associated cell-type labels.

Each case was evaluated under paired skill ON and skill OFF retrieval-only conditions for Qwen3.5-35B and Qwen3.5-122B, yielding 120 retrieval runs. The skill ON condition used the biomedical-literature-search protocol, including coverage validation and targeted gap-filling searches for missing biological context. The skill OFF condition used the same case inputs and retrieval-only execution mode but omitted the biomedical-literature-search guide. Both arms used the same downstream evidence-bucket policy after retrieval. Direct ligand-receptor evidence and receptor/pathway context evidence were retained as the interpreter-facing citable set, whereas disease-only background and weak evidence were retained for audit but excluded from the citable set. The citable handoff was capped at 40 papers per case.

Coverage was evaluated for three entity classes: ligand/receptor genes, pathway annotations, and cell-type labels. Coverage for a case was defined as the fraction of target entities in a class that appeared in the union of retrieved paper titles and abstracts, allowing aliases and expanded wording. Gene, pathway, and cell-type coverage were recomputed for both the all-retrieved paper set and the interpreter-facing citable set. The primary endpoint for Main Figure 2A should be cell-type coverage in the citable set, because gene coverage was expected to be near-saturated by ligand-receptor queries and pathway coverage was available only for the subset of cases with pathway annotations. All-retrieved coverage should be reported as supplementary evidence.

Coverage labels were assigned with a fixed Qwen3.5-122B labeling model over unique case-paper pairs and aggregated by case, model size, condition, entity class, and paper set. Paired comparisons used case-level skill ON minus skill OFF differences within the same model setting. Wilcoxon signed-rank tests, exact sign tests, and bootstrap confidence intervals were used for paired coverage analysis; pooled analyses combined the Qwen3.5-35B and Qwen3.5-122B paired cases only after preserving case-level pairing. This benchmark should be interpreted as retrieval-breadth evaluation, not as a direct test of final interpretation quality or per-paper precision.

#### SGCP-RAG source-grounded retrieval benchmark

The SGCP-RAG source-grounded retrieval benchmark tested whether SNI-enabled source navigation improved retrieval of source-bearing chunks before downstream answer generation. The benchmark used the same 2,556 MultiHop-RAG cases [62] for all conditions. MultiHop-RAG was selected because its English news corpus contains overlapping keywords, bridge entities, and bridge topics across related documents, creating a multi-document retrieval setting in which answer grounding depends on locating the correct source chunks rather than retrieving a single duplicated article.

Three paired retrieval conditions were evaluated for Qwen3.5-35B and Qwen3.5-122B: baseline retrieval, static-reference promotion, and SNI-enabled document-routed retrieval. Baseline retrieval used the ordinary hybrid search path. Static-reference promotion selected SNI pages and promoted exact source-referenced chunks from those pages. SNI-enabled document-routed retrieval selected SNI pages, routed search to the corresponding source documents, and performed query-conditioned hybrid search within those documents. All conditions used hybrid search with a search limit of five chunks per retrieval call and at most three query rewrites. In all SGCP-RAG conditions, SNI summaries, titles, and concept labels were treated only as navigation metadata; they were not injected into answer generation and were not counted as evidence. Promoted chunks were deduplicated, merged with ordinary retrieval results, and passed through the same relevance grading, answer generation, hallucination grading, and answer-quality grading steps used by baseline retrieval.

The primary comparison was baseline retrieval versus SNI-enabled document-routed retrieval, with static-reference promotion retained as a supplementary ablation. Exact-answer containment was evaluated over 2,556 rows per condition. Evidence recall was evaluated over the 2,255 paired cases with expected evidence keys available and was computed over LLM-graded relevant chunks. Token F1, no-relevant-context failure rate, retrieved and promoted chunk counts, and latency were treated as secondary endpoints. Exact-answer containment used exact McNemar tests for paired binary outcomes, and evidence recall used paired Wilcoxon signed-rank tests. Main Figure 2B should present Qwen3.5-35B and Qwen3.5-122B together to show both model-scale robustness and the larger gain in the 35B setting.

#### Structured CCI interpretation benchmark

The structured CCI interpretation benchmark tested whether structured biological SKILL guidance reduced unsupported free-text interpretation of ligand-receptor pairs from breast cancer Visium data. The benchmark used 30 ligand-receptor cases sampled from LIANA+ outputs using a 3 x 2 stratified design over Moran's R magnitude and literature/pathway annotation status. Cell type-specific spatially variable genes were identified with Celina [82], and ligand and receptor cell-type annotations were derived separately from the Celina ct-SVG calls for each ligand-receptor pair. Each case included the interaction identifier, spatial co-localization statistics, ligand and receptor expression metrics, Celina-derived ligand and receptor cell-type annotations, pathway and disease annotations, interest-cluster enrichment statistics, and tissue context. The cell-type annotations were included to calibrate source-target directionality claims, because broadly distributed ligand expression does not support assignment to a single sender cell type. The main comparison used no skill guidance, unstructured prose guidance, and guide-compliant structured SKILL guidance; a fourth basic structured-SKILL condition was retained for supplementary analysis. Each condition was repeated five times per case, yielding 600 generated interpretations across four conditions. Interpretations were generated with GPT-5.4-nano and independently scored at temperature 0 by a dual-judge panel comprising GPT-5.4 through the OpenAI API and Claude Sonnet 4.6 through the Anthropic API. Judges assigned faithfulness, uncertainty-handling, spatial-calibration, overclaiming, and fabrication-count scores, and judge-level scores were averaged for the consensus hallucination-control endpoint.

#### Evidence-grounded follow-up recommendation benchmark

The Evidence-Grounded Follow-up Recommendations validation tested whether the Target Recommender workflow improved recommendation quality after spatial ligand-receptor and target-prioritization evidence had been fixed. The benchmark used a controlled breast cancer evidence substrate generated by Deep Drug Target Prioritizer, including prioritized target candidates, ligand-receptor candidates, malignant-cell pair evidence, gene-level target evidence, target-disease evidence from Open Targets Platform [44], known-drug annotations, and recommendation-validation metadata. The featured target set comprised ERBB3, EPHB4, ERBB2, INSR, EFNB2, NECTIN4, and LAMA5.

Guided and baseline prompts used the same Qwen3.5-122B generator, source evidence, operational contract, schema contract, evidence-reference validation, save gate, and retry policy. The output contract required four to six retained recommendations, coverage of every featured gene in at least one recommendation, at least one retained recommendation in each of four categories (Mechanism of Action, Therapeutic Strategy, Cross-Target Interaction, and Novel Pathway), evidence references restricted to loaded evidence, and cautious falsifiable predictions rather than clinical-efficacy claims. In the baseline condition, the Target Recommender received the operational contract but no follow-up recommendation guide and was prohibited from reading a skill guide. In the guided condition, the Target Recommender was required to read the Target Recommender guide before generating recommendations. Runs were included only when the process completed successfully, the generated report passed schema and evidence-reference validation, the guide-use trace matched the assigned condition, and no deterministic host-side fallback output was used. Additional attempts were generated until each condition reached 20 valid outputs; invalid exploratory runs were excluded from valid-output analysis.

The valid-output analysis included 20 guided and 20 baseline runs, matched by valid-run order for downstream paired comparisons. Automated auditing recorded guide-use status, fallback status, evidence coverage, retained recommendation count, evidence-reference count, retry attempts, category coverage, and lexical evidence-use indicators including Stage 1, Stage 3, Open Targets, malignant-cell, not-yet-established, and causal-language mentions. Blinded judging compared anonymized guided and baseline output pairs without exposing guide-use labels and used a dual-judge panel comprising GPT-5.4 through the OpenAI API and Claude Sonnet 4.6 through the Anthropic API. Judges scored evidence grounding, biological plausibility, therapeutic relevance, claim-boundary restraint, and specificity/testability, with unsupported-claim penalties and major-error flags. The primary endpoint should be Figure 3C right, claim-boundary restraint; Figure 3C left should be treated as a secondary evidence-coverage summary.

### Biological application workflows

The complementary human cancer Visium analyses were used to demonstrate modularity across upstream execution and curated downstream interpretation. In the prostate cancer arm, Pipeline Executor first selected a single-cell reference for deconvolution, then exposed downstream spatial analysis through MCP-mediated execution before outputs were passed to Deep Interpreter. In the breast cancer arm, curated HITL selection used interest clusters 17, 4, and 14, the Prolif Invasive Tumor cell type, and Factor3. STworkbench MCP generated the NMF/factor spatial program summary, selected ligand-receptor spatial maps, and quantitative interaction summaries. Deep Interpreter then generated literature-grounded disease-context interpretation from these selected outputs.

The breast cancer follow-up recommendation workflow was retained only as the controlled evidence substrate for Figure 3C. Full staged target-evidence assessment, druggability evidence, and deterministic report finalization should be described in the IPF/Figure 5 target-prioritization analysis rather than as an additional main Figure 3 panel.

The human IPF Visium analysis should be presented as the strongest drug target-prioritization application. Methods should describe the Visium input, CCI or ligand-receptor candidate generation, Deep Drug Target Prioritizer run, CELLxGENE, Open Targets Platform, GWAS Catalog, STRING, and ChEMBL evidence sources when used, featured and novel candidate selection, and any experimental or external validation included in the manuscript. Drug-target language should remain conservative: DeepMAST prioritizes candidate drug targets and generates Evidence-Grounded Follow-up Recommendations; it does not establish clinical efficacy without downstream experimental validation.

### Statistical analysis, software, and reproducibility

Benchmark analyses used paired or matched tests when the same case, prompt, or question produced condition-matched outcomes. Omnibus or rank-sum tests were used when the benchmark generated independent replicate outputs across multiple conditions. The CCI hallucination benchmark uses Kruskal-Wallis tests for omnibus condition differences, Mann-Whitney U tests with Bonferroni correction for post-hoc comparisons, and quadratic weighted kappa for inter-rater agreement. Literature-retrieval coverage uses paired case-level differences, bootstrap confidence intervals, and paired Wilcoxon signed-rank tests. SGCP-RAG uses exact McNemar tests for answer containment and paired Wilcoxon signed-rank tests for evidence recall, token F1, chunk count, and latency. Follow-up recommendation evidence-coverage comparisons use paired Wilcoxon signed-rank tests over matched valid runs. Blind-judge preferences use exact two-sided sign tests over non-tie pairs, and claim-boundary restraint uses paired Wilcoxon signed-rank tests after averaging judge scores within each pair, with judge-stratified tests as sensitivity analyses.

Model assignment followed task complexity. DeepMAST served locally deployed open-weight Qwen3.5 models through Ollama. Qwen3.5-35B was used for planning, search, and evidence-assessment subagents, whereas Qwen3.5-122B was used for interpretation, reporting, and hypothesis-writing subagents. In SGCP-RAG, Qwen3.5-9B was used for query expansion and Qwen3.5-122B was used for agentic source-grounded retrieval and SNI rebuild. Software environments were recorded for reproducibility. STworkbench MCP used Python >=3.10 with Scanpy [84], Squidpy [51], LIANA+ [54], decoupleR [85], OmniPath [55], scikit-learn [87], statsmodels [88], Plotly [89], FastMCP [50], and MCP [22]. rMCPAgent was implemented in R >=4.0.0 with ellmer [90], mcptools [91], zellkonverter [86], Bioconductor containers [92], sparse matrix support, workflow templates, JSON/HTTP utilities, and package-development/test dependencies. sc_reference_selector used FastMCP [50], AnnData [83], Scanpy [84], optimal transport and JAX-compatible computation [93] when available, and Plotly [89] report generation. SGCP-RAG benchmarks used the frozen raw provenance files and offline regeneration scripts in the SGCP-RAG reproducibility bundle.

Data availability and code availability should be reported separately from manuscript references. Public dataset accessions, public tool repositories, software versions, and archived benchmark bundles belong in Methods or Source Artifacts. Local file paths, generated CSV/JSON/JSONL artifacts, notebook paths, and repository-internal implementation files should not be added to the manuscript References section unless they are replaced by public URLs, DOIs, or archival repository identifiers.

Methods에서 중요한 원칙:
- 4개 MCP와 3개 Skill은 Methods 앞부분에서 study-specific resources로 먼저 설명합니다. 이 블록은 DeepMAST가 단순 agent wrapper가 아니라 실행 가능한 분석 리소스와 evidence workflow를 함께 구축했다는 점을 보여줍니다.
- Skill 관련 하위제목은 `skill-guided evidence workflows`로 쓰고, 각 skill은 재현 가능한 evidence protocol로 설명합니다.
- Pipeline Builder/Executor는 자세히 쓰되 novelty를 과장하지 않습니다. 이들은 DeepMAST의 analytical substrate입니다.
- Complementary cancer Visium Methods에서는 prostate cancer가 sc_reference_selector와 rMCPAgent/Pipeline Executor를 보여주는 reference-guided execution setting이고, breast cancer가 preprocessed annotations/spatial clustering을 사용하는 curated downstream-interpretation setting이면서 Figure 3의 Evidence-Grounded Follow-up Recommendations validation으로 이어진다는 점을 명시합니다.
- Deep Drug Target Prioritizer와 Deep Interpreter는 core biological harness modules로 더 자세히 씁니다.
- HITL과 expert review는 "사용자가 알아서 확인한다"는 disclaimer가 아니라, DeepMAST가 auditable artifacts, provenance, and claim-level checks를 제공하는 이유로 Methods에 명시합니다.
- DeepMAST를 formal acronym으로 강하게 풀어쓰지 않습니다. 이름 유래를 설명해야 할 때만 "DeepAgents-based, multi-agent spatial transcriptomics architecture"를 반영한 이름이라고 약하게 쓰고, 곧바로 primary contribution이 evidence-governed harness이고 구조적 작동 원리가 validation-driven looping임을 명시합니다.
- SGCP-RAG는 method = **Summary-Guided Chunk Promotion RAG**, artifact = **the SGCP-RAG index**로 명확히 씁니다.
- Benchmark methods는 각 benchmark의 direct endpoint를 분명히 제한합니다.
- Main Figure 2A는 citable set(direct + context)만 main에 두되 Qwen3.5-35B와 Qwen3.5-122B를 함께 제시하고, all-retrieved analyses는 supplement에 둡니다.
- Main Figure 2B는 Qwen3.5-35B와 Qwen3.5-122B를 함께 제시해서 model-scale robustness와 Qwen3.5-35B의 larger gain을 동시에 보여줍니다.

---

# Discussion Structure

Discussion은 "more tools"가 아니라 **better biological control layer**, **evidence-governed claims**, and **validation-driven looping**으로 닫습니다. 전체 구조는 Discussion hourglass를 따릅니다: specific findings recap -> prior-work positioning -> interpretation of governance mechanisms -> limitations -> future directions -> broad field significance.

## academic_writer_brief

```yaml
target_result: "Update this writing blueprint so the Discussion can be drafted around DeepMAST as an evidence-governed biological agent harness."
likely_section_type: "discussion"
scope_included: "Graphical abstract/five-step governance pattern, Figure 2 model-scale evidence-entry findings, local Qwen3.5 task-dependent model use, Figure 3 claim-governance bridge, cancer Visium modularity, IPF target-prioritization application, limitations, future directions, external references."
scope_excluded: "Full Discussion prose draft, new benchmark claims, new figure creation, new local artifact references in the manuscript bibliography."
constraints: "No new data in Discussion; avoid claiming every DeepMAST module has identical hard gates; use Qwen3.5-9B/Qwen3.5-35B/Qwen3.5-122B notation where relevant; frame model-size effects as stage-specific task fit, not model ranking; do not imply frontier models are required for every agent step."
completion_criteria: "The Discussion outline names the argument, paragraph order, claim boundaries, source anchors, citation candidates, limitations, and additional points worth adding."
existing_context: "Introduction/Results/Methods blueprint in this file, Image #1 graphical abstract, docs/DeepMAST_fivestep_governance_pattern.md, docs/writing/figures/fig2.svg, LR retrieval coverage and content-utility interpretation notes."
open_questions: "Target journal and final word limit remain unspecified; default to 1000-2500 words per academic-writer Discussion guidance."
```

## run_reference_layers

```yaml
structure_references:
  - source: "docs/paper/MEDEA.pdf"
    role: "structure"
    notes: "Use system -> verification-aware benchmark -> application -> limitations/future flow; MEDEA Discussion is the closest verification-aware omics-agent reference [13]."
  - source: "docs/paper/SPARK.pdf"
    role: "structure"
    notes: "Use concept-centered system -> validation/use cases -> limitations flow and careful hallucination-control framing [16]."
  - source: "docs/paper/STAgent.md"
    role: "structure"
    notes: "Use spatial-transcriptomics agent positioning, but avoid STAgent-style broad autonomy claims without claim-governance qualification [11]."
  - source: "docs/paper/SpatialAgent.md"
    role: "structure"
    notes: "Use spatial-biology bottleneck, democratization, HITL/collaboration, and limitations structure [12]."
  - source: "docs/paper/twasis.pdf"
    role: "structure"
    notes: "Use discovery-to-prioritization evidence progression and conservative drug-repositioning interpretation."
voice_references:
  - source: "same as structure references"
    role: "voice_tone"
    notes: "Use contribution-first opening, balanced prior-work comparison, limitation-to-future-direction pairing, and cautious translational language."
merge_policy:
  structure_priority: "MEDEA/SPARK for verification-aware agent discussion; STAgent/SpatialAgent for spatial-biology agent contrast; twasis for prioritization/discovery restraint."
  voice_priority: "MEDEA/SPARK for cautious agent-validation tone; SpatialAgent/STAgent only for spatial-biology motivation and broader impact."
```

## Reference-paper structure lessons

- **MEDEA pattern:** open with what the agent achieved across tasks, then explain why verification-aware design mattered, then state concrete limitations and future directions. DeepMAST should mirror this by first summarizing evidence-governed claim control, then interpreting validation-driven loops.
- **SPARK pattern:** emphasize interpretable concepts, careful task framing, review steps that reduce hallucination risk, explicit limits of autonomy, and practical cost constraints from state-of-the-art model use. DeepMAST should use this tone for claim-boundary restraint and for positioning open-source or local models as part of scalable agent deployment rather than as a claim that larger models are unnecessary.
- **STAgent/SpatialAgent pattern:** position spatial-transcriptomics/spatial-biology analysis as expertise-intensive and bottlenecked, then show how agents lower the analysis barrier. DeepMAST should contrast with them by saying its novelty is not only automation, but governance over which biological interpretations and target-prioritization claims survive.
- **twasis pattern:** discovery and prioritization claims should remain evidence-progressive, moving from associations to support analyses to drug-repositioning hypotheses without overstating causal or clinical validation.

## Recommended Discussion order

### 1. DeepMAST extends spatial-transcriptomics agents from automation to claim governance

Opening paragraph should address the Introduction gap directly. Start from the specific findings: DeepMAST links MCP-enabled spatial analysis, literature retrieval, biological databases, structured skills, and validation-driven loops into an evidence-governed harness. Then expand to significance: reliable biological summarization and interpretation require more than tool access.

핵심 문장:

```text
DeepMAST suggests that the next stage of biomedical agent development will not be defined by adding more tools, longer context, or larger harnesses alone, but by building biological harnesses that preserve task-relevant state, convert valid feedback into subsequent actions, govern when retrieved evidence should enter context, decide which claims are sufficiently supported, and make target-prioritization conclusions fail closed when evidence remains insufficient.
```

Claim boundary:
- Say DeepMAST is an evidence-governed biomedical agent harness for spatial transcriptomics interpretation and drug-target prioritization.
- Do not say DeepMAST proves autonomous therapeutic discovery or replaces expert review.
- Cite agentic science/biomedical agent context [6-8,14-16], spatial agents [11,12], and harness/skills work [23-38,71-73,94].

### 2. Harness governance is needed because biological summarization is a claim lifecycle

Use Image #1 and `docs/DeepMAST_fivestep_governance_pattern.md` as the conceptual Discussion anchor. The five-step pattern is:

1. evidence check
2. source check
3. claim support
4. claim boundary
5. finalization

Manuscript-facing interpretation:

```text
The graphical abstract summarizes this logic as a harness gate: spatial outputs, literature, and target databases enter as evidence, but only claims that pass evidence checking, source checking, claim-support review, claim-boundary calibration, and finalization are promoted into biological interpretation, follow-up recommendations, or target prioritization.
```

Important nuance:
- The drug-target path is the clearest deterministic hard-gate exemplar.
- The deep-interpreter path implements the same governance logic through literature-first retrieval, PMID-constrained citation, inline validation, unsupported-claim labeling, and synthesis.
- Avoid "all modules have identical hard gates"; use "core biomedical interpretation pipelines" and "where implemented."

### 3. Evidence-entry controls and claim controls are complementary

Frame the Figure 2/3 bridge as the central Discussion mechanism:

```text
Figure 2 tested whether the harness improves evidence entry points, whereas Figure 3 tested whether structured guidance constrains the biological and follow-up claims generated from that evidence.
```

Interpretation:
- Figure 2A supports retrieval breadth, especially citable cell-type context coverage.
- Figure 2B supports source-grounded retrieval gains from SGCP-RAG.
- Figure 3B supports reduced unsupported CCI interpretation under structured biological guidance.
- Figure 3C supports downstream claim-boundary restraint in breast cancer follow-up recommendations.

Claim boundary:
- Figure 2 does not prove final interpretation quality by itself.
- `INTERPRETATION_KO.md` reports that clean retrieval-only Benchmark A had neutral final content-utility overall; use this as a limitation and nuance, not a contradiction.
- Figure 3C validates generated follow-up recommendation restraint, not therapeutic efficacy.

### 4. Local model use and model size should be interpreted as stage-specific task fit, not a rank order

This section mirrors the Introduction deployment argument and adds the Discussion-level takeaway that future biomedical agents should not default every step to frontier cloud models. DeepMAST should be framed as using local Qwen3.5 models across task difficulty levels, while reserving frontier models such as GPT-5.4 or Sonnet 4.6 for selected judging, auditing, or high-difficulty review roles when needed.

Evidence anchors:
- Figure 2A / coverage summary: Qwen3.5-122B showed the larger absolute citable cell-type coverage gain in the interpreter-facing set: 26.8% to 46.4% (+19.6 pp), while Qwen3.5-35B increased from 27.7% to 38.7% (+11.0 pp). In the all-retrieved set, Qwen3.5-122B also had the larger cell-type gain (+24.7 pp vs +20.6 pp). This supports stronger-model benefit for this retrieval-breadth endpoint.
- Figure 2B / SGCP-RAG: Qwen3.5-35B showed larger SGCP gains than Qwen3.5-122B in exact-answer accuracy (+8.6 pp vs +3.7 pp) and evidence recall (+10.1 pp vs +6.6 pp), and after SGCP exact-answer accuracy was higher in Qwen3.5-35B (34.9% vs 31.7%) while evidence recall was nearly tied (25.6% vs 25.8%).
- `INTERPRETATION_KO.md`: final content utility in the clean retrieval-only run was model-dependent and neutral overall; Qwen3.5-122B showed a positive real-use signal, whereas Qwen3.5-35B did not.
- Deployment rationale: Qwen3.5-9B and Qwen3.5-35B can be discussed as candidates for routine extraction, classification, schema-following, and constrained reasoning; Qwen3.5-122B can be discussed for broader retrieval, synthesis, validation-sensitive stages, selected high-difficulty generation, judging, or audit roles when used.

Recommended interpretation:

```text
These results argue against treating model size as a monotonic proxy for scientific reliability. In DeepMAST, model choice interacts with the stage objective: larger local models can improve broader context acquisition in some retrieval settings, whereas smaller or more literal local models may benefit more from structured retrieval controls and may be useful for contract-following stages after evidence is constrained. This supports a practical agent-design principle in which sensitive or routine work can remain on local Qwen3.5 models, while frontier models are reserved for selected review, judging, or high-difficulty synthesis roles rather than used as the default substrate for every model call.
```

Do not write:
- "Qwen3.5-35B is better than Qwen3.5-122B."
- "Large models are not useful."
- "Weak model outperforms strong model" without specifying endpoint and context.

Better wording:

```text
The safer conclusion is stage-specific complementarity: Qwen3.5-9B and Qwen3.5-35B can support routine or constrained steps, Qwen3.5-122B remains useful for broader retrieval and synthesis, and frontier systems can be reserved for selected high-difficulty review or benchmarking roles. DeepMAST therefore benefits from matching model behavior to the evidence-governance stage rather than selecting the largest or most expensive model by default.
```

Paper-ready Discussion paragraph:

```text
A further implication is that biomedical agents should be designed as governed systems of model calls rather than as frontier-model-only pipelines. Frontier systems remain valuable for difficult synthesis, independent judging, and stress-testing claim boundaries, but routine extraction, classification, retrieval control, schema following, and constrained reasoning can often be assigned to local models selected by task difficulty [18-20]. This point is practical as well as scientific. Local Qwen3.5 deployment can reduce privacy exposure, cost, and latency, while the harness determines whether any model output has enough evidence support to enter the final report. In this view, DeepMAST's use of Qwen3.5-9B, Qwen3.5-35B, and Qwen3.5-122B is not a model-ranking claim; it is a control-layer design choice that matches model capacity to step complexity and reserves frontier or larger models for stages where their additional reasoning or review capacity is justified.
```

External citation support:
- Small-language-model, task-level model selection, and hybrid local-large deployment work supports the broader deployment argument that many agent steps need not use the largest model [18-20].
- Agent skills as reusable procedural artifacts that coordinate tools, memory, and runtime context [27,94].
- Structured-output reliability can depend on constraints and output contracts rather than model size alone [95].
- Instruction following and alignment are not guaranteed by scale alone; if needed, cite existing alignment/skills references rather than adding broad unsupported claims.

### 5. Biological applications demonstrate modularity, not comparative oncology

The paired cancer Visium application should be discussed as a modularity demonstration:
- Prostate cancer exercises upstream reference-guided execution, single-cell reference selection, and MCP-mediated workflow execution.
- Breast cancer exercises curated downstream interpretation and selected ligand-receptor handoff after the Figure 3 claim-governance bridge.
- IPF demonstrates target-prioritization evidence progression and should carry the strongest translational framing.

Claim boundary:
- Do not compare cancer datasets as if they test disease-specific superiority.
- Do not treat breast cancer follow-up recommendation validation as clinical validation.
- For target prioritization, write "follow-up candidates", "prioritization", "evidence-supported recommendations", and "experimental validation needs"; avoid "validated therapeutic targets" unless supported by external validation.

### 6. DeepMAST complements expert review rather than replacing biological expertise

This paragraph should connect the harness to practical use:

```text
DeepMAST is best viewed as an expert-review amplifier: it converts spatial outputs, literature, and target databases into auditable artifacts with explicit provenance, claim boundaries, and unresolved validation needs. This makes biological interpretation easier to inspect, reproduce, and challenge, but it does not remove the need for expert biological judgment or prospective experiments.
```

Tie to reference papers:
- SpatialAgent emphasizes democratization and collaboration [12].
- SPARK emphasizes interpretable, reviewable concepts and careful task framing [16].
- MEDEA emphasizes context verification and abstention when evidence is insufficient [13].

### 7. Limitations

Write limitations as specific limitation-to-future pairs.

Required limitations:
- **Benchmark scope:** current benchmarks cover selected spatial, retrieval, CCI, follow-up recommendation, cancer Visium, and IPF use cases; broader disease and assay coverage is needed.
- **Model dependence:** model behavior changes across retrieval, synthesis, and constrained-output stages; results should not be generalized across model families without revalidation.
- **Literature/database bias:** PubMed, RAG indexes, Open Targets, GWAS Catalog, STRING, ChEMBL, and cell atlas resources are incomplete and unevenly studied across diseases/cell types.
- **Pathway underpowering:** LR retrieval pathway coverage was directionally positive but underpowered because only 11/30 cases contained pathway annotations.
- **Latency cost:** SGCP-RAG improves source-grounded retrieval but adds approximately 29-31 s latency.
- **Validation scale:** target-prioritization recommendations remain computational and literature-grounded; prospective perturbation, imaging, and disease-model validation remain future work.
- **Governance heterogeneity:** deterministic hard gates are strongest in the drug-target path; deep interpretation uses softer prompt/tool-mediated claim validation.

### 8. Future directions

Concrete future directions:
- Larger multi-disease, multi-assay benchmark panels.
- Expert adjudication of biological interpretation and target-prioritization outputs.
- Adaptive retrieval budgets that turn SGCP-RAG on when source grounding matters more than latency.
- Prospective validation of prioritized targets in spatial perturbation, organoid, or disease-model systems.
- Curated failure-trace mining for biological skill updates, only after regression testing and expert review.
- Community biological skill libraries with explicit scope, evidence requirements, and failure modes.

Safe future-facing claim:

```text
DeepMAST should not be described as self-evolving. A safer claim is that validated failure traces could support curated biological skill updates after regression testing and expert review.
```

## Additional content worth adding

- A one-sentence graphical abstract callout in Discussion: "The five-step harness gate provides a compact model for how DeepMAST turns evidence into bounded claims."
- A short "model-task matching" paragraph after Figure 2/3 interpretation; this is the most useful new conceptual point from Image #2.
- A limitation sentence explicitly separating retrieval breadth from final content utility, using `INTERPRETATION_KO.md`.
- A caution that "evidence-bounded follow-up recommendations" are not clinical treatment recommendations.
- A final sentence returning to the Introduction gap: reliable spatial-transcriptomics interpretation requires governing claim promotion, not just automating workflow execution.

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

[11] DOI: 10.1101/2025.04.01.646731. "Spatial transcriptomics AI agent charts hPSC-pancreas maturation in vivo."

[12] DOI: 10.1101/2025.04.03.646459. "SpatialAgent: An autonomous AI agent for spatial biology."

[13] DOI: 10.64898/2026.01.16.696667. "Medea: An omics AI agent for therapeutic discovery." Public full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC12871667

[14] DOI: 10.1093/bib/bbag075. "Artificial Intelligence agents for biological research: a survey." Public full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC12936789

[15] DOI: 10.1093/bib/bbaf505. "Streamline automated biomedical discoveries with agentic bioinformatics." Public full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC12476841

[16] DOI: 10.1038/s41591-026-04357-y. "An agentic framework for autonomous scientific discovery in cancer pathology."

[17] arXiv: 2606.26627. "A Data-Centric Survey of Privacy in LLM Agents." https://arxiv.org/abs/2606.26627

[18] DOI: 10.48550/arXiv.2506.02153. "Small Language Models are the Future of Agentic AI."

[19] DOI: 10.48550/arXiv.2406.18665. "RouteLLM: Learning to Route LLMs with Preference Data."

[20] DOI: 10.48550/arXiv.2504.00434. "HERA: Hybrid Edge-cloud Resource Allocation for Cost-Efficient AI Agents."

[21] "Deep Agents overview." LangChain documentation. https://docs.langchain.com/oss/python/deepagents/overview

[22] "Model Context Protocol Specification." https://modelcontextprotocol.io/specification/2025-11-25

[23] "SkillsBench: How Agent Skills Improve Performance Across Diverse Tasks." https://citations.gxl.ai/papers/arx_2602.12670#L4-L12

[24] "SkillTester: Holistic Evaluation of Utility and Security for Agent Skills." https://citations.gxl.ai/papers/arx_2603.28815#L10-L18

[25] "Trace2Skill: Generating Agent Skills from Execution Data." https://citations.gxl.ai/papers/arx_2603.25158#L5-L32

[26] "SWE-Skills-Bench: Measuring the Impact of Agent Skills on Software Engineering Tasks." https://citations.gxl.ai/papers/arx_2603.15401#L17-L31

[27] "Agent Skills for Large Language Models." https://citations.gxl.ai/papers/arx_2602.12430#L5-L13

[28] "SkillWeaver: Web Agents can Self-Improve by Discovering and Honing Skills." https://citations.gxl.ai/papers/arx_2504.07079#L7-L21

[29] "SkillNet: Towards Open Infrastructure and General Evaluation for AI Skills." https://citations.gxl.ai/papers/arx_2603.04448#L10-L33

[30] "AgentSkillOS: Towards Automatic Skill Selection, Orchestration, and Ecosystem Management." https://citations.gxl.ai/papers/arx_2603.02176#L4-L37

[31] "Memento-Skills: How to Continuously Learn and Adapt as a Language Agent." https://citations.gxl.ai/papers/arx_2603.18743#L4-L32

[32] "XSkill: Cross-Embodiment Skill Discovery for Visual-Language Agents." https://citations.gxl.ai/papers/arx_2603.12056#L6-L28

[33] "SKILLFOUNDRY: Building Self-Evolving Agent Skill Libraries from Heterogeneous Scientific Resources." Source in `agentpaper` collection: `skillfoundry.pdf`; project URLs reported in the paper: https://github.com/ma-compbio-lab/SkillFoundry and https://ma-compbio-lab.github.io/SkillFoundry/

[34] arXiv: 2605.30785. "Learning Agent-Compatible Context Management for Long-Horizon Tasks." https://arxiv.org/html/2605.30785v1

[35] arXiv: 2605.29682. "Scaling Laws for Agent Harnesses via Effective Feedback Compute." https://arxiv.org/abs/2605.29682

[36] arXiv: 2605.30621. "Harness Updating Is Not Harness Benefit: Disentangling Evolution Capabilities in Self-Evolving LLM Agents." https://arxiv.org/abs/2605.30621

[37] arXiv: 2606.09498. "Self-Harness: Harnesses That Improve Themselves." https://arxiv.org/abs/2606.09498

[38] arXiv: 2606.05080. "AutoLab: Can Frontier Models Solve Long-Horizon Auto Research and Engineering Tasks?" https://arxiv.org/abs/2606.05080

[39] arXiv: 2505.09388. "Qwen3 Technical Report." https://arxiv.org/abs/2505.09388

[40] URL: https://ollama.com/library/qwen3.5. "qwen3.5." Ollama model library.

[41] "LangGraph overview." LangChain documentation. https://docs.langchain.com/oss/python/langgraph/overview

[42] DOI: 10.48550/arXiv.2210.03629. "ReAct: Synergizing Reasoning and Acting in Language Models."

[43] "CZ CELLxGENE Discover: A single-cell data platform for scalable exploration, analysis and modeling of aggregated data." CZ CELLxGENE citation page and bioRxiv DOI. https://cellxgene.cziscience.com/docs/08__Cite%20cellxgene%20in%20your%20publications

[44] "Open Targets Platform: facilitating therapeutic hypotheses building in drug discovery." Open Targets Platform citation page. https://platform-docs.opentargets.org/citation

[45] "GWAS Catalog current citation." NHGRI-EBI GWAS Catalog related resources. https://www.ebi.ac.uk/gwas/docs/related-resources

[46] "The STRING database in 2025: protein networks with directionality of regulation." Nucleic Acids Research. https://academic.oup.com/nar/article/53/D1/D730/7903368

[47] "The ChEMBL Database in 2023: a drug discovery platform spanning multiple bioactivity data types and time periods." Nucleic Acids Research. https://academic.oup.com/nar/article/52/D1/D1180/7337608

[48] DOI: 10.1038/s41467-023-43458-x. "High resolution mapping of the tumor microenvironment using integrated single-cell, spatial and in situ analysis."

[49] DOI: 10.1038/s41587-024-02173-8. "Starfysh integrates spatial transcriptomic and histologic data to reveal heterogeneous tumor-immune hubs."

[50] URL: https://github.com/PrefectHQ/fastmcp. "FastMCP."

[51] DOI: 10.1038/s41592-021-01358-2. "Squidpy: a scalable framework for spatial omics analysis."

[52] DOI: 10.1038/s41467-017-02391-6. "Perturbation-response genes reveal signaling footprints in cancer gene expression."

[53] DOI: 10.1186/s13059-022-02663-5. "Explainable multiview framework for dissecting spatial relationships from highly multiplexed data."

[54] DOI: 10.1038/s41556-024-01469-w. "LIANA+ provides an all-in-one framework for cell-cell communication inference."

[55] DOI: 10.1093/nar/gkaf1126. "OmniPath: integrated knowledgebase for multi-omics analysis."

[56] DOI: 10.1038/s41467-021-21246-9. "Inference and analysis of cell-cell communication using CellChat."

[57] DOI: 10.1038/s41596-020-0292-x. "CellPhoneDB: inferring cell-cell communication from combined expression of multi-subunit ligand-receptor complexes."

[58] DOI: 10.1038/s41467-020-18873-z. "Predicting cell-to-cell communication networks using NATMI."

[59] DOI: 10.1093/bib/bbaa269. "CellTalkDB: a manually curated database of ligand-receptor interactions in humans and mice."

[60] DOI: 10.1101/2023.10.16.562533. "GenePT: A Simple But Effective Foundation Model for Genes and Cells Built From ChatGPT." bioRxiv preprint: https://www.biorxiv.org/content/10.1101/2023.10.16.562533v1

[61] DOI: 10.1016/j.ajhg.2019.01.002. "ACAT: a fast and powerful p value combination method for rare-variant analysis in sequencing studies."

[62] DOI: 10.48550/arXiv.2401.15391. "MultiHop-RAG: Benchmarking Retrieval-Augmented Generation for Multi-Hop Queries."

[63] URL: https://www.10xgenomics.com/datasets/human-prostate-cancer-adenocarcinoma-with-invasive-carcinoma-ffpe-1-standard-1-3-0. "Human Prostate Cancer, Adenocarcinoma with Invasive Carcinoma (FFPE)." 10x Genomics Spatial Gene Expression dataset analyzed using Space Ranger 1.3.0.

[64] DOI: 10.1038/s41467-023-36325-2. "Dissecting the immune suppressive human prostate tumor microenvironment via integrated single-cell and spatial transcriptomic analyses." GEO accession: GSE181294; PMID: 36750562.

[65] DOI: 10.1038/s41467-022-33780-1. "Single cell analysis of cribriform prostate cancer reveals cell intrinsic and tumor microenvironmental pathways of aggressive disease." GEO accession: GSE185344; PMID: 36229464.

[66] DOI: 10.1186/1471-2407-7-73. "Nectin-4 is a new histological and serological tumor associated marker for breast cancer."

[67] DOI: 10.1002/path.6394. "Afadin loss induces breast cancer metastasis through destabilisation of E-cadherin to F-actin linkage."

[68] DOI: 10.1111/jcmm.15140. "E-cadherin deregulation in breast cancer."

[69] DOI: 10.1186/1471-2407-13-383. "HRG-beta1-driven ErbB3 signaling induces epithelial-mesenchymal transition in breast cancer cells."

[70] DOI: 10.3390/ijms25115978. "Disrupting EGFR-HER2 Transactivation by Pertuzumab in HER2-Positive Cancer: Quantitative Analysis Reveals EGFR Signal Input as Potential Predictor of Therapeutic Outcome."

[71] "Natural-Language Agent Harnesses." https://arxiv.org/abs/2603.25723

[72] "AutoHarness: Automatic Generation of Agent Harnesses." https://citations.gxl.ai/papers/arx_2603.03329#L6-L21

[73] "Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering." https://arxiv.org/abs/2604.08224

[74] "CRISPR-GPT: An LLM Agent for Automated Design of Gene-Editing Experiments." https://citations.gxl.ai/papers/bio_ea67019d70c5#L17-L45

[75] URL: https://github.com/K-Dense-AI/scientific-agent-skills. "K-Dense-AI scientific-agent-skills."

[76] DOI: 10.1038/s41588-024-01819-2. "Mapping spatially resolved transcriptomes in human and mouse pulmonary fibrosis."

[77] DOI: 10.1186/s12931-019-1161-4. "Antifibrotic therapy for idiopathic pulmonary fibrosis. Time to treat."

[78] DOI: 10.1136/thoraxjnl-2016-208710. "Nintedanib in patients with idiopathic pulmonary fibrosis and preserved lung volume."

[79] DOI: 10.1183/13993003.01966-2015. "Efficacy of pirfenidone in patients with idiopathic pulmonary fibrosis with more preserved lung function."

[80] DOI: 10.1038/s41467-020-17358-3. "Alveolar regeneration through a Krt8+ transitional stem cell state that persists in human lung fibrosis."

[81] DOI: 10.1165/rcmb.2024-0372TR. "The emerging role of alveolar epithelial type 2 cell-derived transitional cells in lung fibrosis."

[82] DOI: 10.1038/s41467-025-56280-4. "Statistical identification of cell type-specific spatially variable genes in spatial transcriptomics."

[83] DOI: 10.21105/joss.04371. "anndata: Access and store annotated data matrices."

[84] DOI: 10.1186/s13059-017-1382-0. "SCANPY: large-scale single-cell gene expression data analysis."

[85] DOI: 10.1093/bioadv/vbac016. "decoupleR: ensemble of computational methods to infer biological activities from omics data."

[86] DOI: 10.18129/B9.bioc.zellkonverter. "zellkonverter: Conversion Between scRNA-seq Objects."

[87] URL: https://jmlr.org/papers/v12/pedregosa11a.html. "Scikit-learn: Machine Learning in Python."

[88] DOI: 10.25080/Majora-92bf1922-011. "Statsmodels: Econometric and Statistical Modeling with Python."

[89] URL: https://plotly.com/chart-studio-help/citations/. "Collaborative data science."

[90] DOI: 10.32614/CRAN.package.ellmer. "ellmer: Chat with Large Language Models."

[91] DOI: 10.32614/CRAN.package.mcptools. "mcptools: Model Context Protocol Servers and Clients."

[92] DOI: 10.1186/gb-2004-5-10-r80. "Bioconductor: open software development for computational biology and bioinformatics."

[93] URL: https://github.com/jax-ml/jax. "JAX: composable transformations of Python+NumPy programs."

[94] arXiv: 2605.07358. "A Comprehensive Survey on Agent Skills: Taxonomy, Techniques, and Applications." https://arxiv.org/html/2605.07358v1

[95] arXiv: 2505.04016. "SLOT: Structuring the Output of Large Language Models." https://arxiv.org/abs/2505.04016
