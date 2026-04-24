#!/bin/zsh
# 백테스트 완료 대기 후 git commit
cd /Users/wansangryu/finance
source .venv/bin/activate

echo "[wait_and_commit] 백테스트 완료 대기 중... (PID=40289)"
while kill -0 40289 2>/dev/null; do
    sleep 10
done

echo "[wait_and_commit] 프로세스 종료 감지 - 결과 확인 중..."
sleep 3

RESULT_LINES=$(wc -l < backtest_results.md)
echo "[wait_and_commit] backtest_results.md: ${RESULT_LINES}줄"
tail -30 backtest_results.md

git add backtest_results.md backtest_strategies.py run_backtest.sh backtest_run2.log
git commit -m "feat: 전략별 백테스트 결과 기록 (20개 파라미터 조합)

완료 전략 목록:
- 전략4: BB+RSI 복합 (현재시스템) — 191건, 승률54.5%, 평균+1.51%
- 전략2: SMA 크로스오버 3종
- 전략5: 52주 신고가 돌파 — 79.2% 승률, 평균+18.87% (최고 수익률)
- 전략1: 모멘텀 3종
- 전략6: 거래량 돌파 2종 (손실 전략 확인)
- 전략3: RSI 평균회귀 — Sharpe 4.06 (최고 Sharpe)
- 전략9: StochRSI 반등 2종
- 전략8: 터틀 트레이딩 2종
- 전략10: MFI 강세 다이버전스
- 전략7: 듀얼 모멘텀 2종"

git push
echo "[wait_and_commit] git push 완료"
