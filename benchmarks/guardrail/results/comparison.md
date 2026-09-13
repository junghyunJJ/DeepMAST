# SNI guardrail ON/OFF post-hoc 비교

생성 시각: 2026-09-08T06:56:29.482801+00:00

주요 지표는 arm당 계획된 20회 전체를 분모로 둔다. 미완료 보고서, 생성 실패, 평가 실패는 통과로 세지 않는다.
unknown이 남아 있으면 범위는 관측 통과부터 관측 통과+unknown까지의 정확한 경계이며 신뢰구간이 아니다.

| Metric | ON | OFF |
|---|---:|---:|
| Complete reports | 18/20 | 20/20 |
| Primary passes | 16/20 | 0/20 |
| Unknown bounds | 16/20 to 16/20 | 0/20 to 0/20 |
| Known invalid outputs (/20) | 2/20 | 20/20 |
| Blocked reports | 2 | 0 |
| Unknown | 0 | 0 |
| Mean generation minutes | 171.8 | 37.2 |

## Historic ON correction summary

- Initial errors: 341 (deterministic 189, semantic 152)
- Final staged counter: 2
- Repair passes: ordinary 61, terminal 5
- Changed sections/claims: 339 / 23
- Before/after Markdown pairs: 78, different 58
- Examples: [repair_examples.md](repair_examples.md)

## Known content error codes

- ON: inline_citation_overclaimed: 2
- OFF: factor_pathway_direction_mismatch: 5, lr_metric_value_mismatch: 16, part3_therapeutic_spillover: 157, unsupported_pathway_factor_significance: 23

## 해석 한계

- 이 평가는 사전 정의된 정책 준수 여부이며 전체 과학적 진실성 판정이 아니다.
- ON 과거 실행과 OFF 실행은 달력 시간이 달라 historical calendar confound가 남는다.
- 모든 반복은 하나의 BC dataset에서 나온 실행 반복이며 독립 생물학 표본이 아니다.
- missing RAG audit만 있고 4개 Markdown과 HTML이 완성된 경우는 생성 차단이 아니라 audit gap으로 분리했다.
- 내용 hard error가 확인되면 0-error 주 지표의 불합격은 확정된다. 나머지 의미 검사를 생략한 경우 evaluation_complete=false이며, 표시된 오류 수는 확인된 최소치다.
- 교정 표의 초기·최종 오류는 과거 실행의 단계별 검출 카운터다. 고유한 오류 수나 수정된 문장 수가 아니며, 이번 공통 사후 판정과 구분해야 한다.
- 평가 복구는 기존 성공 체크포인트를 재사용했다. 닫힌 이벤트 루프 재사용을 고쳤으며, 도구 응답 형식이 깨진 경우에만 같은 모델·근거·분류 기준의 JSON 응답으로 복구했다.
