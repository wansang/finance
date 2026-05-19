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

## 🤖 Gemini AI 활용 방식

본 프로젝트는 Google Gemini API를 핵심 의사결정 엔진으로 활용합니다. `GEMINI_API_KEY` 환경변수(또는 `.env` 파일)가 설정되어 있을 때만 AI 기능이 활성화되며, 미설정 시 로컬 룰 기반 로직으로 자동 대체됩니다.

### 사용 모델 및 라이브러리

- **기본 모델**: `gemini-flash-latest` (불가 시 `gemini-pro-latest` → `gemini-2.5-flash` → `gemini-2.0-flash` 순으로 자동 폴백)
- **SDK**: `google-genai` (최신) 또는 `google-generativeai` (구버전) 중 설치된 것을 자동 감지

### AI가 수행하는 4가지 역할

#### 1. 투자 리포트 생성 (`analyzer.py` — `ask_ai_report`)
시장 상황·보유 종목·관심 종목 데이터를 프롬프트로 전달하면 Gemini가 한국어 투자 전문가 스타일의 리포트를 생성합니다.
- **monitor 모드**: 30분 단위 실시간 모니터링 리포트 (보유 종목, 지금진입가능관심주, 관심 종목, AI 추천 종목 섹션 구성)
- **daily 모드**: 일간 종합 투자 리포트 (국제정세 뉴스 요약 포함)
- API 한도 초과(429) 시 최대 2회 재시도, 실패 시 로컬 요약 리포트로 자동 대체

#### 2. 신규 투자 전략 탐색 (`agent/agent_search.py` — `run_agent_search`)
기존에 시도된 전략(searchBacklog_history.json 기록)을 제외하고, `strategy_config.json` 파라미터 조정만으로 구현 가능한 **새로운 투자 방법론 20가지**를 JSON 형태로 생성합니다. 각 전략에는 `제안_파라미터_변경` 객체가 포함됩니다.

#### 3. 알고리즘 자동 최적화 (`optimizer.py`)
`searchBacklog.json`의 전략 후보를 처리하는 파이프라인에서 Gemini가 세 에이전트 역할을 수행합니다:

| 에이전트 | 함수 | 역할 |
|---|---|---|
| agent_stock | `_call_agent_stock` | 방법론 → KOSPI 주식 전용 파라미터 변경 제안 |
| agent_etf | `_call_agent_etf` | 방법론 → ETF 전용 파라미터 변경 제안 |
| agent_backtest | `_call_agent_backtest` | 백테스트 Before/After 비교 후 파라미터 채택 여부 최종 판단 |

파라미터 단위 혼동 방지를 위해 프롬프트에 단위·범위 제약을 명시합니다 (예: `*_WIN_RATE`는 정수 %, `TIER1_MIN_RS`는 소수 등).

#### 4. Backlog 사전 검증 (`optimizer.py` — `_process_backlog`)
최적화 실행 전 `searchBacklog.json`에 쌓인 전략 후보를 Gemini가 사전 검토하여 유효하지 않은 항목을 필터링합니다. `GEMINI_API_KEY`가 없으면 단순 아카이브만 수행합니다.

### 설정 방법

```bash
# 환경변수로 설정
export GEMINI_API_KEY=AIza...

# 또는 .env 파일에 저장
echo "GEMINI_API_KEY=AIza..." >> .env
```

GitHub Actions에서는 저장소 Secrets에 `GEMINI_API_KEY`를 등록하면 모든 워크플로우(`analyze.yml`, `monitor.yml`, `optimize.yml`, `agent_search.yml`)에 자동으로 주입됩니다.

---

## 🚀 기술 스택
- **Language**: Python 3.11+
- **Data**: FinanceDataReader
- **Indicators**: pandas-ta-classic
- **AI**: Google Gemini API (`google-genai` / `google-generativeai`)
- **Notification**: python-telegram-bot
- **Platform**: GitHub Actions, Google Apps Script, Cloud Scheduler, Google Cloud Run

## ☁️ 배포 (텔레그램 봇 서버)

텔레그램 봇은 [Google Cloud Run](https://cloud.google.com/run) 무료 플랜으로 운영됩니다.

- **프로젝트**: `finance-stock-bot-2026` (asia-northeast3, 서울 인근)
- **메모리**: 512MB
- **모드**: Webhook (메시지 수신 시 자동 시작 → 처리 후 자동 중지)
- **서비스 URL**: `https://stock-bot-315747802244.asia-northeast3.run.app`
- **비용**: 무료 (월 2M 요청, 360K GB-초 이내)

### 최초 설정

```bash
# 1. gcloud CLI 설치
brew install --cask google-cloud-sdk
export PATH=/usr/local/share/google-cloud-sdk/bin:"$PATH"

# 2. 로그인 및 프로젝트 설정
gcloud auth login
gcloud config set project finance-stock-bot-2026

# 3. Docker 인증
gcloud auth configure-docker asia-northeast3-docker.pkg.dev
```

### 배포
```bash
# 이미지 빌드 & 푸시 (Cloud Build 사용, 로컬 Docker 불필요)
gcloud builds submit \
  --tag asia-northeast3-docker.pkg.dev/finance-stock-bot-2026/stock-bot/stock-bot:latest \
  --project finance-stock-bot-2026 .

# Cloud Run 배포
gcloud run deploy stock-bot \
  --image asia-northeast3-docker.pkg.dev/finance-stock-bot-2026/stock-bot/stock-bot:latest \
  --platform managed \
  --region asia-northeast3 \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 1 \
  --allow-unauthenticated \
  --project finance-stock-bot-2026 \
  --set-env-vars "TELEGRAM_TOKEN=...,TELEGRAM_CHAT_ID=...,GITHUB_PAT=...,GEMINI_API_KEY=...,WEBHOOK_URL=https://stock-bot-315747802244.asia-northeast3.run.app"
```

### 로그 확인
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=stock-bot" \
  --project finance-stock-bot-2026 --limit 20 --format="value(textPayload)"
```

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
