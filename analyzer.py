import FinanceDataReader as fdr
import pandas_ta_classic as ta
import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
from notifier import TelegramNotifier
import datetime
import time
import json
import os
import html

class StockAnalyzer:
    def __init__(self):
        self.notifier = TelegramNotifier()
        self.holdings_file = 'holdings.json'
        self.holdings = self.load_holdings()

    def load_holdings(self):
        """보유 종목 데이터 로드"""
        if os.path.exists(self.holdings_file):
            with open(self.holdings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_holdings(self, holdings):
        """보유 종목 데이터 저장"""
        with open(self.holdings_file, 'w', encoding='utf-8') as f:
            json.dump(holdings, f, ensure_ascii=False, indent=4)

    def get_us_market_summary(self):
        """미국 주요 지수 요약 (S&P 500, Nasdaq, Dow)"""
        indices = {
            'S&P 500': 'US500', 
            'Nasdaq': 'IXIC', 
            'Dow': 'DJI'
        }
        summary = "<b>[미국 시장 요약]</b>\n"
        for name, symbol in indices.items():
            try:
                df = fdr.DataReader(symbol)
                last_row = df.iloc[-1]
                prev_row = df.iloc[-2]
                change = last_row['Close'] - prev_row['Close']
                pct_change = (change / prev_row['Close']) * 100
                emoji = "📈" if change > 0 else "📉"
                summary += f"{emoji} {name}: {last_row['Close']:.2f} ({pct_change:+.2f}%)\n"
            except Exception as e:
                summary += f"⚠️ {name}: 데이터 오류\n"
        return summary

    def get_market_sentiment(self):
        """코스피/코스닥 지수 기반 시장 상태 분석"""
        indices = {'코스피': 'KS11', '코스닥': 'KQ11'}
        sentiment_report = "<b>[국내 시장 상태 분석]</b>\n"
        is_positive = False
        
        details = []
        for name, symbol in indices.items():
            try:
                # 최근 40거래일 데이터
                df = fdr.DataReader(symbol, start=(datetime.datetime.now() - datetime.timedelta(days=60)).strftime('%Y-%m-%d'))
                df['SMA20'] = df['Close'].rolling(window=20).mean()
                df['SMA5'] = df['Close'].rolling(window=5).mean()
                
                last = df.iloc[-1]
                prev = df.iloc[-2]
                
                # 상태 판별
                curr_price = last['Close']
                sma20 = last['SMA20']
                sma5 = last['SMA5']
                prev_sma5 = prev['SMA5']
                
                status = "보통"
                emoji = "➡️"
                
                if curr_price > sma20 * 1.01 and sma5 > prev_sma5:
                    status = "<b>우호적</b>"
                    emoji = "🚀"
                    is_positive = True
                elif curr_price < sma20 * 0.99:
                    status = "주의"
                    emoji = "⚠️"
                
                pct = (curr_price - prev['Close']) / prev['Close'] * 100
                details.append(f"{emoji} {name}: {curr_price:,.2f} ({pct:+.2f}%) - {status}")
            except Exception as e:
                details.append(f"⚠️ {name}: 분석 오류")
                
        sentiment_report += "\n".join(details) + "\n"
        return sentiment_report, is_positive

    def get_indicators(self, df, kospi_index=None):
        """기술적 지표 계산 (SMA, RSI, MACD, BB, StochRSI, MFI)"""
        # SMAs for Trend Template
        df['SMA50'] = ta.sma(df['Close'], length=50)
        df['SMA150'] = ta.sma(df['Close'], length=150)
        df['SMA200'] = ta.sma(df['Close'], length=200)
        
        # Relative Strength vs KOSPI Index
        if kospi_index is not None:
            # 주가와 지수의 상대적 수익률 비교 (최근 1년치 기준 가중 평균)
            # 단순화를 위해 최근 120일간의 지수 대비 초과 수익률 합산
            common_idx = df.index.intersection(kospi_index.index)
            if len(common_idx) > 20:
                stock_returns = df.loc[common_idx, 'Close'].pct_change(20)
                index_returns = kospi_index.loc[common_idx, 'Close'].pct_change(20)
                df.loc[common_idx, 'RS_LINE'] = stock_returns - index_returns
        
        # RSI
        df['RSI'] = ta.rsi(df['Close'], length=14)
        
        # MACD
        macd = ta.macd(df['Close'])
        df['MACD'] = macd['MACD_12_26_9']
        df['MACDs'] = macd['MACDs_12_26_9']
        df['MACDh'] = macd['MACDh_12_26_9']
        
        # Bollinger Bands
        bbands = ta.bbands(df['Close'], length=20, std=2)
        df['BBU'] = bbands['BBU_20_2.0']
        df['BBM'] = bbands['BBM_20_2.0']
        df['BBL'] = bbands['BBL_20_2.0']
        df['BBW'] = (df['BBU'] - df['BBL']) / df['BBM']
        
        # Stochastic RSI
        stoch = ta.stochrsi(df['Close'], length=14, rsi_length=14, k=3, d=3)
        df['STOCH_K'] = stoch['STOCHRSIk_14_14_3_3']
        df['STOCH_D'] = stoch['STOCHRSId_14_14_3_3']
        
        # MFI (Money Flow Index)
        df['MFI'] = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
        
        # Volume Average
        df['VOL_AVG'] = df['Volume'].rolling(window=20).mean()
        
        return df

    def detect_divergence(self, df, idx=-1):
        """RSI 상승 다이버전스 감지 (가격은 하락, RSI는 상승)"""
        if len(df[:idx if idx != -1 else len(df)]) < 20: return False
        
        # 기준 시점까지의 데이터
        df_target = df.iloc[:idx+1] if idx != -1 else df
        df_recent = df_target.tail(20)
        
        lows = df_recent['Close'].values
        rsi_vals = df_recent['RSI'].values
        
        if len(lows) < 20: return False
        
        # 최근 5일 vs 그 전 15일
        p1 = lows[:-5].min()
        p2 = lows[-5:].min()
        r1 = rsi_vals[:-5][lows[:-5].argmin()]
        r2 = rsi_vals[-5:][lows[-5:].argmin()]
        
        if p2 < p1 and r2 > r1:
            return True
        return False

    def detect_patterns(self, df, idx=-1):
        """Wedge & Flag 패턴 감지 (단순화된 로직)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 20: return ""
        
        recent_vol = df_target['High'].tail(10).max() - df_target['Low'].tail(10).min()
        prev_vol = df_target['High'].iloc[-20:-10].max() - df_target['Low'].iloc[-20:-10].min()
        
        patterns = []
        if recent_vol < prev_vol * 0.7:
            patterns.append("Wedge(수렴)")
            
        # Flag 패턴: 급등 후 횡보
        returns = df_target['Close'].pct_change(5).iloc[-10:-5]
        if len(returns) > 0 and returns.max() > 0.05: # 5일간 5% 이상 급등 후
            curr_returns = df_target['Close'].pct_change(5).iloc[-1]
            if abs(curr_returns) < 0.02: # 현재는 횡보 중
                patterns.append("Flag(깃발)")
                
        return ", ".join(patterns)

    def is_taj_mahal_signal(self, df, idx=-1):
        """타지마할 밴드 유사 로직 (BB 하단 지지 + RSI 반등)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        prev = df_target.iloc[-2]
        
        # 가격이 BB 하단 부근에서 반등하고 RSI가 40 이상으로 올라올 때
        if prev['Close'] <= prev['BBL'] * 1.01 and last['Close'] > last['BBL']:
            if last['RSI'] > 40 and last['RSI'] > prev['RSI']:
                return True
        return False

    def detect_bb_squeeze(self, df, idx=-1):
        """Bollinger Band Squeeze 감지 (변동성 수렴)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 30: return False
        
        # 현재 BBW가 최근 30일 중 하위 10% 수준인지 확인
        current_bbw = df_target['BBW'].iloc[-1]
        bbw_history = df_target['BBW'].tail(30)
        
        if current_bbw <= bbw_history.quantile(0.1):
            return True
        return False

    def detect_volume_spike(self, df, idx=-1):
        """거래량 급증 감지 (평균 대비 2배 이상)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        if last['Volume'] > last['VOL_AVG'] * 2:
            return True
        return False

    def detect_stoch_mfi_rebound(self, df, idx=-1):
        """Stochastic RSI & MFI 기반 과매도 반등 감지"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        prev = df_target.iloc[-2]
        
        # StochRSI K가 D를 골든크로스하고 20 이하(과매도)에서 반등할 때
        if prev['STOCH_K'] < prev['STOCH_D'] and last['STOCH_K'] > last['STOCH_D']:
            if last['STOCH_K'] < 30 or last['MFI'] < 30:
                return True
        return False

    def check_signals(self, df, idx=-1):
        """다양한 기술적 지표들을 종합하여 매수 신호 확인"""
        reasons = []
        
        # 1. RSI 다이버전스
        if self.detect_divergence(df, idx):
            reasons.append("RSI Divergence")
            
        # 2. Wedge/Flag 패턴
        patterns = self.detect_patterns(df, idx)
        if patterns:
            reasons.append(patterns)
            
        # 3. 타지마할 밴드 (BB 하단 지지 + RSI 반등)
        if self.is_taj_mahal_signal(df, idx):
            reasons.append("바닥권 반등 신호(BB 하단)")
            
        # 4. 볼린저 밴드 스퀴즈 (변동성 수렴)
        if self.detect_bb_squeeze(df, idx):
            reasons.append("에너지 응축(변동성 수렴)")
            
        # 5. 거래량 급증
        if self.detect_volume_spike(df, idx):
            reasons.append("거래량 급증")
            
        # 6. Stochastic RSI & MFI 과매도 반등
        if self.detect_stoch_mfi_rebound(df, idx):
            reasons.append("과매도 반등 신호")
            
        return reasons

    def check_trailing_stop(self, df, buy_date, threshold=0.03):
        """트레일링 스톱 감지 (고점 대비 일정 비율 하락 시 매도)"""
        # buy_date 이후의 데이터만 추출
        df_since_buy = df[df.index >= buy_date]
        if len(df_since_buy) < 1: return False, 0
        
        # 구매 이후 최고가 찾기
        peak_price = df_since_buy['Close'].max()
        current_price = df_since_buy['Close'].iloc[-1]
        
        # 하락률 계산
        drop_pct = (peak_price - current_price) / peak_price
        
        if drop_pct >= threshold:
            return True, drop_pct * 100
        return False, drop_pct * 100

    def is_trend_template(self, df, idx=-1):
        """마크 미너비니의 Trend Template (상승 추세 확인)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 200: return False
        
        last = df_target.iloc[-1]
        
        # 1. 현재가가 150일, 200일 이평선 위에 있음
        c1 = last['Close'] > last['SMA150'] and last['Close'] > last['SMA200']
        # 2. 150일 이평선이 200일 이평선 위에 있음
        c2 = last['SMA150'] > last['SMA200']
        # 3. 200일 이평선이 최소 1개월간 상승 추세 (여기서는 단순하게 현재가 > 20일 전보다 큰지 확인)
        c3 = last['SMA200'] > df_target['SMA200'].iloc[-20]
        # 4. 50일 이평선이 150일, 200일 위에 있음
        c4 = last['SMA50'] > last['SMA150'] and last['SMA50'] > last['SMA200']
        # 5. 현재가가 52주 신고가 대비 25% 이내 (단순화: 최근 250일 최고가 대비)
        high_52w = df_target['Close'].tail(250).max()
        c5 = last['Close'] >= (high_52w * 0.75)
        
        return c1 and c2 and c3 and c4 and c5

    def validate_strategy(self, df, current_idx):
        """특정 종목의 과거 6개월 승률 검증 (미니 백테스트)"""
        # current_idx 기준 과거 120거래일(약 6개월) 분석
        lookback = 120
        start_idx = max(200, current_idx - lookback)
        
        trades = []
        for i in range(start_idx, current_idx):
            reasons = self.check_signals(df, i)
            # 트렌드 템플릿도 맞아야 함
            if reasons and self.is_trend_template(df, i):
                buy_price = df.iloc[i]['Close']
                # 트레일링 스톱 시뮬레이션 (최대 20일간 홀딩)
                max_p = buy_price
                result = -0.03 # 기본 손절
                for j in range(i + 1, min(i + 21, current_idx + 1)):
                    curr_p = df.iloc[j]['Close']
                    if curr_p > max_p: max_p = curr_p
                    if (max_p - curr_p) / max_p >= 0.03:
                        result = (curr_p - buy_price) / buy_price
                        break
                    if j == i + 20: # 타임컷
                        result = (curr_p - buy_price) / buy_price
                trades.append(result)
        
        if not trades: return 0, 0
        win_rate = len([t for t in trades if t > 0]) / len(trades) * 100
        avg_ret = sum(trades) / len(trades) * 100
        return win_rate, avg_ret

    def analyze_kospi(self, target_date=None):
        """코스피 전 종목 정밀 분석 (Tiered System)"""
        stocks = fdr.StockListing('KOSPI')
        kospi_index = fdr.DataReader('KS11', start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        
        results = {1: [], 2: [], 3: []}
        count = 0
        total = len(stocks)
        
        print(f"Starting Tiered Analysis for {total} stocks...")
        
        for _, stock in stocks.iterrows():
            code = stock['Code']
            name = stock['Name']
            
            try:
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d'))
                if len(df) < 200: continue
                
                df = self.get_indicators(df, kospi_index)
                target_idx = len(df) - 1
                if target_date:
                    df_target = df[df.index <= target_date]
                    if len(df_target) < 1: continue
                    target_idx = len(df_target) - 1
                
                reasons = self.check_signals(df, target_idx)
                if not reasons: continue

                # 지표 추출
                last = df.iloc[target_idx]
                win_rate, avg_ret = self.validate_strategy(df, target_idx)
                is_elite = self.is_trend_template(df, target_idx)
                is_above_200 = last['Close'] > last['SMA200']
                rs_score = last['RS_LINE'] if 'RS_LINE' in last else 0
                
                safe_name = html.escape(name)
                safe_reasons = html.escape(", ".join(reasons))
                
                stock_data = {
                    'name': safe_name, 'code': code, 'reasons': safe_reasons,
                    'win_rate': win_rate, 'avg_ret': avg_ret, 'rs_score': rs_score
                }

                # Tier Classification
                if is_elite and win_rate >= 60:
                    results[1].append(stock_data)
                elif is_above_200 and win_rate >= 50:
                    results[2].append(stock_data)
                elif win_rate >= 40:
                    results[3].append(stock_data)
                
                count += 1
                if count % 200 == 0: print(f"Analyzed {count}/{total} stocks...")
            except Exception:
                continue

        # 결과 포맷팅
        formatted_recs = []
        tier_names = {1: "🥇 1등급 (Elite Setup)", 2: "🥈 2등급 (Strong Trend)", 3: "🥉 3등급 (Active Signal)"}
        
        for t in [1, 2, 3]:
            if not results[t]: continue
            # RS_SCORE 기준 정렬
            results[t].sort(key=lambda x: x['rs_score'], reverse=True)
            
            formatted_recs.append(f"\n<b>{tier_names[t]}</b>")
            for r in results[t][:5]: # 각 등급별 상위 5개만 노출
                msg = f"• <b>{r['name']}</b>({r['code']}): {r['reasons']}\n"
                formatted_recs.append(msg)
            
        return formatted_recs, results

    def analyze_holdings(self):
        """보유 종목의 매도 타이밍(트레일링 스톱) 분석"""
        sell_alerts = []
        if not self.holdings: return sell_alerts
        
        print(f"Analyzing {len(self.holdings)} current holdings...")
        for code, info in self.holdings.items():
            try:
                name = info.get('name', code)
                buy_date = info.get('buy_date')
                if not buy_date: continue
                
                # 충분한 데이터 가져오기
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=100)).strftime('%Y-%m-%d'))
                df = self.get_indicators(df)
                
                triggered, drop_pct = self.check_trailing_stop(df, buy_date)
                
                if triggered:
                    safe_name = html.escape(name)
                    sell_alerts.append(f"🚨 <b>{safe_name}({code}) 매도 알림</b>: 고점 대비 {drop_pct:.2f}% 하락 (트레일링 스톱)")
            except Exception as e:
                continue
        return sell_alerts

        # 0. 시장 상태 분석
        sentiment_msg, is_positive = self.get_market_sentiment()
        
        # 1. 새 추천 종목 분석
        recs_msg, recs_raw = self.analyze_kospi()
        
        # 2. 보유 종목 매도 타이밍 분석
        sell_alerts = self.analyze_holdings()
        
        report = us_summary + "\n" + sentiment_msg
        
        if sell_alerts:
            advice = ""
            if is_positive:
                advice = "\n💡 <i>시장이 우호적이므로 매도 결정을 신중히(분할 매도 등) 하셔도 좋습니다.</i>"
            report += "\n<b>[🚨 매도 알림]</b>\n" + "\n".join(sell_alerts) + advice + "\n"
            
        report += "\n<b>[📊 추천 종목 분석 결과]</b>\n"
        if recs_msg:
            report += "".join(recs_msg[:15]) # 메시지 길이 제한
            if len(recs_msg) > 15:
                report += f"\n...외 {len(recs_msg)-15}개 종목"
        else:
            report += "조건에 맞는 추천 종목이 없습니다."
            
        # 3. 추천 내역 기록 (CSV 저장)
        self.log_recommendations(recs_raw)
            
        self.notifier.send_message(report)
        print("Analysis complete and message sent.")

    def log_recommendations(self, results):
        """추천 결과를 recommendations.csv 파일에 저장"""
        csv_file = 'recommendations.csv'
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        
        new_rows = []
        tier_names = {1: "Elite", 2: "Strong", 3: "Active"}
        
        for tier, stocks in results.items():
            for s in stocks:
                new_rows.append({
                    'Date': today,
                    'Tier': tier_names[tier],
                    'Name': s['name'],
                    'Code': s['code'],
                    'Reasons': s['reasons'],
                    'WinRate': f"{s['win_rate']:.1f}%",
                    'AvgReturn': f"{s['avg_ret']:.1f}%"
                })
        
        if new_rows:
            df_new = pd.DataFrame(new_rows)
            if os.path.exists(csv_file):
                df_new.to_csv(csv_file, mode='a', header=False, index=False, encoding='utf-8-sig')
            else:
                df_new.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"Logged {len(new_rows)} recommendations to {csv_file}")

if __name__ == "__main__":
    analyzer = StockAnalyzer()
    analyzer.run()
