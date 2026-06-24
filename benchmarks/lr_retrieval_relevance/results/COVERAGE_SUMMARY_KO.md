# Retrieval Coverage 정리 — biomedical-literature-search skill ON vs OFF

> Run: `cci_retrieval_skill_only_qwen_full_thinkfalse` (retrieval_only, benchmark_mode A)
> 분석일: 2026-06-02
> 측정 대상: skill ON/OFF 두 arm이 회수한 문헌이 케이스의 생물학(gene/pathway/celltype)을
> 얼마나 포괄하는가 (coverage). depth/utility가 아니라 **breadth** 지표.

## 0. 측정 방법

- **coverage_pct** = 케이스의 entity(gene/pathway/celltype) 중, 해당 arm이 회수한 논문들의
  title+abstract에 (동의어·별칭·풀어쓴 표현 포함) 등장한 비율. arm의 논문 union 기준.
- **regex 버전**: `src/agents/deep_interpreter/tools/literature.py::_calculate_coverage` (정규식/별칭 매칭).
- **LLM 버전 (주 분석)**: per-paper로 "이 논문이 케이스의 어떤 entity를 다루나"를 LLM이 추출 →
  arm union. judge = `qwen3.5:122b` (ollama, `think:False`, `temperature:0`), 1423 unique
  (case, pmid), 실패 0.
- **judge 모델 주의**: `qwen3.5:35b`로도 돌렸으나 celltype을 과대-inclusive 판정(양 arm ~90% 포화)해
  실제 차이를 지워버림 → **35b는 신뢰 불가, 122b 채택**. (regex와 122b는 절대값·Δ 모두 수렴.)
- 두 집합: **raw**(회수 전체, ~30편/case)와 **filtered = direct+context handoff**(interpreter가
  실제 보는 `papers.json`, cap 40, ~12–14편/case).

---

## 1. Descriptive coverage (통계검정 전) — qwen3.5:122b

### Table 1 — ALL retrieved (raw)

| 지표 | strong ON | strong OFF | Δ | weak ON | weak OFF | Δ |
|---|---:|---:|---:|---:|---:|---:|
| genes_coverage | 100.0 | 100.0 | +0.0 | 100.0 | 100.0 | +0.0 |
| pathways_coverage | 95.5 | 72.7 | +22.7 | 86.4 | 63.6 | +22.7 |
| celltypes_coverage | 65.1 | 40.4 | +24.7 | 63.2 | 42.6 | +20.6 |
| N papers (총 / 평균per case) | 1105 / 37 | 900 / 30 | — | 900 / 30 | 900 / 30 | — |

### Table 2 — direct/context only (filtered, interpreter-facing)

| 지표 | strong ON | strong OFF | Δ | weak ON | weak OFF | Δ |
|---|---:|---:|---:|---:|---:|---:|
| genes_coverage | 95.0 | 95.0 | +0.0 | 95.0 | 95.0 | +0.0 |
| pathways_coverage | 63.6 | 50.0 | +13.6 | 63.6 | 45.5 | +18.2 |
| celltypes_coverage | 46.4 | 26.8 | +19.6 | 38.7 | 27.7 | +11.0 |
| N papers (총 / 평균per case) | 417 / 14 | 368 / 12 | — | 387 / 13 | 383 / 13 | — |

### 참고 — regex 버전 (raw, row-stored)

| 지표 | strong ON | strong OFF | Δ | weak ON | weak OFF | Δ |
|---|---:|---:|---:|---:|---:|---:|
| genes_coverage | 100.0 | 100.0 | +0.0 | 100.0 | 100.0 | +0.0 |
| pathways_coverage | 100.0 | 54.5 | +45.5 | 100.0 | 36.4 | +63.6 |
| celltypes_coverage | 60.5 | 35.7 | +24.8 | 61.6 | 38.0 | +23.7 |
| coverage_pass 비율 | 1.00 | 0.83 | +0.17 | 1.00 | 0.77 | +0.23 |

> regex vs 122b: **celltype Δ는 거의 동일**(regex +24.8/+23.7 ≈ 122b +24.7/+20.6) → 견고.
> **pathway Δ는 regex가 부풀림**(weak +63.6 → +22.7): regex가 OFF arm의 동의어·풀어쓴 pathway
> 언급을 못 잡아 OFF를 과소평가하기 때문(122b OFF 63.6% vs regex OFF 36.4%). 방향은 일치.
> `coverage_pass`는 regex 파이프라인 게이트(gene≥90% & pathway 임계)라 LLM 표에는 미포함.

---

## 2. Paired statistical tests (qwen3.5:122b)

케이스별 ON−OFF 차이에 대한 paired test. Wilcoxon signed-rank (two-sided),
exact sign test, bootstrap 95% CI (10k). `n` = paired cases. genes/celltypes는 전 케이스(30/strength),
pathways는 **pathway 주석이 있는 케이스만**(11/strength).

### Table 1 stats — ALL retrieved (raw)

| metric | strata | n쌍 | meanΔ | 95% CI | Wilcoxon p | sign p |
|---|---|--:|--:|--:|--:|--:|
| genes | pooled | 60 | +0.0 | [+0.0, +0.0] | nan | — |
| pathways | strong | 11 | +22.7 | [0, +50.0] | 0.25 ns | 0.25 |
| pathways | weak | 11 | +22.7 | [0, +50.0] | 0.25 ns | 0.25 |
| pathways | pooled | 22 | +22.7 | [+6.8, +40.9] | **0.023 \*** | 0.031 |
| celltypes | strong | 30 | +24.7 | [+18.2, +31.8] | **<0.001 \*\*\*** | <0.001 |
| celltypes | weak | 30 | +20.6 | [+14.6, +27.0] | **<0.001 \*\*\*** | <0.001 |
| celltypes | pooled | 60 | +22.7 | [+18.1, +27.4] | **<0.001 \*\*\*** | <0.001 |

### Table 2 stats — direct/context only (filtered)

| metric | strata | n쌍 | meanΔ | 95% CI | Wilcoxon p | sign p |
|---|---|--:|--:|--:|--:|--:|
| genes | pooled | 60 | +0.0 | [+0.0, +0.0] | nan | — |
| pathways | strong | 11 | +13.6 | [0, +31.8] | 0.50 ns | 0.50 |
| pathways | weak | 11 | +18.2 | [0, +45.5] | 0.50 ns | 0.50 |
| pathways | pooled | 22 | +15.9 | [+2.3, +31.8] | 0.059 ns | 0.125 |
| celltypes | strong | 30 | +19.6 | [+12.7, +27.3] | **0.0001 \*\*\*** | <0.001 |
| celltypes | weak | 30 | +11.0 | [+5.7, +16.8] | **0.001 \*\*** | <0.001 |
| celltypes | pooled | 60 | +15.3 | [+10.7, +20.2] | **<0.001 \*\*\*** | <0.001 |

`*` p<0.05, `**` p<0.01, `***` p<0.001.

---

## 3. 해석

1. **celltype coverage 우위 = 통계적으로 확고.** raw·filtered, strong·weak·pooled 모두 p<0.01~0.001,
   CI가 0을 포함하지 않음. n=30/strength로 검정력 충분, 다중비교 보정(Bonferroni)에도 생존.
   → 가장 강하게 주장할 수 있는 결과.
2. **pathway coverage 우위 = 큰 효과크기, 약한 유의성.** pathway 주석 케이스가 11개뿐이라
   strength별 n=11로 underpowered → 개별 ns, pooled(raw)만 p=0.034, filtered는 p=0.059(경계).
   방향·크기는 일관(+16~23pp)되나 "유의"로 단정하기 어렵고 다중비교 보정 시 탈락. → "directionally
   consistent, underpowered" 로 기술.
3. **gene coverage = 효과 없음.** 검색이 LR 쌍 중심이라 ligand·receptor는 양 arm ~95–100%로 포화(ns).
4. **모델 일치 ≠ 통계 유의**: pathway는 35b·122b가 동일 수치였지만 n이 작아 비유의; celltype은
   n=30이라 유의. 보고 시 이 구분 필요.

### 권장 claim 문장
> The skill significantly increases **cell-type coverage** of retrieved literature
> (pooled Δ ≈ +22.7pp raw / +15.3pp on the interpreter-facing citable set, Wilcoxon p<0.001,
> n=60 paired cases; significant in both model strengths). **Pathway coverage** shows a
> consistent large positive effect (+16–23pp) but is statistically underpowered (only 11/30
> cases carry pathway annotations). **Gene coverage** is saturated (~95–100% both arms; no effect).

---

## 4. Scope — 이 결과가 보이는 것 / 안 보이는 것

| 주장 | 판정 |
|---|---|
| skill이 **celltype 문헌 coverage**를 높인다 | ✅ 통계 유의 (p<0.001) |
| skill이 **pathway coverage**를 높인다 | ⚠️ 효과는 크나 underpowered (n=11) |
| skill이 **gene coverage**를 높인다 | ❌ 포화, 효과 없음 |
| skill이 **논문당 관련 깊이/precision**을 높인다 | ❌ 3중 독립 측정 모두 flat/희석 |
| skill이 **direct-LR 근거**를 더 찾는다 | ❌ 양 arm ~동일 (~4%) |
| skill이 **최종 해석 content-utility**를 높인다 | ❌ neutral (단 카드 기반 측정, 실제 RAG 해석 미측정) |

coverage(breadth) 메커니즘 = skill ON의 `coverage_weighted_sort=True` (coverage-aware greedy
truncation). `used_lr_pair_queries`는 양 arm 모두 True라 차이 아님.

---

## 5. 재현성 (artifacts & code)

- 라벨: `entity_coverage_labels_122b.jsonl` (pathway/celltype), `gene_coverage_labels_122b.jsonl` (gene)
  — 각 1423 (case, pmid) pairs, 실패 0. (참고용 35b: `entity_coverage_labels.jsonl`.)
- 스코어러: `scripts/benchmarks/score_entity_coverage_llm.py`, `score_gene_coverage_llm.py`
- 집계: `scripts/benchmarks/analyze_full_coverage_122b.py` (Table 1/2), `analyze_coverage_stats.py` (paired stats)
- judge: `qwen3.5:122b` @ `http://localhost:6000`, `think:False`, `temp:0`; bootstrap seed 20260602.
- 입력 retrieval: `cci_retrieval_skill_only_qwen_full_thinkfalse` (retrieval_only, 동일 posthoc cap-40 filter 양 arm).
