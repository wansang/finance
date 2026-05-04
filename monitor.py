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
                name = info.get('name', code)
                buy_date = info.get('buy_date')
                buy_price = info.get('buy_price', 0)
                
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=100)).strftime('%Y-%m-%d'))
                df = self.analyzer.get_indicators(df)
                
                triggered, drop_pct = self.analyzer.check_trailing_stop(df, buy_date)
                latest_price = self.analyzer.get_latest_price(code)
                if latest_price:
                    current_price = latest_price['last']
                    prev_price = latest_price.get('prev_close') or latest_price.get('previous')
                else:
                    current_price = df.iloc[-1]['Close']
                    prev_price = df.iloc[-2]['Close'] if len(df) > 1 else current_price
                profit_pct = (current_price - buy_price) / buy_price * 100
                price_text = self.analyzer.format_price(current_price, code)
                change_text = self.analyzer.format_price_change(current_price, prev_price, code)
                high_price = self.analyzer.get_intraday_high(code)
                high_text = self.analyzer.format_price(high_price, code) if high_price is not None else None
                volume = self.analyzer.get_intraday_volume(code)
                volume_text = self.analyzer.format_volume(volume, code)

                if triggered:
                    status = "매도 권장"
                    reason = f"매수 이후 최고가 대비 {drop_pct:.2f}% 하락하여 손실 제한 조건이 충족되었습니다."
                    sell_triggered = True
                else:
                    status = "포지션 유지"
                    if profit_pct >= 0:
                        reason = "현재 수익 구간이며 하락 제한 조건이 아직 충족되지 않아 보유를 유지합니다."
                    else:
                        reason = "현재는 손실 구간이나 매도 기준에는 미달하여 추가 관찰이 필요합니다."

                high_52w = self.analyzer.get_52week_high(code)
                high_52w_text = self.analyzer.format_price(high_52w, code) if high_52w is not None else None
                near_high_label = ""
                if high_52w and current_price >= high_52w * 0.98:
                    if current_price >= high_52w:
                        near_high_label = " 📈 52주 신고가 돌파!"
                    else:
                        near_high_label = " 📈 52주 신고가 근접"

                # 보유종목 손절가·목표가 계산 (현재가 기준 트레일링 스톱 + BB상단)
                entry_info = self.analyzer.calculate_holding_targets(df, code, buy_date)
                entry_suffix = (f" | {self.analyzer.format_holding_targets(entry_info, code)}") if entry_info else ""

                holding_data.append(
                    self._format_monitor_line(
                        name,
                        price_text,
                        change_text,
                        high_text,
                        volume_text,
                        f"수익률 {profit_pct:+.2f}%, 상태: {status}. 이유: {reason}{near_high_label}{entry_suffix}",
                        high_52w_text=high_52w_text
                    )
                )
            except Exception:
                holding_data.append(f"- {code}: 분석 오류")

        # 3. 관심 종목 데이터 수집 (일반 관심종목 / AI 추천 관심종목 / 지금진입가능 분리)
        watch_data = []
        ai_watch_data = []
        entry_now_data = []  # 매수 신호가 포착된 관심종목 (즉시 진입 가능)
        for code, info in watchlist.items():
            try:
                name = info.get('name', code)
                is_ai_recommended = info.get('source') == 'auto_recommendation'

                # AI 추천 종목은 승률/수익률 계산을 위해 더 많은 데이터 필요
                fetch_days = 400 if is_ai_recommended else 100
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=fetch_days)).strftime('%Y-%m-%d'))
                df = self.analyzer.get_indicators(df)

                latest_price = self.analyzer.get_latest_price(code)
                if latest_price:
                    current_price = latest_price['last']
                    prev_price = latest_price.get('prev_close') or latest_price.get('previous')
                else:
                    current_price = df.iloc[-1]['Close']
                    prev_price = df.iloc[-2]['Close'] if len(df) > 1 else current_price
                price_text = self.analyzer.format_price(current_price, code)
                change_text = self.analyzer.format_price_change(current_price, prev_price, code)
                high_price = self.analyzer.get_intraday_high(code)
                high_text = self.analyzer.format_price(high_price, code) if high_price is not None else None
                volume = self.analyzer.get_intraday_volume(code)
                volume_text = self.analyzer.format_volume(volume, code)

                reasons = self.analyzer.check_signals(df, -1)
                has_signal = bool(reasons)
                if has_signal:
                    sig_text = " / ".join(reasons)
                else:
                    sig_text = "현재 매수 신호는 없습니다."
                high_52w = self.analyzer.get_52week_high(code)
                high_52w_text = self.analyzer.format_price(high_52w, code) if high_52w is not None else None
                near_high_label = ""
                if high_52w and current_price >= high_52w * 0.98:
                    if current_price >= high_52w:
                        near_high_label = " 📈 52주 신고가 돌파!"
                    else:
                        near_high_label = " 📈 52주 신고가 근접"

                # 진입가 계산 (신호 유무 상관없이 항상 계산)
                entry_info = self.analyzer.calculate_entry_price(df, code)
                entry_suffix = (f" | {self.analyzer.format_entry_info(entry_info, code)}") if entry_info else ""

                # 진입 가능 판단: 신호 발생 AND 현재가가 진입가 대비 5% 이내
                # (현재가가 진입가보다 훨씬 높으면 신호가 있어도 "대기" 섹션으로 분류)
                ENTRY_TOLERANCE = 0.05
                at_or_near_entry = (
                    entry_info is not None and
                    entry_info.get('entry') is not None and
                    current_price <= entry_info['entry'] * (1 + ENTRY_TOLERANCE)
                )
                is_enterable = has_signal and at_or_near_entry

                if is_ai_recommended:
                    # Tier 1 지표 추가 계산 (승률 / 평균수익률)
                    win_rate, avg_ret = self.analyzer.validate_strategy(df, len(df) - 1)
                    add_date = info.get('add_date', '')
                    detail = (
                        f"신호: {sig_text}, 승률: {win_rate:.1f}%, "
                        f"평균수익률: {avg_ret:+.2f}%, 추가일: {add_date}{near_high_label}{entry_suffix}"
                    )
                    line = self._format_monitor_line(
                        name, price_text, change_text, high_text, volume_text, detail,
                        high_52w_text=high_52w_text
                    )
                    if is_enterable:
                        entry_now_data.append(f"{line}  [AI추천]")
                        entry_stocks_detail.append({
                            'name': name, 'code': code,
                            'current_price': current_price,
                            'entry': entry_info['entry'],
                            'stop_loss': entry_info['stop_loss'],
                            'target': entry_info['target'],
                            'signals': sig_text,
                            'rsi': float(df.iloc[-1]['RSI']) if 'RSI' in df.columns else None,
                            'volume_ratio': float(df.iloc[-1]['Volume'] / df.iloc[-1]['VOL_AVG']) if 'VOL_AVG' in df.columns else None,
                            'near_52w_high': bool(high_52w and current_price >= high_52w * 0.98),
                            'is_etf': info.get('sector') == 'ETF',
                        })
                    else:
                        ai_watch_data.append(line)
                else:
                    line = self._format_monitor_line(
                        name, price_text, change_text, high_text, volume_text,
                        f"신호: {sig_text}{near_high_label}{entry_suffix}",
                        high_52w_text=high_52w_text
                    )
                    if is_enterable:
                        entry_now_data.append(line)
                        entry_stocks_detail.append({
                            'name': name, 'code': code,
                            'current_price': current_price,
                            'entry': entry_info['entry'],
                            'stop_loss': entry_info['stop_loss'],
                            'target': entry_info['target'],
                            'signals': sig_text,
                            'rsi': float(df.iloc[-1]['RSI']) if 'RSI' in df.columns else None,
                            'volume_ratio': float(df.iloc[-1]['Volume'] / df.iloc[-1]['VOL_AVG']) if 'VOL_AVG' in df.columns else None,
                            'near_52w_high': bool(high_52w and current_price >= high_52w * 0.98),
                            'is_etf': False,  # 일반 관심종목 (주식)
                        })
                    else:
                        watch_data.append(line)
            except Exception:
                if info.get('source') == 'auto_recommendation':
                    ai_watch_data.append(f"- {code}: 분석 오류")
                else:
                    watch_data.append(f"- {code}: 분석 오류")

        # 4. 지금진입가능 종목 타이밍 의견 (Gemini 1회 호출)
        if entry_stocks_detail:
            print(f"[Monitor] 진입가능 {len(entry_stocks_detail)}개 종목 타이밍 의견 요청 중...")
            timing_opinions = self.analyzer.ask_entry_timing_opinions(
                entry_stocks_detail, market_context=sentiment_msg.strip()
            )
            if timing_opinions:
                annotated = []
                for line in entry_now_data:
                    matched_opinion = None
                    for name_key, opinion in timing_opinions.items():
                        if name_key in line:
                            matched_opinion = opinion
                            break
                    if matched_opinion:
                        stock_op = matched_opinion.get('stock_expert', '').strip()
                        etf_op = matched_opinion.get('etf_expert', '').strip()
                        op_text = ""
                        if stock_op:
                            op_text += f"\n  📊 [주식전문가] {stock_op}"
                        if etf_op:
                            op_text += f"\n  🌐 [ETF전문가] {etf_op}"
                        annotated.append(line + op_text)
                    else:
                        annotated.append(line)
                entry_now_data = annotated

        # 5. AI 리포트 생성
        market_section = sentiment_msg.strip()
        holding_section = "\n\n".join(holding_data) if holding_data else "없음"
        watch_section = "\n\n".join(watch_data) if watch_data else "없음"
        ai_watch_section = "\n\n".join(ai_watch_data) if ai_watch_data else "없음"
        entry_now_section = "\n\n".join(entry_now_data) if entry_now_data else "없음"

        final_report = self.analyzer.ask_ai_report(
            market_data=market_section,
            holding_data=holding_section,
            watch_data=watch_section,
            report_mode="monitor",
            ai_watch_data=ai_watch_section,
            entry_now_data=entry_now_section
        )
        
        final_report = "🕒 <b>[실시간 모니터링 알림]</b>\n\n" + final_report.strip()

        self.analyzer.notifier.send_message(final_report)
        print("AI 감시 보고서 전송 완료.")

if __name__ == "__main__":
    monitor = MarketMonitor()
    monitor.run()