# Google Cloud Scheduler for Strategy Optimizer

이 디렉터리는 `google cloud scheduler`에서 GitHub Actions `optimize.yml` 워크플로우를 매주 토요일 오전 9시(KST)에 실행하도록 설정하는 데 필요한 안내를 담고 있습니다.

## 1) 목표

- GitHub Actions `optimize.yml` 워크플로우는 이제 `workflow_dispatch` 전용으로 동작합니다.
- 외부 스케줄러(예: Google Cloud Scheduler)가 매주 토요일 오전 09:00 KST에 GitHub Actions dispatch API를 호출합니다.

## 2) Cloud Scheduler 설정

### 2-1) 스케줄 표현식
- KST 기준 매주 토요일 09:00 → UTC 기준 `0 0 * * 6`

### 2-2) HTTP 타겟
- URL: `https://api.github.com/repos/wansang/finance/actions/workflows/optimize.yml/dispatches`
- HTTP method: `POST`
- Content-Type: `application/json`
- 헤더:
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <YOUR_GITHUB_PAT>`

### 2-3) 요청 본문
```json
{"ref":"main"}
```

## 3) GitHub PAT 권한

- `repo` 또는 `workflow` 권한이 포함된 PAT
- `Contents: Read` 이상
- `Actions: Read and write`

## 4) Cloud Scheduler 작업 생성

Google Cloud Scheduler에서 매주 토요일 오전 09:00 KST(UTC 00:00)에 `optimize.yml` 디스패치를 실행하려면 다음 명령을 사용합니다.

```bash
export PROJECT_ID=<YOUR_GCP_PROJECT_ID>
export LOCATION=asia-northeast3
export GITHUB_PAT=<YOUR_GITHUB_PAT>

gcloud scheduler jobs create http optimize-dispatch \
  --project="$PROJECT_ID" \
  --location="$LOCATION" \
  --schedule="0 0 * * 6" \
  --time-zone="UTC" \
  --uri="https://api.github.com/repos/wansang/finance/actions/workflows/optimize.yml/dispatches" \
  --http-method=POST \
  --headers="Content-Type=application/json","Accept=application/vnd.github+json","Authorization=Bearer $GITHUB_PAT" \
  --message-body='{"ref":"main"}'
```

> `LOCATION`은 Cloud Scheduler가 실행될 리전입니다. `asia-northeast3` 또는 사용 가능한 리전으로 변경할 수 있습니다.

## 5) 실행 테스트

로컬에서 아래 스크립트를 실행하여 동작을 확인할 수 있습니다.

```bash
bash google-scheduler/dispatch_optimize_workflow.sh
```

## 6) 참고

`google-scheduler/dispatch_optimize_workflow.sh`는 GitHub Actions dispatch API 호출을 자동화하는 간단한 헬퍼 스크립트입니다.
## 6) Google Apps Script 등록 예

아래 코드는 Google Apps Script에서 `optimize.yml` 워크플로우를 매주 토요일 오전 09:00 KST에만 호출하도록 검증하는 예시입니다.

```javascript
const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'optimize.yml';
const GITHUB_PAT = PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');

function dispatchOptimizeWorkflow() {
  const now = new Date();
  const kst = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
  const day = kst.getDay();
  const hour = kst.getHours();
  const minute = kst.getMinutes();

  // 토요일 오전 09:00에만 실행
  if (day !== 6) return;
  if (hour !== 9 || minute !== 0) return;

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
  const payload = { ref: 'main' };
  const options = {
    method: 'post',
    headers: {
      Authorization: `Bearer ${GITHUB_PAT}`,
      Accept: 'application/vnd.github+json'
    },
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url, options);
  Logger.log(response.getResponseCode());
  Logger.log(response.getContentText());
}
```

`dispatchOptimizeWorkflow`를 5분 간격으로 트리거하도록 등록하면, 정확히 토요일 09:00에만 실제 요청이 전송됩니다.
