# qwen3.5:397b-cloud DTH Yes vs No cumulative summary

- Current stamp: `ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911`
- Excluded initial failed stamp: `ollama_cloud_qwen397b_dth_minimal_v120_2each_20260619_193457`
- Target: 20 valid runs per condition
- Status: complete: 20 valid DTH_yes and 20 valid DTH_no

## Counts
| condition | prior valid | current valid | cumulative valid / 20 | remaining valid | attempted rows | failed rows | DTH activation in valid | fallback used in valid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DTH_yes | 11 | 9 | 20/20 | 0 | 20 | 0 | 20 | 0 |
| DTH_no | 11 | 9 | 20/20 | 0 | 20 | 0 | 0 | 0 |

## Valid-only metrics
| condition | mean evidence coverage | median evidence coverage | mean hypotheses | mean evidence refs | retry attempts distribution | mean Not yet established | mean Stage1 mentions | mean Stage3 mentions | mean OpenTargets mentions | causal-language mean |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| DTH_yes | 78.53 | 76.47 | 6.0 | 21.0 | {0: 7, 1: 8, 2: 5} | 10.3 | 68.6 | 29.35 | 5.65 | 1.4 |
| DTH_no | 74.412 | 76.47 | 5.8 | 20.35 | {0: 5, 1: 5, 2: 5, 3: 5} | 0.0 | 56.75 | 21.75 | 0.9 | 3.6 |

## Current batch status
- DTH_yes: valid 9/9, failed 0/9, remaining-to-current-target 0; coverage values [76.47, 76.47, 82.35, 70.59, 76.47, 70.59, 88.24, 88.24, 76.47]
- DTH_no: valid 9/9, failed 0/9, remaining-to-current-target 0; coverage values [76.47, 76.47, 76.47, 70.59, 82.35, 76.47, 70.59, 76.47, 76.47]

## Interpretation
- DTH_yes and DTH_no are now both complete at 20 valid runs.
- DTH_yes activated `drug-target-hypothesis` in every valid run; DTH_no activated it in no valid runs; host fallback was never used.
- Valid-only comparison still favors DTH_yes: higher mean evidence coverage, more explicit Stage1/Stage3/OpenTargets boundary handling, much more uncertainty framing, and lower causal overstatement.

## Failed rows still present
- None in included final valid set.
