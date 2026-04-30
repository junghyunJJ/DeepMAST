# Synthetic Drug Report — ungrounded_mechanism fixture

### FOO — Classification: validated_target | Priority: high

DRUG_X inhibits FOO kinase activity through competitive ATP-binding site occupancy.

DRUG_Y inhibits FOO signaling in preclinical models of test indication.

DRUG_X inhibits FOO kinase activity [source: mechanism_of_action].

The mechanism of DRUG_Z is not available in source data.

| Drug | MoA | Phase |
|------|-----|-------|
| DRUG_X | kinase inhibitor | 4 |
| DRUG_Y | unknown | 2 |

```python
# Mechanism verb in code block — must not fire
result = {"drug": "DRUG_Y", "action": "inhibits"}
```
