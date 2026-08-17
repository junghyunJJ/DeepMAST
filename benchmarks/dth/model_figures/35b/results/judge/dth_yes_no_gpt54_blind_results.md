# DTH Yes/No Blind Judge

- Status: `judged`
- Source summary: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/cumulative_valid_only_summary_for_20each_target.json`
- Pair count: 20
- Judge: `openai:gpt-5.4`
- Tie threshold: 2.0

## Blind Result

| condition | wins | win rate | mean score |
| --- | ---: | ---: | ---: |
| DTH_yes | 14 | 70.00% | 16.70 |
| DTH_no | 1 | 5.00% | 12.60 |
| tie | 5 | 25.00% | - |

- Non-tie comparisons: 15
- Sign-test p-value, yes vs no: 0.0009766
- Mean score delta, yes minus no: 4.10
- Judge errors: 0
- Input/output tokens: 61853 / 11566
- Estimated total cost USD: 0.524996

## Output Files

```json
{
  "pair_panel": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_gpt54_blind_pair_panel.jsonl",
  "judge_rows": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_gpt54_blind_judge_rows.jsonl",
  "summary": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_gpt54_blind_summary.json",
  "results_md": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_gpt54_blind_results.md",
  "prompt_previews": "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/benchmarks/dth/model_figures/35b/results/judge/dth_yes_no_gpt54_blind_prompt_previews"
}
```
