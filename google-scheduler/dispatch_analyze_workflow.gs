const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
const WORKFLOW_FILE = 'analyze.yml';
const GITHUB_PAT = PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');

// 한국 공휴일 리스트 (YYYY-MM-DD)
const HOLIDAYS = [
  // 2025
  '2025-01-01', // 신정
  '2025-01-28', // 설날
  '2025-01-29', // 설날
  '2025-01-30', // 설날
  '2025-03-01', // 삼일절
  '2025-05-05', // 어린이날
  '2025-05-06', // 대체공휴일
  '2025-05-13', // 석가탄신일
  '2025-06-06', // 현충일
  '2025-08-15', // 광복절
  '2025-10-03', // 개천절
  '2025-10-05', // 추석
  '2025-10-06', // 추석
  '2025-10-07', // 추석
  '2025-10-08', // 대체공휴일
  '2025-10-09', // 한글날
  '2025-12-25', // 크리스마스
  // 2026
  '2026-01-01', // 신정
  '2026-02-17', // 설날
  '2026-02-18', // 설날
  '2026-02-19', // 설날
  '2026-03-01', // 삼일절
  '2026-05-05', // 어린이날
  '2026-05-06', // 대체공휴일
  '2026-05-24', // 석가탄신일
  '2026-06-06', // 현충일
  '2026-08-15', // 광복절
  '2026-09-24', // 추석
  '2026-09-25', // 추석
  '2026-09-26', // 추석
  '2026-10-03', // 개천절
  '2026-10-09', // 한글날
  '2026-12-25', // 크리스마스
];

function isHoliday(date) {
  const dateStr = date.getFullYear() + '-' +
                  String(date.getMonth() + 1).padStart(2, '0') + '-' +
                  String(date.getDate()).padStart(2, '0');
  return HOLIDAYS.includes(dateStr);
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
