const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'monitor.yml';
const GITHUB_PAT = PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');

// 2026년 한국 공휴일 리스트 (YYYY-MM-DD 형식)
const HOLIDAYS_2026 = [
  '2026-01-01', // 신정
  '2026-02-17', // 설날
  '2026-02-18', // 설날
  '2026-03-01', // 삼일절
  '2026-05-05', // 어린이날
  '2026-05-06', // 대체공휴일 (어린이날)
  '2026-05-24', // 석가탄신일
  '2026-06-06', // 현충일
  '2026-08-15', // 광복절
  '2026-09-24', // 추석
  '2026-09-25', // 추석
  '2026-10-03', // 개천절
  '2026-10-09', // 한글날
  '2026-12-25'  // 크리스마스
];

function isHoliday(date) {
  const dateStr = date.getFullYear() + '-' + 
                  String(date.getMonth() + 1).padStart(2, '0') + '-' + 
                  String(date.getDate()).padStart(2, '0');
  return HOLIDAYS_2026.includes(dateStr);
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