// ============================================================
// Finance Bot - GitHub Actions 스케줄러
// - dispatchAnalyzeWorkflow : 평일 오전 8~9시 (공휴일 제외)
// - dispatchOptimizeWorkflow: 토요일 오전 9시 정각
// - dispatchMonitorWorkflow : 평일 오전 9시 ~ 오후 8시, 30분마다
// ============================================================

const GITHUB_OWNER = 'wansang';
const GITHUB_REPO = 'finance';
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

function dispatchWorkflow(workflowFile) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${workflowFile}/dispatches`;
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
  Logger.log('[' + workflowFile + '] 응답: ' + response.getResponseCode());
  Logger.log(response.getContentText());
}

// 평일 오전 8~9시 실행 (공휴일 제외) → 트리거: 하루 타이머 오전 8~9시
function dispatchAnalyzeWorkflow() {
  const now = new Date();
  const kst = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
  const day = kst.getDay();
  const hour = kst.getHours();

  if (day === 0 || day === 6) { Logger.log('주말 스킵'); return; }
  if (hour < 8 || hour >= 9) { Logger.log('시간 외 스킵 (' + hour + '시)'); return; }
  if (isHoliday(kst)) { Logger.log('공휴일 스킵'); return; }

  Logger.log('Analyze 실행: ' + kst.toLocaleString('ko-KR'));
  dispatchWorkflow('analyze.yml');
}

// 토요일 오전 9시 정각 실행 → 트리거: 하루 타이머 오전 9~10시
function dispatchOptimizeWorkflow() {
  const now = new Date();
  const kst = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
  const day = kst.getDay();
  const hour = kst.getHours();
  const minute = kst.getMinutes();

  if (day !== 6) { Logger.log('토요일 아님 스킵'); return; }
  if (hour !== 9 || minute !== 0) { Logger.log('시간 외 스킵 (' + hour + ':' + String(minute).padStart(2,'0') + ')'); return; }

  Logger.log('Optimize 실행: ' + kst.toLocaleString('ko-KR'));
  dispatchWorkflow('optimize.yml');
}

// 평일 오전 9시~오후 8시, 30분마다 실행 → 트리거: 분 단위 타이머 30분마다
function dispatchMonitorWorkflow() {
  const now = new Date();
  const kst = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
  const day = kst.getDay();
  const hour = kst.getHours();
  const minute = kst.getMinutes();

  if (day === 0 || day === 6) { Logger.log('주말 스킵'); return; }
  if (isHoliday(kst)) { Logger.log('공휴일 스킵'); return; }
  if (hour < 9 || hour > 20) { Logger.log('시간 외 스킵 (' + hour + '시)'); return; }
  if (hour === 20 && minute !== 0) { Logger.log('20시 정각 아님 스킵'); return; }

  Logger.log('Monitor 실행: ' + kst.toLocaleString('ko-KR'));
  dispatchWorkflow('monitor.yml');
}
