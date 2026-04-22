const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'monitor.yml';

// 한국 공휴일 여부 확인 (Google 공개 iCal 피드 사용, CalendarApp 불필요)
function isKoreanHoliday(dateObj) {
  const dateStr = Utilities.formatDate(dateObj, 'Asia/Seoul', 'yyyyMMdd');
  const cache = CacheService.getScriptCache();
  const cacheKey = 'holiday_' + dateStr;
  const cached = cache.get(cacheKey);
  if (cached !== null) return cached === 'true';

  try {
    const url = 'https://www.google.com/calendar/ical/ko.south_korea%23holiday%40group.v.calendar.google.com/public/basic.ics';
    const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    const isHoliday = res.getResponseCode() === 200 &&
      res.getContentText().includes('DTSTART;VALUE=DATE:' + dateStr);
    cache.put(cacheKey, String(isHoliday), 43200); // 12시간 캐시
    return isHoliday;
  } catch (e) {
    Logger.log('[WARN] 공휴일 체크 실패: ' + e.message);
    return false;
  }
}

function dispatchMonitorWorkflow() {
  const now = new Date();
  // GAS에서 안전한 KST 요일/시간 계산 (Utilities.formatDate 사용)
  const kstDay = parseInt(Utilities.formatDate(now, 'Asia/Seoul', 'u')); // 1=월 ... 6=토, 7=일
  const kstHour = parseInt(Utilities.formatDate(now, 'Asia/Seoul', 'H'));
  const kstLabel = Utilities.formatDate(now, 'Asia/Seoul', 'yyyy-MM-dd HH:mm');

  // 평일(월-금)만 실행
  if (kstDay === 6 || kstDay === 7) {
    Logger.log('[SKIP] 주말: ' + kstLabel);
    return;
  }

  // 공휴일 제외
  if (isKoreanHoliday(now)) {
    Logger.log('[SKIP] 공휴일: ' + kstLabel);
    return;
  }

  // 09:00 ~ 20:00 사이만 실행
  if (kstHour < 9 || kstHour > 20) {
    Logger.log('[SKIP] 실행 시간 외 (' + kstHour + '시): ' + kstLabel);
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
      Logger.log('[OK] Monitor 워크플로 트리거 성공: ' + kstLabel);
    } else {
      Logger.log('[ERROR] ' + kstLabel + ' 응답코드: ' + code + ' / ' + body);
    }
  } catch (e) {
    Logger.log('[EXCEPTION] ' + e.message);
  }
}

// GAS 트리거 설정: 매 30분마다 실행 (시간대 필터는 코드에서 처리)
// Apps Script 에디터에서 한 번만 실행하면 트리거 등록됨
function createEvery30MinTrigger() {
  // 기존 동일 함수 트리거 중복 방지
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'dispatchMonitorWorkflow') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('dispatchMonitorWorkflow')
    .timeBased()
    .everyMinutes(30)
    .create();
  Logger.log('[SETUP] 30분 간격 트리거 등록 완료');
}