# Selective7 Significance Summary

Endpoint: repeat-level F1, Precision, Recall, and Specificity. Validation-failed runs receive zero metric credit.

## Friedman Omnibus

| dataset | model | metric | n blocks | statistic | df | p |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Breast cancer | 122B | F1 | 10 | NaN | 2 | NA |
| Breast cancer | 122B | Precision | 10 | NaN | 2 | NA |
| Breast cancer | 122B | Recall | 10 | NaN | 2 | NA |
| Breast cancer | 122B | Specificity | 10 | NaN | 2 | NA |
| Breast cancer | 35B | F1 | 10 | 14.824 | 2 | 6.041e-04 |
| Breast cancer | 35B | Precision | 10 | 2.000 | 2 | 3.679e-01 |
| Breast cancer | 35B | Recall | 10 | 14.824 | 2 | 6.041e-04 |
| Breast cancer | 35B | Specificity | 10 | NaN | 2 | NA |
| Lung/IPF | 122B | F1 | 10 | 11.185 | 2 | 3.725e-03 |
| Lung/IPF | 122B | Precision | 10 | 5.333 | 2 | 6.948e-02 |
| Lung/IPF | 122B | Recall | 10 | 11.185 | 2 | 3.725e-03 |
| Lung/IPF | 122B | Specificity | 10 | 2.000 | 2 | 3.679e-01 |
| Lung/IPF | 35B | F1 | 20 | 23.310 | 2 | 8.674e-06 |
| Lung/IPF | 35B | Precision | 20 | 1.750 | 2 | 4.169e-01 |
| Lung/IPF | 35B | Recall | 20 | 23.310 | 2 | 8.674e-06 |
| Lung/IPF | 35B | Specificity | 20 | 1.750 | 2 | 4.169e-01 |

## Holm-Adjusted Paired Wilcoxon Post-Hoc

| dataset | model | metric | comparison | raw p | Holm p | label |
| --- | --- | --- | --- | ---: | ---: | --- |
| Breast cancer | 122B | F1 | Governor vs Activator | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | F1 | Governor vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | F1 | Activator vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Precision | Governor vs Activator | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Precision | Governor vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Precision | Activator vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Recall | Governor vs Activator | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Recall | Governor vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Recall | Activator vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Specificity | Governor vs Activator | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Specificity | Governor vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 122B | Specificity | Activator vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 35B | F1 | Governor vs Activator | 1.028e-02 | 2.056e-02 | * |
| Breast cancer | 35B | F1 | Governor vs Middleware only | 4.237e-03 | 1.271e-02 | * |
| Breast cancer | 35B | F1 | Activator vs Middleware only | 9.161e-01 | 9.161e-01 | ns |
| Breast cancer | 35B | Precision | Governor vs Activator | 3.458e-01 | 1.000e+00 | ns |
| Breast cancer | 35B | Precision | Governor vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 35B | Precision | Activator vs Middleware only | 7.728e-01 | 1.000e+00 | ns |
| Breast cancer | 35B | Recall | Governor vs Activator | 1.028e-02 | 2.056e-02 | * |
| Breast cancer | 35B | Recall | Governor vs Middleware only | 4.237e-03 | 1.271e-02 | * |
| Breast cancer | 35B | Recall | Activator vs Middleware only | 9.153e-01 | 9.153e-01 | ns |
| Breast cancer | 35B | Specificity | Governor vs Activator | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 35B | Specificity | Governor vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Breast cancer | 35B | Specificity | Activator vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Lung/IPF | 122B | F1 | Governor vs Activator | 3.054e-02 | 6.109e-02 | ns |
| Lung/IPF | 122B | F1 | Governor vs Middleware only | 1.198e-02 | 3.593e-02 | * |
| Lung/IPF | 122B | F1 | Activator vs Middleware only | 7.835e-01 | 7.835e-01 | ns |
| Lung/IPF | 122B | Precision | Governor vs Activator | 7.186e-02 | 2.156e-01 | ns |
| Lung/IPF | 122B | Precision | Governor vs Middleware only | 7.186e-02 | 2.156e-01 | ns |
| Lung/IPF | 122B | Precision | Activator vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Lung/IPF | 122B | Recall | Governor vs Activator | 3.054e-02 | 6.109e-02 | ns |
| Lung/IPF | 122B | Recall | Governor vs Middleware only | 1.198e-02 | 3.593e-02 | * |
| Lung/IPF | 122B | Recall | Activator vs Middleware only | 7.835e-01 | 7.835e-01 | ns |
| Lung/IPF | 122B | Specificity | Governor vs Activator | 1.000e+00 | 1.000e+00 | ns |
| Lung/IPF | 122B | Specificity | Governor vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Lung/IPF | 122B | Specificity | Activator vs Middleware only | 1.000e+00 | 1.000e+00 | ns |
| Lung/IPF | 35B | F1 | Governor vs Activator | 1.844e-03 | 5.533e-03 | ** |
| Lung/IPF | 35B | F1 | Governor vs Middleware only | 1.942e-03 | 5.533e-03 | ** |
| Lung/IPF | 35B | F1 | Activator vs Middleware only | 7.768e-01 | 7.768e-01 | ns |
| Lung/IPF | 35B | Precision | Governor vs Activator | 2.330e-01 | 6.991e-01 | ns |
| Lung/IPF | 35B | Precision | Governor vs Middleware only | 4.237e-01 | 8.474e-01 | ns |
| Lung/IPF | 35B | Precision | Activator vs Middleware only | 7.768e-01 | 8.474e-01 | ns |
| Lung/IPF | 35B | Recall | Governor vs Activator | 1.844e-03 | 5.533e-03 | ** |
| Lung/IPF | 35B | Recall | Governor vs Middleware only | 1.942e-03 | 5.533e-03 | ** |
| Lung/IPF | 35B | Recall | Activator vs Middleware only | 7.768e-01 | 7.768e-01 | ns |
| Lung/IPF | 35B | Specificity | Governor vs Activator | 2.330e-01 | 6.991e-01 | ns |
| Lung/IPF | 35B | Specificity | Governor vs Middleware only | 4.237e-01 | 8.474e-01 | ns |
| Lung/IPF | 35B | Specificity | Activator vs Middleware only | 7.768e-01 | 8.474e-01 | ns |
