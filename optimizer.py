import copy
import json
import os
from analyzer import StockAnalyzer
from backtester import Backtester

class StrategyOptimizer:
    def __init__(self, config_file='strategy_config.json'):
        self.config_file = config_file
        self.analyzer = StockAnalyzer()
        self.backtester = Backtester()
        self.backtester.analyzer = self.analyzer
        self.base_config = copy.deepcopy(self.analyzer.config)

    def load_config(self):
        if not os.path.exists(self.config_file):
            return self.base_config
        with open(self.config_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_config(self, config):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def score_results(self, df):
        if df.empty or len(df) < 8:
            return None
        avg_ret = df['Return(%)'].mean()
        win_rate = (df['Return(%)'] > 0).sum() / len(df) * 100
        return avg_ret + max(win_rate - 45, 0) * 0.4

    def optimize(self):
        print("[Optimizer] 현재 전략을 평가합니다...")
        current_df = self.backtester.run_backtest(days_ago=30)
        current_score = self.score_results(current_df)
        if current_score is None:
            print("[Optimizer] 현재 전략으로는 유효한 백테스트 결과를 얻지 못했습니다.")
            current_score = -999
        else:
            print(f"[Optimizer] 현재 전략 점수: {current_score:.2f}, 종목 수: {len(current_df)}")

        search_space = {
            'TRAILING_STOP_PCT': [0.02, 0.025, 0.03, 0.035, 0.04],
            'TIER1_WIN_RATE': [55, 60, 65],
            'TIER2_WIN_RATE': [45, 50, 55],
            'TREND_TEMPLATE_PEAK_FACTOR': [0.70, 0.75, 0.80],
            'VALIDATE_MAX_HOLD_DAYS': [15, 20, 25]
        }

        best_score = current_score
        best_config = copy.deepcopy(self.base_config)
        candidates = 0

        for tier1 in search_space['TIER1_WIN_RATE']:
            for tier2 in search_space['TIER2_WIN_RATE']:
                for peak_factor in search_space['TREND_TEMPLATE_PEAK_FACTOR']:
                    for stop_pct in search_space['TRAILING_STOP_PCT']:
                        for max_hold in search_space['VALIDATE_MAX_HOLD_DAYS']:
                            candidates += 1
                            candidate = copy.deepcopy(self.base_config)
                            candidate['TIER1_WIN_RATE'] = tier1
                            candidate['TIER2_WIN_RATE'] = tier2
                            candidate['TREND_TEMPLATE_PEAK_FACTOR'] = peak_factor
                            candidate['TRAILING_STOP_PCT'] = stop_pct
                            candidate['VALIDATE_MAX_HOLD_DAYS'] = max_hold
                            self.analyzer.config = candidate
                            self.backtester.analyzer = self.analyzer

                            result_df = self.backtester.run_backtest(days_ago=30)
                            score = self.score_results(result_df)
                            if score is None:
                                continue
                            if score > best_score:
                                best_score = score
                                best_config = copy.deepcopy(candidate)
                                print(f"[Optimizer] 새로운 최고 전략 발견: score={score:.2f}, tier1={tier1}, tier2={tier2}, peak={peak_factor}, stop={stop_pct}, hold={max_hold}, count={len(result_df)}")

        if best_score > current_score:
            self.save_config(best_config)
            print(f"[Optimizer] 전략을 최적화하여 {self.config_file}에 저장했습니다. 최종 점수: {best_score:.2f}")
        else:
            print("[Optimizer] 현재 전략이 가장 우수합니다. 구성 변경 없이 종료합니다.")

        self.analyzer.config = self.base_config
        self.backtester.analyzer = self.analyzer

if __name__ == '__main__':
    optimizer = StrategyOptimizer()
    optimizer.optimize()
import copy
import datetime
import json

from analyzer import StockAnalyzer


class StrategyOptimizer:
    def __init__(self, config_path='strategy_config.json', sample_size=100):
        self.config_path = config_path
        self.analyzer = StockAnalyzer()
        self.base_config = copy.deepcopy(self.analyzer.strategy_config)
        self.min_samples = self.base_config.get('optimizer', {}).get('min_sampled_stocks', 20)
        self.win_rate_weight = self.base_config.get('optimizer', {}).get('win_rate_weight', 0.6)
        self.avg_return_weight = self.base_config.get('optimizer', {}).get('avg_return_weight', 0.4)
        self.sample_score_cap = self.base_config.get('optimizer', {}).get('sample_score_cap', 150)
        self.sample_size = sample_size
        self.stocks = self.load_sample_stocks(sample_size)

    def load_sample_stocks(self, sample_size):
        stocks = self.analyzer.get_stock_listing('KOSPI')
        return stocks.head(sample_size)

    def evaluate_config(self, config):
        self.analyzer.strategy_config = config
        results = []
        for _, stock in self.stocks.iterrows():
            code = stock['Code']
            lookback = self.base_config.get('data', {}).get('default_lookback_days', 400)
            start_date = (datetime.datetime.now() - datetime.timedelta(days=lookback)).strftime('%Y-%m-%d')
            df = self.analyzer.fetch_data(code, start=start_date)
            if df is None or len(df) < config['trend_template'].get('min_history', 200):
                continue

            df = self.analyzer.get_indicators(df)
            target_idx = len(df) - 1
            reasons = self.analyzer.check_signals(df, target_idx)
            if not reasons or not self.analyzer.is_trend_template(df, target_idx):
                continue

            win_rate, avg_ret = self.analyzer.validate_strategy(df, target_idx)
            results.append({'win_rate': win_rate, 'avg_ret': avg_ret})

        if not results:
            return {'mean_win_rate': 0.0, 'mean_avg_ret': 0.0, 'sampled_stocks': 0}

        mean_win_rate = sum(item['win_rate'] for item in results) / len(results)
        mean_avg_ret = sum(item['avg_ret'] for item in results) / len(results)
        return {
            'mean_win_rate': mean_win_rate,
            'mean_avg_ret': mean_avg_ret,
            'sampled_stocks': len(results)
        }

    def search(self):
        entry = self.base_config.get('entry', {})
        trend_template = self.base_config.get('trend_template', {})
        indicators = self.base_config.get('indicators', {})

        candidates = []
        for trailing_stop in [0.02, 0.03, 0.04]:
            for lookback in [60, 90, 120]:
                for max_hold in [10, 15, 20]:
                    for high_ratio in [0.70, 0.75, 0.80]:
                        candidate = copy.deepcopy(self.base_config)
                        candidate['entry']['trailing_stop_pct'] = trailing_stop
                        candidate['entry']['validation_lookback_days'] = lookback
                        candidate['entry']['max_hold_days'] = max_hold
                        candidate['trend_template']['high_52w_ratio'] = high_ratio

                        stats = self.evaluate_config(candidate)
                        if stats['sampled_stocks'] < 20:
                            print(f"Skip candidate due to 낮은 샘플 수: {stats['sampled_stocks']}개")
                            continue
                        score = stats['mean_win_rate'] * 0.6 + stats['mean_avg_ret'] * 0.4
                        score *= min(stats['sampled_stocks'] / 100, 1.0)
                        candidates.append((score, candidate, stats))
                        print(f"Tested stop={trailing_stop}, lookback={lookback}, max_hold={max_hold}, high_ratio={high_ratio} => win={stats['mean_win_rate']:.1f}%, avg_ret={stats['mean_avg_ret']:.2f}%, samples={stats['sampled_stocks']}, score={score:.2f}")

        best = max(candidates, key=lambda x: x[0]) if candidates else None
        return best

    def save_config(self, config):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def run(self):
        print('Starting strategy optimizer...')
        best = self.search()
        if not best:
            print('최적화 결과를 찾지 못했습니다.')
            return

        score, config, stats = best
        self.save_config(config)
        print('최적 전략을 strategy_config.json에 저장했습니다.')
        print(f"Best score: {score:.2f}")
        print(f"Win rate: {stats['mean_win_rate']:.2f}%")
        print(f"Average return: {stats['mean_avg_ret']:.2f}%")
        print(f"Signal sample count: {stats['sampled_stocks']}")
        
        review = self.analyzer.review_strategy(config, stats)
        print("\n=== AI 전략 리뷰 ===")
        print(review)


if __name__ == '__main__':
    optimizer = StrategyOptimizer(sample_size=100)
    optimizer.run()
