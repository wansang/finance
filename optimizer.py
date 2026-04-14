import copy
import json
import os
from analyzer import StockAnalyzer
from backtester import Backtester
from algorithm_update_report import AlgorithmUpdateReport, compute_config_changes, describe_issues, summarize_backtest

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
        current_metrics = summarize_backtest(current_df)
        current_notes = describe_issues(current_metrics)

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
            print("[Optimizer] 더 나은 전략을 찾았습니다. 최종 검증을 수행합니다...")
            self.analyzer.config = best_config
            self.backtester.analyzer = self.analyzer
            optimized_df = self.backtester.run_backtest(days_ago=30)
            optimized_metrics = summarize_backtest(optimized_df)
            changes = compute_config_changes(self.base_config, best_config)
            notes = current_notes

            report = AlgorithmUpdateReport(
                title='이번주 분석 알고리즘 업데이트 내용',
                before_metrics=current_metrics,
                after_metrics=optimized_metrics,
                changes=changes,
                notes=notes
            )
            summary_path = report.save_markdown()
            log_path = report.save_log()
            report.send_telegram()

            self.save_config(best_config)
            print(f"[Optimizer] 전략을 최적화하여 {self.config_file}에 저장했습니다. 최종 점수: {best_score:.2f}")
            print(f"[Optimizer] 업데이트 요약을 파일로 저장했습니다: {summary_path}, {log_path}")
        else:
            print("[Optimizer] 현재 전략이 가장 우수합니다. 구성 변경 없이 종료합니다.")

        self.analyzer.config = self.base_config
        self.backtester.analyzer = self.analyzer

if __name__ == '__main__':
    optimizer = StrategyOptimizer()
    optimizer.optimize()
