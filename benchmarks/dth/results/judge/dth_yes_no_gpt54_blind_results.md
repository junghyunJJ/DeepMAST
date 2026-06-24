# DTH Yes/No Blind Judge

- Status: `judged`
- Source summary: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/cumulative_valid_only_summary_for_20each_target.json`
- Pair count: 20
- Judge: `openai:gpt-5.4`
- Tie threshold: 2.0

## Blind Result

| condition | wins | win rate | mean score |
| --- | ---: | ---: | ---: |
| DTH_yes | 18 | 90.00% | 19.60 |
| DTH_no | 1 | 5.00% | 14.25 |
| tie | 1 | 5.00% | - |

- Non-tie comparisons: 19
- Sign-test p-value, yes vs no: 7.629e-05
- Mean score delta, yes minus no: 5.35
- Judge errors: 0
- Input/output tokens: 63802 / 11784
- Estimated total cost USD: 0.538024

## Output Files

```json
{
  "pair_panel": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_gpt54_blind_pair_panel.jsonl",
  "judge_rows": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_gpt54_blind_judge_rows.jsonl",
  "summary": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_gpt54_blind_summary.json",
  "results_md": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_gpt54_blind_results.md",
  "prompt_previews": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_gpt54_blind_prompt_previews"
}
```
