"""
optimizer.py
------------
매주 실행되어 실제 추천한 종목(1등급 "지금 매수")의 실제 수익률을 확인하고,
전략 파라미터(TRAILING_STOP_PCT, TIER1_WIN_RATE)를 자동으로 최적화합니다.

핵심 로직:
1. recommendations.csv 에서 지난 30일 1등급 추천 종목을 로드
2. 추천일 매수 → 오늘 현재가 또는 트레일링 스톱 발동 시 매도 기준으로 실제 수익률 계산
3. TRAILING_STOP_PCT: 다양한 값으로 재계산해 실제 수익 최대화 값 탐색
4. TIER1_WIN_RATE: CSV에 저장된 사전 승률(WinRate) vs 실제 수익 상관관계로 최적 임계값 탐색
5. 변경이 있으면 strategy_config.json 저장 및 텔레그램 알림
"""

import copy
import datetime
import json
import os
import time

import FinanceDataReader as fdr
import pandas as pd

from analyzer import StockAnalyzer
from algorithm_update_report import AlgorithmUpdateReport, compute_config_changes

RECOMMENDATIONS_FILE = 'recommendations.csv'


class StrategyOptimizer:
    def __init__(self, config_file='strategy_config.json'):
        self.config_file = config_file
        self.analyzer = StockAnalyzer()
        self.base_config = copy.deepcopy(self.analyzer.config)
        self.time_limit_seconds = self._safe_int(
            os.environ.get('OPTIMIZER_TIME_LIMIT_SECONDS',
                           self.base_config.get('OPTIMIZER_TIME_LIMIT_SECONDS', 900)),
            900
        )

    @staticmethod
    def _safe_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def save_config(self, config):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    # ------------------------------------------------------------------
    # 1. 추천 이력 로드
    # ------------------------------------------------------------------
    def load_tier1_recommendations(self, days_back=30):
        """
        recommendations.csv 에서 1등급("지금 매수") 종목을 읽어 반환합니다.
        반환 형식:
          [{'date': datetime, 'name': str, 'code': str,
            'stored_win_rate': float|None, 'buy_price': float|None}, ...]
        """
        if not os.path.exists(RECOMMENDATIONS_FILE):
            return []

        cutoff = datetime.datetime.now() - datetime.timedelta(days=days_back)
        recs = []

        try:
            raw = pd.read_csv(RECOMMENDATIONS_FILE, header=None, dtype=str, encoding='utf-8-sig')
            # 첫 행이 헤더이면 제거
            if str(raw.iloc[0, 0]).strip().lower() == 'date':
                raw = raw.iloc[1:].reset_index(drop=True)

            for _, row in raw.iterrows():
                try:
                    rec_date = datetime.datetime.strptime(str(row.iloc[0]).strip(), '%Y-%m-%d')
                    if rec_date < cutoff:
                        continue
                    tier = str(row.iloc[1]).strip()
                    if tier != '지금 매수':
                        continue
                    name = str(row.iloc[2]).strip()
                    code = str(row.iloc[3]).strip()

                    # WinRate (col 5): "66.7%"
                    stored_win_rate = None
                    try:
                        stored_win_rate = float(str(row.iloc[5]).strip().replace('%', ''))
                    except (ValueError, IndexError):
                        pass

                    # BuyPrice (col 7): 신버전에서만 존재
                    buy_price = None
                    if len(row) > 7:
                        try:
                            bp = float(str(row.iloc[7]).strip())
                            if bp > 0:
                                buy_price = bp
                        except (ValueError, TypeError):
                            pass

                    recs.append({
                        'date': rec_date,
                        'name': name,
                        'code': code,
                        'stored_win_rate': stored_win_rate,
                        'buy_price': buy_price,
                    })
                except Exception:
                    continue
        except Exception:
            return []

        return recs

    # ------------------------------------------------------------------
    # 2. 실제 수익률 계산
    # ------------------------------------------------------------------
    def fetch_actual_performance(self, recs, trailing_stop_pct):
        """
        각 추천 종목을 추천일 종가에 매수, 오늘까지 보유 또는 트레일링 스톱 발동 시 매도.
        실제 수익률 목록을 반환합니다.
        """
        results = []
        for rec in recs:
            code = rec['code']
            try:
                start_str = (rec['date'] - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
                df = fdr.DataReader(code, start=start_str)
                if df.empty or len(df) < 2:
                    continue

                # 매수가 결정
                buy_price = rec.get('buy_price')
                if not buy_price or buy_price <= 0:
                    rec_ts = pd.Timestamp(rec['date']).normalize()
                    on_day = df[df.index.normalize() == rec_ts]
                    if not on_day.empty:
                        buy_price = float(on_day.iloc[0]['Close'])
                    else:
                        buy_price = float(df.iloc[0]['Close'])

                if not buy_price or buy_price <= 0:
                    continue

                # 추천일 이후 데이터만 사용
                df_after = df[df.index >= pd.Timestamp(rec['date'])]
                if df_after.empty:
                    df_after = df

                sell_price = float(df_after.iloc[-1]['Close'])
                sell_date = df_after.index[-1]
                max_price = buy_price
                exit_reason = '현재 보유'

                for i in range(len(df_after)):
                    curr_p = float(df_after.iloc[i]['Close'])
                    if curr_p > max_price:
                        max_price = curr_p
                    if max_price > 0 and (max_price - curr_p) / max_price >= trailing_stop_pct:
                        sell_price = curr_p
                        sell_date = df_after.index[i]
                        exit_reason = f'트레일링 스톱 {trailing_stop_pct * 100:.1f}%'
                        break

                ret = (sell_price - buy_price) / buy_price * 100
                results.append({
                    'code': code,
                    'name': rec['name'],
                    'buy_date': rec['date'].date(),
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'sell_date': sell_date.date() if hasattr(sell_date, 'date') else sell_date,
                    'return_pct': ret,
                    'stored_win_rate': rec.get('stored_win_rate'),
                    'exit_reason': exit_reason,
                })
            except Exception:
                continue

        return results

    # ------------------------------------------------------------------
    # 3. 메인 최적화 루틴
    # ------------------------------------------------------------------
    def optimize(self):
        optimize_started = time.time()
        print("[Optimizer] 실제 추천 종목 성과 분석을 시작합니다...")

        # ── 1. 추천 이력 로드 ──────────────────────────────────────────
        recs = self.load_tier1_recommendations(days_back=30)
        if len(recs) < 3:
            print(f"[Optimizer] 최근 30일 1등급 추천 종목이 {len(recs)}개입니다. "
                  "최소 3개가 필요합니다. 이력이 더 쌓이면 다시 실행하세요.")
            return

        print(f"[Optimizer] {len(recs)}개 1등급 추천 종목 발견.")

        # ── 2. 현재 파라미터로 실제 성과 계산 ───────────────────────────
        current_stop = self.base_config.get('TRAILING_STOP_PCT', 0.03)
        current_results = self.fetch_actual_performance(recs, current_stop)

        if not current_results:
            print("[Optimizer] 실제 성과 데이터를 불러올 수 없습니다. 종료합니다.")
            return

        # ── 3. 성과 리포트 출력 ──────────────────────────────────────────
        print("\n" + "=" * 72)
        print("  [실제 추천 종목 성과 리포트]")
        print("=" * 72)
        print(f"{'종목':<14} {'매수일':<12} {'매수가':>10} {'현재/매도가':>12} {'수익률':>8}  사유")
        print("-" * 72)
        for r in sorted(current_results, key=lambda x: x['return_pct'], reverse=True):
            print(
                f"{r['name']:<14} {str(r['buy_date']):<12} "
                f"{r['buy_price']:>10,.0f} {r['sell_price']:>12,.0f} "
                f"{r['return_pct']:>+7.2f}%  {r['exit_reason']}"
            )

        returns = [r['return_pct'] for r in current_results]
        avg_ret = sum(returns) / len(returns)
        win_rate = len([r for r in returns if r > 0]) / len(returns) * 100
        current_score = avg_ret + max(win_rate - 45, 0) * 0.4

        print("-" * 72)
        print(f"총 {len(current_results)}개  |  평균 수익률: {avg_ret:+.2f}%  |  승률: {win_rate:.1f}%  |  점수: {current_score:.2f}")
        print("=" * 72)

        before_metrics = {
            'count': len(current_results),
            'avg_return': avg_ret,
            'win_rate': win_rate,
            'max_return': max(returns),
            'min_return': min(returns),
        }

        # ── 4. TRAILING_STOP_PCT 최적화 ──────────────────────────────────
        print("\n[Optimizer] 트레일링 스톱 최적값 탐색 중...")
        best_stop = current_stop
        best_score = current_score
        best_results = current_results

        for stop_pct in [0.02, 0.025, 0.03, 0.035, 0.04]:
            if time.time() - optimize_started >= self.time_limit_seconds:
                print("[Optimizer] 시간 제한 도달, 탐색 중단.")
                break
            if abs(stop_pct - current_stop) < 0.0001:
                marker = ' <-- 현재'
                test_avg, test_wr, test_score = avg_ret, win_rate, current_score
                print(f"  {stop_pct*100:.1f}%: 평균 {test_avg:+.2f}%, 승률 {test_wr:.1f}%, 점수 {test_score:.2f}{marker}")
                continue

            test_results = self.fetch_actual_performance(recs, stop_pct)
            if not test_results:
                continue
            test_returns = [r['return_pct'] for r in test_results]
            test_avg = sum(test_returns) / len(test_returns)
            test_wr = len([r for r in test_returns if r > 0]) / len(test_returns) * 100
            test_score = test_avg + max(test_wr - 45, 0) * 0.4
            print(f"  {stop_pct*100:.1f}%: 평균 {test_avg:+.2f}%, 승률 {test_wr:.1f}%, 점수 {test_score:.2f}")
            if test_score > best_score:
                best_score = test_score
                best_stop = stop_pct
                best_results = test_results

        if best_stop != current_stop:
            print(f"  -> 최적 TRAILING_STOP_PCT: {best_stop*100:.1f}%  (기존: {current_stop*100:.1f}%)")
        else:
            print(f"  -> 현재 TRAILING_STOP_PCT({current_stop*100:.1f}%)가 최적입니다.")

        # ── 5. TIER1_WIN_RATE 최적화 ─────────────────────────────────────
        # 저장된 사전 승률(WinRate)과 실제 수익 상관관계 분석
        recs_with_perf = [r for r in current_results if r.get('stored_win_rate') is not None]
        best_tier1 = self.base_config.get('TIER1_WIN_RATE', 60)

        if len(recs_with_perf) >= 3:
            print("\n[Optimizer] 사전 승률 vs 실제 수익 상관관계 분석...")
            print(f"  {'TIER1 기준':>10}  {'선택':>5}  {'실제 승률':>9}  {'평균 수익률':>11}  {'점수':>7}")
            print("  " + "-" * 52)

            best_tier1_score = -9999
            for threshold in [40, 45, 50, 55, 60, 65, 70]:
                selected = [r for r in recs_with_perf if r['stored_win_rate'] >= threshold]
                if len(selected) < 2:
                    continue
                sel_returns = [r['return_pct'] for r in selected]
                sel_avg = sum(sel_returns) / len(sel_returns)
                sel_wr = len([r for r in sel_returns if r > 0]) / len(sel_returns) * 100
                sel_score = sel_avg + max(sel_wr - 45, 0) * 0.4
                marker = ' <-- 현재' if threshold == self.base_config.get('TIER1_WIN_RATE', 60) else ''
                print(
                    f"  >= {threshold:>5}%:  {len(selected):>4}개  "
                    f"{sel_wr:>7.1f}%  {sel_avg:>+9.2f}%  {sel_score:>7.2f}{marker}"
                )
                if sel_score > best_tier1_score:
                    best_tier1_score = sel_score
                    best_tier1 = threshold

            if best_tier1 != self.base_config.get('TIER1_WIN_RATE', 60):
                print(f"  -> 최적 TIER1_WIN_RATE: {best_tier1}%  (기존: {self.base_config.get('TIER1_WIN_RATE', 60)}%)")
            else:
                print(f"  -> 현재 TIER1_WIN_RATE({self.base_config.get('TIER1_WIN_RATE', 60)}%)가 최적입니다.")
        else:
            print("\n[Optimizer] 사전 승률 저장 데이터가 부족해 TIER1 임계값 분석을 건너뜁니다. "
                  "(다음 주부터 BuyPrice가 포함된 신규 이력이 쌓이면 분석됩니다.)")

        # ── 6. 변경사항 저장 및 보고 ─────────────────────────────────────
        best_config = copy.deepcopy(self.base_config)
        best_config['TRAILING_STOP_PCT'] = best_stop
        best_config['TIER1_WIN_RATE'] = best_tier1
        changes = compute_config_changes(self.base_config, best_config)

        if not changes:
            print("\n[Optimizer] 현재 전략이 최적입니다. 변경 없이 종료합니다.")
        else:
            print(f"\n[Optimizer] 파라미터 변경: {list(changes.keys())}")
            self.save_config(best_config)

            # after metrics: 변경된 trailing stop으로 재계산
            final_results = self.fetch_actual_performance(recs, best_stop)
            final_returns = [r['return_pct'] for r in final_results] if final_results else returns
            after_metrics = {
                'count': len(final_results),
                'avg_return': sum(final_returns) / len(final_returns) if final_returns else 0,
                'win_rate': (
                    len([r for r in final_returns if r > 0]) / len(final_returns) * 100
                    if final_returns else 0
                ),
                'max_return': max(final_returns) if final_returns else 0,
                'min_return': min(final_returns) if final_returns else 0,
            }

            notes = [f"실제 추천 종목 {len(current_results)}개 성과 기반 최적화"]
            if avg_ret < 0:
                notes.append(f"현재 전략 평균 수익률이 {avg_ret:.2f}%로 손실 구간입니다.")
            if win_rate < 50:
                notes.append(f"실제 승률이 {win_rate:.1f}%로 50% 미만입니다.")

            report = AlgorithmUpdateReport(
                title='이번주 추천 종목 실적 기반 알고리즘 업데이트',
                before_metrics=before_metrics,
                after_metrics=after_metrics,
                changes=changes,
                notes=notes,
            )
            report.save_markdown()
            report.save_log()
            report.send_telegram()
            print(f"[Optimizer] 업데이트 완료. {self.config_file} 저장됨.")

        self.analyzer.config = self.base_config


            test_results = self.fetch_actual_performance(recs, stop_pct)
            if not test_results:
                continue
            test_returns = [r['return_pct'] for r in test_results]
            test_avg = sum(test_returns) / len(test_returns)
            test_wr = len([r for r in test_returns if r > 0]) / len(test_returns) * 100
            test_score = test_avg + max(test_wr - 45, 0) * 0.4
            print(f"  {stop_pct*100:.1f}%: 평균 {test_avg:+.2f}%, 승률 {test_wr:.1f}%, 점수 {test_score:.2f}")
            if test_score > best_score:
                best_score = test_score
                best_stop = stop_pct
                best_results = test_results

        if best_stop != current_stop:
            print(f"  -> 최적 TRAILING_STOP_PCT: {best_stop*100:.1f}%  (기존: {current_stop*100:.1f}%)")
        else:
            print(f"  -> 현재 TRAILING_STOP_PCT({current_stop*100:.1f}%)가 최적입니다.")

        # ── 5. TIER1_WIN_RATE 최적화 ─────────────────────────────────────
        # 저장된 사전 승률(WinRate)과 실제 수익 상관관계 분석
        recs_with_perf = [r for r in current_results if r.get('stored_win_rate') is not None]
        best_tier1 = self.base_config.get('TIER1_WIN_RATE', 60)

        if len(recs_with_perf) >= 3:
            print("\n[Optimizer] 사전 승률 vs 실제 수익 상관관계 분석...")
            print(f"  {'TIER1 기준':>10}  {'선택':>5}  {'실제 승률':>9}  {'평균 수익률':>11}  {'점수':>7}")
            print("  " + "-" * 52)

            best_tier1_score = -9999
            for threshold in [40, 45, 50, 55, 60, 65, 70]:
                selected = [r for r in recs_with_perf if r['stored_win_rate'] >= threshold]
                if len(selected) < 2:
                    continue
                sel_returns = [r['return_pct'] for r in selected]
                sel_avg = sum(sel_returns) / len(sel_returns)
                sel_wr = len([r for r in sel_returns if r > 0]) / len(sel_returns) * 100
                sel_score = sel_avg + max(sel_wr - 45, 0) * 0.4
                marker = ' <-- 현재' if threshold == self.base_config.get('TIER1_WIN_RATE', 60) else ''
                print(
                    f"  >= {threshold:>5}%:  {len(selected):>4}개  "
                    f"{sel_wr:>7.1f}%  {sel_avg:>+9.2f}%  {sel_score:>7.2f}{marker}"
                )
                if sel_score > best_tier1_score:
                    best_tier1_score = sel_score
                    best_tier1 = threshold

            if best_tier1 != self.base_config.get('TIER1_WIN_RATE', 60):
                print(f"  -> 최적 TIER1_WIN_RATE: {best_tier1}%  (기존: {self.base_config.get('TIER1_WIN_RATE', 60)}%)")
            else:
                print(f"  -> 현재 TIER1_WIN_RATE({self.base_config.get('TIER1_WIN_RATE', 60)}%)가 최적입니다.")
        else:
            print("\n[Optimizer] 사전 승률 저장 데이터가 부족해 TIER1 임계값 분석을 건너뜁니다. "
                  "(다음 주부터 BuyPrice가 포함된 신규 이력이 쌓이면 분석됩니다.)")

        # ── 6. 변경사항 저장 및 보고 ─────────────────────────────────────
        best_config = copy.deepcopy(self.base_config)
        best_config['TRAILING_STOP_PCT'] = best_stop
        best_config['TIER1_WIN_RATE'] = best_tier1
        changes = compute_config_changes(self.base_config, best_config)

        if not changes:
            print("\n[Optimizer] 현재 전략이 최적입니다. 변경 없이 종료합니다.")
        else:
            print(f"\n[Optimizer] 파라미터 변경: {list(changes.keys())}")
            self.save_config(best_config)

            # after metrics: 변경된 trailing stop으로 재계산
            final_results = self.fetch_actual_performance(recs, best_stop)
            final_returns = [r['return_pct'] for r in final_results] if final_results else returns
            after_metrics = {
                'count': len(final_results),
                'avg_return': sum(final_returns) / len(final_returns) if final_returns else 0,
                'win_rate': (
                    len([r for r in final_returns if r > 0]) / len(final_returns) * 100
                    if final_returns else 0
                ),
                'max_return': max(final_returns) if final_returns else 0,
                'min_return': min(final_returns) if final_returns else 0,
            }

            notes = [f"실제 추천 종목 {len(current_results)}개 성과 기반 최적화"]
            if avg_ret < 0:
                notes.append(f"현재 전략 평균 수익률이 {avg_ret:.2f}%로 손실 구간입니다.")
            if win_rate < 50:
                notes.append(f"실제 승률이 {win_rate:.1f}%로 50% 미만입니다.")

            report = AlgorithmUpdateReport(
                title='이번주 추천 종목 실적 기반 알고리즘 업데이트',
                before_metrics=before_metrics,
                after_metrics=after_metrics,
                changes=changes,
                notes=notes,
            )
            report.save_markdown()
            report.save_log()
            report.send_telegram()
            print(f"[Optimizer] 업데이트 완료. {self.config_file} 저장됨.")

        self.analyzer.config = self.base_config


if __name__ == '__main__':
    optimizer = StrategyOptimizer()
    optimizer.optimize()
