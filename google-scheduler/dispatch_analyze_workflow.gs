const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'analyze.yml';
const GITHUB_PAT = PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');

// Google 대한민국 공휴일 캘린더로 동적 체크 (수동 업데이트 불필요)
function isHoliday(date) {
  const cal = CalendarApp.getCalendarById('ko.south_korea#holiday@group.v.calendar.google.com');
  return cal.getEventsForDay(date).length > 0;
}

function dispatchAnalyzeWorkflow() {
  const now = new Date();
  const kst = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
  const day = kst.getDay();   // 0=일, 1=월, ..., 6=토
  const hour = kst.getHours();

  // 평일(월-금)만 실행
  if (day === 0 || day === 6) {
    Logger.log('주말 스킵: ' + kst.toLocaleString('ko-KR'));
    return;
  }

  // 오전 08:00 ~ 09:00 사이만 실행
  if (hour < 8 || hour >= 9) {
    Logger.log('실행 시간 외 스킵 (' + hour + '시): ' + kst.toLocaleString('ko-KR'));
    return;
  }

  // 공휴일 스킵
  if (isHoliday(kst)) {
    Logger.log('공휴일 스킵: ' + kst.toLocaleDateString('ko-KR'));
    return;
  }

  Logger.log('Analyze 워크플로 실행: ' + kst.toLocaleString('ko-KR'));

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
  const options = {
    method: 'post',
    headers: {
      Authorization: `Bearer ${GITHUB_PAT}`,
      Accept: 'application/vnd.github+json'
    },
    contentType: 'application/json',
    payload: JSON.stringify({ ref: 'main' }),
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url, options);
  Logger.log('응답 코드: ' + response.getResponseCode());
  Logger.log('응답 내용: ' + response.getContentText());
}
