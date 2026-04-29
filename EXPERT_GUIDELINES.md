# 전문가 지침서 (Expert Guidelines)

> 각 역할별 상세 지침은 `agent/` 폴더의 개별 파일을 참조하세요.

---

## 역할별 파일 목록

| 역할 | 파일 | 설명 |
|------|------|------|
| A. 투자분석전문가 | [agent/agent_stock.md](agent/agent_stock.md) | 기술적 분석 기반 알고리즘 검증·개선 |
| B. 백테스트 검증전문가 | [agent/agent_backtest.md](agent/agent_backtest.md) | 수익률·승률·MDD 등 성과 지표 검증 |
| C. 자동화 전문가 | [agent/agent_auto.md](agent/agent_auto.md) | 주간 Self-Evolution 자동화 루프 운영 |
| ETF. ETF 투자 전문가 | [agent/agent_etf.md](agent/agent_etf.md) | 차트 분석 기반 ETF 종목 선정 및 포트폴리오 최적화 |
| 검색. 검색 전문가 | [agent/agent_search.md](agent/agent_search.md) | 역할 정의 예정 |

---

## 관련 파일 구조

```
finance/
├── analyzer.py            # 매매 신호 생성 엔진
├── backtester.py          # 백테스트 실행기
├── optimizer.py           # 주간 자동 최적화 엔진
├── strategy_config.json   # 최적화된 파라미터 저장소
├── signal_performance.json# 신호별 누적 성과 기록
├── recommendations.csv    # 실제 추천 이력
├── algorithm_update_log.json # 알고리즘 변경 이력
├── agent/
│   ├── agent_stock.md     # 투자분석전문가 지침
│   ├── agent_backtest.md  # 백테스트 검증전문가 지침
│   ├── agent_auto.md      # 자동화 전문가 지침
│   ├── agent_etf.md       # ETF 투자 전문가 지침
│   └── agent_search.md    # 검색 전문가 지침
└── google-scheduler/
    └── dispatch_optimize_workflow.gs  # 토요일 9시 자동 트리거
```
