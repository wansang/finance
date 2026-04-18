from analyzer import StockAnalyzer
import datetime
import os
import sys
from zoneinfo import ZoneInfo
import holidays

# 봇 실행을 위한 import
try:
    from bot import StockBot
    BOT_AVAILABLE = True
except ImportError:
    BOT_AVAILABLE = False

def main():
    # 봇 모드로 실행 (환경변수로 구분)
    if os.environ.get("RUN_BOT") == "true" and BOT_AVAILABLE:
        print("Starting Telegram Bot...")
        bot = StockBot()
        bot.run()
        return

    # 기존 분석 로직
    now_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
    kr_holidays = holidays.KR()
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    force_run = os.environ.get("FORCE_RUN", "").lower() in ("1", "true", "yes")

    # 주말/한국 공휴일에는 자동 스케줄 실행을 건너뜁니다.
    if now_kst.weekday() >= 5 or now_kst.date() in kr_holidays:
        if is_manual or force_run:
            print(f"[{now_kst}] 수동 실행/강제 실행 모드로 주말/공휴일 체크를 무시하고 분석을 진행합니다.")
        else:
            print(f"[{now_kst}] 주말 또는 한국 공휴일 휴장일입니다. 분석을 건너뜁니다.")
            sys.exit(0)

    print("Starting Automated Stock Analysis...")
    analyzer = StockAnalyzer()
    analyzer.run()
    print("Analysis Completed.")

if __name__ == "__main__":
    main()
