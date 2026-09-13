# SNI Guardrail ON/OFF: 교정 효과와 출력 차단 효과

## 짧은 종합 요약

기존 SNI 실행 기록에서 가드레일이 **같은 ON 보고서의 잘못된 수치·방향 표현·파트 범위를 고친 사례**와, **오류가 남은 ON 실행 2건의 최종 출력을 중단한 사례**를 각각 확인했다. 두 역할을 포함한 종합 결과는 공통 검사 통과 **ON 16/20(80%), OFF 0/20(0%)**다. 완성됐으나 내용 hard error가 확인된 보고서는 ON 2/20, OFF 20/20이다. 이 차이 전체를 차단 효과나 순수 교정 효과로 귀속할 수는 없다.

분석 단위는 동일 BC 데이터셋의 실행 반복이다. Pair 16–25 × AB/BA의 기존 ON 20회와 별도로 생성한 OFF 20회, 총 40회를 포함하며 각 조건의 주 지표 분모는 항상 전체 20회다. 20개의 독립 데이터셋이나 환자가 아니다. **OFF 보고서는 ON 보고서의 수정 전 초안이 아니다.**

최종 판정은 복구 폴더의 [comparison.json](../comparison.json), [comparison.csv](../comparison.csv), [개별 assessments](../assessments/)를 사용했다. 원본은 [manifest.json](../../metadata/manifest.json)의 `rows[].data_dir`를 따라 확인했다. [기존 요약](../comparison.md), [교정·차단 사례](../../metadata/repair_examples.md), [복구 방법](../../metadata/recovery_method.md), [검증 기록](../../metadata/verification.json)도 교차 확인했다. 제시된 확정 집계와 불일치는 없었다.

## 1. 교정 효과: 동일 ON 실행 안에서 무엇이 바뀌었는가

### 근거와 확인 범위

각 ON 실행의 `before/` → `diffs/` → `after/`를 연결하고, `report_validation_initial.json` 및 의미 검사 기록과 `parts_guardrail_result.json`·`synthesis_guardrail_result.json`의 최종 상태를 대조했다. 비교 가능한 Markdown은 **78쌍(Part 1–3 60쌍 + synthesis 18쌍)**이며, **58쌍의 내용이 변경**됐다. **78쌍 모두 제목 목록과 순서가 유지**됐다. 이는 파일 변경과 문서 구조 보존의 확인이며, 모든 변경 문장이 오류 교정이었거나 모든 의미가 보존됐음을 뜻하지 않는다.

과거 ON 가드레일의 단계별 카운터를 원본 결과 JSON에서 다시 합산하면 다음과 같다.

| 생성 시점 검사 단계 | 초기 deterministic | 초기 semantic | 초기 합계 | 최종 잔여 |
|---|---:|---:|---:|---:|
| Parts 가드레일 | 187 | 133 | 320 | 2 |
| Synthesis 가드레일 | 2 | 19 | 21 | 0 |
| 합계 | **189** | **152** | **341** | **2** |

이들은 단계별 검출 카운터이며 동일 오류나 문장이 여러 단계에서 다뤄질 수 있다. 따라서 **‘고유 오류 339개 교정’ 또는 ‘교정률 99.4%’로 계산하지 않는다.** 기존 요약의 `changed_sections=339`, `changed_claims=23`, 일반 repair 61회·terminal repair 5회도 작업 카운터이며 고유 교정 건수가 아니다. 실행별 원본 경로와 카운터는 [실행별 표](two_effects_run_table.csv)의 교정 근거에 연결했다.

### 오류 종류별 대표 사례

**A. 수치 불일치 — `lr_metric_value_mismatch`, ON Pair 25 BA / Part 2**

- 수정 전: `LAMA5-ITGB4 ... combined score 0.8060`
- 수정 후: `LAMA5-ITGB4 ... combined score 0.7171`
- `report_validation_initial.json`은 원자료 `sig_liana.csv`의 LAMA5–ITGB4 `combinedscore=0.7171`을 근거로 기록한다. CSV의 실제 combinedscore는 `0.7170684216386449`이며, 수정 전 값 `0.8060`은 같은 행의 별도 지표 `genept_score=0.8060464169291524`와 일치한다. 동일 실행의 diff와 수정 후 문장에서 combinedscore에 맞게 바뀐 것을 확인했다.

근거: [수정 전 Part 2](../../inputs/evidence/pair-25-BA/part2_before.md#L13), [수정 후 Part 2](../../inputs/evidence/pair-25-BA/part2_after.md#L13), [초기 오류와 치환값](../../inputs/evidence/pair-25-BA/report_validation_initial.json), [원자료 sig_liana.csv](../../inputs/evidence/pair-25-BA/sig_liana.csv).

**B. 경로 방향 표현 불일치 — `factor_pathway_direction_mismatch`, ON Pair 19 BA / Part 2**

- 수정 전: `EGFR pathway enrichment in Factor3 (estimate = -2.897, p = 0.0038)`
- 수정 후: `EGFR pathway depletion in Factor3 (estimate = -2.897, p = 0.0038)`
- 음수 estimate에 맞춰 `enrichment`를 `depletion`으로 수정했다. 이는 저장된 경로–factor 값과 방향 표현의 정합성을 고친 사례다. 주변 문장 전체의 과학적 타당성을 별도로 입증한 것은 아니다.

근거: [수정 전 Part 2](../../inputs/evidence/pair-19-BA/part2_before.md#L35), [수정 후 Part 2](../../inputs/evidence/pair-19-BA/part2_after.md#L35), [초기 검출](../../inputs/evidence/pair-19-BA/report_validation_initial.json), [원자료 경로–factor 표](../../inputs/evidence/pair-19-BA/sig_liana_pathway_factor.csv).

**C. 파트 범위 위반 — `part3_therapeutic_spillover`, ON Pair 25 BA / Part 3**

> 수정 전: This spatial information could inform targeted therapeutic strategies that account for microenvironmental heterogeneity.

> 수정 후: This spatial information characterizes microenvironmental heterogeneity in L-R interactions.

치료 전략을 제안하던 문장을 공간적 L-R 이질성을 기술하는 문장으로 바꿨다. Part 3은 공간·통계 해석, 치료 해석은 Part 4라는 사전 정의된 범위 규칙을 적용한 사례다. 치료 해석의 생물학적 참·거짓을 판정한 사례로 해석하지 않는다.

근거: [수정 전 Part 3](../../inputs/evidence/pair-25-BA/part3_before.md#L84), [수정 후 Part 3](../../inputs/evidence/pair-25-BA/part3_after.md#L84), [초기 범위 위반 기록](../../inputs/evidence/pair-25-BA/report_validation_initial.json).

세 사례가 속한 Pair 25 BA와 Pair 19 BA는 각 실행의 과거 Parts 가드레일에서 `status=passed`, `final_error_count=0`이며, 이번 공통 사후 검사에서도 각각 합격했다. 과거 판정 근거는 [Pair 25 BA 가드레일 결과](../../inputs/evidence/pair-25-BA/parts_guardrail_result.json), [Pair 25 BA 최종 검사](../../inputs/evidence/pair-25-BA/report_validation_final.json), [Pair 19 BA 가드레일 결과](../../inputs/evidence/pair-19-BA/parts_guardrail_result.json), [Pair 19 BA 최종 검사](../../inputs/evidence/pair-19-BA/report_validation_final.json)이고, 공통 사후 판정은 [Pair 25 BA assessment](../assessments/pair-25-BA-on.json), [Pair 19 BA assessment](../assessments/pair-19-BA-on.json)이다.

### 교정 효과의 해석

저장된 오류 기록과 실제 문장·수치 변경이 연결되므로 교정이 작동한 구체적 사례는 확인된다. 다만 초기 초안을 이번 공통 기준으로 다시 평가한 실험이 아니므로 **교정만으로 불합격에서 합격으로 전환된 보고서 수와 고유 오류별 교정률은 현재 자료로 확인 불가**다. 최종 합격 16건을 곧바로 ‘교정으로 구제한 보고서 16개’라고 부르지 않는다.

과거 가드레일 판정과 이번 공통 사후 판정도 다르다. ON의 완성된 18건은 과거 가드레일 최종 잔여 카운터가 0이지만, 이번 검사에서는 **Pair 17 AB의 synthesis와 Pair 24 BA의 Part 3에서 `inline_citation_overclaimed`가 각각 1개** 확인됐다. 따라서 과거 ‘잔여 0’은 이번 공통 검사 합격이나 독립적인 과학적 정확성을 보장하지 않는다. 이는 [Pair 17 AB assessment](../assessments/pair-17-AB-on.json), [Pair 24 BA assessment](../assessments/pair-24-BA-on.json)에 기록된 판정이다.

## 2. 출력 차단 효과: 어떤 잔여 오류 때문에 출력이 중단됐는가

| ON 실행 | 과거 최종 가드레일의 잔여 오류 | 오류가 기록된 보고서 위치 | 실제 중단 위치 | 최종 출력 |
|---|---|---|---|---|
| Pair 16 BA | `factor_pathway_direction_mismatch` 1개 | Part 2, Analysis 2-8의 Factor3–Estrogen 방향 표현 | Part 3 가드레일 | synthesis.md·최종 HTML 없음 |
| Pair 17 BA | `inline_citation_overclaimed` 1개 | Part 1, Analysis 1-2의 stromal cell–EGFR 문장 | Part 3 가드레일 | synthesis.md·최종 HTML 없음 |

**오류가 적힌 파트와 실행이 중단된 단계는 다르다.** 두 사례 모두 Part 3 단계에서 앞선 파트까지 검사한 가드레일이 중단 원인이다.

Pair 16 BA에서는 `report_validation_final.json`에 Factor3–Estrogen의 음수 estimate와 표현 불일치 오류가 남았다. `parts_guardrail_result.json`의 `status=failed`, `final_error_count=1`과 stderr의 `Report guardrail failed with 1 hard error(s)`가 연결된다. `timing.json`은 Part 3 `return_code=1`에서 끝나고 Reporter 단계가 없으며, 원본 디렉터리에도 synthesis와 HTML이 없다.

근거: [Pair 16 BA 잔여 오류](../../inputs/evidence/pair-16-BA/report_validation_final.json), [가드레일 실패 결과](../../inputs/evidence/pair-16-BA/parts_guardrail_result.json), [중단 stderr](../../inputs/evidence/pair-16-BA/part3.stderr.txt), [실행 단계 기록](../../inputs/evidence/pair-16-BA/timing.json), [산출물 결손 assessment](../assessments/pair-16-BA-on.json).

Pair 17 BA에서는 stromal cell의 EGFR transactivation 주장을 인용 근거가 지지하지 못한다는 `inline_citation_overclaimed` 기록이 최종 검사와 terminal 검사에 남았다. 최종 hard error 1개 → 같은 가드레일 실패 메시지 → Part 3 종료 코드 1 → Reporter 미실행 → synthesis·HTML 부재의 연결을 확인했다.

근거: [Pair 17 BA 잔여 오류](../../inputs/evidence/pair-17-BA/report_validation_final.json), [terminal 검사](../../inputs/evidence/pair-17-BA/report_validation_terminal.json), [가드레일 실패 결과](../../inputs/evidence/pair-17-BA/parts_guardrail_result.json), [중단 stderr](../../inputs/evidence/pair-17-BA/part3.stderr.txt), [실행 단계 기록](../../inputs/evidence/pair-17-BA/timing.json), [산출물 결손 assessment](../assessments/pair-17-BA-on.json).

따라서 직접 확인된 **최종 출력 차단은 ON 2/20(10%), OFF 0/20(0%)**다. 이 두 ON 실행에서는 Part 1–3 등의 중간 파일이 남아 있으므로 ‘아무 보고서도 생성되지 않음’이 아니라 ‘오류가 남아 synthesis·최종 HTML 출력이 중단됨’으로 표현한다. 이 2건의 공통 사후 `hard_error_count=null`은 0이 아니다. 완성 보고서의 공통 내용 오류 총수는 **현재 자료로 확인 불가**이지만 필수 산출물 부재로 주 지표 불합격은 확정되며, 과거 차단 원인 1개씩은 별도 기록으로 확인된다.

OFF 20건에는 모두 최종 보고서가 있고 차단은 없다. 그중 과거 `failed` 18건은 생성 후 missing RAG audit 검사 때문에 붙은 표시이며, 최종 출력 부재나 가드레일 차단으로 세지 않는다. **오류 포함 출력 ON 2건 대 OFF 20건의 차이는 교정과 차단이 함께 작용한 종합 결과**로만 제시한다.

## 3. 종합 ON/OFF 결과와 한계

### 모든 계획 실행을 분모로 한 결과

| 지표 | ON (전체 20회) | OFF (전체 20회) |
|---|---:|---:|
| 보고서 완성 | 18/20 (90%) | 20/20 (100%) |
| **공통 검사 통과: 주 지표** | **16/20 (80%)** | **0/20 (0%)** |
| 완성됐지만 내용 hard error 있음 | 2/20 (10%) | 20/20 (100%) |
| 가드레일에 의한 최종 출력 차단 | 2/20 (10%) | 0/20 (0%) |
| 주 지표 불합격 합계 | 4/20 (20%) | 20/20 (100%) |
| 주 지표 판정 미확정 | 0 | 0 |

ON의 전체 20회는 **합격 16 + 오류 포함 완성 출력 2 + 출력 차단 2**로 나뉜다. OFF는 **오류 포함 완성 출력 20**이다. 완성된 실행만으로 분모를 줄이지 않았다.

### 판정 규칙과 검사 범위

필수 보고서가 없거나, 확인된 내용 hard error가 하나라도 있으면 주 지표는 불합격이다. 필요한 검사를 모두 마치고 hard error가 0이면 합격이다. 오류가 확인되지 않았지만 필요한 검사가 남았다면 미확정이며, 단순히 오류가 보이지 않는 상태를 합격으로 처리하지 않는다. warning은 hard error와 구분한다.

이번 자료에서 ON 완성 18건은 필요한 공통 검사를 마쳤고, 차단된 2건은 산출물 결손으로 불합격이다. **OFF 20건 모두 `status=deterministic_only`, `evaluation_complete=false`이며, deterministic hard error로 불합격이 이미 확정되어 추가 의미 검사를 생략**했다. 따라서 `evaluation_complete=false`를 주 지표 미확정으로 되돌리지 않는다.

| 공통 사후 검사에서 확인된 유형 | 해당 실행 수 | 검사 범위 |
|---|---:|---|
| ON `inline_citation_overclaimed` | 2/20 | 완성된 ON 18건의 필요 검사 완료; 차단 2건의 과거 잔여 오류와 별개 |
| OFF `part3_therapeutic_spillover` | 20/20 | deterministic 검사에서 확인 |
| OFF `unsupported_pathway_factor_significance` | 9/20 | deterministic 검사에서 확인 |
| OFF `lr_metric_value_mismatch` | 6/20 | deterministic 검사에서 확인 |
| OFF `factor_pathway_direction_mismatch` | 4/20 | deterministic 검사에서 확인 |

유형별 해당 실행 수는 서로 중복될 수 있어 합산하지 않는다. 실행별 CSV의 OFF 오류 수는 **확인된 최소치**다. 의미 검사를 생략한 범위를 오류 0으로 채우거나, ON/OFF 오류 총수를 동일한 완전 검사 결과처럼 비교하지 않는다.

### 해석 한계와 원본 보존

- 모든 결과는 **사전 정의된 자동검증 기준의 준수와 교정·차단 역할**에 관한 것이다. 별도의 독립적인 과학적 정확성 평가는 수행하지 않았다. 합격은 모든 과학적 주장이나 인용의 진실성을 보증하지 않는다.
- 같은 BC 데이터셋의 반복 실행이며 독립 생물학적 표본이 아니다. 서로 별도 생성된 ON/OFF 보고서를 이용하므로 차이를 개별 오류의 수정 전후 변화로 볼 수 없다.
- 과거 ON과 신규 OFF의 실행 시점 차이가 남는다. 관측된 통과율 차이에서 교정만의 효과 크기나 차단만의 기여율을 분리 추정할 수 없다.
- 원래 실행 루트 `guardrail_on_off_20260905T154030Z`의 기존 `status.json/comparison.md`에는 이전 평가기 오류가 남아 있어 최종 판정에 사용하지 않았다. 초기 어댑터 문제로 제외된 `guardrail_on_off_20260905T101853Z`는 포함하지 않았다.
- 복구 평가는 기존 성공 공통 사후 체크포인트를 재사용하고 이벤트 루프 및 응답 형식 오류를 복구한 결과다. 구체적 기준과 복구 경계는 [recovery_method.md](../../metadata/recovery_method.md)에 따른다. 이번 정리에서는 **보고서 재생성, 실험 재실행, LLM/RAG 재평가를 수행하지 않았다.**
- 40개 실행의 JSON·CSV·manifest·개별 판정을 대조하고, manifest에 기록된 원본 보고서 **196개 SHA-256**이 현재 원본과 일치함을 확인했다. 기존 [verification.json](../../metadata/verification.json)의 `84 passed`는 이전 복구 작업의 검증 기록이며 이번에 테스트나 평가를 다시 실행한 결과가 아니다. 이번에는 요청된 Markdown·CSV만 새로 작성했다.

## 산출물과 실행별 표 읽는 방법

- [two_effects_summary.md](two_effects_summary.md): 교정·차단의 직접 근거, 종합 결과, 해석 한계.
- [two_effects_run_table.csv](two_effects_run_table.csv): 40행, UTF-8 BOM. `실행 번호 + 조건`이 고유 식별자다. 판정·검사 범위·교정 근거·차단 근거를 분리했으며, `근거 파일 경로`는 실제 존재하는 파일의 절대 경로 JSON 배열이다.

CSV의 `오류 종류`는 공통 사후 판정에 따른 내용 hard error 또는 산출물 결손을 기록한다. `차단 잔여 오류 종류`와 `과거_가드레일_최종_판정`은 생성 당시 기록이므로 서로 합산하지 않는다. OFF의 before/after 교정 관련 칸은 ‘해당 없음’이고, 미완성 ON의 공통 내용 오류 수는 ‘현재 자료로 확인 불가’다. ‘필요 검사 완료’는 정의된 검사 범위의 완료를 의미하며 독립 과학적 검증을 뜻하지 않는다.
