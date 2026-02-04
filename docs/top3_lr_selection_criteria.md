# Top 3 L-R Interactions 선정 기준

## 개요

Deep Interpreter의 Part 3 분석에서 사용되는 Top L-R (Ligand-Receptor) interactions 선정 기준을 문서화합니다.

## 1. 데이터 소스

### interest_sig_liana.csv
- **위치**: `{data_directory}/interest_sig_liana.csv`
- **행 수**: 약 479 rows (데이터셋에 따라 변동)
- **설명**: 관심 클러스터(interest clusters) 기준으로 필터링된 유의미한 L-R pairs
- **생성**: Part 2-9 ctSVG(cell-type Spatially Variable Genes) 분석에서 생성

### 주요 컬럼
| 컬럼명 | 설명 |
|--------|------|
| `ligand` | 리간드 유전자명 |
| `receptor` | 수용체 유전자명 |
| `source` | 리간드 발현 세포 타입 |
| `target` | 수용체 발현 세포 타입 |
| `morans` | Moran's R (공간 상관관계 지표) |
| `pval_interest_adj` | 보정된 p-value (관심 클러스터) |
| `mean_interest` | 관심 클러스터에서의 평균 발현량 |
| `Factor1`, `Factor2`, `Factor3` | NMF Factor 연관성 점수 |

## 2. 선정 기준

### Primary Ranking: Moran's R (`morans`)
- **정의**: 공간 자기상관(spatial autocorrelation) 측정 지표
- **범위**: -1 ~ 1
- **해석**:
  - **높은 값 (>0.3)**: 강한 양의 공간 상관관계 → 클러스터링 패턴
  - **0 근처**: 무작위 분포
  - **음수**: 분산 패턴
- **선정 기준**: 높을수록 우선순위 높음

### Secondary Criteria

#### 1. 통계적 유의성 (`pval_interest_adj`)
- Benjamini-Hochberg 보정된 p-value
- 일반적으로 < 0.05 기준 적용

#### 2. 발현 강도 (`mean_interest`)
- 관심 클러스터에서의 평균 발현량
- 생물학적 중요성 판단에 활용

#### 3. NMF Factor 연관성
- `Factor1`, `Factor2`, `Factor3` 점수
- 특정 생물학적 프로그램과의 연관성 평가

## 3. Top 3 선정 알고리즘

```python
# Pseudocode
def select_top_lr_pairs(interest_sig_liana_df, n=3):
    """
    Top L-R pairs 선정

    1. pval_interest_adj < 0.05로 필터링
    2. morans 값 기준 내림차순 정렬
    3. 상위 n개 선택
    """
    filtered = interest_sig_liana_df[
        interest_sig_liana_df['pval_interest_adj'] < 0.05
    ]
    sorted_df = filtered.sort_values('morans', ascending=False)
    return sorted_df.head(n)
```

## 4. Part 3 분석 구조

### Part 3-10: Top L-R Pairs 공간 발현 패턴
- **목적**: 선정된 Top L-R pairs의 공간적 분포 시각화
- **분석 내용**:
  - 리간드/수용체 유전자의 공간 발현 패턴
  - 세포 타입별 발현 분포
  - 공간 클러스터링 특성

### Part 3-11: Top L-R Pairs 상호작용 요약
- **목적**: 선정된 Top L-R pairs의 상호작용 특성 요약
- **분석 내용**:
  - L-R pair별 통계 요약
  - 세포 타입 간 상호작용 네트워크
  - NMF Factor와의 연관성

### 공통점
- **동일한 Top L-R pairs** 사용
- **다른 관점**에서 시각화 및 해석

## 5. Workflow 요약

```
┌─────────────────────────────────────────────────────────────┐
│                    Part 2-9: ctSVG 분석                      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ interest_sig_liana.csv 생성                          │   │
│  │ - 479 L-R pairs (관심 클러스터 기준 필터링)           │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 INTERPRETER: Top 3 선정                      │
│                                                             │
│  선정 기준:                                                  │
│  1. pval_interest_adj < 0.05 필터링                         │
│  2. morans (Moran's R) 기준 내림차순 정렬                    │
│  3. 상위 3-5개 선택                                         │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│   Part 3-10             │     │   Part 3-11             │
│   공간 발현 패턴         │     │   상호작용 요약          │
│                         │     │                         │
│ - Spatial expression    │     │ - Interaction summary   │
│ - Cell type distribution│     │ - Network visualization │
│ - Clustering patterns   │     │ - Factor associations   │
└─────────────────────────┘     └─────────────────────────┘
```

## 6. 참고 사항

### 선정 개수 조정
- 기본값: Top 3
- 데이터셋 특성에 따라 3-5개로 조정 가능
- morans 분포가 유사한 경우 더 많은 pairs 포함 고려

### 생물학적 해석 우선
- 통계적 기준 외에 생물학적 관련성 고려
- 알려진 pathway와의 연관성 확인
- 문헌 기반 검증 수행 (SEARCHER 활용)

### 데이터 품질 확인
- NaN/Inf 값 처리
- 이상치(outlier) 검토
- 샘플 수 충분성 확인
