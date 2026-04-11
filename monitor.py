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
        print(f"[{datetime.datetime.now()}] 실시간 감시 시작...")
        
        holdings = self.analyzer.load_holdings()
        watchlist = self.analyzer.load_watchlist()
        
        sentiment_msg, is_positive = self.analyzer.get_market_sentiment()
        
        report = "<b>[🕒 30분 정기 실시간 감시 보고]</b>\n"
        report += f"감시 시간: {datetime.datetime.now().strftime('%H:%M')}\n\n"
        report += sentiment_msg + "\n"
        
        # 1. 보유 종목 분석
        report += "\n<b>[🏦 보유 종목 현황]</b>\n"
        sell_triggered = False
        hold_lines = []
        
        for code, info in holdings.items():
            try:
                name = info.get('name', code)
                buy_date = info.get('buy_date')
                buy_price = info.get('buy_price', 0)
                
                start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d')
                df = fdr.DataReader(code, start=start_date)
                df = self.analyzer.get_indicators(df)
                
                triggered, drop_pct = self.analyzer.check_trailing_stop(df, buy_date)
                current_price = df.iloc[-1]['Close']
                profit_pct = (current_price - buy_price) / buy_price * 100
                
                status_emoji = "✅"
                action_text = "포지션 유지"
                reason_text = "시장 흐름이 양호하며 상승 추세를 유지하고 있습니다." if is_positive else "지수는 불안정하지만 종목의 지지선이 견고합니다."
                
                if triggered:
                    status_emoji = "🚨"
                    action_text = "<b>매도 대응 권장</b>"
                    if is_positive:
                        reason_text = "시장은 우호적이나 종목의 단기 낙폭이 큽니다. 분할 매도로 대응하세요."
                    else:
                        reason_text = "시장 악화와 함께 종목의 지지선이 이탈되었습니다. 리스크 관리가 필요합니다."
                    sell_triggered = True

                line = f"{status_emoji} <b>{name}</b>: {action_text}\n"
                line += f"  └ 수익률: {profit_pct:+.2f}% | 사유: {reason_text}\n"
                hold_lines.append(line)
            except Exception as e:
                hold_lines.append(f"⚠️ {code}: 데이터 확인 불가")

        report += "".join(hold_lines) if hold_lines else "보유 종목이 없습니다.\n"

        # 2. 관심 종목 분석
        report += "\n<b>[👀 관심 종목 모니터링]</b>\n"
        watch_lines = []
        for code, info in watchlist.items():
            try:
                name = info.get('name', code)
                start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d')
                df = fdr.DataReader(code, start=start_date)
                df = self.analyzer.get_indicators(df)
                
                reasons = self.analyzer.check_signals(df, -1)
                
                if reasons:
                    line = f"💰 <b>{name}</b>: 매수 기회 포착!\n"
                    line += f"  └ 신호: {', '.join(reasons)}\n"
                else:
                    line = f"⌛ <b>{name}</b>: 상승 에너지 응축 중\n"
                    line += "  └ 관망: 아직 확실한 매수 신호가 나오지 않았습니다.\n"
                watch_lines.append(line)
            except Exception as e:
                watch_lines.append(f"⚠️ {code}: 데이터 확인 불가")
        
        report += "".join(watch_lines) if watch_lines else "관심 종목이 없습니다.\n"
        
        if sell_triggered:
            report = "📢 <b>[매도 긴급 신호 포착]</b>\n\n" + report
            
        self.analyzer.notifier.send_message(report)
        print("감시 보고서 전송 완료.")

if __name__ == "__main__":
    monitor = MarketMonitor()
    monitor.run()
