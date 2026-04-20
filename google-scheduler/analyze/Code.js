const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'analyze.yml';

function isHoliday(date) {
  const cal = CalendarApp.getCalendarById('ko.south_korea#holiday@group.v.calendar.google.com');
  return cal.getEventsForDay(date).length > 0;
}

function dispatchAnalyzeWorkflow() {
  const kst = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));

  if (isHoliday(kst)) {
    Logger.log('공휴일 스킵: ' + kst.toLocaleDateString('ko-KR'));
    return;
  }

  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');
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
  const response = UrlFetchApp.fetch(url, options);
  Logger.log(response.getResponseCode());
  Logger.log(response.getContentText());
}