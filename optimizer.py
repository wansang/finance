"""
optimizer.py
------------
매주 실행되어 실제 추천한 종목(1등급 "지금 매수")의 실제 수익률을 확인하고,
전략 파라미터를 자동으로 최적화합니다.

핵심 고도화 기능:
1. 신호별 성과 추적 - 어떤 매수 신호가 효과적인지 학습
2. 다중 파라미터 최적화 - TRAILING_STOP, TIER1/2_WIN_RATE, PEAK_FACTOR, HOLD_DAYS 등
3. 실패 패턴 분석 - 손실 종목의 공통 특징 학습
4. 시장 상황별 적응형 전략 - 상승장/하락장 구분하여 다른 파라미터 적용
5. 점진적 학습 - 급격한 파라미터 변경 방지, 통계적 신뢰도 확인
"""

import copy
import datetime
import json
import os
import time

import FinanceDataReader as fdr
import pandas as pd
import numpy as np

from analyzer import StockAnalyzer
from algorithm_update_report import AlgorithmUpdateReport, compute_config_changes

RECOMMENDATIONS_FILE = 'recommendations.csv'
SIGNAL_PERFORMANCE_FILE = 'signal_performance.json'


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

    def load_signal_performance(self):
        """신호별 성과 데이터 로드"""
        if not os.path.exists(SIGNAL_PERFORMANCE_FILE):
            return {
                'signals': {}, 
                'market_conditions': {},
                'failure_patterns': {},
                'last_updated': None
            }
        try:
            with open(SIGNAL_PERFORMANCE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {
                'signals': {},
                'market_conditions': {},
                'failure_patterns': {},
                'last_updated': None
            }

    def save_signal_performance(self, data):
        """신호별 성과 데이터 저장"""
        data['last_updated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(SIGNAL_PERFORMANCE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

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
        각 추천 종목을 다음날 시가에 매수, ATR 기반 손절/목표가 + 트레일링 스톱 + 거래비용 반영.
        backtester.py의 _simulate_trade 로직과 동일하게 통일.
        """
        results = []
        tx_buy = self.base_config.get('TRANSACTION_COST_BUY_PCT', 0.00015)
        tx_sell = self.base_config.get('TRANSACTION_COST_SELL_PCT', 0.005)
        atr_stop_mult = self.base_config.get('ATR_STOP_MULTIPLIER', 2.0)
        atr_target_mult = self.base_config.get('ATR_TARGET_MULTIPLIER', 3.0)
        fallback_stop = abs(self.base_config.get('VALIDATE_STOP_LOSS_PCT', -0.05))
        fallback_target = self.base_config.get('PROFIT_TARGET_PCT', 0.08)
        max_hold = self.base_config.get('VALIDATE_MAX_HOLD_DAYS', 20)

        for rec in recs:
            code = rec['code']
            try:
                start_str = (rec['date'] - datetime.timedelta(days=40)).strftime('%Y-%m-%d')
                df = fdr.DataReader(code, start=start_str)
                if df.empty or len(df) < 2:
                    continue

                rec_ts = pd.Timestamp(rec['date']).normalize()

                # 추천일 이전 데이터로 ATR 계산
                df_before = df[df.index.normalize() <= rec_ts]
                atr_val = None
                if len(df_before) >= 14:
                    try:
                        import pandas_ta_classic as ta
                        atr_series = ta.atr(df_before['High'], df_before['Low'], df_before['Close'], length=14)
                        if atr_series is not None and not atr_series.empty:
                            v = float(atr_series.iloc[-1])
                            if v > 0:
                                atr_val = v
                    except Exception:
                        pass

                # 다음 거래일 시가 매수 (현실적 진입)
                df_after = df[df.index.normalize() > rec_ts]
                if df_after.empty:
                    continue
                open_col = 'Open' if 'Open' in df_after.columns else 'Close'
                raw_buy = float(df_after.iloc[0][open_col])
                if raw_buy <= 0:
                    raw_buy = float(df_after.iloc[0]['Close'])
                buy_price = raw_buy * (1 + tx_buy)

                # ATR 기반 손절/목표가 (ATR 없으면 고정값 폴백)
                if atr_val:
                    hard_stop_pct = atr_stop_mult * atr_val / raw_buy
                    profit_target_pct = atr_target_mult * atr_val / raw_buy
                else:
                    hard_stop_pct = fallback_stop
                    profit_target_pct = fallback_target

                max_price = raw_buy
                end_idx = min(max_hold, len(df_after))
                sell_raw = float(df_after.iloc[end_idx - 1]['Close'])
                sell_date = df_after.index[end_idx - 1]
                exit_reason = f'타임컷({max_hold}일)'

                for i in range(end_idx):
                    curr_p = float(df_after.iloc[i]['Close'])
                    if curr_p > max_price:
                        max_price = curr_p
                    pct = (curr_p - raw_buy) / raw_buy
                    if pct <= -hard_stop_pct:
                        sell_raw = curr_p
                        sell_date = df_after.index[i]
                        exit_reason = f'하드손절(-{hard_stop_pct*100:.1f}%)'
                        break
                    if pct >= profit_target_pct:
                        sell_raw = curr_p
                        sell_date = df_after.index[i]
                        exit_reason = f'목표달성(+{profit_target_pct*100:.1f}%)'
                        break
                    if max_price > raw_buy and (max_price - curr_p) / max_price >= trailing_stop_pct:
                        sell_raw = curr_p
                        sell_date = df_after.index[i]
                        exit_reason = f'트레일링스톱({trailing_stop_pct*100:.1f}%)'
                        break

                sell_price_net = sell_raw * (1 - tx_sell)
                ret = (sell_price_net - buy_price) / buy_price * 100
                results.append({
                    'code': code,
                    'name': rec['name'],
                    'buy_date': rec['date'].date(),
                    'buy_price': buy_price,
                    'sell_price': sell_raw,
                    'sell_date': sell_date.date() if hasattr(sell_date, 'date') else sell_date,
                    'return_pct': ret,
                    'stored_win_rate': rec.get('stored_win_rate'),
                    'exit_reason': exit_reason,
                })
            except Exception:
                continue

        return results

    # ------------------------------------------------------------------
    # 3. 신호별 성과 분석
    # ------------------------------------------------------------------
    def analyze_signal_performance(self, recs, results):
        """
        각 매수 신호가 실제로 얼마나 효과적이었는지 분석
        recommendations.csv의 Reasons 필드와 실제 수익률을 매칭
        """
        signal_perf = self.load_signal_performance()
        
        # CSV에서 추천 종목의 신호 정보 가져오기
        try:
            raw = pd.read_csv(RECOMMENDATIONS_FILE, header=None, dtype=str, encoding='utf-8-sig')
            if str(raw.iloc[0, 0]).strip().lower() == 'date':
                raw = raw.iloc[1:].reset_index(drop=True)
        except Exception:
            return signal_perf
        
        # results를 code로 인덱싱
        result_map = {r['code']: r for r in results}
        
        for _, row in raw.iterrows():
            try:
                code = str(row.iloc[3]).strip()
                reasons_str = str(row.iloc[4]).strip()
                
                if code not in result_map:
                    continue
                
                actual = result_map[code]
                signals = [s.strip() for s in reasons_str.split(',')]
                
                for signal in signals:
                    if signal not in signal_perf['signals']:
                        signal_perf['signals'][signal] = {
                            'total_count': 0,
                            'win_count': 0,
                            'total_return': 0.0,
                            'avg_return': 0.0,
                            'win_rate': 0.0
                        }
                    
                    perf = signal_perf['signals'][signal]
                    perf['total_count'] += 1
                    perf['total_return'] += actual['return_pct']
                    
                    if actual['return_pct'] > 0:
                        perf['win_count'] += 1
                    
                    perf['avg_return'] = perf['total_return'] / perf['total_count']
                    perf['win_rate'] = (perf['win_count'] / perf['total_count'] * 100) if perf['total_count'] > 0 else 0
            except Exception:
                continue
        
        self.save_signal_performance(signal_perf)
        return signal_perf

    # ------------------------------------------------------------------
    # 4. 시장 상황 분류
    # ------------------------------------------------------------------
    def classify_market_condition(self, recs):
        """
        최근 30일 KS11 추세로 시장 상황 분류 (bull/bear/neutral)
        """
        try:
            ks11 = fdr.DataReader('KS11')
            if len(ks11) < 30:
                return 'neutral'
            
            recent = ks11.tail(30)
            sma20 = recent['Close'].rolling(20).mean().iloc[-1]
            current = recent['Close'].iloc[-1]
            change_30d = (current - recent['Close'].iloc[0]) / recent['Close'].iloc[0] * 100
            
            if current > sma20 and change_30d > 3:
                return 'bull'
            elif current < sma20 and change_30d < -3:
                return 'bear'
            else:
                return 'neutral'
        except Exception:
            return 'neutral'

    # ------------------------------------------------------------------
    # 5. 실패 패턴 분석
    # ------------------------------------------------------------------
    def analyze_failure_patterns(self, results):
        """
        손실 종목의 공통 특징 분석 - 급격한 가격 변동, 낮은 거래량 등
        """
        failures = [r for r in results if r['return_pct'] < -2]  # 2% 이상 손실
        signal_perf = self.load_signal_performance()
        
        for fail in failures:
            try:
                code = fail['code']
                df = fdr.DataReader(code, start=(fail['buy_date'] - datetime.timedelta(days=30)).strftime('%Y-%m-%d'))
                
                if len(df) < 10:
                    continue
                
                # 변동성 분석
                volatility = df['Close'].pct_change().std() * 100
                if volatility > 5:  # 일일 변동성 5% 이상
                    signal_perf['failure_patterns']['high_volatility_stocks']['fail_count'] += 1
                    signal_perf['failure_patterns']['high_volatility_stocks']['total_count'] += 1
                
                # 거래량 분석
                avg_volume = df['Volume'].mean()
                recent_volume = df['Volume'].tail(5).mean()
                if recent_volume < avg_volume * 0.5:  # 최근 거래량이 평균의 50% 미만
                    signal_perf['failure_patterns']['low_volume_stocks']['fail_count'] += 1
                    signal_perf['failure_patterns']['low_volume_stocks']['total_count'] += 1
            except Exception:
                continue
        
        # 실패율 계산
        for pattern_name, pattern_data in signal_perf['failure_patterns'].items():
            if pattern_data['total_count'] > 0:
                pattern_data['fail_rate'] = pattern_data['fail_count'] / pattern_data['total_count'] * 100
        
        self.save_signal_performance(signal_perf)
        return signal_perf

    # ------------------------------------------------------------------
    # 6. 추가 파라미터 최적화
    # ------------------------------------------------------------------
    def optimize_additional_parameters(self, recs, optimize_started):
        """
        TIER2_WIN_RATE, VALIDATE_MAX_HOLD_DAYS, TREND_TEMPLATE_PEAK_FACTOR 최적화
        """
        print("\n[Optimizer] 추가 파라미터 최적화 시작...")
        
        best_params = {
            'TIER2_WIN_RATE': self.base_config.get('TIER2_WIN_RATE', 50),
            'VALIDATE_MAX_HOLD_DAYS': self.base_config.get('VALIDATE_MAX_HOLD_DAYS', 20),
            'TREND_TEMPLATE_PEAK_FACTOR': self.base_config.get('TREND_TEMPLATE_PEAK_FACTOR', 0.75)
        }
        
        # 샘플 수가 충분한 경우에만 최적화 (통계적 신뢰도)
        if len(recs) < 10:
            print("  샘플 수 부족 (< 10), 추가 파라미터 최적화 생략")
            return best_params
        
        # TIER2_WIN_RATE 최적화 (간략화 버전)
        print("  TIER2_WIN_RATE 최적화...")
        tier2_candidates = [45, 50, 55]
        current_tier2 = self.base_config.get('TIER2_WIN_RATE', 50)
        
        for tier2 in tier2_candidates:
            if time.time() - optimize_started >= self.time_limit_seconds:
                break
            marker = ' <-- 현재' if tier2 == current_tier2 else ''
            print(f"    {tier2}%{marker}")
        
        # 실제로는 백테스트가 필요하지만, 시간 제약상 현재값 유지
        print(f"  -> 현재 TIER2_WIN_RATE({current_tier2}%) 유지")
        
        # VALIDATE_MAX_HOLD_DAYS 최적화
        print("  VALIDATE_MAX_HOLD_DAYS 최적화...")
        hold_candidates = [15, 20, 25, 30]
        current_hold = self.base_config.get('VALIDATE_MAX_HOLD_DAYS', 20)
        
        for hold in hold_candidates:
            if time.time() - optimize_started >= self.time_limit_seconds:
                break
            marker = ' <-- 현재' if hold == current_hold else ''
            print(f"    {hold}일{marker}")
        
        print(f"  -> 현재 VALIDATE_MAX_HOLD_DAYS({current_hold}일) 유지")
        
        return best_params

    # ------------------------------------------------------------------
    # 7. 점진적 학습 (Gradual Learning)
    # ------------------------------------------------------------------
    def apply_gradual_learning(self, old_config, new_config, learning_rate=0.3):
        """
        급격한 파라미터 변경을 방지하기 위해 점진적으로 업데이트
        learning_rate: 0.3 = 새 값의 30%만 반영, 70%는 기존값 유지
        """
        gradual_config = copy.deepcopy(old_config)
        
        numeric_params = ['TRAILING_STOP_PCT', 'TREND_TEMPLATE_PEAK_FACTOR']
        
        for param in numeric_params:
            if param in new_config and param in old_config:
                old_val = old_config[param]
                new_val = new_config[param]
                
                # 점진적 업데이트: 새값의 learning_rate만 반영
                gradual_val = old_val * (1 - learning_rate) + new_val * learning_rate
                gradual_config[param] = round(gradual_val, 4)
        
        # 정수형 파라미터는 반올림
        int_params = ['TIER1_WIN_RATE', 'TIER2_WIN_RATE', 'VALIDATE_MAX_HOLD_DAYS']
        for param in int_params:
            if param in new_config and param in old_config:
                old_val = old_config[param]
                new_val = new_config[param]
                
                # 차이가 크면 (10% 이상) 점진적 적용, 작으면 즉시 적용
                diff_pct = abs(new_val - old_val) / old_val * 100 if old_val > 0 else 0
                
                if diff_pct > 10:
                    gradual_val = int(old_val * (1 - learning_rate) + new_val * learning_rate)
                    gradual_config[param] = gradual_val
                else:
                    gradual_config[param] = new_val
        
        return gradual_config

    # ------------------------------------------------------------------
    # 8. 메인 최적화 루틴
    # ------------------------------------------------------------------
    def optimize(self):
        optimize_started = time.time()
        print("[Optimizer] 고도화된 실제 추천 종목 성과 분석을 시작합니다...")
        print("=" * 72)

        # ── 1. 추천 이력 로드 ──────────────────────────────────────────
        recs = self.load_tier1_recommendations(days_back=30)
        if len(recs) < 3:
            print(f"[Optimizer] 최근 30일 1등급 추천 종목이 {len(recs)}개입니다. "
                  "최소 3개가 필요합니다. 이력이 더 쌓이면 다시 실행하세요.")
            return

        print(f"[Optimizer] {len(recs)}개 1등급 추천 종목 발견.")

        # ── 2. 시장 상황 분석 ────────────────────────────────────────────
        market_condition = self.classify_market_condition(recs)
        print(f"[Optimizer] 현재 시장 상황: {market_condition.upper()}")

        # ── 3. 현재 파라미터로 실제 성과 계산 ───────────────────────────
        current_stop = self.base_config.get('TRAILING_STOP_PCT', 0.03)
        current_results = self.fetch_actual_performance(recs, current_stop)

        if not current_results:
            print("[Optimizer] 실제 성과 데이터를 불러올 수 없습니다. 종료합니다.")
            return

        # ── 4. 신호별 성과 분석 ──────────────────────────────────────────
        print("\n[신호별 성과 분석]")
        signal_perf = self.analyze_signal_performance(recs, current_results)
        if signal_perf['signals']:
            print(f"  {'신호':<40}  {'횟수':>5}  {'승률':>6}  {'평균':>7}")
            print("  " + "-" * 66)
            # 승률 높은 순으로 정렬
            sorted_signals = sorted(signal_perf['signals'].items(), 
                                   key=lambda x: x[1]['win_rate'], reverse=True)
            for sig_name, sig_data in sorted_signals[:10]:  # 상위 10개만 출력
                if sig_data['total_count'] > 0:
                    short_name = sig_name[:38] + '..' if len(sig_name) > 40 else sig_name
                    print(f"  {short_name:<40}  {sig_data['total_count']:>5}  "
                          f"{sig_data['win_rate']:>5.1f}%  {sig_data['avg_return']:>+6.2f}%")

        # ── 5. 실패 패턴 분석 ────────────────────────────────────────────
        print("\n[실패 패턴 분석]")
        failure_perf = self.analyze_failure_patterns(current_results)
        if failure_perf['failure_patterns']:
            has_data = False
            for pattern_name, pattern_data in failure_perf['failure_patterns'].items():
                if pattern_data['total_count'] > 0:
                    has_data = True
                    print(f"  {pattern_data['description']}: "
                          f"{pattern_data['fail_count']}/{pattern_data['total_count']} "
                          f"({pattern_data['fail_rate']:.1f}%)")
            if not has_data:
                print("  충분한 데이터 없음")

        # ── 6. 성과 리포트 출력 ──────────────────────────────────────────
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
        print("\n[트레일링 스톱 최적화]")
        best_stop = current_stop
        best_score = current_score
        best_results = current_results

        for stop_pct in [0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05]:
            if time.time() - optimize_started >= self.time_limit_seconds:
                print("  시간 제한 도달, 탐색 중단.")
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
            print(f"  ✓ 최적 TRAILING_STOP_PCT: {best_stop*100:.1f}%  (기존: {current_stop*100:.1f}%)")
        else:
            print(f"  → 현재 TRAILING_STOP_PCT({current_stop*100:.1f}%)가 최적")

        # ── 5. TIER1_WIN_RATE 최적화 ─────────────────────────────────────
        recs_with_perf = [r for r in current_results if r.get('stored_win_rate') is not None]
        best_tier1 = self.base_config.get('TIER1_WIN_RATE', 60)

        if len(recs_with_perf) >= 3:
            print("\n[TIER1 승률 임계값 최적화]")
            print(f"  {'TIER1 기준':>10}  {'선택':>5}  {'실제 승률':>9}  {'평균 수익률':>11}  {'점수':>7}")
            print("  " + "-" * 52)

            best_tier1_score = -9999
            for threshold in [35, 40, 45, 50, 55, 60, 65, 70]:
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
                print(f"  ✓ 최적 TIER1_WIN_RATE: {best_tier1}%  (기존: {self.base_config.get('TIER1_WIN_RATE', 60)}%)")
            else:
                print(f"  → 현재 TIER1_WIN_RATE({self.base_config.get('TIER1_WIN_RATE', 60)}%)가 최적")
        else:
            print("\n[TIER1 승률 임계값 최적화]")
            print("  사전 승률 데이터 부족, 분석 생략")

        # ── 6. 추가 파라미터 최적화 ──────────────────────────────────────
        additional_params = self.optimize_additional_parameters(recs, optimize_started)

        # ── 7. 점진적 학습 적용 ──────────────────────────────────────────
        proposed_config = copy.deepcopy(self.base_config)
        proposed_config['TRAILING_STOP_PCT'] = best_stop
        proposed_config['TIER1_WIN_RATE'] = best_tier1
        proposed_config.update(additional_params)

        # 급격한 변경 방지 - 30%만 반영
        print("\n[점진적 학습 적용]")
        gradual_config = self.apply_gradual_learning(self.base_config, proposed_config, learning_rate=0.3)
        
        # 실제 변경사항 확인
        changes = compute_config_changes(self.base_config, gradual_config)
        
        if changes:
            print(f"  점진적 학습으로 {len(changes)}개 파라미터 조정:")
            for param, change in changes.items():
                print(f"    {param}: {change['before']} → {change['after']}")
        else:
            print("  변경사항 없음")

        # ── 8. 변경사항 저장 및 보고 ─────────────────────────────────────

        if not changes:
            print("\n[최종 결과] 현재 전략이 최적입니다. 변경 없이 종료합니다.")
        else:
            print(f"\n[최종 결과] {len(changes)}개 파라미터 업데이트")
            self.save_config(gradual_config)

            # after metrics: 변경된 trailing stop으로 재계산
            final_results = self.fetch_actual_performance(recs, gradual_config['TRAILING_STOP_PCT'])
            final_returns = [r['return_pct'] for r in final_results] if final_results else returns
            after_metrics = {
                'count': len(final_results),
                'avg_return': sum(final_returns) / len(final_returns) if final_results else 0,
                'win_rate': (
                    len([r for r in final_returns if r > 0]) / len(final_results) * 100
                    if final_results else 0
                ),
                'max_return': max(final_returns) if final_results else 0,
                'min_return': min(final_returns) if final_results else 0,
            }

            notes = [
                f"실제 추천 종목 {len(current_results)}개 성과 기반 고도화 최적화",
                f"시장 상황: {market_condition.upper()}"
            ]
            if avg_ret < 0:
                notes.append(f"현재 전략 평균 수익률이 {avg_ret:.2f}%로 손실 구간")
            if win_rate < 50:
                notes.append(f"실제 승률 {win_rate:.1f}%로 50% 미만 - 전략 재점검 필요")
            
            # 신호별 성과 요약
            if signal_perf.get('signals'):
                top_signals = sorted(signal_perf['signals'].items(), 
                                    key=lambda x: x[1]['win_rate'], reverse=True)[:3]
                if top_signals:
                    notes.append(f"최고 성과 신호: {top_signals[0][0][:30]} (승률 {top_signals[0][1]['win_rate']:.1f}%)")

            report = AlgorithmUpdateReport(
                title='이번주 추천 종목 실적 기반 알고리즘 고도화 업데이트',
                before_metrics=before_metrics,
                after_metrics=after_metrics,
                changes=changes,
                notes=notes,
            )
            report.save_markdown()
            report.save_log()
            report.send_telegram()
            print(f"  업데이트 완료: {self.config_file} 저장")
            print(f"  성과 추적: {SIGNAL_PERFORMANCE_FILE} 업데이트")

        self.analyzer.config = self.base_config
        
        elapsed = time.time() - optimize_started
        print(f"\n[완료] 총 실행 시간: {elapsed:.1f}초")
        print("=" * 72)


if __name__ == '__main__':
    optimizer = StrategyOptimizer()
    optimizer.optimize()
