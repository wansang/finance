import FinanceDataReader as fdr
import pandas as pd
import datetime
from analyzer import StockAnalyzer
import time

class Backtester:
    def __init__(self):
        self.analyzer = StockAnalyzer()
        self.data_cache = {}
        self.us_market_cache = {}

    def _simulate_trade(self, df, target_idx, reasons, max_hold_days=None, config_override=None):
        """
        단일 거래 시뮬레이션
        - 매수: 신호 다음날 시가 (현실적 진입 — 당일 종가 매수 비현실적 문제 해결)
        - 손절: ATR × 2배 (ATR 없으면 고정 -5%)
        - 목표가: ATR × 3배 (ATR 없으면 +8%, PowerCombo +12%)
        - 트레일링 스톱: 고점 대비 3.5%
        - 거래비용: 매수 0.015% + 매도 0.5% (코스피 실비: 수수료+세금)
        """
        cfg = {**self.analyzer.config, **config_override} if config_override else self.analyzer.config
        if max_hold_days is None:
            max_hold_days = cfg.get('VALIDATE_MAX_HOLD_DAYS', 20)

        trailing_stop = cfg.get('TRAILING_STOP_PCT', 0.035)
        trailing_activate = cfg.get('TRAILING_STOP_ACTIVATE_PCT', 0.04)
        fallback_stop = abs(cfg.get('VALIDATE_STOP_LOSS_PCT', -0.05))
        fallback_target = cfg.get('PROFIT_TARGET_PCT', 0.08)
        atr_stop_mult = cfg.get('ATR_STOP_MULTIPLIER', 2.0)
        atr_target_mult = cfg.get('ATR_TARGET_MULTIPLIER', 3.0)
        tx_buy = cfg.get('TRANSACTION_COST_BUY_PCT', 0.00015)
        tx_sell = cfg.get('TRANSACTION_COST_SELL_PCT', 0.005)

        # 다음날 시가 진입
        buy_idx = target_idx + 1
        if buy_idx >= len(df):
            return 0.0, "NoData", 0.0, 0.0

        open_col = 'Open' if 'Open' in df.columns else 'Close'
        raw_buy = float(df.iloc[buy_idx][open_col])
        if raw_buy <= 0:
            raw_buy = float(df.iloc[buy_idx]['Close'])
        buy_price = raw_buy * (1 + tx_buy)  # 매수 비용 반영

        # ATR 기반 손절/목표가 (없으면 고정값 폴백)
        atr_val = None
        if 'ATR' in df.columns:
            v = df.iloc[target_idx]['ATR']
            if pd.notna(v) and float(v) > 0:
                atr_val = float(v)

        max_hard_stop = cfg.get('MAX_HARD_STOP_PCT', 0.07)
        has_premium = any(s in reasons for s in ["RSI 반전 신호(상승 가능성)", "바닥권 반등 신호(BB 하단)"])
        if atr_val:
            hard_stop_pct = min(atr_stop_mult * atr_val / raw_buy, max_hard_stop)
            profit_target_pct = atr_target_mult * (1.5 if has_premium else 1.0) * atr_val / raw_buy
            stop_label = f"ATR×{atr_stop_mult:.0f}"
        else:
            hard_stop_pct = min(fallback_stop, max_hard_stop)
            profit_target_pct = fallback_target * (1.5 if has_premium else 1.0)
            stop_label = "Fixed"

        max_p = raw_buy
        end_idx = min(buy_idx + max_hold_days + 1, len(df))
        sell_raw = float(df.iloc[end_idx - 1]['Close'])
        exit_reason = "TimeOut"

        for j in range(buy_idx, end_idx):
            curr_p = float(df.iloc[j]['Close'])
            if curr_p > max_p:
                max_p = curr_p
            pct = (curr_p - raw_buy) / raw_buy
            if pct <= -hard_stop_pct:
                sell_raw = curr_p
                exit_reason = f"HardStop({stop_label},-{hard_stop_pct*100:.1f}%)"
                break
            if pct >= profit_target_pct:
                sell_raw = curr_p
                exit_reason = f"Target({stop_label},+{profit_target_pct*100:.1f}%)"
                break
            if max_p >= raw_buy * (1 + trailing_activate) and (max_p - curr_p) / max_p >= trailing_stop:
                sell_raw = curr_p
                exit_reason = f"TrailingStop({trailing_stop*100:.0f}%)"
                break

        sell_price_net = sell_raw * (1 - tx_sell)  # 매도 비용 반영
        ret = (sell_price_net - buy_price) / buy_price * 100
        return ret, exit_reason, buy_price, sell_raw

    def _load_us_candidates(self):
        dow_candidates = self.analyzer.config.get('US_DOW_TICKERS', [])
        nasdaq_candidates = self.analyzer.config.get('US_NASDAQ_TICKERS', [])
        seen = set()
        candidates = []
        for code in dow_candidates + nasdaq_candidates:
            token = str(code).strip().upper()
            if token and token not in seen:
                seen.add(token)
                candidates.append(token)
        return candidates

    def _backtest_universe(self, universe, target_date, market_name, benchmark_symbol=None, market_uptrend=True):
        results = []
        count = 0
        total = len(universe)
        market_filter = self.analyzer.config.get('MARKET_FILTER_ENABLED', True)
        if market_filter and not market_uptrend:
            print(f"⚠️ {market_name} 하락장 감지: Power Combo(RSI다이버전스+타지마할) 종목만 Tier1 허용")
        print(f"Analyzing {total} {market_name} stocks for signals on {target_date.date()}...")

        # 시장별 파라미터 오버라이드 (US: 더 넓은 ATR 손절, 낮은 거래세, 긴 보유기간)
        cfg_override = None
        if market_name == 'US':
            cfg_override = {
                'VALIDATE_STOP_LOSS_PCT': self.analyzer.config.get('US_VALIDATE_STOP_LOSS_PCT', -0.07),
                'PROFIT_TARGET_PCT': self.analyzer.config.get('US_PROFIT_TARGET_PCT', 0.10),
                'ATR_STOP_MULTIPLIER': self.analyzer.config.get('US_ATR_STOP_MULTIPLIER', 2.5),
                'ATR_TARGET_MULTIPLIER': self.analyzer.config.get('US_ATR_TARGET_MULTIPLIER', 4.0),
                'TRAILING_STOP_PCT': self.analyzer.config.get('US_TRAILING_STOP_PCT', 0.05),
                'VALIDATE_MAX_HOLD_DAYS': self.analyzer.config.get('US_VALIDATE_MAX_HOLD_DAYS', 30),
                'TRANSACTION_COST_BUY_PCT': self.analyzer.config.get('US_TRANSACTION_COST_BUY_PCT', 0.0001),
                'TRANSACTION_COST_SELL_PCT': self.analyzer.config.get('US_TRANSACTION_COST_SELL_PCT', 0.0005),
            }
        max_hold = cfg_override.get('VALIDATE_MAX_HOLD_DAYS', 20) if cfg_override else self.analyzer.config.get('VALIDATE_MAX_HOLD_DAYS', 20)

        for item in universe:
            if isinstance(item, tuple):
                code, name = item
            else:
                code = str(item).strip().upper()
                name = code
            if not code:
                continue

            try:
                cache_key = (code, benchmark_symbol)

                if cache_key in self.data_cache:
                    df = self.data_cache[cache_key]
                else:
                    history_window_days = max(550, self.analyzer.config.get('VALIDATE_MIN_HISTORY', 252) * 2 + 60)
                    start_date = (target_date - datetime.timedelta(days=history_window_days)).strftime('%Y-%m-%d')
                    df = fdr.DataReader(code, start=start_date)
                    min_history = max(50, self.analyzer.config.get('SMA200', 200))
                    if len(df) < min_history:
                        continue

                    if benchmark_symbol:
                        try:
                            bench_key = ("BENCHMARK", benchmark_symbol)
                            if bench_key in self.data_cache:
                                benchmark = self.data_cache[bench_key]
                            else:
                                benchmark = fdr.DataReader(benchmark_symbol, start=start_date)
                                self.data_cache[bench_key] = benchmark
                        except Exception:
                            benchmark = None
                        df = self.analyzer.get_indicators(df, benchmark)
                    else:
                        df = self.analyzer.get_indicators(df)

                    self.data_cache[cache_key] = df

                if target_date not in df.index:
                    df_target_subset = df[df.index <= target_date]
                    if len(df_target_subset) == 0:
                        continue
                    target_idx = len(df_target_subset) - 1
                    actual_buy_date = df_target_subset.index[-1]
                else:
                    target_idx = df.index.get_loc(target_date)
                    actual_buy_date = target_date

                # 매도 구간 데이터가 충분한지 확인 (다음날 시가 진입 + max_hold일)
                if target_idx + 1 + max_hold >= len(df):
                    continue

                reasons = self.analyzer.check_signals(df, target_idx)
                if not reasons:
                    continue

                # ATR 변동성 필터: ATR이 주가의 6% 초과 종목 스킵 (너무 불안정)
                last = df.iloc[target_idx]
                max_atr_ratio = self.analyzer.config.get('MAX_ATR_RATIO', 0.06)
                if 'ATR' in df.columns and pd.notna(last['ATR']) and last['Close'] > 0:
                    if last['ATR'] / last['Close'] > max_atr_ratio:
                        continue

                win_rate, avg_ret = self.analyzer.validate_strategy(df, target_idx, config_override=cfg_override)
                is_elite = self.analyzer.is_trend_template(df, target_idx)
                is_above_200 = last['Close'] > last['SMA200']
                tier1 = self.analyzer.config.get('US_TIER1_WIN_RATE', 50) if market_name == 'US' else self.analyzer.config.get('TIER1_WIN_RATE', 60)
                tier2 = self.analyzer.config.get('US_TIER2_WIN_RATE', 45) if market_name == 'US' else self.analyzer.config.get('TIER2_WIN_RATE', 50)

                has_divergence = "RSI 반전 신호(상승 가능성)" in reasons
                has_taj_mahal = "바닥권 반등 신호(BB 하단)" in reasons
                power_combo = has_divergence and has_taj_mahal
                market_ok = market_uptrend or not market_filter or power_combo

                if not ((is_elite and win_rate >= tier1 and market_ok) or (is_above_200 and win_rate >= tier2 and market_ok)):
                    continue

                # 포지션 사이징: PowerCombo 1.5배, Tier1 1.0배, Tier2 0.5배
                is_tier1 = is_elite and win_rate >= tier1 and market_ok
                if power_combo:
                    position_size = 1.5
                elif is_tier1:
                    position_size = 1.0
                else:
                    position_size = 0.5

                ret, exit_reason, buy_price, sell_price = self._simulate_trade(df, target_idx, reasons, max_hold, config_override=cfg_override)
                sell_date = df.index[min(target_idx + 1 + max_hold, len(df) - 1)]

                results.append({
                    'Market': market_name,
                    'Code': code,
                    'Name': name,
                    'Reasons': ", ".join(reasons),
                    'BuyDate': actual_buy_date.date(),
                    'BuyPrice': buy_price,
                    'SellDate': sell_date.date(),
                    'SellPrice': sell_price,
                    'Return(%)': ret,
                    'ExitReason': exit_reason,
                    'WinRate_Hist': win_rate,
                    'PowerCombo': power_combo,
                    'MarketUptrend': market_uptrend,
                    'PositionSize': position_size,
                })

                count += 1
                if count % 100 == 0:
                    print(f"Progress: {count}/{total} {market_name} stocks analyzed...")
            except Exception:
                continue

        return results

    def run_backtest(self, days_ago=30):
        """단일 기간 백테스트 (기존 방식, 빠른 확인용)"""
        print(f"Starting single-period backtest (매수일: {days_ago}거래일 전)...")

        ks11_key = ('KS11', None)
        if ks11_key in self.data_cache:
            ks11 = self.data_cache[ks11_key]
        else:
            ks11 = fdr.DataReader('KS11')
            self.data_cache[ks11_key] = ks11
        target_date = ks11.index[-(days_ago + 1)]

        print(f"Target Date (Buy): {target_date.date()}")
        print(f"Current Date: {ks11.index[-1].date()}")

        kospi_uptrend = self.analyzer._is_market_in_uptrend(ks11, target_idx=len(ks11[ks11.index <= target_date]) - 1)
        try:
            sp500 = fdr.DataReader('US500', start=(target_date - datetime.timedelta(days=300)).strftime('%Y-%m-%d'), end=target_date.strftime('%Y-%m-%d'))
            us_uptrend = self.analyzer._is_market_in_uptrend(sp500)
        except Exception:
            us_uptrend = True

        us_market = self.analyzer.get_us_market_condition(target_date)
        print("US Market condition on buy date:")
        for name in ['S&P 500', 'Nasdaq', 'Dow']:
            info = us_market.get(name, {})
            if info.get('date') is not None:
                trend = 'Up' if info['positive'] else 'Down'
                print(f"  {name}: {trend} ({info['pct_change']:+.2f}%) on {info['date']}")

        sample_size = self.analyzer.config.get('BACKTEST_SAMPLE_SIZE', 200)
        stocks = fdr.StockListing('KOSPI')[:sample_size]
        kospi_universe = [(row['Code'], row['Name']) for _, row in stocks.iterrows()]
        results = self._backtest_universe(kospi_universe, target_date, 'KOSPI', market_uptrend=kospi_uptrend)

        if self.analyzer.config.get('US_RECOMMENDATION_ENABLED', True):
            us_candidates = self._load_us_candidates()
            if us_candidates:
                results.extend(self._backtest_universe(us_candidates, target_date, 'US', benchmark_symbol='IXIC', market_uptrend=us_uptrend))

        df_results = pd.DataFrame(results)
        if not df_results.empty:
            df_results['US_MarketSummary'] = us_market.get('summary', '')
        return df_results

    def run_walkforward_backtest(self, periods=8, interval_weeks=6):
        """
        워크포워드 백테스트: 과거 N개 구간에서 각각 신호 포착 → max_hold_days 보유 → 청산
        - periods: 테스트할 기간 수 (기본 8개 구간)
        - interval_weeks: 구간 간격 (기본 6주)
        - 각 구간은 독립적으로 시뮬레이션 (데이터 미래 참조 없음)
        - 통계: 전체·시장별·상승장/하락장·신호별 승률·수익률
        """
        print(f"\n{'='*60}")
        print(f"  워크포워드 백테스트: {periods}개 구간 × {interval_weeks}주 간격")
        print(f"{'='*60}")

        ks11 = fdr.DataReader('KS11', start=(datetime.datetime.now() - datetime.timedelta(days=900)).strftime('%Y-%m-%d'))
        max_hold = self.analyzer.config.get('VALIDATE_MAX_HOLD_DAYS', 20)
        sample_size = self.analyzer.config.get('BACKTEST_SAMPLE_SIZE', 200)

        # 테스트 날짜 선정: 최근부터 interval_weeks 간격으로 거슬러 올라감
        # 각 구간은 매수 후 max_hold일 청산이 가능해야 하므로 최소 max_hold일 이전 날짜
        trading_dates = ks11.index
        min_offset = max_hold + 5  # 청산 여유
        test_dates = []
        for p in range(periods):
            offset_days = min_offset + p * interval_weeks * 7
            cutoff = trading_dates[-offset_days] if offset_days < len(trading_dates) else trading_dates[0]
            test_dates.append(cutoff)
        test_dates = sorted(test_dates)

        all_results = []
        stocks = fdr.StockListing('KOSPI')[:sample_size]
        kospi_universe = [(row['Code'], row['Name']) for _, row in stocks.iterrows()]
        us_candidates = self._load_us_candidates() if self.analyzer.config.get('US_RECOMMENDATION_ENABLED', True) else []

        for i, target_date in enumerate(test_dates):
            period_label = f"Period {i+1}/{periods} ({target_date.date()})"
            print(f"\n[{period_label}]")

            kospi_uptrend = self.analyzer._is_market_in_uptrend(
                ks11, target_idx=len(ks11[ks11.index <= target_date]) - 1
            )
            market_label = "상승장" if kospi_uptrend else "하락장"
            print(f"  코스피 시장 상태: {market_label}")

            try:
                sp500 = fdr.DataReader('US500', start=(target_date - datetime.timedelta(days=300)).strftime('%Y-%m-%d'))
                us_uptrend = self.analyzer._is_market_in_uptrend(sp500)
            except Exception:
                us_uptrend = True

            period_results = self._backtest_universe(
                kospi_universe, target_date, 'KOSPI', market_uptrend=kospi_uptrend
            )
            if us_candidates:
                period_results.extend(self._backtest_universe(
                    us_candidates, target_date, 'US', benchmark_symbol='IXIC', market_uptrend=us_uptrend
                ))

            for r in period_results:
                r['Period'] = period_label
                r['PeriodDate'] = target_date.date()

            trades = len(period_results)
            if trades > 0:
                df_p = pd.DataFrame(period_results)
                wr = (df_p['Return(%)'] > 0).sum() / trades * 100
                avg = df_p['Return(%)'].mean()
                print(f"  → 신호: {trades}개, 승률: {wr:.0f}%, 평균수익: {avg:+.2f}%")
            else:
                print(f"  → 신호 없음")

            all_results.extend(period_results)

        return pd.DataFrame(all_results)

    def print_summary(self, df_results, title="백테스트"):
        if df_results is None or df_results.empty:
            print("\n[백테스트 결과] 조건에 맞는 종목이 없었습니다.")
            return

        total = len(df_results)
        wins = (df_results['Return(%)'] > 0).sum()
        avg_ret = df_results['Return(%)'].mean()
        win_rate = wins / total * 100
        best = df_results.loc[df_results['Return(%)'].idxmax()]
        worst = df_results.loc[df_results['Return(%)'].idxmin()]

        # 포지션 사이징 가중 수익률 (PowerCombo 1.5배, Tier1 1.0배, Tier2 0.5배)
        if 'PositionSize' in df_results.columns:
            total_weight = df_results['PositionSize'].sum()
            weighted_ret = (df_results['Return(%)'] * df_results['PositionSize']).sum() / total_weight if total_weight > 0 else avg_ret
        else:
            weighted_ret = avg_ret

        print(f"\n{'='*60}")
        print(f"  [{title} 종합 결과]")
        print(f"{'='*60}")
        print(f"  총 거래 수:   {total}개  (통계 신뢰도: {'높음 ✅' if total >= 80 else '보통 ⚠️' if total >= 30 else '낮음 ❌'})")
        print(f"  승률:         {win_rate:.1f}%  ({wins}승 {total-wins}패)")
        print(f"  평균 수익률:  {avg_ret:+.2f}%  (가중평균: {weighted_ret:+.2f}%)")
        print(f"  최고 수익:    {best['Return(%)']:+.2f}%  ({best['Name']})")
        print(f"  최저 수익:    {worst['Return(%)']:+.2f}%  ({worst['Name']})")
        print(f"{'─'*60}")

        # 시장별
        if 'Market' in df_results.columns:
            print("\n  [시장별]")
            for market, g in df_results.groupby('Market'):
                wr = (g['Return(%)'] > 0).sum() / len(g) * 100
                print(f"    {market:6s}: {len(g):3d}건  승률 {wr:5.1f}%  평균 {g['Return(%)'].mean():+.2f}%")

        # 상승장 vs 하락장
        if 'MarketUptrend' in df_results.columns:
            print("\n  [시장 상태별]")
            for uptrend, label in [(True, '상승장'), (False, '하락장')]:
                g = df_results[df_results['MarketUptrend'] == uptrend]
                if len(g) == 0:
                    continue
                wr = (g['Return(%)'] > 0).sum() / len(g) * 100
                print(f"    {label}: {len(g):3d}건  승률 {wr:5.1f}%  평균 {g['Return(%)'].mean():+.2f}%")

        # Power Combo (RSI 다이버전스 + 타지마할)
        if 'PowerCombo' in df_results.columns:
            pc = df_results[df_results['PowerCombo'] == True]
            if len(pc) > 0:
                wr = (pc['Return(%)'] > 0).sum() / len(pc) * 100
                print(f"\n  [⭐ PowerCombo(RSI다이버전스+타지마할)]")
                print(f"    {len(pc):3d}건  승률 {wr:5.1f}%  평균 {pc['Return(%)'].mean():+.2f}%")

        # 청산 사유별
        if 'ExitReason' in df_results.columns:
            print("\n  [청산 사유별]")
            for reason, g in df_results.groupby(df_results['ExitReason'].str.split('(').str[0]):
                wr = (g['Return(%)'] > 0).sum() / len(g) * 100
                print(f"    {reason:20s}: {len(g):3d}건  승률 {wr:5.1f}%  평균 {g['Return(%)'].mean():+.2f}%")

        # 기간별 (워크포워드)
        if 'Period' in df_results.columns:
            print("\n  [기간별 성과]")
            for period, g in df_results.groupby('PeriodDate'):
                wr = (g['Return(%)'] > 0).sum() / len(g) * 100
                trend_mark = '↑' if g['MarketUptrend'].iloc[0] else '↓'
                print(f"    {period} {trend_mark}  {len(g):2d}건  승률 {wr:5.1f}%  평균 {g['Return(%)'].mean():+.2f}%")

        print(f"\n  [상위 10개 거래]")
        cols = ['Name', 'Return(%)', 'ExitReason', 'Reasons']
        if 'PeriodDate' in df_results.columns:
            cols = ['PeriodDate', 'Name', 'Return(%)', 'ExitReason']
        top10 = df_results.sort_values('Return(%)', ascending=False).head(10)[cols]
        print(top10.to_string(index=False))
        print(f"{'='*60}")


if __name__ == "__main__":
    backtester = Backtester()

    print("\n▶ 워크포워드 백테스트 실행 중 (8개 구간, 6주 간격)...")
    wf_results = backtester.run_walkforward_backtest(periods=8, interval_weeks=6)
    backtester.print_summary(wf_results, title="워크포워드 백테스트 (8구간)")

    print("\n\n▶ 최근 30거래일 단일 백테스트...")
    single_results = backtester.run_backtest(days_ago=30)
    backtester.print_summary(single_results, title="최근 30거래일 단일 백테스트")
