const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'monitor.yml';
const GITHUB_PAT = PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');

// Google 대한민국 공휴일 캘린더로 동적 체크 (수동 업데이트 불필요)
function isHoliday(date) {
  const cal = CalendarApp.getCalendarById('ko.south_korea#holiday@group.v.calendar.google.com');
  return cal.getEventsForDay(date).length > 0;
}

function dispatchMonitorWorkflow() {
  const now = new Date();
  const kst = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
  const day = kst.getDay();
  const hour = kst.getHours();
  const minute = kst.getMinutes();

  // 평일(월-금)만 실행, 공휴일 제외
  if (day === 0 || day === 6) return; // 일요일, 토요일 제외
  if (isHoliday(kst)) return; // 공휴일 제외

  // 09:00 ~ 20:00 사이, 30분 마다 실행
  if (hour < 9 || hour > 20) return;
  if (hour === 20 && minute !== 0) return;

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