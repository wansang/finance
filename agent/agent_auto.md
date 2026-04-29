# 자동화 전문가 역할 지침

## 자동화 루프 (주간 Self-Evolution 사이클)

본 시스템은 **Google Apps Script 스케줄러** + **GitHub Actions**를 통해 아래 일정으로 자동 실행됩니다.

| 워크플로우 | 실행 일정 | 실행 파일 |
|-----------|----------|----------|
| `analyze.yml` | 평일 오전 8~9시 (공휴일 제외) | `analyzer.py` |
| `monitor.yml` | 평일 오전 9시 ~ 오후 8시, 30분마다 | `monitor.py` |
| `optimize.yml` | **토요일 오전 9시** | `optimizer.py` |

## optimizer.py가 수행하는 8단계 자동화 과정

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

## ⚠️ 토요일 오전 optimizer 결과의 신뢰도 주의사항

**결론: 비슷한 수준의 결과가 나올 수 있으나, 아래 조건에 주의해야 합니다.**

### 토요일 실행이 유리한 이유
- 금요일 장 마감 후 일주일치 데이터가 완전히 확정된 상태이므로 수익률 계산이 정확합니다.
- 주말이라 GitHub Actions 서버 부하가 낮아 안정적으로 실행됩니다.
- `OPTIMIZER_TIME_LIMIT_SECONDS: 1200` (20분) 내에 완료 가능합니다.

### 주의해야 할 한계
| 항목 | 내용 |
|------|------|
| 데이터 지연 | `FinanceDataReader` 가 최신 금요일 종가를 즉시 반영 못할 수 있음 |
| 과최적화(Overfitting) 위험 | 단기 데이터(1주)에 과도하게 맞춰진 파라미터가 생성될 수 있음 |
| 샘플 수 부족 | 주간 추천 종목 수가 적으면 통계 신뢰도가 낮아짐 |
| 시장 노이즈 | 특정 주에 시장 이상 이벤트가 있었다면 편향된 최적화가 발생할 수 있음 |

### 권장 검증 절차
```
토요일 optimizer 자동 실행
    ↓
strategy_config.json 변경 내용 확인 (algorithm_update_log.json)
    ↓
월요일 장 시작 전 backtester.py 수동 실행으로 재검증
    ↓
이상 없으면 그대로 사용 / 이상 있으면 A·B 전문가 루틴 가동
```
