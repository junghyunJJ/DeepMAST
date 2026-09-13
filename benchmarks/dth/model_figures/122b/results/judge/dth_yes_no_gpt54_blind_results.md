# DTH Yes/No Blind Judge

- Status: `judged`
- Source summary: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/cumulative_valid_only_summary_for_20each_target.json`
- Pair count: 20
- Judge: `openai:gpt-5.4`
- Tie threshold: 2.0

## Blind Result

| condition | wins | win rate | mean score |
| --- | ---: | ---: | ---: |
| DTH_yes | 15 | 75.00% | 17.30 |
| DTH_no | 2 | 10.00% | 13.55 |
| tie | 3 | 15.00% | - |

- Non-tie comparisons: 17
- Sign-test p-value, yes vs no: 0.00235
- Mean score delta, yes minus no: 3.75
- Judge errors: 0
- Input/output tokens: 61937 / 12156
- Estimated total cost USD: 0.539492

## Output Files

```json
{
  "pair_panel": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_gpt54_blind_pair_panel.jsonl",
  "judge_rows": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_gpt54_blind_judge_rows.jsonl",
  "summary": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_gpt54_blind_summary.json",
  "results_md": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_gpt54_blind_results.md",
  "prompt_previews": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_gpt54_blind_prompt_previews"
}
```
