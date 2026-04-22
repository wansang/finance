const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'analyze.yml';

function isHoliday(date) {
  try {
    const cal = CalendarApp.getCalendarById('ko.south_korea#holiday@group.v.calendar.google.com');
    if (!cal) {
      Logger.log('[WARN] 공휴일 캘린더를 찾을 수 없습니다. 공휴일 체크를 건너뜁니다.');
      return false;
    }
    return cal.getEventsForDay(date).length > 0;
  } catch (e) {
    Logger.log('[WARN] 공휴일 체크 중 오류: ' + e.message + '. 공휴일 체크를 건너뜁니다.');
    return false;
  }
}

function dispatchAnalyzeWorkflow() {
  const now = new Date();
  // GAS에서 안전한 KST 요일/시간 계산 (Utilities.formatDate 사용)
  const kstDay = parseInt(Utilities.formatDate(now, 'Asia/Seoul', 'u')); // 1=월 ... 6=토, 7=일
  const kstDateObj = new Date(Utilities.formatDate(now, 'Asia/Seoul', 'yyyy/MM/dd'));
  const kstLabel = Utilities.formatDate(now, 'Asia/Seoul', 'yyyy-MM-dd HH:mm');

  // 주말(토/일) 제외
  if (kstDay === 6 || kstDay === 7) {
    Logger.log('[SKIP] 주말: ' + kstLabel);
    return;
  }

  // 공휴일 제외
  if (isHoliday(kstDateObj)) {
    Logger.log('[SKIP] 공휴일: ' + kstLabel);
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
      Logger.log('[OK] Analyze 워크플로 트리거 성공: ' + kstLabel);
    } else {
      Logger.log('[ERROR] ' + kstLabel + ' 응답코드: ' + code + ' / ' + body);
    }
  } catch (e) {
    Logger.log('[EXCEPTION] ' + e.message);
  }
}

// GAS 트리거 설정: 매일 오전 8~9시 실행
// Apps Script 에디터에서 한 번만 실행하면 트리거 등록됨
function createDailyTrigger() {
  // 기존 동일 함수 트리거 중복 방지
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'dispatchAnalyzeWorkflow') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('dispatchAnalyzeWorkflow')
    .timeBased()
    .everyDays(1)
    .atHour(8)
    .create();
  Logger.log('[SETUP] 매일 오전 8시 트리거 등록 완료');
}