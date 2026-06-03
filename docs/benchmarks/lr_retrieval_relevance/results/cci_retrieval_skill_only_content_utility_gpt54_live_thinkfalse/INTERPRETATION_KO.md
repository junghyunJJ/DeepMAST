# CCI Retrieval Skill-Only Benchmark 해석

## 실행 범위

- Retrieval input: `cci_retrieval_skill_only_qwen_full_thinkfalse`
- Content-utility output: `cci_retrieval_skill_only_content_utility_gpt54_live_thinkfalse`
- Retrieval rows: 120/120, error 0
- Judge model: `gpt-5.4`
- Judge protocol: `realuse` primary, `matched` sensitivity
- Handoff policy: skill ON/OFF 모두 동일한 posthoc direct/context filter, cap 40

이번 결과는 기존 `cci_content_utility_full_gpt54_live` 또는 old `full_paper_relevance_v1` 결과와 섞지 않은 clean `_thinkfalse` run이다.

## 핵심 결론

이번 clean Benchmark A에서는 `biomedical-literature-search` skill ON이 최종 content utility에서 뚜렷하게 우월하다고 보기 어렵다.

Primary real-use 기준으로 updated skill과 no-skill은 거의 동률이다.

- Valid paired tasks: 59
- updated_skill wins: 22
- no_skill wins: 22
- ties: 15
- strength-balanced effect: -0.002
- bootstrap 95% CI: -0.104 to 0.108
- one-sided exact sign-flip p: 0.558

Matched-budget sensitivity에서는 오히려 no-skill 쪽으로 약간 기울지만, 이 역시 유의한 효과는 아니다.

- Valid paired tasks: 59
- updated_skill wins: 13
- no_skill wins: 17
- ties: 29
- strength-balanced effect: -0.035
- bootstrap 95% CI: -0.128 to 0.052
- one-sided exact sign-flip p: 0.817

따라서 이번 run의 최종 결론은 "skill ON이 final biological interpretation utility를 안정적으로 개선했다"가 아니라, "retrieval 결과는 model strength에 따라 mixed signal을 보였고, 최종 judge utility에서는 전체적으로 neutral"이다.

## 모델별 해석

qwen3.5:122b에서는 skill ON이 어느 정도 긍정적이다.

- Real-use strong effect: +0.100
- updated_skill wins/ties/no_skill wins: 15/6/9
- Handoff papers: skill ON 417 vs skill OFF 368
- Unique PMID overlap: shared 266, skill-only 44, no-skill-only 11

즉 strong model에서는 skill이 더 넓은 direct/context citable pool을 만들고, no-skill 대비 고유 논문도 더 많이 확보했다. judge도 real-use에서는 skill ON을 더 자주 선호했다.

qwen3.5:35b에서는 반대 방향이다.

- Real-use weak effect: -0.103
- updated_skill wins/ties/no_skill wins: 7/9/13
- Handoff papers: skill ON 387 vs skill OFF 383
- Unique PMID overlap: shared 274, skill-only 17, no-skill-only 20

즉 weak model에서는 skill ON이 handoff count를 조금 늘렸지만, 최종 해석 품질로 이어지지 않았다. judge preference는 no-skill baseline 쪽이 조금 더 안정적이었다.

## Retrieval bucket 해석

Direct LR evidence는 전체적으로 매우 적다.

- weak ON/OFF direct: 6 / 6
- strong ON/OFF direct: 8 / 8

대부분의 usable citable evidence는 `receptor_pathway_context_evidence`이다.

- weak ON context: 381
- weak OFF context: 377
- strong ON context: 409
- strong OFF context: 360

따라서 이 benchmark에서는 direct LR paper를 많이 찾아서 이긴다기보다, receptor/pathway context paper를 얼마나 유용하게 모으고 해석에 쓰는지가 핵심이다.

## Figure 해석

생성된 figure는 새 clean `_thinkfalse` 결과만 사용한다.

- `manuscript/figures/fig2.svg`
- `manuscript/figures/figs2.svg`

Figure의 주요 메시지는 다음과 같다.

1. Strong model에서는 skill ON이 더 많은 context/handoff papers와 더 많은 skill-only PMIDs를 만든다.
2. Weak model에서는 skill ON의 handoff count가 거의 같거나 약간 많지만, judge preference는 no-skill 쪽으로 기운다.
3. Content-utility panel에서는 primary effect가 거의 0이고 confidence interval이 0을 넓게 포함한다.
4. Matched-budget sensitivity에서는 signal이 더 약해지며, tie가 많아진다.

## 최종 판단

이번 결과는 updated retrieval skill의 효과가 "항상 우월"이 아니라 "strong model에서는 도움이 될 수 있지만 weak model에서는 오히려 불안정할 수 있음"을 보여준다.

실제 manuscript/benchmark claim은 다음처럼 쓰는 것이 안전하다.

> In the clean retrieval-only Benchmark A with identical posthoc direct/context filtering, the updated biomedical-literature-search skill did not produce a significant overall content-utility advantage. The effect was model-dependent: qwen3.5:122b showed a positive retrieval and real-use judge signal, whereas qwen3.5:35b showed a negative signal. This indicates that the skill may amplify stronger-model search planning, but its benefit is not model-agnostic.

다음 분석에서 볼 만한 것은 `strong model only` claim을 따로 세울 수 있는지, 그리고 weak model에서 skill ON이 왜 불리해졌는지에 대한 query/paper-level error analysis이다.
