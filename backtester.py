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

    def _backtest_universe(self, universe, target_date, market_name, benchmark_symbol=None):
        results = []
        count = 0
        total = len(universe)
        print(f"Analyzing {total} {market_name} stocks for signals on {target_date.date()}...")

        for item in universe:
            if isinstance(item, tuple):
                code, name = item
            else:
                code = str(item).strip().upper()
                name = code
            if not code:
                continue

            try:
                # Cache key includes benchmark to handle different indicators
                cache_key = (code, benchmark_symbol)
                
                if cache_key in self.data_cache:
                    df = self.data_cache[cache_key]
                else:
                    history_window_days = max(350, self.analyzer.config.get('VALIDATE_MIN_HISTORY', 200) * 2 + 30)
                    start_date = (target_date - datetime.timedelta(days=history_window_days)).strftime('%Y-%m-%d')
                    df = fdr.DataReader(code, start=start_date)
                    min_history = max(50, self.analyzer.config.get('SMA200', 200))
                    if len(df) < min_history:
                        continue

                    if benchmark_symbol:
                        try:
                            # Benchmark also cached globally per symbol to save calls
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

                reasons = self.analyzer.check_signals(df, target_idx)
                if not reasons:
                    continue

                # These depend on TIER rates and TREND_TEMPLATE_PEAK_FACTOR, but
                # we call them anyway - the optimization inner loop will be in optimizer.py
                win_rate, avg_ret = self.analyzer.validate_strategy(df, target_idx)
                last = df.iloc[target_idx]
                is_elite = self.analyzer.is_trend_template(df, target_idx)
                is_above_200 = last['Close'] > last['SMA200']
                tier1 = self.analyzer.config.get('TIER1_WIN_RATE', 60)
                tier2 = self.analyzer.config.get('TIER2_WIN_RATE', 50)
                if not ((is_elite and win_rate >= tier1) or (is_above_200 and win_rate >= tier2)):
                    continue

                buy_price = float(last['Close'])
                sell_price = float(df.iloc[-1]['Close'])
                sell_date = df.index[-1]
                max_price_since_buy = buy_price
                exit_reason = "Max Hold (30d+)"

                for i in range(target_idx + 1, len(df)):
                    curr_row = df.iloc[i]
                    if curr_row['Close'] > max_price_since_buy:
                        max_price_since_buy = curr_row['Close']
                    if (max_price_since_buy - curr_row['Close']) / max_price_since_buy >= self.analyzer.config.get('TRAILING_STOP_PCT', 0.03):
                        sell_price = float(curr_row['Close'])
                        sell_date = df.index[i]
                        exit_reason = f"Trailing Stop ({self.analyzer.config.get('TRAILING_STOP_PCT', 0.03) * 100:.1f}%)"
                        break

                ret = (sell_price - buy_price) / buy_price * 100
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
                    'ExitReason': exit_reason
                })

                count += 1
                if count % 100 == 0:
                    print(f"Progress: {count}/{total} {market_name} stocks analyzed...")
            except Exception:
                continue

        return results

    def run_backtest(self, days_ago=30):
        print(f"Starting {days_ago}-day backtest...")

        ks11_key = ('KS11', None)
        if ks11_key in self.data_cache:
            ks11 = self.data_cache[ks11_key]
        else:
            ks11 = fdr.DataReader('KS11')
            self.data_cache[ks11_key] = ks11
        target_date = ks11.index[-(days_ago + 1)]
        current_date = ks11.index[-1]

        print(f"Target Date (Buy): {target_date.date()}")
        print(f"Current Date (Sell): {current_date.date()}")

        market_cache_key = str(target_date.date())
        if market_cache_key in self.us_market_cache:
            us_market = self.us_market_cache[market_cache_key]
        else:
            us_market = self.analyzer.get_us_market_condition(target_date)
            self.us_market_cache[market_cache_key] = us_market
        print("US Market condition on buy date:")
        for name in ['S&P 500', 'Nasdaq', 'Dow']:
            info = us_market.get(name, {})
            if info.get('date') is not None:
                trend = 'Up' if info['positive'] else 'Down'
                print(f"  {name}: {trend} ({info['pct_change']:+.2f}%) on {info['date']}")
            else:
                print(f"  {name}: 데이터 없음")
        if self.analyzer.config.get('BACKTEST_REQUIRE_US_MARKET_POSITIVE', False) and not us_market.get('all_positive', False):
            print("US market was not broadly positive on the buy date. BACKTEST_REQUIRE_US_MARKET_POSITIVE is enabled, so backtest is skipped.")
            return pd.DataFrame([])

        sample_size = self.analyzer.config.get('BACKTEST_SAMPLE_SIZE', 200)
        stocks = fdr.StockListing('KOSPI')[:sample_size]
        kospi_universe = [(row['Code'], row['Name']) for _, row in stocks.iterrows()]
        results = self._backtest_universe(kospi_universe, target_date, 'KOSPI')

        if self.analyzer.config.get('US_RECOMMENDATION_ENABLED', True):
            us_candidates = self._load_us_candidates()
            if us_candidates:
                results.extend(self._backtest_universe(us_candidates, target_date, 'US', benchmark_symbol='IXIC'))

        df_results = pd.DataFrame(results)
        df_results['US_SP500_Positive'] = us_market.get('S&P 500', {}).get('positive', False)
        df_results['US_Nasdaq_Positive'] = us_market.get('Nasdaq', {}).get('positive', False)
        df_results['US_Dow_Positive'] = us_market.get('Dow', {}).get('positive', False)
        df_results['US_MarketSummary'] = us_market.get('summary', '')

        return df_results

    def print_summary(self, df_results):
        if df_results.empty:
            print("\n[백테스트 결과] 조건에 맞는 종목이 없었습니다.")
            return

        if 'US_MarketSummary' in df_results.columns and not df_results['US_MarketSummary'].empty:
            us_summary = df_results['US_MarketSummary'].iloc[0]
            print(f"US Market summary on buy date: {us_summary}")

        print("\n" + "="*50)
        print("           [30일 백테스트 요약 결과]")
        print("="*50)
        print(f"총 추천 종목 수: {len(df_results)}개")
        print(f"평균 수익률: {df_results['Return(%)'].mean():.2f}%")
        print(f"최고 수익률: {df_results['Return(%)'].max():.2f}% ({df_results.loc[df_results['Return(%)'].idxmax(), 'Name']})")
        print(f"최저 수익률: {df_results['Return(%)'].min():.2f}% ({df_results.loc[df_results['Return(%)'].idxmin(), 'Name']})")
        print(f"승률(수익 발생): {(df_results['Return(%)'] > 0).sum() / len(df_results) * 100:.1f}%")
        print("-" * 50)

        if 'Market' in df_results.columns:
            print("\n[시장별 요약]")
            for market, group in df_results.groupby('Market'):
                print(f"{market}: {len(group)}개, 평균 {group['Return(%)'].mean():.2f}%, 승률 {(group['Return(%)'] > 0).sum() / len(group) * 100:.1f}%")
            print("-" * 50)

        print("\n[상위 10개 종목 상세]")
        print(df_results.sort_values(by='Return(%)', ascending=False).head(10)[['Market','Name', 'Reasons', 'Return(%)']].to_string(index=False))
        print("="*50)

if __name__ == "__main__":
    backtester = Backtester()
    results = backtester.run_backtest(days_ago=30)
    backtester.print_summary(results)
