# Plan: Reframe B' — Skill-Gated Fan-out Pilot

## Context

Reframe B (post-hoc decision-quality analysis on existing 48-trial 파일럿 데이터)는 **실패**. 4개 condition의 papers.json을 비교하면 거의 모든 decision 필드가 동일:

- `iterations=2`, `think_success=True`, `coverage_sufficient=False`, `filter_stage=deterministic_only` — 전부 4개 condition 동일
- `recommended_actions`: 개수(2개)와 문구 모두 동일
- `coverage_history`: iter 0 → 1 → final의 진행과 최종 값 모두 동일
- `n_generated_queries = 9`, 첫 2개 deterministic queries 동일
- 유일한 variance는 LLM이 쓴 `unique_keywords = 26~33` (~4-7 keyword 차이)

근본 원인: BENCHMARK_APPENDIX + SEARCHER_PROMPT가 **`enable_lr_pair_queries=True, coverage_weighted_sort=True`를 양 arm 모두에 pin**하고 있음. 이 두 kwarg가 production 코드의 deterministic fan-out + pathway hybrid queries + tag-on coverage를 전부 트리거하는데, 양 arm이 같은 값을 쓰므로 LLM decision space가 거의 0으로 collapse. `search_literature_dynamic`은 monolithic tool — 내부에서 fan-out + search + coverage + reflection + recommended_actions를 한 호출로 끝내버려서 LLM은 tool의 kwargs를 설정하는 것 외에 결정할 게 없음.

**Reframe B' (승인됨)**: BENCHMARK_APPENDIX의 kwarg pin을 제거하고, SEARCHER_PROMPT에서 kwarg 언급을 strip해서 "skill ON은 kwargs를 올바르게 설정하고, skill OFF는 default(`False`)로 떨어진다"는 contrast를 만든다. 이게 원래 플랜 파일의 "skill-gated fan-out 의미론" — "skill ON은 기존 동작을 유지하고 skill OFF는 legitimately 덜 검색함".

**목표**: 48-trial 재파일럿으로 skill ON arm이 full production retrieval(30 papers, 100% coverage)을 내고, skill OFF arm이 default retrieval(더 적은 papers, 더 낮은 coverage)을 내는지 측정. GLMM이 실제 interaction effect를 검출할 수 있게 됨.

---

## 핵심 결정: 어디서 kwarg 힌트를 주고 어디서 가릴 것인가

**Production 파일 미터치 원칙**. 건드리지 않을 것:
- `src/agents/deep_interpreter/subagents/prompts.py` (production SEARCHER_PROMPT)
- `skills/biomedical-literature-search/SKILL.md`
- `src/agents/deep_interpreter/tools/literature.py`

**벤치마크 파일만 수정**:
- `docs/benchmarks/harness_x_model/common.py` (`compose_searcher_prompt`, `BENCHMARK_APPENDIX`, 새 constant)
- `docs/benchmarks/harness_x_model/RUNBOOK.md` (새 measurement caveat 추가)
- `tests/benchmarks/test_harness_x_model.py` (regression 가드 추가)

**전략**:

1. **Production SEARCHER_PROMPT에서 benchmark-only로 strip할 구간 식별** (grep으로):
   - Section `## Auto-Save: output_path Parameter` (lines ~242-282) — kwargs 예시 + "enable_lr_pair_queries=True" 명시
   - `## Tools Available` 섹션의 `search_literature_dynamic` 설명 line (line ~288) — "Set `enable_lr_pair_queries=True`..." 언급
   - 다른 kwarg 언급 (grep으로 전부 찾기)

2. **Stripped base prompt** 만들기: production prompt에서 위 구간을 replace로 제거하거나 중립 문장으로 대체.

3. **Benchmark-side kwarg hint**: skill ON arm에만 새 constant `BENCHMARK_SKILL_KWARG_HINT`를 주입. 이 힌트는 harness prompt 바로 뒤에 오는 supplementary block으로 삽입.

4. **BENCHMARK_APPENDIX에서 kwarg pin 제거**: steps 1-6 그대로 두고, step 4의 kwarg list에서 `enable_lr_pair_queries=True, coverage_weighted_sort=True` 두 줄만 삭제. LLM이 kwarg를 스스로 결정하게 함.

5. **Telemetry 추가**: `generated_queries` structure에서 deterministic singleton 쿼리가 emit됐는지 감지 → `used_lr_pair_queries: bool | None` 필드. 이건 LLM이 실제로 어떤 kwarg를 passed 했는지의 proxy.

---

## Critical files

**수정**:
- `docs/benchmarks/harness_x_model/common.py` — stripped prompt, BENCHMARK_SKILL_KWARG_HINT, BENCHMARK_APPENDIX 수정, `compose_searcher_prompt` 재작성, `SearchTrialResult`에 `used_lr_pair_queries` 추가, `run_single_trial`에서 해당 감지
- `docs/benchmarks/harness_x_model/analyze_pilot_workspaces.py` — `used_lr_pair_queries` 추출 + skill-gated fan-out 변수 variance 분석
- `docs/benchmarks/harness_x_model/RUNBOOK.md` — 재파일럿 경로 + Reframe B' measurement caveat
- `tests/benchmarks/test_harness_x_model.py` — 3개 regression test 추가

**재실행**:
- 48-trial 파일럿 (기존 `results/pilot/`, `workspaces/pilot/` 백업 후 fresh run)

**읽기만 (strip 대상 탐색용)**:
- `src/agents/deep_interpreter/subagents/prompts.py:168-322` (SEARCHER_PROMPT 전체)
- `skills/biomedical-literature-search/SKILL.md` (kwarg 언급 여부 재확인 — grep 결과 0건이었음)
- `src/agents/deep_interpreter/tools/literature.py:2360-2400` (`search_literature_dynamic` 시그니처의 default 값)

---

## 실행 단계

### S1 — Production SEARCHER_PROMPT의 kwarg 언급 전수 조사 (15분)

```bash
grep -n "enable_lr_pair_queries\|coverage_weighted_sort\|lr_pair_queries" \
  src/agents/deep_interpreter/subagents/prompts.py
```

찾아낸 모든 언급 위치를 기록. strip 대상 line 범위 확정.

### S2 — `common.py` 수정 (1시간)

**S2.1 — 새 constants 추가**:
```python
# 제거할 section (string replace 대상)
_SEARCHER_PROMPT_KWARG_SECTIONS = [
    # "## Auto-Save: output_path Parameter" 전체 section (S1에서 확정)
    "...",
]

# Skill ON arm에만 주입할 kwarg hint
BENCHMARK_SKILL_KWARG_HINT = """
## Advanced Kwargs (activated by biomedical-literature-search skill)

When calling `search_literature_dynamic`, set these kwargs to activate
the full production retrieval pipeline:

- `enable_lr_pair_queries=True` — activates deterministic gene fan-out
  (one BioMCP query per input gene) and hybrid pathway query injection.
  Without this, only LLM-generated queries are used.
- `coverage_weighted_sort=True` — activates hub-coverage greedy truncation
  (selects final 30 papers to maximize gene coverage). Without this, pure
  SJR sort is used.

These kwargs together trigger production SEARCHER behavior. Do not set them
if you lack guidance on which kwargs are appropriate for your task.
""".strip()
```

**S2.2 — `BENCHMARK_APPENDIX` 수정**: `enable_lr_pair_queries=True`, `coverage_weighted_sort=True` 두 줄만 제거. 나머지 workflow 지시(read, write, output_path, data_dir)는 그대로.

**S2.3 — `compose_searcher_prompt` 재작성**:
```python
def compose_searcher_prompt(skill_on: bool) -> str:
    base = SUBAGENT_PROMPTS["searcher"]
    base = base.replace(HARDCODED_SKILL_BLOCK, BENCHMARK_SKILL_BLOCK)
    for section in _SEARCHER_PROMPT_KWARG_SECTIONS:
        base = base.replace(section, "")  # or replace with neutral stub
    base = base.strip()

    harness_prompt = _render_skill_harness_prompt(skill_on)
    if skill_on:
        harness_prompt += "\n\n" + BENCHMARK_SKILL_KWARG_HINT

    return f"{base}\n\n{BENCHMARK_APPENDIX}\n\n{harness_prompt}".strip()
```

**S2.4 — `SearchTrialResult`에 `used_lr_pair_queries: bool | None = None` 추가**

**S2.5 — `run_single_trial`에서 감지**:
```python
queries = saved.get("generated_queries") or []
# deterministic 싱글톤 쿼리가 있으면 enable_lr_pair_queries=True 사용한 것으로 추정
deterministic_singletons = sum(
    1 for q in queries
    if isinstance(q, dict)
    and len(q.get("genes") or []) == 1
    and not q.get("keywords")
)
expected_singletons = len(normalized["genes"])  # 2 for current case pack
result.used_lr_pair_queries = deterministic_singletons >= expected_singletons
```

### S3 — Regression tests (30분)

`tests/benchmarks/test_harness_x_model.py`에 추가:

1. `test_benchmark_appendix_does_not_pin_kwargs`:
   ```python
   from docs.benchmarks.harness_x_model.common import BENCHMARK_APPENDIX
   assert "enable_lr_pair_queries=True" not in BENCHMARK_APPENDIX
   assert "coverage_weighted_sort=True" not in BENCHMARK_APPENDIX
   ```

2. `test_compose_searcher_prompt_on_arm_has_kwarg_hint`:
   ```python
   prompt_on = compose_searcher_prompt(skill_on=True)
   assert "enable_lr_pair_queries=True" in prompt_on
   assert "coverage_weighted_sort=True" in prompt_on
   # Must appear in the skill-side hint, not the base prompt
   assert "Advanced Kwargs" in prompt_on
   ```

3. `test_compose_searcher_prompt_off_arm_hides_kwarg_hint`:
   ```python
   prompt_off = compose_searcher_prompt(skill_on=False)
   assert "enable_lr_pair_queries=True" not in prompt_off
   assert "coverage_weighted_sort=True" not in prompt_off
   assert "Advanced Kwargs" not in prompt_off
   ```

4. `test_search_trial_result_has_used_lr_pair_queries_field`: introspection

기존 11 테스트는 전부 pass 유지해야 함.

### S4 — 기존 pilot 결과 백업 + workspace 정리 (5분)

```bash
mv docs/benchmarks/harness_x_model/results/pilot \
   docs/benchmarks/harness_x_model/results/pilot_reframe_b_attempt
mv docs/benchmarks/harness_x_model/workspaces/pilot \
   docs/benchmarks/harness_x_model/workspaces/pilot_reframe_b_attempt
```

기존 결과는 "Reframe B 시도 및 saturation 발견" 증거로 archive.

### S5 — 48-trial fresh pilot 재실행 (2-3시간)

```bash
mkdir -p docs/benchmarks/harness_x_model/results/pilot \
         docs/benchmarks/harness_x_model/workspaces/pilot
export OLLAMA_HOST=http://localhost:6000 OLLAMA_BASE_URL=http://localhost:6000
python -u docs/benchmarks/harness_x_model/run_pilot.py \
  --results-dir docs/benchmarks/harness_x_model/results/pilot \
  --workspace-root docs/benchmarks/harness_x_model/workspaces/pilot \
  --per-category 2 --repeats 1 \
  2>&1 | tee docs/benchmarks/harness_x_model/results/pilot/_runner.log
```

백그라운드로 돌리고 완료 알림 대기.

### S6 — `analyze_pilot_workspaces.py` 확장 + 실행 (30분)

- `per_trial.csv`에 `used_lr_pair_queries`, `n_deterministic_queries`, `n_llm_queries` 추가
- Variance ranking에 새 metric 포함
- Cross-arm 분석: ON arm에서 몇 % trial이 `used_lr_pair_queries=True`? OFF arm은?

### S7 — GLMM 재적합 + Gate 재검사 (30분)

새 `pilot_gates.json`:
- Gate A (saturation): OFF arm coverage가 drop했는가? Strong-arm saturation 해소됐는가?
- Gate B (BioMCP health): 0% error rate 유지?
- Gate C (distributional): unique 값이 3 초과인가?
- Variance: per-case between-condition std-dev >= 2pp?

GLMM primary: `coverage_pass ~ skill_on * model_strength + (1|case_id)` — 이제 real variance가 있어야 함.

### S8 — FINDINGS_REFRAME_B_PRIME.md 작성 (45분)

문서:
- Reframe B 실패 원인 (pin된 kwarg → decision space collapse)
- Reframe B' 설계 근거
- 재파일럿 결과
- Skill-gated fan-out 확인 여부 (`used_lr_pair_queries` 분포)
- GLMM interaction effect
- Nature Methods 방향성

### S9 — Architect 검증 (30분)

`oh-my-claudecode:architect`에게 delegate:
- strip 구간이 필요충분한가
- `used_lr_pair_queries` proxy가 실제 kwarg 사용을 반영하는가
- 측정 타당성 (ON/OFF 자연 contrast vs artificial setup)
- Nature Methods 방어 가능성

---

## 리스크 & 완화

| 리스크 | 완화 |
|---|---|
| OFF arm의 qwen3.5:35b가 `search_literature_dynamic`을 호출조차 안 함 | BENCHMARK_APPENDIX의 workflow 지시는 유지 (어떤 tool을 쓸지는 지시). kwargs만 제거. 호출 자체는 여전히 유도됨. |
| OFF arm이 내부 추론으로 `enable_lr_pair_queries=True`를 그냥 기본값처럼 passing | 강력한 contrast 안 남 → Gate A가 여전히 saturate. 이 경우도 유효한 negative finding ("skill이 실질적 load-bearing work 안 함"). |
| Strip한 section이 다른 동작에 영향 (e.g., LLM이 output_path를 모름) | `output_path` / `data_dir`는 BENCHMARK_APPENDIX에 명시 유지. Strip은 kwargs 언급에만 국한. |
| 기존 11 regression tests가 깨짐 | S3에서 해결. 특히 `test_compose_searcher_prompt_strips_mandatory_block`은 그대로 pass해야 함. |
| 재파일럿이 또 Ollama swap 영향으로 outlier 생성 | 동일 seed, 동일 Option β schedule. outlier는 latency 분석에서 post_swap 필터링으로 제거. |
| fresh pilot 중 BioMCP outage | Gate B가 잡음. 재파일럿 재시도 가능. |

---

## Verification

### S3 직후:
```bash
pytest tests/benchmarks/test_harness_x_model.py -v
```
- 14 tests pass (기존 11 + 새 3)

### S5 직전:
```bash
python -c "
from docs.benchmarks.harness_x_model.common import compose_searcher_prompt, BENCHMARK_APPENDIX
on = compose_searcher_prompt(skill_on=True)
off = compose_searcher_prompt(skill_on=False)
print('ON has kwarg hint:', 'enable_lr_pair_queries=True' in on)
print('OFF has kwarg hint:', 'enable_lr_pair_queries=True' in off)
print('Appendix has pin:', 'enable_lr_pair_queries=True' in BENCHMARK_APPENDIX)
"
```
기대: `ON=True, OFF=False, Appendix=False`

### S5 진행 중:
```bash
ls docs/benchmarks/harness_x_model/results/pilot/trial_*.jsonl | wc -l
```

### S6 이후:
`per_trial.csv`에서 `used_lr_pair_queries` 분포:
- ON arm (24 trials): 대다수 True 기대
- OFF arm (24 trials): 대다수 False 기대

### S7 이후:
`pilot_gates.json`:
- Gate A PASS (saturation 해소)
- Gate B PASS (0% error rate)
- Gate C PASS (variance 생김)
- Variance PASS (per-case stdev >= 2pp)

### S8 이후:
`FINDINGS_REFRAME_B_PRIME.md`가 GLMM 결과와 함께 존재.

### S9 이후:
Architect APPROVED 또는 specific revisions.

---

## 예상 총 시간

- S1-S3 (코드 + 테스트): ~2시간
- S4-S5 (백업 + 파일럿): ~3시간 wallclock
- S6-S8 (분석 + 문서): ~2시간
- S9 (architect): ~30분
- **총: ~7.5시간** (파일럿 재실행 포함)

---

## 다음 단계 (이 plan 승인 후)

1. ExitPlanMode → 실행 시작
2. S1부터 순차 진행 (S5는 백그라운드)
3. Architect 승인되면 `/oh-my-claudecode:cancel`로 ralph/state 정리
4. FINDINGS 결과 사용자 보고

Reframe B' 결과가 signal을 보이면:
- Nature Methods 1차 실험 완료
- 시간 여유 있으므로 Reframe C (downstream citation accuracy) companion track 고려 가능

Reframe B' 결과가 또 null signal이면:
- Negative finding으로 FINDINGS에 기록 (skill이 kwargs를 설정해도 downstream 차이 없음 → skill의 load-bearing claim 기각)
- Reframe C로 전환 필수 — 이 시점에서 재plan
