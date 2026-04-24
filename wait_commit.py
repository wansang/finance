"""
백테스트(PID=40289) 완료 대기 후 git add/commit/push 수행
"""
import os
import subprocess
import time
import sys

TARGET_PID = 40289
BASE_DIR = "/Users/wansangryu/finance"

print(f"[wait_commit] PID {TARGET_PID} 완료 대기 중...")
sys.stdout.flush()

while True:
    try:
        os.kill(TARGET_PID, 0)
        time.sleep(10)
    except ProcessLookupError:
        break

print("[wait_commit] 프로세스 종료 확인. 3초 후 결과 처리...")
sys.stdout.flush()
time.sleep(3)

# 결과 파일 줄 수 확인
with open(os.path.join(BASE_DIR, "backtest_results.md"), encoding="utf-8") as f:
    content = f.read()
lines = content.count("\n")
print(f"[wait_commit] backtest_results.md: {lines}줄")
print("[wait_commit] 마지막 30줄:")
print("\n".join(content.splitlines()[-30:]))
sys.stdout.flush()

# git add & commit & push
os.chdir(BASE_DIR)
files = [
    "backtest_results.md",
    "backtest_strategies.py",
    "run_backtest.sh",
    "backtest_run2.log",
]
subprocess.run(["git", "add"] + files, check=False)

commit_msg = (
    "feat: 전략별 백테스트 결과 기록 (20개 파라미터 조합)\n\n"
    "완료 전략 목록:\n"
    "- 전략4: BB+RSI 복합 (현재시스템) - 191건, 승률54.5%, 평균+1.51%\n"
    "- 전략2: SMA 크로스오버 3종\n"
    "- 전략5: 52주 신고가 돌파 - 79.2% 승률, 평균+18.87% (최고 수익률)\n"
    "- 전략1: 모멘텀 3종\n"
    "- 전략6: 거래량 돌파 2종 (손실 전략)\n"
    "- 전략3: RSI 평균회귀 - Sharpe 4.06 (최고 Sharpe)\n"
    "- 전략9: StochRSI 반등 2종\n"
    "- 전략8: 터틀 트레이딩 2종\n"
    "- 전략10: MFI 강세 다이버전스\n"
    "- 전략7: 듀얼 모멘텀 2종"
)

result = subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
sys.stdout.flush()

push_result = subprocess.run(["git", "push"], capture_output=True, text=True)
print(push_result.stdout)
print(push_result.stderr)
sys.stdout.flush()

print("[wait_commit] 완료! git push 성공")
