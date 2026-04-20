# Biomedical Literature Search Use Cases

Use Case: Grounded ST/CCI literature search
Trigger: User says "find PubMed literature for this ST/CCI result" or "run the SEARCHER literature workflow"
Steps:
1. Load `search_context` from the prepared analysis directory.
2. Run `search_literature_dynamic` with genes, pathways, celltypes, disease, `output_path`, and `data_dir`.
3. Inspect `coverage`, `coverage_sufficient`, and `recommended_actions`.
4. Save the grounded result set to `/papers.json`.
Result: A SEARCHER-ready `/papers.json` with a grounded paper set for downstream interpretation.

Use Case: Bundled pathway and celltype recovery
Trigger: User says "do a literature pass for pathway and celltype gaps" or "don't stop early if pathway or celltype coverage is still weak"
Steps:
1. Run the primary dynamic search.
2. Inspect `coverage["pathways_coverage_pct"]`, `coverage["celltypes_coverage_pct"]`, and the matching missing lists.
3. Run a bundled `search_literature` follow-up that combines pathway, celltype, and disease keywords in one pass.
4. Use `search_pubmed_advanced` only if the bundled pass still leaves important gaps.
Result: A more context-rich paper set that improves pathway or celltype support without widening the workflow indefinitely.

Use Case: Manual wrapper rerun for debugging
Trigger: User says "rerun the literature search manually" or "smoke test the literature wrapper outside SEARCHER"
Steps:
1. Run `scripts/search_literature_dynamic.py` with explicit `--genes`, `--pathways`, `--celltypes`, `--disease`, `--output-path`, and `--data-dir`.
2. Inspect the printed JSON summary and saved file path.
3. Review the saved `/papers.json` and coverage block.
4. Decide whether a manual bundled follow-up is needed.
Result: A reproducible manual rerun that mirrors the SEARCHER entrypoint closely enough for debugging and smoke testing.
