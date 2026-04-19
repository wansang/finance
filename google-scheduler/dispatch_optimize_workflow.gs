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
  if (day !== 6) {
    Logger.log('토요일 아님 스킵: ' + kst.toLocaleString('ko-KR'));
    return;
  }
  if (hour !== 9 || minute !== 0) {
    Logger.log('실행 시간 외 스킵 (' + hour + ':' + String(minute).padStart(2,'0') + '): ' + kst.toLocaleString('ko-KR'));
    return;
  }

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
