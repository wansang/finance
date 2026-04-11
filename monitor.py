from analyzer import StockAnalyzer
import FinanceDataReader as fdr
import pandas as pd
import numpy as np
import datetime
import json
import os
import html

class MarketMonitor:
    def __init__(self):
        self.analyzer = StockAnalyzer()
        
    def run(self):
        import sys
        import holidays
        import os
        
        today = datetime.datetime.now()
        kr_holidays = holidays.KR()
        is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        
        # 주말(5: 토요일, 6: 일요일) 이거나 공휴일인 경우 스케줄 실행 안함 (수동 강제 실행 시에는 무조건 동작)
        if not is_manual and (today.weekday() >= 5 or today.date() in kr_holidays):
            print(f"[{today}] 주말 또는 한국 공휴일 휴장일입니다. 실시간 감시를 건너뜁니다.")
            sys.exit(0)
            
        print(f"[{today}] AI 기반 실시간 감시 시작...")
        
        holdings = self.analyzer.load_holdings()
        watchlist = self.analyzer.load_watchlist()
        
        # 1. 시장 심리 요약 데이터 확보
        sentiment_msg, is_positive = self.analyzer.get_market_sentiment()
        
        # 2. 보유 종목 데이터 수집
        holding_data = []
        sell_triggered = False
        for code, info in holdings.items():
            try:
                name = info.get('name', code)
                buy_date = info.get('buy_date')
                buy_price = info.get('buy_price', 0)
                
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=100)).strftime('%Y-%m-%d'))
                df = self.analyzer.get_indicators(df)
                
                triggered, drop_pct = self.analyzer.check_trailing_stop(df, buy_date)
                current_price = df.iloc[-1]['Close']
                profit_pct = (current_price - buy_price) / buy_price * 100
                
                status = "매도 권장" if triggered else "포지션 유지"
                if triggered: sell_triggered = True
                
                holding_data.append(f"- {name}: 현재가 {current_price:,.0f}원 (수익률 {profit_pct:+.2f}%), 상태: {status}")
            except Exception as e:
                holding_data.append(f"- {code}: 분석 오류")

        # 3. 관심 종목 데이터 수집
        watch_data = []
        for code, info in watchlist.items():
            try:
                name = info.get('name', code)
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=100)).strftime('%Y-%m-%d'))
                df = self.analyzer.get_indicators(df)
                
                reasons = self.analyzer.check_signals(df, -1)
                sig_text = ", ".join(reasons) if reasons else "특이 신호 없음"
                watch_data.append(f"- {name}: {sig_text}")
            except Exception as e:
                watch_data.append(f"- {code}: 분석 오류")

        # 4. AI 리포트 생성
        final_report = self.analyzer.ask_ai_report(
            market_data=sentiment_msg,
            holding_data="\n".join(holding_data) if holding_data else "없음",
            watch_data="\n".join(watch_data) if watch_data else "없음"
        )
        
        # 매도 신호가 있을 경우 제목 추가
        if sell_triggered:
            final_report = "🚨 <b>[매도 긴급 신호 포착]</b>\n\n" + final_report
        else:
            final_report = "🕒 <b>[30분 정기 AI 시장 감시]</b>\n\n" + final_report
            
        self.analyzer.notifier.send_message(final_report)
        print("AI 감시 보고서 전송 완료.")

if __name__ == "__main__":
    monitor = MarketMonitor()
    monitor.run()
