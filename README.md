# 🚀 KOSPI Elite Stock Analyzer (수익률 극대화 프로젝트)

본 프로젝트는 단순한 주식 분석기를 넘어, 전 세계 상위 1% 트레이더들의 매매 철학을 녹여낸 **'고신뢰도 자동화 트레이딩 시스템'**입니다.

## 📖 프로젝트 히스토리 (AI 페어 프로그래밍)

사용자와 AI의 긴밀한 대화를 통해 다음과 같은 과정을 거쳐 진화해 왔습니다.

1.  **Phase 1: 기초 엔진 구축**
    - FinanceDataReader 기반 KOSPI 전 종목 데이터 수급.
    - RSI Divergence, MACD Golden Cross, Bollinger Bands Squeeze 등 핵심 지표 구현.
2.  **Phase 2: 리스크 관리 (Trailing Stop)**
    - "물리는 주식"을 방지하기 위한 **3% 트레일링 스톱** 매도 전략 도입.
    - `holdings.json`을 통한 실시간 포트폴리오 관리.
3.  **Phase 3: 사용자 편의성 (Telegram Bot)**
    - 스마트폰에서 실시간으로 `/buy`, `/sell`, `/analyze` 명령어로 제어 가능한 인터페이스 구축.
4.  **Phase 4: 업그레이드 (Elite Return System)**
    - **Trend Template**: 마크 미너비니의 원칙에 따른 150/200일 이평 정배열 종목만 선별.
    - **Relative Strength (RS)**: 지수 대비 강한 주도주 탐색.
    - **Validation Layer**: 추천 전 6개월 과거 데이터를 즉석에서 시뮬레이션하여 **승률 70% 이상인 종목**만 최종 추천.
5.  **Phase 5: 100% 자동화 (GitHub Actions)**
    - 매일 아침 **08:30 (KST)**에 서버가 알아서 분석 리포트를 전송.
    - 분석 결과와 보유 종목 변동 사항을 자동으로 GitHub에 재커밋하여 데이터 보존.

## 🛠 주요 기능 및 명령어

### 🤖 텔레그램 봇 명령어
- `/start`: 안내 및 명령어 확인
- `/buy 005930 75000`: 삼성전자를 7.5만원에 포트폴리오에 추가 (감시 시작)
- `/sell 005930`: 해당 종목 삭제
- `/list`: 현재 감시 중인 종목 리스트 확인
- `/analyze`: 지금 즉시 전체 코스피 종목을 엘리트 전략으로 분석

### ⚙️ 자동화 설정 (GitHub Actions)
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`를 GitHub Secrets에 등록하면 매일 아침 자동으로 리포트가 전송됩니다.
- `Elite Stock Analysis` 리포트에는 오늘의 주요 주식/증시 관련 뉴스 요약도 포함됩니다.

## 🧑‍💼 전문가 역할 (Agent)

각 역할별 상세 지침은 `agent/` 폴더를 참조하세요.

| 역할 | 파일 | 설명 |
|------|------|------|
| 투자분석전문가 | [agent/agent_stock.md](agent/agent_stock.md) | 기술적 분석 기반 알고리즘 검증·개선 |
| 백테스트 검증전문가 | [agent/agent_backtest.md](agent/agent_backtest.md) | 수익률·승률·MDD 등 성과 지표 검증 |
| 자동화 전문가 | [agent/agent_auto.md](agent/agent_auto.md) | 주간 Self-Evolution 자동화 루프 운영 |
| ETF 투자 전문가 | [agent/agent_etf.md](agent/agent_etf.md) | 차트 분석 기반 ETF 종목 선정 및 포트폴리오 최적화 |
| 검색 전문가 | [agent/agent_search.md](agent/agent_search.md) | **차트의 기술 중심 탐색, 외부 방법론 발굴** |

## 🚀 기술 스택
- **Language**: Python 3.9+ (권장: 3.10 이상)
- **Data**: FinanceDataReader
- **Indicators**: pandas-ta-classic
- **Notification**: python-telegram-bot
- **Platform**: GitHub Actions, Google Apps Script, Cloud Scheduler

## ⏰ 자동화 및 스케줄링

- GitHub Actions 워크플로우(분석, 모니터, 최적화, agent_search 등)는 `workflow_dispatch` API로 트리거됩니다.
- 정시 실행이 필요하면 Google Cloud Scheduler, Apps Script 등 외부 스케줄러에서 API를 호출하세요.

### 주요 워크플로우 및 호출 예시

| 워크플로우 | API URL |
|---|---|
| Elite Stock Analysis | `POST /actions/workflows/analyze.yml/dispatches` |
| Real-Time Market Monitor | `POST /actions/workflows/monitor.yml/dispatches` |
| Strategy Optimizer | `POST /actions/workflows/optimize.yml/dispatches` |
| Agent Search (신규 전략 탐색) | `POST /actions/workflows/agent_search.yml/dispatches` |

#### 예시 (curl)
```bash
curl -X POST "https://api.github.com/repos/wansang/finance/actions/workflows/agent_search.yml/dispatches" \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <YOUR_GITHUB_PAT>" \
  -d '{"ref":"main"}'
```

### Google Apps Script 연동 예시

`google-scheduler/agent_search/Code.js` 참고. (GITHUB_PAT은 Script Properties에 등록)

```js
function dispatchAgentSearchWorkflow() {
  var url = "https://api.github.com/repos/wansang/finance/actions/workflows/agent_search.yml/dispatches";
  var payload = JSON.stringify({ ref: "main" });
  var token = PropertiesService.getScriptProperties().getProperty("GITHUB_PAT");
  var options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": "Bearer " + token
    },
    payload: payload,
    muteHttpExceptions: true
  };
  var response = UrlFetchApp.fetch(url, options);
  Logger.log(response.getContentText());
}
```

### 크론 예시 (Asia/Seoul 기준)
- 분석: 평일 08:30 → `30 8 * * 1-5`
- 모니터: 평일 09:00~20:00 30분 간격 → `0,30 9-19 * * 1-5`, `0 20 * * 1-5`
- 최적화: 토요일 09:00 → `0 0 * * 6`
- agent_search: 금요일 23:00(UTC) → `0 23 * * 5`

### 1) GitHub 토큰 준비
- GitHub PAT(Fine-grained) 생성
- 권한: `Actions: Read and write`, `Contents: Read`
- 대상 저장소: `wansang/finance`


---
*본 프로그램은 기술적 분석을 통한 보조 도구이며, 모든 투자의 책임은 투자자 본인에게 있습니다.*

---
*본 프로그램은 기술적 분석을 통한 보조 도구이며, 모든 투자의 책임은 투자자 본인에게 있습니다.*
