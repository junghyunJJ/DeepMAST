# DTH Yes/No Blind Judge

- Status: `judged`
- Source summary: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/cumulative_valid_only_summary_for_20each_target.json`
- Pair count: 20
- Judge: `ollama:glm-5.2:cloud`
- Tie threshold: 2.0

## Blind Result

| condition | wins | win rate | mean score |
| --- | ---: | ---: | ---: |
| DTH_yes | 15 | 75.00% | 19.65 |
| DTH_no | 2 | 10.00% | 16.60 |
| tie | 3 | 15.00% | - |

- Non-tie comparisons: 17
- Sign-test p-value, yes vs no: 0.00235
- Mean score delta, yes minus no: 3.05
- Judge errors: 0
- Input/output tokens: 64525 / 27663
- Estimated total cost USD: None

## Output Files

```json
{
  "pair_panel": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_glm52_cloud_blind_pair_panel.jsonl",
  "judge_rows": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_glm52_cloud_blind_judge_rows.jsonl",
  "summary": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_glm52_cloud_blind_summary.json",
  "results_md": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_glm52_cloud_blind_results.md",
  "prompt_previews": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/hypothesis-main-run-20260613/docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/dth_yes_no_glm52_cloud_blind_prompt_previews"
}
```
