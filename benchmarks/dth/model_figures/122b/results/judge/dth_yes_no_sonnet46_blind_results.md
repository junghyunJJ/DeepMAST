# DTH Yes/No Blind Judge

- Status: `judged`
- Source summary: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/cumulative_valid_only_summary_for_20each_target.json`
- Pair count: 20
- Judge: `anthropic:claude-sonnet-4-6`
- Tie threshold: 2.0

## Blind Result

| condition | wins | win rate | mean score |
| --- | ---: | ---: | ---: |
| DTH_yes | 10 | 50.00% | 17.10 |
| DTH_no | 5 | 25.00% | 15.90 |
| tie | 5 | 25.00% | - |

- Non-tie comparisons: 15
- Sign-test p-value, yes vs no: 0.3018
- Mean score delta, yes minus no: 1.20
- Judge errors: 0
- Input/output tokens: 79778 / 17977
- Estimated total cost USD: 0.508989

## Output Files

```json
{
  "pair_panel": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_sonnet46_blind_pair_panel.jsonl",
  "judge_rows": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_sonnet46_blind_judge_rows.jsonl",
  "summary": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_sonnet46_blind_summary.json",
  "results_md": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_sonnet46_blind_results.md",
  "prompt_previews": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/122b/results/judge/dth_yes_no_sonnet46_blind_prompt_previews"
}
```
