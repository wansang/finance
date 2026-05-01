from analyzer import StockAnalyzer
import FinanceDataReader as fdr
import pandas as pd
import numpy as np
import datetime
import json
import os
import html
from zoneinfo import ZoneInfo

class MarketMonitor:
    def __init__(self):
        self.analyzer = StockAnalyzer()
        
    def _format_monitor_line(self, name, price_text, change_text, high_text, volume_text, detail, high_52w_text=None):
        high_segment = f", 당일최고가 {high_text}" if high_text else ""
        high_52w_segment = f", 52주신고가 {high_52w_text}" if high_52w_text else ""
        vol_segment = f", 거래량 {volume_text}" if volume_text else ""
        return f"- {name}: 현재가 {price_text} {change_text}{high_segment}{high_52w_segment}{vol_segment}. {detail}"

    def run(self):
        import sys
        import holidays
        import os
        
        today = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
        kr_holidays = holidays.KR()
        is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        force_run = os.environ.get("FORCE_RUN", "").lower() in ("1", "true", "yes")
        
        # 주말(5: 토요일, 6: 일요일) 또는 공휴일인 경우 스케줄 실행 안함
        # 단, 수동 실행(workflow_dispatch) 또는 FORCE_RUN=true일 경우에는 강제 실행합니다.
        if today.weekday() >= 5 or today.date() in kr_holidays:
            if is_manual or force_run:
                print(f"[{today}] 수동 실행/강제 실행 모드로 주말/공휴일 체크를 무시하고 실시간 감시를 진행합니다.")
            else:
                print(f"[{today}] 주말 또는 한국 공휴일 휴장일입니다. 실시간 감시를 건너뜁니다.")
                sys.exit(0)
        
        if force_run and not is_manual:
            print("FORCE_RUN이 활성화되어 있어 강제 실행합니다.")
        
        print(f"[{today}] AI 기반 실시간 감시 시작...")
        
        holdings = self.analyzer.load_holdings()
        self.analyzer.clean_watchlist()
        watchlist = self.analyzer.load_watchlist()
        
        # 1. 시장 심리 요약 데이터 확보
        sentiment_msg, is_positive = self.analyzer.get_market_sentiment()
        
        # 2. 보유 종목 데이터 수집
        holding_data = []
        sell_triggered = False
        for code, info in holdings.items():
            try:
                    pass
            except Exception as e:
                pass  # 예외 처리

        # 3. 관심 종목 데이터 수집 (일반 관심종목 / AI 추천 관심종목 분리)
        watch_data = []
        ai_watch_data = []
        def run(self):
            import sys
            import holidays
            import os
            today = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
            kr_holidays = holidays.KR()
            is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
            force_run = os.environ.get("FORCE_RUN", "").lower() in ("1", "true", "yes")

            # 주말/공휴일 체크
            if today.weekday() >= 5 or today.date() in kr_holidays:
                if is_manual or force_run:
                    print(f"[{today}] 수동 실행/강제 실행 모드로 주말/공휴일 체크를 무시하고 실시간 감시를 진행합니다.")
                else:
                    print(f"[{today}] 주말 또는 한국 공휴일 휴장일입니다. 실시간 감시를 건너뜁니다.")
                    sys.exit(0)
            if force_run and not is_manual:
                print("FORCE_RUN이 활성화되어 있어 강제 실행합니다.")
            print(f"[{today}] AI 기반 실시간 감시 시작...")

            holdings = self.analyzer.load_holdings()
            self.analyzer.clean_watchlist()
            watchlist = self.analyzer.load_watchlist()
            sentiment_msg, is_positive = self.analyzer.get_market_sentiment()

            # 2. 보유 종목 데이터 수집
            holding_data = []
            sell_triggered = False
            for code, info in holdings.items():
                try:
                    # 실제 보유 종목 데이터 처리 로직 (예: 수익률, 가격, 신호 등)
                    pass
                except Exception as e:
                    pass

            # 3. 관심 종목 데이터 수집
            watch_data = []
            ai_watch_data = []
            instant_entry_watch_data = []
            instant_entry_ai_watch_data = []
            for code, info in watchlist.items():
                try:
                    # 실제 관심종목 데이터 처리 로직 (예: 신호, AI 추천 등)
                    pass
                except Exception as e:
                    pass

            # 4. AI 리포트 생성 및 전송
            market_section = sentiment_msg.strip()
            holding_section = "\n\n".join(holding_data) if holding_data else "없음"
            watch_section = "\n\n".join(watch_data) if watch_data else "없음"
            ai_watch_section = "\n\n".join(ai_watch_data) if ai_watch_data else "없음"

            # 즉시 진입 가능 종목 섹션 생성
            instant_entry_section = ""
            instant_lines = []
            if instant_entry_watch_data:
                instant_lines.append("[관심종목 즉시 진입가능 종목]\n" + "\n".join(instant_entry_watch_data))
            if instant_entry_ai_watch_data:
                instant_lines.append("[AI 추천 관심종목 즉시 진입가능 종목]\n" + "\n".join(instant_entry_ai_watch_data))
            if instant_lines:
                instant_entry_section = "\n\n".join(instant_lines) + "\n\n"

            final_report = self.analyzer.ask_ai_report(
                market_data=market_section,
                holding_data=holding_section,
                watch_data=watch_section,
                report_mode="monitor",
                ai_watch_data=ai_watch_section
            )
            final_report = "🕒 <b>[실시간 모니터링 알림]</b>\n\n" + instant_entry_section + final_report.strip()
            self.analyzer.notifier.send_message(final_report)
            print("AI 감시 보고서 전송 완료.")

        self.analyzer.notifier.send_message(final_report)
        print("AI 감시 보고서 전송 완료.")

if __name__ == "__main__":
    monitor = MarketMonitor()
    monitor.run()