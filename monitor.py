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
        print(f"[{datetime.datetime.now()}] Starting 30-min market monitor...")
        
        holdings = self.analyzer.load_holdings()
        if not holdings:
            print("No holdings to monitor.")
            return

        report = "<b>[🕒 30분 정기 실시간 감시 보고]</b>\n"
        report += f"감시 시간: {datetime.datetime.now().strftime('%H:%M')}\n\n"
        
        sell_triggered = False
        status_lines = []
        
        for code, info in holdings.items():
            try:
                name = info.get('name', code)
                buy_date = info.get('buy_date')
                buy_price = info.get('buy_price', 0)
                
                # 실시간 가격 데이터 (지표 계산을 위해 충분한 400일 데이터 확보)
                start_date = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d')
                df = fdr.DataReader(code, start=start_date)
                df = self.analyzer.get_indicators(df)
                
                # 트레일링 스톱 평가
                triggered, drop_pct = self.analyzer.check_trailing_stop(df, buy_date)
                current_price = df.iloc[-1]['Close']
                profit_pct = (current_price - buy_price) / buy_price * 100
                
                # 마일스톤 알림 (5% 단위)
                milestone_text = ""
                if profit_pct <= -15: milestone_text = "🚨[위험] "
                elif profit_pct <= -10: milestone_text = "⛔[경고] "
                elif profit_pct <= -5: milestone_text = "🔴[유의] "
                elif profit_pct >= 20: milestone_text = "🔥[대박] "
                elif profit_pct >= 15: milestone_text = "💎[급등] "
                elif profit_pct >= 10: milestone_text = "🚀[돌파] "
                elif profit_pct >= 5: milestone_text = "🟢[양호] "

                status_emoji = "✅"
                action_text = "보유(HOLD)"
                
                if triggered:
                    status_emoji = "🚨"
                    action_text = "<b>즉시매도(SELL)</b>"
                    sell_triggered = True

                # HTML 이스케이프 적용 (특수문자 방어)
                safe_name = html.escape(name)
                safe_code = html.escape(code)
                
                line = f"{status_emoji} {milestone_text}<b>{safe_name}({safe_code})</b>: {action_text}\n"
                line += f"  - 현재가: {current_price:,.0f}원 ({profit_pct:+.2f}%)\n"
                line += f"  - 고점대비: -{drop_pct:.2f}%"
                status_lines.append(line)
                
            except Exception as e:
                print(f"Error monitoring {code}: {e}")
                status_lines.append(f"⚠️ {code}: 데이터 오류")

        report += "\n".join(status_lines)
        
        if sell_triggered:
            report = "📢 <b>[매도 긴급 신호 포착]</b>\n\n" + report
            
        self.analyzer.notifier.send_message(report)
        print("Monitor report sent to Telegram.")

if __name__ == "__main__":
    monitor = MarketMonitor()
    monitor.run()
