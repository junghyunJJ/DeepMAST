# 저장 기록으로 확인한 가드레일의 교정·차단 사례

이 문서는 원본 보고서를 수정하지 않고, 과거 Guardrail ON 실행의 before/after와 오류 기록을 연결한 것이다. 효과의 전체 크기는 같은 폴더의 comparison.md에서 확인한다.

수정 전후를 비교할 수 있는 78개 Markdown 파일쌍에서 제목 목록과 순서는 모두 동일했다. 수정 후/전 문자 수 비율의 중앙값은 99.83%, 최솟값은 93.87%였다. 이는 문서 구조와 분량에 대한 확인이며, 모든 문장의 의미가 보존됐다는 독립 평가를 뜻하지 않는다.

## 교정 사례 1: 원자료와 다른 수치 수정

ON Pair 25 BA의 Part 2에서 `LAMA5–ITGB4`의 combined score가 **0.8060 → 0.7171**로 바뀌었다. 기록된 규칙은 `lr_metric_value_mismatch`이며, 원자료 `sig_liana.csv`의 combinedscore 값에 맞춘 변경이다.

- [수정 전 Part 2:13](../inputs/evidence/pair-25-BA/part2_before.md#L13)
- [수정 후 Part 2:13](../inputs/evidence/pair-25-BA/part2_after.md#L13)
- [초기 오류 기록](../inputs/evidence/pair-25-BA/report_validation_initial.json)
- [원자료](../inputs/evidence/pair-25-BA/sig_liana.csv)

## 교정 사례 2: Part 3의 역할 범위에 맞게 문장 수정

같은 실행에서 `part3_therapeutic_spillover`가 표시된 문장은 다음과 같이 변경됐다.

> Before: This spatial information could inform targeted therapeutic strategies that account for microenvironmental heterogeneity.

> After: This spatial information characterizes microenvironmental heterogeneity in L-R interactions.

이것은 Part 3를 공간·통계 해석으로 제한하고 치료 해석을 Part 4에 배치하는 사전 규칙의 적용 사례다. 독립적인 생물학적 참·거짓 판정으로 해석하지 않는다.

- [수정 전 Part 3:84](../inputs/evidence/pair-25-BA/part3_before.md#L84)
- [수정 후 Part 3:84](../inputs/evidence/pair-25-BA/part3_after.md#L84)

## 출력 차단 사례

| ON 실행 | 최종 남은 오류 | 중단 위치 | 결과 |
|---|---|---|---|
| Pair 16 BA | factor_pathway_direction_mismatch 1개 | Part 3 guardrail | synthesis.md와 최종 HTML 없음 |
| Pair 17 BA | inline_citation_overclaimed 1개 | Part 3 guardrail | synthesis.md와 최종 HTML 없음 |

두 실행 모두 stderr에 `Report guardrail failed with 1 hard error(s)`가 남았으며, timing.json에는 Part 3 종료 코드 1 이후 Reporter 실행이 없다.

- [Pair 16 BA 차단 로그](../inputs/evidence/pair-16-BA/part3.stderr.txt)
- [Pair 16 BA 최종 오류](../inputs/evidence/pair-16-BA/report_validation_final.json)
- [Pair 17 BA 차단 로그](../inputs/evidence/pair-17-BA/part3.stderr.txt)
- [Pair 17 BA 최종 오류](../inputs/evidence/pair-17-BA/report_validation_final.json)

반면 OFF 실행의 missing RAG audit 표시는 이미 생성된 HTML을 차단한 것이 아니다. 출력 차단 횟수에 포함하지 않는다.
