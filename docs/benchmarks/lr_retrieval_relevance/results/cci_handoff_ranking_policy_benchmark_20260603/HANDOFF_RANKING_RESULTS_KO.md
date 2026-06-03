# Handoff Ranking Policy Benchmark 결과

- 생성 시각(UTC): 2026-06-03T18:18:27Z
- active policies: baseline_current, bucket_lr_coverage, bucket_lr_coverage_journal_tiebreak
- direct quota policy: 이번 실행에서는 제외. `available_direct_count`와 `selected_direct_count`만 추적.
- excluded buckets: `disease_only_background`, `rejected_weak_evidence`

## 정책별 요약

| policy | 후보 파일 | 평균 선택 | direct 평균 | context 평균 | LR coverage | gene | pathway | celltype | journal | receptor HHI | pathway HHI | leakage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_current | 1 | 40.00 | 2.00 | 38.00 | 100.00% | 44.68% | 85.71% | 53.85% | 0.500 | 0.055 | 0.238 | 0 |
| bucket_lr_coverage | 1 | 40.00 | 2.00 | 38.00 | 100.00% | 42.55% | 85.71% | 53.85% | 0.500 | 0.057 | 0.232 | 0 |
| bucket_lr_coverage_journal_tiebreak | 1 | 40.00 | 2.00 | 38.00 | 100.00% | 42.55% | 85.71% | 53.85% | 0.500 | 0.057 | 0.232 | 0 |

## 정책 간 overlap

| policy A | policy B | overlap | A only | B only | Jaccard |
| --- | --- | ---: | ---: | ---: | ---: |
| baseline_current | bucket_lr_coverage | 27 | 13 | 13 | 0.509 |
| baseline_current | bucket_lr_coverage_journal_tiebreak | 27 | 13 | 13 | 0.509 |
| bucket_lr_coverage | bucket_lr_coverage_journal_tiebreak | 40 | 0 | 0 | 1.000 |

## 해석

- coverage 관점 최고 정책은 `baseline_current`입니다. LR/gene/pathway/celltype coverage를 우선 비교하고, leakage가 0인지 확인했습니다.
- journal quality 평균은 모든 active policy에서 0.500으로 같았습니다. 따라서 이번 후보에서는 journal tie-break가 독립적인 품질 신호를 제공하지 않았습니다.
- direct 후보는 평균 2.00개였고 coverage-aware policy가 평균 2.00개를 선택했습니다. 이번 실행에서는 direct under-selection이 관찰되지 않았으므로 direct quota policy는 후속 optional로 유지합니다.
- `bucket_lr_coverage`는 baseline 대비 pathway HHI를 0.238에서 0.232로 낮췄지만, gene coverage는 44.68%에서 42.55%로 낮았습니다.
- journal tie-break policy는 `bucket_lr_coverage`와 동일한 40편을 선택했습니다. 현재 후보의 journal_quality 값이 구분력을 거의 제공하지 않아 별도 이득을 보이지 않았습니다.
- `disease_only_background`와 `rejected_weak_evidence`는 모든 policy의 handoff에서 제외되어야 하며, leakage 열이 그 중단 조건을 검증합니다.
- direct quota는 아직 실행하지 않았습니다. direct 후보가 충분히 있는데도 coverage-aware 정책에서 direct 선택 수가 줄어드는 경우에만 별도 후속 PR로 다루는 것이 좋습니다.

## 산출물

- `ranking_policy_summary.csv`: policy 단위 집계
- `ranking_policy_percase.csv`: 후보 파일별 policy metric
- `ranking_policy_overlap.csv`: policy pair overlap과 Jaccard
- `selected_papers/<candidate>/<policy>/papers.json`: INTERPRETER handoff 형식의 cap 적용 선택 결과
