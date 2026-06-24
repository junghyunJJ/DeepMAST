# DTH Yes/No Blind Judge

- Status: `judged`
- Source summary: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/cumulative_valid_only_summary_for_20each_target.json`
- Pair count: 20
- Judge: `anthropic:claude-sonnet-4-6`
- Tie threshold: 2.0

## Blind Result

| condition | wins | win rate | mean score |
| --- | ---: | ---: | ---: |
| DTH_yes | 11 | 55.00% | 18.05 |
| DTH_no | 5 | 25.00% | 16.25 |
| tie | 4 | 20.00% | - |

- Non-tie comparisons: 16
- Sign-test p-value, yes vs no: 0.2101
- Mean score delta, yes minus no: 1.80
- Judge errors: 0
- Input/output tokens: 82375 / 18442
- Estimated total cost USD: 0.523755

## Output Files

```json
{
  "pair_panel": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_sonnet46_blind_pair_panel.jsonl",
  "judge_rows": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_sonnet46_blind_judge_rows.jsonl",
  "summary": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_sonnet46_blind_summary.json",
  "results_md": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_sonnet46_blind_results.md",
  "prompt_previews": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_sonnet46_blind_prompt_previews"
}
```
