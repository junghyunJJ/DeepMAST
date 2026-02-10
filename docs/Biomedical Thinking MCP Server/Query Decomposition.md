# Research Summary: LLM-Guided Search and Query Decomposition

## Query: Instructed Retriever and LLM-Assisted Literature Search

### Research Date: 2026-02-07

---

## 1. Databricks Instructed Retriever Concept

### What It Is
The **Instructed Retriever** is a novel retrieval architecture unveiled by Databricks on January 6, 2026, designed to move enterprise AI beyond the limitations of traditional RAG systems. Rather than treating retrieval as a thin similarity layer, it carries **full system context**—instructions, examples, and index schema—across query generation, retrieval, and response.

**Source**: [Databricks Blog - Instructed Retriever](https://www.databricks.com/blog/instructed-retriever-unlocking-system-level-reasoning-search-agents)

### How It Works

The architecture includes three core capabilities:

1. **Query Decomposition**: Breaks down complex, multi-part requests into a full search plan containing multiple keyword searches and filter instructions
   - Example: "Find me a FooBrand product, but only from last year, and not a 'lite' model" → multiple structured sub-queries

2. **Contextual Relevance**: Moves beyond simple text similarity to true relevance understanding in context of query and system instructions
   - Re-ranker uses instructions to boost documents matching user intent (e.g., "recency"), even if keywords are weaker matches

3. **Metadata Reasoning**: Translates natural language instructions into precise, executable search filters
   - Example: "from last year" → `doc_timestamp > TO_TIMESTAMP('2024-11-01')`

**Source**: [VentureBeat - Databricks Instructed Retriever](https://venturebeat.com/data/databricks-instructed-retriever-beats-traditional-rag-data-retrieval-by-70)

### Performance Metrics

**Quantitative Results:**
- **35-50% gain** in retrieval recall on instruction-following benchmarks
- **70% improvement** in end-to-end answer quality compared to standard RAG architectures

**Source**: [TechTarget - Databricks Tool](https://www.techtarget.com/searchdatamanagement/news/366637142/New-Databricks-tool-aims-to-up-agentic-AI-response-accuracy)

### Key Architectural Pattern

Instructed Retriever is **instruction-following, schema-aware, and system-level**, representing a shift from vector similarity to semantic understanding with structured reasoning. It's integrated into Databricks Agent Bricks and powers their Knowledge Assistant product.

**Source**: [Medium - Databricks Instructed Retriever Analysis](https://medium.com/@silavi.m7/databricks-instructed-retriever-the-missing-piece-for-reliable-agentic-ai-search-484bda12de5c)

---

## 2. Query Decomposition in Search: Evidence and Impact

### ParallelSearch: Reinforcement Learning Approach

**Concept**: Train LLMs to recognize parallelizable query structures and execute multiple search operations concurrently using reinforcement learning.

**Quantitative Results:**
- **2.9% average improvement** across 7 question-answering benchmarks vs SOTA baselines
- **12.7% improvement** on parallelizable questions specifically
- **30.4% reduction in LLM calls** (only 69.6% of calls needed vs sequential approaches)

**How It Works:**
- Uses dedicated reward functions that incentivize identification of independent query components
- Jointly considers correctness, query decomposition quality, and parallel execution benefits
- Addresses sequential bottleneck in traditional search architectures

**Source**: [arXiv - ParallelSearch](https://arxiv.org/abs/2508.09303)

### Query Decomposition for Complex Questions

**Research Finding**: Query decomposition involves breaking down complex, multi-step queries that are characterized as:
- Non-factoid
- Multi-step (requiring decomposition)
- Multi-source knowledge
- Higher-order reasoning

**Application**: Essential component of complex question answering systems, particularly in biomedical contexts where queries span multiple domains.

**Source**: [Complex QA Survey](https://hal.science/hal-05173860v2/document)

---

## 3. LLM-Assisted Query Reformulation: Results and Quality Impact

### RQ-RAG: Learning to Refine Queries

**Concept**: Framework that equips LLMs with capabilities for explicit query rewriting, decomposition, and disambiguation.

**Quantitative Results:**
- **1.9% average improvement** over previous SOTA across 3 single-hop QA datasets (Llama2-7B)
- **33.5% improvement** over base Llama2-7B on question answering benchmarks
- **20.3% improvement** over SAIL-7B baseline
- **1.9% improvement** over Self-RAG

**Technical Approach:**
- Tree decoding strategy: generate → retrieve → generate → retrieve
- Trained end-to-end on 7B Llama2 model
- Handles multi-turn dialogue, decomposition needs, and disambiguation

**Key Insight**: Particularly effective on complex, multi-hop QA datasets when applied to Llama3-8B model.

**Source**: [arXiv - RQ-RAG](https://arxiv.org/abs/2404.00610)

### General Finding on Query Rewriting

**Research Result**: Query rewriting has differential impacts based on model strength:
- **Weaker models**: Notable improvements from rewriting
- **Stronger models**: Rewriting can harm performance
- **Implication**: There may be a limit to usefulness of query rewriting on complex tasks with current techniques

**Source**: [Benchmarking Complex Retrieval](https://arxiv.org/html/2509.07253v1)

---

## 4. Biomedical/PubMed Search: Domain-Specific Insights

### BMQExpander: Ontology-Guided Biomedical Query Expansion

**Concept**: Combines UMLS Metathesaurus medical knowledge (definitions, relationships) with LLM generative capabilities to enhance retrieval effectiveness.

**Quantitative Results:**
- **Up to 22.1% improvement in NDCG@10** over sparse baselines
- **Up to 6.5% improvement** over strongest baseline
- **Up to 15.7% improvement** under query perturbation vs strongest baseline
- **Order of magnitude lower hallucination** than CSQE baseline
- **On par with Query2Doc** for hallucination reduction

**Key Domain Insight**: Ontology grounding is CRITICAL for biomedical search because:
- LLMs can generate plausible-sounding but inaccurate/fabricated biomedical terms during query expansion
- Incorrect expansions shift original query intent or introduce clinically invalid terminology
- UMLS grounding limits hallucination dramatically

**Benchmarks Tested**: NFCorpus, TREC-COVID, SciFact

**Source**: [arXiv - Ontology-Guided Query Expansion](https://arxiv.org/abs/2508.11784)

### PubMed Search in the AI Era

**Current State**:
- LLMs can be leveraged to search/query scientific papers from PubMed using RAG methods
- Future literature search engines anticipated to include LLM-generated high-level overviews of returned articles

**Challenge**: Maintaining accuracy and avoiding hallucination when expanding biomedical queries is a primary concern.

**Source**: [PMC - Biomedical Literature Search in AI Age](https://pmc.ncbi.nlm.nih.gov/articles/PMC10850402/)

### Biomedical Literature Q&A Systems

**Architecture**: RAG systems combining:
- PubMed articles
- Curated Q&A datasets
- Medical encyclopedias

**Goal**: Improve access to accurate, evidence-based medical information through integration of diverse sources.

**Source**: [arXiv - Biomedical Literature Q&A](https://arxiv.org/abs/2509.05505)

---

## 5. Key Architectural Patterns for LLM-Powered Search Agents

### 1. Agentic RAG Framework

**Core Pattern**: State-driven agentic system with self-correcting "retrieve-evaluate-refine" loop

**Components**:
- Dynamic query generation
- Semantic validation
- Iterative optimization of search strategies
- Comprehensive context construction

**Application**: Clinical decision support, enterprise knowledge systems

**Source**: [Agentic RAG Survey](https://arxiv.org/html/2501.09136v3)

### 2. Three-Stage Deep Research Pipeline

**Formalized Roadmap**:
1. **Task Planning**: Decompose user request into sub-tasks
2. **Information Acquisition**: Execute searches with query reformulation
3. **Memory Management**: Track retrieved information and search state
4. **Answer Generation**: Synthesize results into coherent response

**Comparison**: More sophisticated than conventional RAG with explicit planning and memory components.

**Source**: [Deep Research Systems Survey](https://www.preprints.org/frontend/manuscript/293d609eb9e3ff1d5e0b93522128610c/download_pub)

### 3. Multi-Agent Query Processing

**Pattern**: Complexity Analyzer Agent inspects queries for:
- Multiple semantic topics
- Compound instructions
- Entity diversity

**Decision**: Multi-issue queries trigger balanced dual-pipeline strategies (parallel processing).

**Source**: [GenAI Personalization Research](https://genai-personalization.github.io/assets/papers/GenAIRecP2025/11_Baban.pdf)

### 4. Hybrid Graph + Vector RAG

**Architecture**: Combines:
- Knowledge graph for structured relationships
- Vector similarity for semantic search
- Agentic control for dynamic strategy selection

**Application**: Clinical domains where accuracy and interpretability are critical.

**Source**: [Agentic Graph RAG for Hepatology](https://pmc.ncbi.nlm.nih.gov/articles/PMC12748213/)

---

## 6. Benchmarks: LLM-Guided vs Naive Search

### Clinical Decision Support: Agentic Graph RAG

**Evaluation Metrics and Results**:
- **Faithfulness**: 0.94 (measures factual accuracy vs source)
- **Context Recall**: 0.92 (measures retrieval completeness)
- **Answer Relevancy**: 0.91 (measures response pertinence)

**Comparison**: Significantly outperformed GPT-4, standard RAG, and Graph RAG baselines across ALL metrics.

**Impact**: Incorporating AI agents into RAG-augmented LLM improved GPT-4 accuracy to **95%**.

**Domain**: Hepatology clinical decision support

**Source**: [Frontiers in Medicine - Self-Correcting Agentic Graph RAG](https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2025.1716327/full)

### Search Quality Metrics for LLM Systems

**Standard Metrics Used**:
- **Retrieval Performance**: F1, NDCG, MRR, Recall@5, Recall@10
- **Semantic Similarity**: BERTScore, BLEURT
- **Ranking Metrics**: NDCG@10, MRR (Mean Reciprocal Rank)

**LLM-as-a-Judge**:
- Can achieve **>90% alignment** with human judgments across evaluation types
- Validated for search query parsing in large-scale, real-world search systems

**Source**: [LLM-as-a-Judge for Search Query Parsing](https://pmc.ncbi.nlm.nih.gov/articles/PMC12319771/)

### BioASQ Challenge 2024

**Benchmark**: 12th edition of large-scale biomedical semantic indexing and question answering challenge

**Standard Metrics**:
- Query-level retrieval: F1, NDCG, MRR, Recall@5
- Semantic evaluation: BERTScore, BLEURT
- Document retrieval: NDCG@10, Recall@10

**Purpose**: Major evaluation framework for biomedical NLP systems

**Source**: [BioASQ 2024 Overview](https://dl.acm.org/doi/abs/10.1007/978-3-031-71908-0_1)

---

## 7. Additional Key Research Papers

### Query Understanding with LLMs

**Paper**: "Reasoning-enhanced Query Understanding through Decomposition and Interpretation"

**Approach**: Three-stage LLM-based pipeline:
1. Decompose complex query into sub-queries (cover diverse user intents)
2. Augment each sub-query with semantic interpretation
3. Improve alignment between intent and document content

**Source**: [UvA Research](https://staff.fnwi.uva.nl/m.derijke/wp-content/papercite-data/pdf/zhong-2025-reasoning-enhanced-arxiv.pdf)

### Open-Source Agentic Hybrid RAG

**Focus**: Scientific literature review

**Approach**: Combines agentic control with hybrid retrieval strategies for comprehensive literature analysis.

**Source**: [arXiv - Open-Source Agentic Hybrid RAG](https://arxiv.org/abs/2508.05660)

---

## Summary of Key Takeaways

### 1. Query Decomposition is Essential
- Enables 2.9-12.7% performance improvements
- Reduces computational costs by ~30%
- Critical for complex, multi-hop questions

### 2. LLM Reformulation Works But Needs Constraints
- RQ-RAG shows 1.9-33.5% improvements with structured reformulation
- Raw query expansion can harm strong models
- Domain-specific grounding (ontologies) reduces hallucination by order of magnitude

### 3. Biomedical Domain Requires Special Handling
- Ontology-guided expansion (BMQExpander) achieves 6.5-22.1% improvements
- Hallucination is major risk without grounding
- UMLS/structured knowledge integration is critical

### 4. Agentic Patterns Outperform Static RAG
- Self-correcting loops achieve 0.94 faithfulness, 0.92 recall
- Dynamic strategy selection beats fixed pipelines
- 70% improvement over naive RAG (Instructed Retriever)

### 5. Key Architecture Components
- Multi-stage planning (task → retrieve → synthesize)
- Parallel query execution where possible
- Metadata reasoning for precise filtering
- Iterative refinement loops
- Schema-aware retrieval

---

## Relevance to DeepMAST Project

### Current Architecture
DeepMAST's SEARCHER subagent currently uses context-aware searches:
- Part 1: `spatial_search_context` (pathways + celltypes, NO genes)
- Part 2+3: `lr_search_context` (genes + pathways + celltypes)

### Recommended Enhancements Based on Research

1. **Query Decomposition**:
   - Implement ParallelSearch-style parallel execution for independent literature queries
   - Break complex CCI interpretation queries into sub-queries

2. **Ontology Grounding**:
   - Integrate Gene Ontology (GO), Reactome, or other biomedical ontologies
   - Use BMQExpander pattern to reduce hallucination in query expansion

3. **Iterative Refinement**:
   - Adopt RQ-RAG's tree decoding strategy for PubMed searches
   - Implement generate → retrieve → refine loops

4. **Metadata Reasoning**:
   - Add structured filters for publication date, study type, organism
   - Translate natural language constraints to PubMed E-utilities filters

5. **Evaluation Metrics**:
   - Implement faithfulness, context recall, answer relevancy tracking
   - Use BERTScore/BLEURT for semantic quality assessment

6. **Agentic Architecture**:
   - Add self-correcting "retrieve-evaluate-refine" loop to SEARCHER
   - Implement complexity analyzer to decide between simple vs decomposed search

---

## References

### Instructed Retriever & Enterprise RAG
- [Databricks Blog - Instructed Retriever](https://www.databricks.com/blog/instructed-retriever-unlocking-system-level-reasoning-search-agents)
- [VentureBeat - 70% Improvement Analysis](https://venturebeat.com/data/databricks-instructed-retriever-beats-traditional-rag-data-retrieval-by-70)
- [InfoWorld - Instructed Retriever vs RAG](https://www.infoworld.com/article/4114484/databricks-says-its-instructed-retriever-offers-better-ai-answers-than-rag-in-the-enterprise.html)

### Query Decomposition
- [arXiv - ParallelSearch](https://arxiv.org/abs/2508.09303)
- [ParallelSearch Project Page](https://shuzhao.me/ParallelSearchProject/)
- [UvA - Reasoning-Enhanced Query Understanding](https://staff.fnwi.uva.nl/m.derijke/wp-content/papercite-data/pdf/zhong-2025-reasoning-enhanced-arxiv.pdf)

### Query Reformulation
- [arXiv - RQ-RAG](https://arxiv.org/abs/2404.00610)
- [OpenReview - RQ-RAG](https://openreview.net/forum?id=tzE7VqsaJ4)

### Biomedical Query Expansion
- [arXiv - BMQExpander (Ontology-Guided)](https://arxiv.org/abs/2508.11784)
- [PMC - Biomedical Literature Search in AI Age](https://pmc.ncbi.nlm.nih.gov/articles/PMC10850402/)
- [arXiv - Biomedical Literature Q&A](https://arxiv.org/abs/2509.05505)

### Agentic RAG
- [arXiv - Agentic RAG Survey](https://arxiv.org/html/2501.09136v3)
- [Frontiers Medicine - Self-Correcting Agentic Graph RAG](https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2025.1716327/full)
- [PMC - Agentic Graph RAG for Clinical Decision](https://pmc.ncbi.nlm.nih.gov/articles/PMC12748213/)
- [arXiv - Open-Source Agentic Hybrid RAG](https://arxiv.org/abs/2508.05660)

### Evaluation & Benchmarks
- [PMC - LLM-as-a-Judge for Search](https://pmc.ncbi.nlm.nih.gov/articles/PMC12319771/)
- [ACM - BioASQ 2024 Overview](https://dl.acm.org/doi/abs/10.1007/978-3-031-71908-0_1)
- [arXiv - Benchmarking Complex Retrieval](https://arxiv.org/html/2509.07253v1)

### LLM Research Surveys
- [Sebastian Raschka - LLM Research 2024](https://sebastianraschka.com/blog/2025/llm-research-2024.html)
- [Deep Research Systems Survey](https://www.preprints.org/frontend/manuscript/293d609eb9e3ff1d5e0b93522128610c/download_pub)
