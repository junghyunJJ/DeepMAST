# Figure X. Outcomes and documented functions of report-level guardrails

**(A)** Final outcomes of 20 Guardrail ON and 20 Guardrail OFF executions using Qwen3.5-122B with SNI enabled on the same breast cancer dataset. Categories are mutually exclusive: complete reports passing the predefined validation checks, complete reports with at least one detected hard error, and runs blocked by the report guardrail. Counts and percentages use all 20 executions per condition. The ON/OFF contrast summarizes the combined pipeline outcome and does not isolate the causal contribution of correction or blocking. **(B)** Illustrative numerical correction in ON run 25–BA: the reported LAMA5–ITGB4 combined score changed from 0.8060 to 0.7171, matching the source-data value rounded to four decimal places. This is a single documented repair, not an aggregate correction-rate estimate. **(C)** The two observed ON output blocks. Each run terminated with one reported residual hard error in Part 3; neither synthesis Markdown nor the final HTML report was produced. The analysis evaluates predefined reporting and consistency requirements rather than overall scientific accuracy. ON controls were generated earlier than OFF runs.

## Files and reproduction

PDF and SVG are vector exports; SVG retains editable text. PNG is 300 dpi. The figure is 180 × 140 mm. No significance tests or uncertainty intervals are implied. The numeric repair is illustrative.

`figure_source_data.csv` provides plotted values and original source paths. `table_s1_per_run.csv` contains all 40 runs.

Reproduce from the repository root:

```bash
.venv/bin/python scripts/plot_sni_guardrail_publication.py
```
