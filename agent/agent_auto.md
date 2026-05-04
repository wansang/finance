# 자동화 전문가 역할 지침

## 역할 정의

| 항목 | 내용 |
|------|------|
| 역할 | 주간 Self-Evolution 자동화 루프 총괄 오케스트레이터 |
| 임무 | 전문가 간 협업 흐름 조율 및 최소 3사이클 개선 루프 보장 |
| 원칙 | 검증 없이 확정된 전략은 없다. agent_backtest 최종 승인 필수 |

---

## 자동화 스케줄

| 워크플로우 | 실행 일정 | 실행 파일 |
|-----------|----------|----------|
| `analyze.yml` | 평일 오전 8~9시 (공휴일 제외) | `analyzer.py` |
| `monitor.yml` | 평일 오전 9시 ~ 오후 8시, 30분마다 | `monitor.py` |
| `optimize.yml` | **토요일 오전 9시** | `optimizer.py` |

---

## 주간 Self-Evolution 전체 흐름

```
┌──────────────────────────────────────────────────────────────┐
│              [토요일 오전 — 주간 Self-Evolution 시작]          │
│                                                              │
│  STEP 1. agent_search — 신규 투자 방법론 탐색                  │
│    - 현재 시스템에 없는 새로운 전략·방법론 발굴                  │
│    - 발굴된 방법론을 agent_stock·agent_etf에 구조화 전달        │
│                          ↓                                  │
│  STEP 2-A. agent_stock — 주식 시스템 점검                     │
│    - analyzer.py / strategy_config.json 전반 분석             │
│    - agent_search 제안 + 자체 발견 개선사항 취합               │
│    - 수정 제안 초안 작성 (사이클 1)                             │
│                                                              │
│  STEP 2-B. agent_etf — ETF 시스템 점검 (병렬)                 │
│    - KOSPI ETF / US ETF 전략 분석                             │
│    - agent_search 제안 반영 ETF 특화 개선사항 작성              │
│                          ↓                                  │
│  STEP 3. agent_backtest — 통합 검증 (최소 3사이클 반복)         │
│    - agent_stock·agent_etf 제안 Before/After 백테스트          │
│    - 승인/거부 피드백 각 전문가에게 전달                         │
│                          ↓                                  │
│  STEP 4. 피드백 반영 재제안 (사이클 2, 3, ...)                  │
│    - 거부 항목 → 해당 전문가 재분석 → 신규 제안                  │
│    - 승인 항목 → 확정 후 다음 개선 사항 탐색                     │
│                          ↓                                  │
│  STEP 5. 최종 확정 (3사이클 이상 + agent_backtest 최종 승인)    │
│    - strategy_config.json 업데이트                            │
│    - analyzer.py 패치 적용                                    │
│    - algorithm_update_log.json 기록                          │
│    - GitHub 자동 커밋/푸시                                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 전문가별 역할 요약

| 전문가 | 파일 | 역할 | 실행 시점 |
|--------|------|------|-----------|
| 검색 전문가 | `agent_search.md` | 신규 투자 방법론 탐색·제안 | STEP 1 |
| 투자분석 전문가 | `agent_stock.md` | 주식 알고리즘 분석·개선 제안 | STEP 2-A |
| ETF 투자 전문가 | `agent_etf.md` | ETF 전략 분석·개선 제안 | STEP 2-B |
| 백테스트 검증 전문가 | `agent_backtest.md` | 모든 제안 검증·승인·거부 | STEP 3 (반복) |
| 자동화 전문가 | `agent_auto.md` | 전체 흐름 오케스트레이션 | 전 단계 총괄 |

---

## 3사이클 반복 규칙

```
[사이클 1]
  agent_stock + agent_etf → 초안 제안
  → agent_backtest 검증 → 피드백 전달

[사이클 2]
  피드백 반영 수정 제안
  → agent_backtest 검증 → 피드백 전달

[사이클 3]
  정제된 최종 제안
  → agent_backtest 최종 검증
  → 승인 시 전략 확정 / 거부 시 사이클 4 진행

※ 3사이클 미만 완료 시 전략 확정 금지
※ agent_backtest 최종 승인 없이 strategy_config.json 변경 금지
```

---

## optimizer.py 8단계 자동화 과정

```
1. 추천 종목 실제 수익률 측정 (recommendations.csv 기반)
2. 신호별 성과 추적 (signal_performance.json 갱신)
3. 실패 패턴 분석 (손실 종목 공통 특징 학습)
4. 시장 상황 분류 (상승장 / 하락장 구분)
5. 다중 파라미터 최적화 (TRAILING_STOP, WIN_RATE, PEAK_FACTOR 등)
6. 통계적 신뢰도 확인 (급격한 파라미터 변경 방지)
7. 최적화된 strategy_config.json 자동 저장
8. GitHub 자동 커밋/푸시 (main 브랜치 반영)
```

---

## 토요일 optimizer 결과 신뢰도 주의사항

| 항목 | 내용 |
|------|------|
| 데이터 지연 | `FinanceDataReader`가 최신 금요일 종가를 즉시 반영 못할 수 있음 |
| 과최적화 위험 | 단기 데이터(1주)에 과도하게 맞춰진 파라미터가 생성될 수 있음 |
| 샘플 수 부족 | 주간 추천 종목 수가 적으면 통계 신뢰도가 낮아짐 |
| 시장 노이즈 | 특정 주 이상 이벤트 시 편향된 최적화 발생 가능 |

### 권장 검증 절차

```
토요일 optimizer 자동 실행
    ↓
algorithm_update_log.json으로 변경 내용 확인
    ↓
3사이클 전문가 협업 루프 가동 (agent_search → agent_stock/etf → agent_backtest)
    ↓
agent_backtest 최종 승인 후 strategy_config.json 반영
    ↓
월요일 장 시작 전 최종 상태 확인
```

---

## 파라미터 오염 방지 가드 (2026-05-04 추가)

> **배경**: Auto Evolution이 TIER1_MIN_RS=90(소수 단위인데 정수로 오해), WIN_RATE=0.6(%인데 비율로 오해)을 strategy_config.json에 저장하여 전 종목 필터링 실패 및 추천 종목 0건 사태 발생.

### 현재 적용된 방어 레이어

| 레이어 | 위치 | 내용 |
|--------|------|------|
| **입력 차단** | `_call_agent_stock` / `_call_agent_etf` 프롬프트 | Gemini에 파라미터별 단위·범위 명시 |
| **출력 차단** | `save_config()` → `_sanitize_config()` | `PARAM_BOUNDS` 범위 초과 시 기존값 유지 + 경고 |
| **함수 보호** | `_parse_expert_a_patches()` | `calculate_entry_price`, `calculate_holding_targets` 자동 패치 금지 |
| **변경 임계값** | `expert_ab_cycle()` | `EXPERT_AB_MIN_IMPROVEMENT=2.0` 미만 변경 채택 금지 |

### PARAM_BOUNDS — 허용 범위

| 파라미터 | 단위 | 허용 범위 | 틀린 예 (차단됨) |
|---------|------|----------|----------------|
| `TIER1_WIN_RATE` | 정수 % | 20 ~ 80 | 0.6, 0.65 |
| `TIER2_WIN_RATE` | 정수 % | 10 ~ 70 | 0.6 |
| `WEAK_SIGNAL_WIN_RATE_THRESHOLD` | 정수 % | 20 ~ 80 | 0.6 |
| `TIER1_MIN_RS` | 소수 | -0.5 ~ 0.5 | 90 |
| `RS_MIN_BEAR_DEFENSE` | 소수 | -0.5 ~ 0.5 | 90 |
| `TRAILING_STOP_PCT` | 소수 | 0.01 ~ 0.30 | 5 (%) |
| `VALIDATE_MAX_HOLD_DAYS` | 정수 일 | 1 ~ 60 | — |

### 자동화 전문가 주의사항

- **WIN_RATE 파라미터는 항상 정수 %**: `win_rate = ... * 100` 코드 기준. 비율(0~1) 입력 금지.
- **RS_LINE은 소수**: RS_LINE은 종목 가격변화율 기반 소수값(-0.1~0.1 일반적). RS Rating 점수(0~100)와 다름.
- **핵심 함수 수정 금지**: `calculate_entry_price`, `calculate_holding_targets`는 agent_stock/agent_backtest 최소 3사이클 검증 후에만 변경 가능.
- **strategy_config.json 변경 후 반드시 범위 확인**: `TIER1_MIN_RS`가 소수인지, WIN_RATE가 % 정수인지 검토.
