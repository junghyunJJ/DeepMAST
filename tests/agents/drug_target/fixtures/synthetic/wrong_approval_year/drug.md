# Synthetic Drug Report — wrong_approval_year fixture

### FOO — Classification: validated_target | Priority: high

Ghostacin received FDA approval in 2020 for treatment of FOO-related disease.

DRUG_Y was approved in 2015 for the treatment of test indication.

DRUG_X was approved in 2018 for treatment of test indication [source: first_approval].

The data for approval years is not available in source data for some compounds.

| Drug | Approval Year | Phase |
|------|---------------|-------|
| DRUG_X | 2018 | 4 |

```python
# Approval year in code block — must not fire
approval = {"drug": "Ghostacin", "year": 2020}
```
