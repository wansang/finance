const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'optimize.yml';

function dispatchOptimizeWorkflow() {
  const kst = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
  const day = kst.getDay();
  const hour = kst.getHours();

  // 토요일(6)만 실행
  if (day !== 6) {
    Logger.log('[SKIP] 토요일 아님: ' + kst.toLocaleString('ko-KR'));
    return;
  }

  // 오전 10~11시 사이만 실행
  if (hour < 10 || hour >= 11) {
    Logger.log('[SKIP] 실행 시간 외 (' + hour + '시): ' + kst.toLocaleString('ko-KR'));
    return;
  }

  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');
  if (!token) {
    Logger.log('[ERROR] GITHUB_PAT 스크립트 속성이 설정되어 있지 않습니다.');
    return;
  }

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
  const options = {
    method: 'post',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json'
    },
    contentType: 'application/json',
    payload: JSON.stringify({ ref: 'main' }),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();
    const body = response.getContentText();
    if (code === 204) {
      Logger.log('[OK] Optimize 워크플로 트리거 성공: ' + kst.toLocaleString('ko-KR'));
    } else {
      Logger.log('[ERROR] 응답코드: ' + code + ' / ' + body);
    }
  } catch (e) {
    Logger.log('[EXCEPTION] ' + e.message);
  }
}

// GAS 트리거 설정: 매주 토요일 오전 10시 실행
// Apps Script 에디터에서 한 번만 실행하면 트리거 등록됨
function createWeeklySaturdayTrigger() {
  // 기존 동일 함수 트리거 중복 방지
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'dispatchOptimizeWorkflow') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('dispatchOptimizeWorkflow')
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.SATURDAY)
    .atHour(10)
    .create();
  Logger.log('[SETUP] 매주 토요일 오전 10시 트리거 등록 완료');
}