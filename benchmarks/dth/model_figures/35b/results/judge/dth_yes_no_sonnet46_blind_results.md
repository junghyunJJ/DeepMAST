# DTH Yes/No Blind Judge

- Status: `judged`
- Source summary: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/cumulative_valid_only_summary_for_20each_target.json`
- Pair count: 20
- Judge: `anthropic:claude-sonnet-4-6`
- Tie threshold: 2.0

## Blind Result

| condition | wins | win rate | mean score |
| --- | ---: | ---: | ---: |
| DTH_yes | 7 | 35.00% | 15.30 |
| DTH_no | 4 | 20.00% | 15.15 |
| tie | 9 | 45.00% | - |

- Non-tie comparisons: 11
- Sign-test p-value, yes vs no: 0.5488
- Mean score delta, yes minus no: 0.15
- Judge errors: 0
- Input/output tokens: 78651 / 17578
- Estimated total cost USD: 0.499623

## Output Files

```json
{
  "pair_panel": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_sonnet46_blind_pair_panel.jsonl",
  "judge_rows": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_sonnet46_blind_judge_rows.jsonl",
  "summary": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_sonnet46_blind_summary.json",
  "results_md": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_sonnet46_blind_results.md",
  "prompt_previews": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_sonnet46_blind_prompt_previews"
}
```
