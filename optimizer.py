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
import shutil
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
            900)

    def process_search_backlog(self):
        """
        searchBacklog.json의 backlog를 agent_stock / agent_etf → backtester → agent_backtest
        이중 검증 루프로 처리한다.

        방법론별 흐름 (두 경로 독립 실행):
          [주식 경로]
          1a. agent_stock  : 방법론 → KOSPI 주식 파라미터 변경 제안 (US_*/ETF_* 키 제외)
          2a. backtester   : Before/After KOSPI 백테스트
          3a. agent_backtest: 주식 기준(MDD<20%, WR≥38%) 승인/거부

          [ETF 경로]
          1b. agent_etf    : 방법론 → ETF 전용 파라미터 변경 제안 (US_*, ETF_*, KOSPI_ETF_* 키)
          2b. backtester   : Before/After ETF 유니버스 백테스트
          3b. agent_backtest: ETF 기준(MDD<15%, KOSPI ETF WR≥38%, US ETF WR≥35%) 승인/거부

          5. 두 경로 승인 변경사항 합산 → strategy_config.json 반영
          6. algorithm_update_log.json 기록
          7. 처리 항목 → searchBacklog_history.json 아카이브 (validation_result 포함)
          8. 미처리 항목은 다음 실행까지 backlog 보존

        설정:
          BACKLOG_VALIDATE_PER_RUN (strategy_config.json): 1회 처리 항목 수 (기본 3)
        """
        backlog_file = 'searchBacklog.json'
        history_file = 'searchBacklog_history.json'

        if not os.path.exists(backlog_file):
            print("[backlog] 파일 없음 — 스킵")
            return
        try:
            with open(backlog_file, 'r', encoding='utf-8') as f:
                backlog = json.load(f)
        except Exception:
            print("[backlog] 파일 파싱 오류 — 스킵")
            return
        if not backlog:
            print("[backlog] 비어 있음 — 스킵")
            return

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[backlog] GEMINI_API_KEY 없음 — 단순 아카이브만 수행")
            self._archive_backlog(backlog, backlog_file, history_file, [])
            return

        max_per_run = self._safe_int(
            self.base_config.get('BACKLOG_VALIDATE_PER_RUN', 3), 3
        )
        to_process = backlog[:max_per_run]
        remaining = backlog[max_per_run:]

        print(f"\n{'='*60}")
        print(f"  [backlog 검증] {len(to_process)}건 처리 (전체 {len(backlog)}건, 잔여 {len(remaining)}건)")
        print(f"{'='*60}")

        from backtester import Backtester
        backtester = Backtester()

        # ── Before 백테스트 (KOSPI 주식 + ETF 각각) ───────────────────────
        print("\n[1단계] Before 백테스트 실행 중 (주식 + ETF)...")
        try:
            df_before_stock = backtester.run_walkforward_backtest(periods=6, interval_weeks=6)
            before_stock_metrics = self._extract_backtest_metrics(df_before_stock)
            print(f"  [주식] Before → 거래:{before_stock_metrics['count']}건, "
                  f"승률:{before_stock_metrics['win_rate']:.1f}%, "
                  f"평균수익:{before_stock_metrics['avg_return']:+.2f}%, "
                  f"MDD:{before_stock_metrics['mdd']:.2f}%, "
                  f"Sharpe:{before_stock_metrics['sharpe']:.2f}")
        except Exception as e:
            print(f"  Before 주식 백테스트 실패: {e} — 단순 아카이브로 전환")
            self._archive_backlog(backlog, backlog_file, history_file, [])
            return

        try:
            df_before_etf = self._run_etf_backtest(backtester, periods=6, interval_weeks=6)
            before_etf_metrics = self._extract_backtest_metrics(df_before_etf)
            print(f"  [ETF]  Before → 거래:{before_etf_metrics['count']}건, "
                  f"승률:{before_etf_metrics['win_rate']:.1f}%, "
                  f"평균수익:{before_etf_metrics['avg_return']:+.2f}%, "
                  f"MDD:{before_etf_metrics['mdd']:.2f}%, "
                  f"Sharpe:{before_etf_metrics['sharpe']:.2f}")
        except Exception as e:
            print(f"  Before ETF 백테스트 실패: {e} — ETF 경로 스킵")
            before_etf_metrics = None

        # ── 시장 희소성 사전 체크 ──────────────────────────────────────────
        STOCK_MIN_BEFORE = 10  # Before 거래 수 미달 시 sparse_market 스킵
        ETF_MIN_BEFORE   = 3
        stock_sparse = before_stock_metrics['count'] < STOCK_MIN_BEFORE
        etf_sparse   = (before_etf_metrics is None or before_etf_metrics['count'] < ETF_MIN_BEFORE)
        if stock_sparse:
            print(f"  ⚠️ [주식] Before 샘플({before_stock_metrics['count']}건) < {STOCK_MIN_BEFORE} "
                  f"— 시장 신호 희소, 주식 경로 검증 스킵")
        if etf_sparse:
            etf_cnt = before_etf_metrics['count'] if before_etf_metrics else 0
            print(f"  ⚠️ [ETF]  Before 샘플({etf_cnt}건) < {ETF_MIN_BEFORE} — ETF 검증 스킵")

        current_config = copy.deepcopy(self.base_config)
        config_str = json.dumps(current_config, ensure_ascii=False, indent=2)

        processed_entries = []
        all_approved_changes = {}

        # ── 방법론별 검증 루프 (주식 + ETF 이중 경로) ────────────────────
        for i, entry in enumerate(to_process):
            method = entry.get('method', {})
            method_name = method.get('방법론명', f'방법론_{i+1}')
            print(f"\n--- [{i+1}/{len(to_process)}] {method_name} ---")

            stock_result = None
            etf_result = None

            # ── 주식 경로: agent_stock → KOSPI 백테스트 → agent_backtest ──
            if stock_sparse:
                print("  [주식] Before 희소 — 검증 스킵 (sparse_market)")
                stock_result = {'verdict': 'sparse_market', 'reason': f'Before 샘플({before_stock_metrics["count"]}건) 희소 — 현재 시장 신호 부족으로 통계 검증 불가'}
            else:
                print("  [agent_stock] 주식 파라미터 변경 제안 생성 중...")
                stock_proposal = self._call_agent_stock(api_key, method, config_str, pre_changes=method.get('제안_파라미터_변경'))
                if stock_proposal and stock_proposal.get('param_changes'):
                    stock_changes = stock_proposal['param_changes']
                    print(f"  → 주식 제안: {stock_changes}")
                    original_config = copy.deepcopy(backtester.analyzer.config)
                    try:
                        backtester.analyzer.config = {**current_config, **stock_changes}
                        backtester.data_cache.clear()
                        df_after_stock = backtester.run_walkforward_backtest(periods=6, interval_weeks=6)
                        after_stock_metrics = self._extract_backtest_metrics(df_after_stock)
                        print(f"  [주식] After → 거래:{after_stock_metrics['count']}건, "
                              f"승률:{after_stock_metrics['win_rate']:.1f}%, "
                              f"MDD:{after_stock_metrics['mdd']:.2f}%, "
                              f"Sharpe:{after_stock_metrics['sharpe']:.2f}")
                        print("  [agent_backtest] 주식 검증 판정 중...")
                        stock_verdict = self._call_agent_backtest(
                            api_key, method_name, stock_proposal,
                            before_stock_metrics, after_stock_metrics, etf_mode=False
                        )
                        stock_result = {
                            'verdict': stock_verdict['decision'],
                            'reason': stock_verdict['reason'],
                            'before_metrics': before_stock_metrics,
                            'after_metrics': after_stock_metrics,
                            'proposed_changes': stock_changes,
                        }
                        if stock_verdict['decision'] == 'approved':
                            print(f"  ✅ [주식] 승인: {stock_verdict['reason']}")
                            all_approved_changes.update(stock_changes)
                        else:
                            print(f"  ❌ [주식] 거부: {stock_verdict['reason']}")
                    except Exception as e:
                        print(f"  [주식] After 백테스트 실패: {e}")
                        stock_result = {'verdict': 'error', 'reason': str(e)}
                    finally:
                        backtester.analyzer.config = original_config
                        backtester.data_cache.clear()
                else:
                    print("  [주식] → 파라미터 변경 없음 (구현 불가)")
                    stock_result = {'verdict': 'skipped', 'reason': 'KOSPI 주식 파라미터로 구현 불가'}

            # ── ETF 경로: agent_etf → ETF 백테스트 → agent_backtest ───────
            if etf_sparse:
                print("  [ETF] Before 희소 — 검증 스킵 (sparse_market)")
                etf_result = {'verdict': 'sparse_market', 'reason': 'ETF Before 샘플 희소 — 현재 시장 신호 부족으로 통계 검증 불가'}
            elif before_etf_metrics is not None:
                print("  [agent_etf] ETF 파라미터 변경 제안 생성 중...")
                etf_proposal = self._call_agent_etf(api_key, method, config_str, pre_changes=method.get('제안_파라미터_변경'))
                if etf_proposal and etf_proposal.get('param_changes'):
                    etf_changes = etf_proposal['param_changes']
                    print(f"  → ETF 제안: {etf_changes}")
                    original_config = copy.deepcopy(backtester.analyzer.config)
                    try:
                        backtester.analyzer.config = {**current_config, **etf_changes}
                        backtester.data_cache.clear()
                        df_after_etf = self._run_etf_backtest(backtester, periods=6, interval_weeks=6)
                        after_etf_metrics = self._extract_backtest_metrics(df_after_etf)
                        print(f"  [ETF]  After → 거래:{after_etf_metrics['count']}건, "
                              f"승률:{after_etf_metrics['win_rate']:.1f}%, "
                              f"MDD:{after_etf_metrics['mdd']:.2f}%, "
                              f"Sharpe:{after_etf_metrics['sharpe']:.2f}")
                        print("  [agent_backtest] ETF 검증 판정 중...")
                        etf_verdict = self._call_agent_backtest(
                            api_key, method_name, etf_proposal,
                            before_etf_metrics, after_etf_metrics, etf_mode=True
                        )
                        etf_result = {
                            'verdict': etf_verdict['decision'],
                            'reason': etf_verdict['reason'],
                            'before_metrics': before_etf_metrics,
                            'after_metrics': after_etf_metrics,
                            'proposed_changes': etf_changes,
                        }
                        if etf_verdict['decision'] == 'approved':
                            print(f"  ✅ [ETF] 승인: {etf_verdict['reason']}")
                            all_approved_changes.update(etf_changes)
                        else:
                            print(f"  ❌ [ETF] 거부: {etf_verdict['reason']}")
                    except Exception as e:
                        print(f"  [ETF] After 백테스트 실패: {e}")
                        etf_result = {'verdict': 'error', 'reason': str(e)}
                    finally:
                        backtester.analyzer.config = original_config
                        backtester.data_cache.clear()
                else:
                    print("  [ETF] → 파라미터 변경 없음 (ETF 파라미터로 구현 불가)")
                    etf_result = {'verdict': 'skipped', 'reason': 'ETF 전용 파라미터로 구현 불가'}
            else:
                etf_result = {'verdict': 'skipped', 'reason': 'Before ETF 백테스트 실패로 ETF 경로 건너뜀'}

            entry['validation_result'] = {
                'stock': stock_result,
                'etf': etf_result,
                'validated_at': datetime.datetime.now().isoformat(),
            }
            processed_entries.append(entry)

        # ── 승인된 변경사항 일괄 반영 ─────────────────────────────────────
        if all_approved_changes:
            print(f"\n[최종] 승인된 파라미터 {len(all_approved_changes)}건 strategy_config.json 반영")
            new_config = {**current_config, **all_approved_changes}
            self.save_config(new_config)
            self.base_config = new_config
            self.analyzer.config = new_config
            self._log_backlog_update(all_approved_changes, before_stock_metrics, processed_entries)
        else:
            print("\n[최종] 승인된 변경사항 없음")

        # ── 처리 항목 아카이브 + backlog 잔여분 보존 ─────────────────────
        self._archive_backlog(remaining, backlog_file, history_file, processed_entries)
        print(f"\n[backlog] {len(processed_entries)}건 처리 완료 → history 아카이브, 잔여 {len(remaining)}건")

    # ─────────────────────────────────────────────────────────────────────
    # backlog 헬퍼 메서드
    # ─────────────────────────────────────────────────────────────────────

    def _archive_backlog(self, remaining_backlog, backlog_file, history_file, processed_entries):
        """처리된 항목을 history에 append하고, backlog는 잔여분만 남긴다."""
        history = []
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                history = []
        history.extend(processed_entries)
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open(backlog_file, 'w', encoding='utf-8') as f:
            json.dump(remaining_backlog, f, ensure_ascii=False, indent=2)

    def _extract_backtest_metrics(self, df):
        """백테스트 DataFrame에서 핵심 지표를 추출한다."""
        if df is None or df.empty:
            return {'count': 0, 'win_rate': 0.0, 'avg_return': 0.0, 'mdd': 0.0, 'sharpe': 0.0}
        total = len(df)
        wins = (df['Return(%)'] > 0).sum()
        avg_ret = float(df['Return(%)'].mean())
        win_rate = float(wins / total * 100)
        # MDD (복리 자본곡선 기반)
        rets_seq = df.sort_values('BuyDate')['Return(%)'].tolist() if 'BuyDate' in df.columns else df['Return(%)'].tolist()
        equity = 1.0; peak_eq = 1.0; mdd = 0.0
        for r in rets_seq:
            equity *= (1 + r / 100)
            if equity > peak_eq:
                peak_eq = equity
            dd = (peak_eq - equity) / peak_eq * 100
            if dd > mdd:
                mdd = dd
        # Sharpe (연율화)
        std_ret = float(df['Return(%)'].std())
        avg_hold = self.base_config.get('VALIDATE_MAX_HOLD_DAYS', 20)
        annual_factor = (250 / max(avg_hold, 1)) ** 0.5
        risk_free = 3.5 / (250 / max(avg_hold, 1))
        sharpe = ((avg_ret - risk_free) / std_ret * annual_factor) if std_ret > 0 else 0.0
        return {
            'count': total,
            'win_rate': win_rate,
            'avg_return': avg_ret,
            'mdd': round(mdd, 4),
            'sharpe': round(sharpe, 4),
        }

    def _make_gemini_model(self, api_key):
        """agent/agent_search.py와 동일한 방식으로 Gemini 모델을 생성한다."""
        genai = None
        lib = None
        try:
            import google.genai as _genai
            if hasattr(_genai, 'GenerativeModel'):
                genai = _genai; lib = 'genai'
            else:
                import google.generativeai as _genai2
                if hasattr(_genai2, 'GenerativeModel'):
                    genai = _genai2; lib = 'generativeai'
        except ImportError:
            try:
                import google.generativeai as _genai2
                if hasattr(_genai2, 'GenerativeModel'):
                    genai = _genai2; lib = 'generativeai'
            except ImportError:
                pass
        if genai is None:
            raise RuntimeError("google-genai 또는 google-generativeai 패키지가 필요합니다.")
        model_name = 'gemini-flash-latest'
        if lib == 'generativeai':
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(model_name)
        if lib == 'genai':
            if hasattr(genai, 'GenerativeModel'):
                return genai.GenerativeModel(model_name)
            client = genai.Client(api_key=api_key)
            return client.chats.create(model=model_name)
        raise RuntimeError("지원되지 않는 AI 모델 인터페이스")

    def _gemini_generate(self, model, prompt):
        """모델에서 텍스트를 생성한다. generate_content / send_message 모두 지원."""
        if hasattr(model, 'generate_content'):
            return model.generate_content(prompt).text.strip()
        if hasattr(model, 'send_message'):
            resp = model.send_message(prompt)
            return resp.text.strip() if hasattr(resp, 'text') else str(resp)
        raise RuntimeError("AI 모델이 generate_content/send_message를 지원하지 않습니다.")

    def _parse_json_from_text(self, text):
        """AI 응답 텍스트에서 JSON 블록을 파싱한다."""
        import re
        for pattern in [r"```json\s*([\s\S]+?)```", r"```[\s\S]*?([\[{][\s\S]+?)```"]:
            m = re.search(pattern, text)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except Exception:
                    pass
        try:
            return json.loads(text)
        except Exception:
            return None

    def _call_agent_stock(self, api_key, method, config_str, pre_changes=None):
        """
        agent_stock 역할 (Gemini):
        방법론 아이디어 → KOSPI 주식 전용 파라미터 변경 제안 (US_*/ETF_* 키 제외).
        pre_changes: agent_search가 사전에 제안한 파라미터 변경값. 있으면 AI 호출 없이 바로 사용.
        반환: {"param_changes": {key: value, ...}, "reasoning": str}
        파라미터 변경이 불가능하면 {"param_changes": {}} 반환.
        """
        # agent_search가 미리 제안한 파라미터가 있으면 AI 호출 없이 바로 사용
        if pre_changes and isinstance(pre_changes, dict):
            stock_changes = {
                k: v for k, v in pre_changes.items()
                if not str(k).startswith(('US_', 'ETF_', 'KOSPI_ETF_'))
            }
            if stock_changes:
                print("  → 사전 제안 파라미터 사용 (AI 호출 생략)")
                return {'param_changes': stock_changes, 'reasoning': method.get('핵심 아이디어', '')}
        try:
            model = self._make_gemini_model(api_key)
            prompt = (
                "너는 40년 경력의 투자분석전문가(agent_stock)다.\n"
                "아래 '신규 방법론 아이디어'를 분석하고, 이 방법론의 핵심 원칙을 "
                "현재 strategy_config.json의 KOSPI 주식 파라미터 조정만으로 근사 구현할 수 있는지 판단하라.\n"
                "단, 'US_', 'ETF_', 'KOSPI_ETF_' 로 시작하는 키는 절대 변경하지 말 것 — ETF 전문가 영역이다.\n\n"
                f"[신규 방법론]\n{json.dumps(method, ensure_ascii=False, indent=2)}\n\n"
                f"[현재 strategy_config.json]\n{config_str}\n\n"
                "가능하다면 변경할 파라미터 키와 값을 JSON 형식으로 제안하라 (기존 키만 사용 가능).\n"
                "불가능하면 param_changes를 빈 객체로 반환하라.\n"
                "반드시 아래 형식으로만 응답하라:\n"
                "```json\n"
                "{\"param_changes\": {\"KEY\": value, ...}, \"reasoning\": \"변경 근거\"}\n"
                "```"
            )
            text = self._gemini_generate(model, prompt)
            result = self._parse_json_from_text(text)
            if isinstance(result, dict):
                # 안전: 주식 전문가가 ETF/US 키를 건드리지 못하도록 필터
                forbidden = [k for k in result.get('param_changes', {})
                             if str(k).startswith(('US_', 'ETF_', 'KOSPI_ETF_'))]
                for k in forbidden:
                    del result['param_changes'][k]
                return result
        except Exception as e:
            print(f"  [agent_stock 오류] {e}")
        return None

    def _call_agent_etf(self, api_key, method, config_str, pre_changes=None):
        """
        agent_etf 역할 (Gemini):
        방법론 아이디어 → ETF 전용 파라미터 변경 제안 (US_*, ETF_*, KOSPI_ETF_* 키만).
        pre_changes: agent_search가 사전에 제안한 파라미터 변경값. 있으면 AI 호출 없이 바로 사용.
        반환: {"param_changes": {key: value, ...}, "reasoning": str}
        파라미터 변경이 불가능하면 {"param_changes": {}} 반환.
        """
        # agent_search가 미리 제안한 ETF 파라미터가 있으면 AI 호출 없이 바로 사용
        if pre_changes and isinstance(pre_changes, dict):
            etf_changes = {
                k: v for k, v in pre_changes.items()
                if str(k).startswith(('US_', 'ETF_', 'KOSPI_ETF_'))
                and not isinstance(v, list)
            }
            if etf_changes:
                print("  → 사전 제안 파라미터 사용 (AI 호출 생략)")
                return {'param_changes': etf_changes, 'reasoning': method.get('핵심 아이디어', '')}
        try:
            model = self._make_gemini_model(api_key)
            prompt = (
                "너는 40년 경력의 ETF 투자 전문가(agent_etf)다.\n"
                "아래 '신규 방법론 아이디어'를 분석하고, 이 방법론의 핵심 원칙을 "
                "현재 strategy_config.json의 ETF 전용 파라미터 조정만으로 근사 구현할 수 있는지 판단하라.\n"
                "변경 가능한 키는 'US_', 'ETF_', 'KOSPI_ETF_' 로 시작하는 숫자/불리언 파라미터만 해당한다.\n"
                "티커 목록(리스트 값)은 변경하지 말 것.\n\n"
                f"[신규 방법론]\n{json.dumps(method, ensure_ascii=False, indent=2)}\n\n"
                f"[현재 strategy_config.json]\n{config_str}\n\n"
                "가능하다면 변경할 파라미터 키와 값을 JSON 형식으로 제안하라 (기존 키만 사용 가능).\n"
                "불가능하면 param_changes를 빈 객체로 반환하라.\n"
                "반드시 아래 형식으로만 응답하라:\n"
                "```json\n"
                "{\"param_changes\": {\"KEY\": value, ...}, \"reasoning\": \"변경 근거\"}\n"
                "```"
            )
            text = self._gemini_generate(model, prompt)
            result = self._parse_json_from_text(text)
            if isinstance(result, dict):
                # 안전: ETF 전문가는 ETF/US 파라미터만 수정 가능, 리스트 값 제외
                filtered = {
                    k: v for k, v in result.get('param_changes', {}).items()
                    if str(k).startswith(('US_', 'ETF_', 'KOSPI_ETF_'))
                    and not isinstance(v, list)
                }
                result['param_changes'] = filtered
                return result
        except Exception as e:
            print(f"  [agent_etf 오류] {e}")
        return None

    def _run_etf_backtest(self, backtester, days_ago=20, periods=1, interval_weeks=8):
        """
        ETF 유니버스(KOSPI ETF + US ETF)만을 대상으로 백테스트를 수행한다.
        periods>1이면 워크포워드 방식으로 여러 시점에서 실행한다.
        backtester의 현재 analyzer.config를 그대로 사용한다.
        """
        from backtester import _fdr_read
        import datetime as _dt

        ks11 = _fdr_read('KS11')
        if ks11 is None or ks11.empty:
            raise RuntimeError("KS11 데이터 로드 실패")

        # 테스트할 날짜 목록 생성 (periods>1이면 interval_weeks 간격으로 거슬러 올라감)
        target_dates = []
        for p in range(max(periods, 1)):
            offset = min(days_ago + 1 + p * interval_weeks * 5, len(ks11) - 1)
            target_dates.append(ks11.index[-offset])

        cfg = backtester.analyzer.config
        kospi_etf = [(code, code) for code in cfg.get('ETF_EXPERT_TICKERS', cfg.get('KOSPI_ETF_TICKERS', []))]
        us_etf = [(code, code) for code in cfg.get('US_ETF_TICKERS', [])]

        all_results = []
        for target_date in target_dates:
            kospi_uptrend = backtester.analyzer._is_market_in_uptrend(
                ks11, target_idx=len(ks11[ks11.index <= target_date]) - 1
            )
            try:
                sp500 = _fdr_read(
                    'US500',
                    start=(target_date - _dt.timedelta(days=300)).strftime('%Y-%m-%d'),
                    end=target_date.strftime('%Y-%m-%d')
                )
                us_uptrend = backtester.analyzer._is_market_in_uptrend(sp500) if sp500 is not None and not sp500.empty else True
            except Exception:
                us_uptrend = True

            if kospi_etf:
                all_results.extend(backtester._backtest_universe(
                    kospi_etf, target_date, 'KOSPI_ETF', market_uptrend=kospi_uptrend
                ))
            if us_etf:
                all_results.extend(backtester._backtest_universe(
                    us_etf, target_date, 'US_ETF', benchmark_symbol='IXIC', market_uptrend=us_uptrend
                ))

        import pandas as pd
        return pd.DataFrame(all_results) if all_results else pd.DataFrame()

    def _call_agent_backtest(self, api_key, method_name, proposal, before_metrics, after_metrics, etf_mode=False):
        """
        agent_backtest 역할 (Gemini):
        Before/After 백테스트 지표를 비교하여 승인/거부 판정.
        etf_mode=True 시 ETF 기준(MDD<15%, KOSPI ETF WR≥38%, US ETF WR≥35%) 적용.
        반환: {"decision": "approved"|"rejected", "reason": str}
        """
        try:
            model = self._make_gemini_model(api_key)
            if etf_mode:
                domain = "ETF"
                criteria = (
                    "ETF 합격 기준: 승률(KOSPI ETF ≥ 38%, US ETF ≥ 35%), 평균수익 > 0.5%, "
                    "MDD < 15% (ETF 기준 강화), Sharpe > 0.5, 샘플 수 ≥ 10건(ETF 유니버스 특성상 완화). "
                    "Before 대비 After에서 1개 이상 지표 개선 + 나머지 지표 퇴행 없음 시 승인."
                )
            else:
                domain = "KOSPI 주식"
                criteria = (
                    "주식 합격 기준: 승률(KOSPI ≥ 38%), 평균수익 > 0.5%, MDD < 20%, "
                    "Sharpe > 0.5, 샘플 수 ≥ 20건. "
                    "Before 대비 After에서 1개 이상 지표 개선 + 나머지 지표 퇴행 없음 시 승인."
                )
            prompt = (
                "너는 40년 경력의 백테스트 검증전문가(agent_backtest)다.\n"
                f"아래 '{method_name}' 방법론 기반 {domain} 파라미터 변경 제안의 "
                "Before/After 백테스트 결과를 비교하고 "
                "승인(approved) 또는 거부(rejected) 판정을 내려라.\n\n"
                f"[제안 파라미터 변경]\n{json.dumps(proposal.get('param_changes', {}), ensure_ascii=False, indent=2)}\n"
                f"[변경 근거] {proposal.get('reasoning', '')}\n\n"
                f"[Before 지표]\n{json.dumps(before_metrics, ensure_ascii=False, indent=2)}\n\n"
                f"[After 지표]\n{json.dumps(after_metrics, ensure_ascii=False, indent=2)}\n\n"
                f"[판정 기준]\n{criteria}\n\n"
                "반드시 아래 형식으로만 응답하라:\n"
                "```json\n"
                "{\"decision\": \"approved\" 또는 \"rejected\", \"reason\": \"판정 근거 (수치 포함)\"}\n"
                "```"
            )
            text = self._gemini_generate(model, prompt)
            result = self._parse_json_from_text(text)
            if isinstance(result, dict) and result.get('decision') in ('approved', 'rejected'):
                return result
        except Exception as e:
            print(f"  [agent_backtest 오류] {e}")
        return {'decision': 'rejected', 'reason': 'AI 판정 실패 — 안전상 거부'}

    def _log_backlog_update(self, approved_changes, before_metrics, processed_entries):
        """승인된 변경사항을 algorithm_update_log.json에 기록한다."""
        log_file = 'algorithm_update_log.json'
        approved_methods = [
            e['method'].get('방법론명', '')
            for e in processed_entries
            if e.get('validation_result', {}).get('verdict') == 'approved'
        ]
        after_metrics_list = [
            e['validation_result']['after_metrics']
            for e in processed_entries
            if e.get('validation_result', {}).get('verdict') == 'approved'
        ]
        avg_after = {}
        if after_metrics_list:
            for key in ('win_rate', 'avg_return', 'mdd', 'sharpe'):
                vals = [m[key] for m in after_metrics_list if m.get(key) is not None]
                avg_after[key] = round(sum(vals) / len(vals), 4) if vals else None

        log_entry = {
            'title': f"[backlog 검증] {', '.join(approved_methods)} 방법론 파라미터 반영",
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'changes': {
                k: {'before': self.base_config.get(k), 'after': v}
                for k, v in approved_changes.items()
            },
            'before_metrics': before_metrics,
            'after_metrics': avg_after,
            'notes': [f"backlog 방법론 검증: {m}" for m in approved_methods],
        }

        logs = []
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                if not isinstance(logs, list):
                    logs = [logs]
            except Exception:
                logs = []
        logs.append(log_entry)
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)

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
            raw = pd.read_csv(RECOMMENDATIONS_FILE, header=None, names=range(8), dtype=str, encoding='utf-8-sig')
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
    def _is_us_stock(self, code):
        """US 주식 여부 판별 (숫자가 아닌 코드 = US 티커)"""
        return bool(code) and not str(code).isdigit()

    def _load_recommendations_by_tier(self, tier='지금 매수', days_back=30):
        """특정 등급(tier) 추천 종목 로드 공용 메서드"""
        if not os.path.exists(RECOMMENDATIONS_FILE):
            return []
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days_back)
        recs = []
        try:
            raw = pd.read_csv(RECOMMENDATIONS_FILE, header=None, names=range(8), dtype=str, encoding='utf-8-sig')
            if str(raw.iloc[0, 0]).strip().lower() == 'date':
                raw = raw.iloc[1:].reset_index(drop=True)
            for _, row in raw.iterrows():
                try:
                    rec_date = datetime.datetime.strptime(str(row.iloc[0]).strip(), '%Y-%m-%d')
                    if rec_date < cutoff:
                        continue
                    if str(row.iloc[1]).strip() != tier:
                        continue
                    name = str(row.iloc[2]).strip()
                    code = str(row.iloc[3]).strip()
                    stored_win_rate = None
                    try:
                        stored_win_rate = float(str(row.iloc[5]).strip().replace('%', ''))
                    except (ValueError, IndexError):
                        pass
                    buy_price = None
                    if len(row) > 7:
                        try:
                            bp = float(str(row.iloc[7]).strip())
                            if bp > 0:
                                buy_price = bp
                        except (ValueError, TypeError):
                            pass
                    recs.append({
                        'date': rec_date, 'name': name, 'code': code,
                        'stored_win_rate': stored_win_rate, 'buy_price': buy_price,
                    })
                except Exception:
                    continue
        except Exception:
            return []
        return recs

    def _load_tier2_recommendations(self, days_back=30):
        """2등급(관심 종목) 추천 이력 로드"""
        return self._load_recommendations_by_tier(tier='관심 종목', days_back=days_back)

    def fetch_actual_performance(self, recs, trailing_stop_pct, max_hold_override=None, use_us_params=False):
        """
        각 추천 종목을 다음날 시가에 매수, ATR 기반 손절/목표가 + 트레일링 스톱 + 거래비용 반영.
        backtester.py의 _simulate_trade 로직과 동일하게 통일.
        """
        results = []
        if use_us_params:
            tx_buy = self.base_config.get('US_TRANSACTION_COST_BUY_PCT', 0.0001)
            tx_sell = self.base_config.get('US_TRANSACTION_COST_SELL_PCT', 0.0005)
            atr_stop_mult = self.base_config.get('US_ATR_STOP_MULTIPLIER', 2.5)
            atr_target_mult = self.base_config.get('US_ATR_TARGET_MULTIPLIER', 4.0)
            fallback_stop = abs(self.base_config.get('US_VALIDATE_STOP_LOSS_PCT', -0.07))
            fallback_target = self.base_config.get('US_PROFIT_TARGET_PCT', 0.10)
            default_max_hold = self.base_config.get('US_VALIDATE_MAX_HOLD_DAYS', 30)
        else:
            tx_buy = self.base_config.get('TRANSACTION_COST_BUY_PCT', 0.00015)
            tx_sell = self.base_config.get('TRANSACTION_COST_SELL_PCT', 0.005)
            atr_stop_mult = self.base_config.get('ATR_STOP_MULTIPLIER', 2.0)
            atr_target_mult = self.base_config.get('ATR_TARGET_MULTIPLIER', 3.0)
            fallback_stop = abs(self.base_config.get('VALIDATE_STOP_LOSS_PCT', -0.05))
            fallback_target = self.base_config.get('PROFIT_TARGET_PCT', 0.08)
            default_max_hold = self.base_config.get('VALIDATE_MAX_HOLD_DAYS', 20)
        max_hold = max_hold_override if max_hold_override is not None else default_max_hold

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
        (code, buy_date) 쌍으로 정확히 매칭하여 중복/오염 방지
        """
        # 매번 신호 통계를 새로 계산 - 누적 오염 방지 (30일 롤링)
        signal_perf = self.load_signal_performance()
        signal_perf['signals'] = {}  # 신호 통계 초기화 (failure_patterns 등은 유지)

        # CSV에서 추천 종목의 신호 정보 가져오기
        try:
            raw = pd.read_csv(RECOMMENDATIONS_FILE, header=None, names=range(8), dtype=str, encoding='utf-8-sig')
            if str(raw.iloc[0, 0]).strip().lower() == 'date':
                raw = raw.iloc[1:].reset_index(drop=True)
        except Exception:
            return signal_perf

        # (code, buy_date_str) 복합키로 인덱싱 - 같은 종목 여러 날짜 추천 혼선 방지
        result_map = {}
        for r in results:
            key = (r['code'], str(r['buy_date']))
            result_map[key] = r

        for _, row in raw.iterrows():
            try:
                date_str = str(row.iloc[0]).strip()
                tier = str(row.iloc[1]).strip()
                code = str(row.iloc[3]).strip()
                reasons_str = str(row.iloc[4]).strip()

                if tier != '지금 매수':
                    continue

                key = (code, date_str)
                if key not in result_map:
                    continue

                actual = result_map[key]
                # 괄호 안 쉼표를 보호하며 분리: "신호A(설명, 추가), 신호B" → ['신호A(설명, 추가)', '신호B']
                import re as _re
                signals_raw = _re.split(r',\s*(?![^()]*\))', reasons_str)
                signals = [s.strip() for s in signals_raw if s.strip()]

                for signal in signals:
                    if not signal:
                        continue
                    if signal not in signal_perf['signals']:
                        signal_perf['signals'][signal] = {
                            'total_count': 0, 'win_count': 0,
                            'total_return': 0.0, 'avg_return': 0.0, 'win_rate': 0.0
                        }
                    perf = signal_perf['signals'][signal]
                    perf['total_count'] += 1
                    perf['total_return'] += actual['return_pct']
                    if actual['return_pct'] > 0:
                        perf['win_count'] += 1
                    perf['avg_return'] = perf['total_return'] / perf['total_count']
                    perf['win_rate'] = (perf['win_count'] / perf['total_count'] * 100)
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
    def optimize_additional_parameters(self, recs, results, optimize_started):
        """
        TIER2_WIN_RATE, VALIDATE_MAX_HOLD_DAYS, TREND_TEMPLATE_PEAK_FACTOR 실제 최적화
        """
        print("\n[추가 파라미터 최적화]")

        best_params = {
            'TIER2_WIN_RATE': self.base_config.get('TIER2_WIN_RATE', 50),
            'VALIDATE_MAX_HOLD_DAYS': self.base_config.get('VALIDATE_MAX_HOLD_DAYS', 20),
            'TREND_TEMPLATE_PEAK_FACTOR': self.base_config.get('TREND_TEMPLATE_PEAK_FACTOR', 0.85)
        }

        current_stop = self.base_config.get('TRAILING_STOP_PCT', 0.035)
        returns = [r['return_pct'] for r in results] if results else []
        win_rate_actual = (len([r for r in returns if r > 0]) / len(returns) * 100) if returns else 0

        # ── A. VALIDATE_MAX_HOLD_DAYS 실제 최적화 ──────────────────────
        if len(recs) >= 5 and time.time() - optimize_started < self.time_limit_seconds:
            print("  [보유 기간 최적화]")
            current_hold = self.base_config.get('VALIDATE_MAX_HOLD_DAYS', 20)
            best_hold = current_hold
            best_hold_score = -9999
            for hold_days in [10, 15, 20, 25, 30]:
                if time.time() - optimize_started >= self.time_limit_seconds:
                    break
                test_res = self.fetch_actual_performance(recs, current_stop, max_hold_override=hold_days)
                if not test_res:
                    continue
                t_rets = [r['return_pct'] for r in test_res]
                t_avg = sum(t_rets) / len(t_rets)
                t_wr = len([r for r in t_rets if r > 0]) / len(t_rets) * 100
                t_score = t_avg + max(t_wr - 45, 0) * 0.4
                marker = ' <-- 현재' if hold_days == current_hold else ''
                print(f"    {hold_days}일: 평균 {t_avg:+.2f}%, 승률 {t_wr:.1f}%, 점수 {t_score:.2f}{marker}")
                if t_score > best_hold_score:
                    best_hold_score = t_score
                    best_hold = hold_days
            if best_hold != current_hold:
                print(f"    ✓ VALIDATE_MAX_HOLD_DAYS: {current_hold}일 → {best_hold}일")
                best_params['VALIDATE_MAX_HOLD_DAYS'] = best_hold
            else:
                print(f"    → 현재 {current_hold}일 유지")

        # ── B. TIER2_WIN_RATE 실제 최적화 (Tier2 추천 종목 활용) ────────
        if len(recs) >= 10 and time.time() - optimize_started < self.time_limit_seconds:
            print("  [TIER2 승률 임계값 최적화]")
            tier2_recs = self._load_tier2_recommendations(days_back=30)
            if len(tier2_recs) >= 5:
                tier2_results = self.fetch_actual_performance(tier2_recs, current_stop)
                recs_with_perf2 = [r for r in tier2_results if r.get('stored_win_rate') is not None]
                if len(recs_with_perf2) >= 3:
                    current_tier2 = self.base_config.get('TIER2_WIN_RATE', 50)
                    best_tier2 = current_tier2
                    best_tier2_score = -9999
                    for threshold in [35, 40, 45, 50, 55, 60]:
                        if time.time() - optimize_started >= self.time_limit_seconds:
                            break
                        selected = [r for r in recs_with_perf2 if r['stored_win_rate'] >= threshold]
                        if len(selected) < 2:
                            continue
                        sel_rets = [r['return_pct'] for r in selected]
                        sel_avg = sum(sel_rets) / len(sel_rets)
                        sel_wr = len([r for r in sel_rets if r > 0]) / len(sel_rets) * 100
                        sel_score = sel_avg + max(sel_wr - 45, 0) * 0.4
                        marker = ' <-- 현재' if threshold == current_tier2 else ''
                        print(f"    >= {threshold}%: {len(selected)}개, 평균 {sel_avg:+.2f}%, 승률 {sel_wr:.1f}%, 점수 {sel_score:.2f}{marker}")
                        if sel_score > best_tier2_score:
                            best_tier2_score = sel_score
                            best_tier2 = threshold
                    if best_tier2 != current_tier2:
                        print(f"    ✓ TIER2_WIN_RATE: {current_tier2}% → {best_tier2}%")
                        best_params['TIER2_WIN_RATE'] = best_tier2
                    else:
                        print(f"    → 현재 {current_tier2}% 유지")
                else:
                    print(f"    Tier2 승률 데이터 부족 ({len(recs_with_perf2)}개 < 3), 생략")
            else:
                print(f"    Tier2 추천 종목 부족 ({len(tier2_recs)}개 < 5), 생략")

        # ── C. TREND_TEMPLATE_PEAK_FACTOR 방향 기반 휴리스틱 조정 ───────
        print("  [추세 템플릿 피크 팩터 조정]")
        current_peak = self.base_config.get('TREND_TEMPLATE_PEAK_FACTOR', 0.85)
        if win_rate_actual >= 65:
            new_peak = min(round(current_peak + 0.02, 3), 0.95)
            print(f"    승률 {win_rate_actual:.1f}% 높음 → 상향 조정: {current_peak} → {new_peak}")
            best_params['TREND_TEMPLATE_PEAK_FACTOR'] = new_peak
        elif win_rate_actual < 50 and len(returns) >= 5:
            new_peak = max(round(current_peak - 0.02, 3), 0.70)
            print(f"    승률 {win_rate_actual:.1f}% 낮음 → 하향 조정: {current_peak} → {new_peak}")
            best_params['TREND_TEMPLATE_PEAK_FACTOR'] = new_peak
        else:
            print(f"    승률 {win_rate_actual:.1f}% 정상 → 현재값 유지 ({current_peak})")

        return best_params

    # ------------------------------------------------------------------
    # 6-B. US 주식 전용 파라미터 최적화
    # ------------------------------------------------------------------
    def optimize_us_parameters(self, optimize_started):
        """미국 주식 추천 종목 실적 기반 US 전용 파라미터 최적화"""
        print("\n[미국 주식 파라미터 최적화]")

        all_recs = self.load_tier1_recommendations(days_back=30)
        us_recs = [r for r in all_recs if self._is_us_stock(r['code'])]

        if len(us_recs) < 3:
            print(f"  US 추천 종목 부족 ({len(us_recs)}개 < 3), 생략")
            return {}

        print(f"  {len(us_recs)}개 US 종목 발견")
        current_us_stop = self.base_config.get('US_TRAILING_STOP_PCT', 0.05)

        # 현재 US 파라미터 기준 성과
        us_current = self.fetch_actual_performance(us_recs, current_us_stop, use_us_params=True)
        if not us_current:
            print("  US 성과 데이터 없음")
            return {}

        us_rets = [r['return_pct'] for r in us_current]
        us_avg = sum(us_rets) / len(us_rets)
        us_wr = len([r for r in us_rets if r > 0]) / len(us_rets) * 100
        best_us_score = us_avg + max(us_wr - 45, 0) * 0.4
        best_us_stop = current_us_stop
        print(f"  현재 US_TRAILING_STOP {current_us_stop*100:.1f}%: 평균 {us_avg:+.2f}%, 승률 {us_wr:.1f}%, 점수 {best_us_score:.2f}")

        for stop_pct in [0.035, 0.04, 0.05, 0.06, 0.07, 0.08]:
            if abs(stop_pct - current_us_stop) < 0.001:
                continue
            if time.time() - optimize_started >= self.time_limit_seconds:
                print("  시간 제한 도달, US 탐색 중단")
                break
            test_res = self.fetch_actual_performance(us_recs, stop_pct, use_us_params=True)
            if not test_res:
                continue
            t_rets = [r['return_pct'] for r in test_res]
            t_avg = sum(t_rets) / len(t_rets)
            t_wr = len([r for r in t_rets if r > 0]) / len(t_rets) * 100
            t_score = t_avg + max(t_wr - 45, 0) * 0.4
            print(f"  US_TRAILING_STOP {stop_pct*100:.1f}%: 평균 {t_avg:+.2f}%, 승률 {t_wr:.1f}%, 점수 {t_score:.2f}")
            if t_score > best_us_score:
                best_us_score = t_score
                best_us_stop = stop_pct

        result_params = {}
        if best_us_stop != current_us_stop:
            print(f"  ✓ 최적 US_TRAILING_STOP_PCT: {current_us_stop*100:.1f}% → {best_us_stop*100:.1f}%")
            result_params['US_TRAILING_STOP_PCT'] = best_us_stop
        else:
            print(f"  → 현재 US_TRAILING_STOP_PCT({current_us_stop*100:.1f}%) 유지")

        # US TIER1_WIN_RATE 최적화
        recs_with_perf_us = [r for r in us_current if r.get('stored_win_rate') is not None]
        if len(recs_with_perf_us) >= 3:
            current_us_tier1 = self.base_config.get('US_TIER1_WIN_RATE', 50)
            best_us_tier1 = current_us_tier1
            best_us_tier1_score = -9999
            print(f"  [US TIER1_WIN_RATE 최적화]")
            for threshold in [35, 40, 45, 50, 55, 60]:
                if time.time() - optimize_started >= self.time_limit_seconds:
                    break
                selected = [r for r in recs_with_perf_us if r['stored_win_rate'] >= threshold]
                if len(selected) < 2:
                    continue
                sel_rets = [r['return_pct'] for r in selected]
                sel_avg = sum(sel_rets) / len(sel_rets)
                sel_wr = len([r for r in sel_rets if r > 0]) / len(sel_rets) * 100
                sel_score = sel_avg + max(sel_wr - 45, 0) * 0.4
                marker = ' <-- 현재' if threshold == current_us_tier1 else ''
                print(f"    >= {threshold}%: {len(selected)}개, 평균 {sel_avg:+.2f}%, 승률 {sel_wr:.1f}%, 점수 {sel_score:.2f}{marker}")
                if sel_score > best_us_tier1_score:
                    best_us_tier1_score = sel_score
                    best_us_tier1 = threshold
            if best_us_tier1 != current_us_tier1:
                print(f"    ✓ US_TIER1_WIN_RATE: {current_us_tier1}% → {best_us_tier1}%")
                result_params['US_TIER1_WIN_RATE'] = best_us_tier1
            else:
                print(f"    → 현재 US_TIER1_WIN_RATE({current_us_tier1}%) 유지")

        return result_params

    # ------------------------------------------------------------------
    # 7. 점진적 학습 (Gradual Learning)
    # ------------------------------------------------------------------
    def apply_gradual_learning(self, old_config, new_config, learning_rate=0.3):
        """
        급격한 파라미터 변경을 방지하기 위해 점진적으로 업데이트
        learning_rate: 0.3 = 새 값의 30%만 반영, 70%는 기존값 유지
        """
        gradual_config = copy.deepcopy(old_config)
        
        numeric_params = [
            'TRAILING_STOP_PCT', 'TREND_TEMPLATE_PEAK_FACTOR',
            'US_TRAILING_STOP_PCT',
        ]

        for param in numeric_params:
            if param in new_config and param in old_config:
                old_val = old_config[param]
                new_val = new_config[param]

                # 점진적 업데이트: 새값의 learning_rate만 반영
                gradual_val = old_val * (1 - learning_rate) + new_val * learning_rate
                gradual_config[param] = round(gradual_val, 4)

        # 정수형 파라미터는 반올림
        int_params = [
            'TIER1_WIN_RATE', 'TIER2_WIN_RATE', 'VALIDATE_MAX_HOLD_DAYS',
            'US_TIER1_WIN_RATE', 'US_TIER2_WIN_RATE', 'US_VALIDATE_MAX_HOLD_DAYS',
        ]
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
    # 8. Expert A/B 자동 개선 사이클
    # ------------------------------------------------------------------

    ANALYZER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analyzer.py')
    ANALYZER_BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analyzer.py.bak')

    def _read_analyzer(self):
        with open(self.ANALYZER_FILE, 'r', encoding='utf-8') as f:
            return f.read()

    def _write_analyzer(self, code):
        with open(self.ANALYZER_FILE, 'w', encoding='utf-8') as f:
            f.write(code)

    def _backup_analyzer(self):
        shutil.copy(self.ANALYZER_FILE, self.ANALYZER_BACKUP)

    def _restore_analyzer(self):
        if os.path.exists(self.ANALYZER_BACKUP):
            shutil.copy(self.ANALYZER_BACKUP, self.ANALYZER_FILE)
            print("  [rollback] analyzer.py 원복 완료")

    # --- 패치 정의 (사전 검증된 안전한 코드 변경) ---

    def _patch_volume_spike_bullish(self, code):
        """거래량 급증 신호에 양봉 확인 조건 추가 (패닉 매도 거래량 제외)"""
        old = """    def detect_volume_spike(self, df, idx=-1):
        \"\"\"거래량 급증 감지 (평균 대비 2.5배 이상)\"\"\"
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        if last['Volume'] > last['VOL_AVG'] * 2.5:
            return True
        return False"""
        new = """    def detect_volume_spike(self, df, idx=-1):
        \"\"\"거래량 급증 감지 (평균 대비 2.5배 이상 + 양봉 확인)
        
        양봉 확인 조건 추가: 패닉 매도 거래량(음봉) 제외, 매수세 우위 확인
        \"\"\"
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        if last['Volume'] > last['VOL_AVG'] * 2.5:
            # 양봉 확인 (Close > Open) - 매수세가 매도세보다 강한 경우만
            if 'Open' in df_target.columns and last['Open'] == last['Open'] and float(last['Open']) > 0:
                return float(last['Close']) > float(last['Open'])
            return True
        return False"""
        if old in code:
            return code.replace(old, new), True
        return code, False

    def _patch_taj_mahal_rsi_35(self, code):
        """BB 하단 반등 RSI 과매도 기준 강화 (40→35)"""
        old = "        rsi_was_oversold = any(r <= 40 for r in rsi_recent if r == r)"
        new = "        rsi_was_oversold = any(r <= 35 for r in rsi_recent if r == r)"
        if old in code:
            return code.replace(old, new), True
        return code, False

    def _patch_stoch_mfi_volume(self, code):
        """과매도 반등 신호에 거래량 확인 추가 (VOL_AVG 1.2배)"""
        old = """        # StochRSI K가 D를 골든크로스하고 20 이하(과매도)에서 반등할 때
        if prev['STOCH_K'] < prev['STOCH_D'] and last['STOCH_K'] > last['STOCH_D']:
            if last['STOCH_K'] < 30 or last['MFI'] < 30:
                return True
        return False"""
        new = """        # StochRSI K가 D를 골든크로스하고 20 이하(과매도)에서 반등할 때
        if prev['STOCH_K'] < prev['STOCH_D'] and last['STOCH_K'] > last['STOCH_D']:
            if last['STOCH_K'] < 30 or last['MFI'] < 30:
                # 거래량 확인 (가짜 반등 필터)
                if 'VOL_AVG' in df_target.columns and last['VOL_AVG'] == last['VOL_AVG']:
                    return float(last['Volume']) >= float(last['VOL_AVG']) * 1.2
                return True
        return False"""
        if old in code:
            return code.replace(old, new), True
        return code, False

    # --- 빠른 백테스트 ---

    def run_quick_backtest_stats(self, sample_size=50, periods=4):
        """경량 백테스트 (소규모 샘플로 빠른 전/후 비교용)"""
        from backtester import Backtester
        try:
            bt = Backtester()
            bt.analyzer.config['BACKTEST_SAMPLE_SIZE'] = sample_size
            df = bt.run_walkforward_backtest(periods=periods, interval_weeks=6)
            if df is None or df.empty:
                return None
            total = len(df)
            if total == 0:
                return None
            wins = int((df['Return(%)'] > 0).sum())
            win_rate = wins / total * 100
            avg_ret = float(df['Return(%)'].mean())
            std_ret = float(df['Return(%)'].std()) if total > 1 else 0.0
            annual_factor = (250 / 20) ** 0.5
            risk_free = 3.5 / (250 / 20)
            sharpe = ((avg_ret - risk_free) / std_ret * annual_factor) if std_ret > 0 else 0.0
            equity = 1.0
            peak_eq = 1.0
            mdd = 0.0
            for r in df['Return(%)'].tolist():
                equity *= (1 + r / 100)
                if equity > peak_eq:
                    peak_eq = equity
                dd = (peak_eq - equity) / peak_eq * 100
                if dd > mdd:
                    mdd = dd
            return {
                'total': total, 'wins': wins, 'win_rate': win_rate,
                'avg_ret': avg_ret, 'sharpe': sharpe, 'mdd': mdd,
            }
        except Exception as e:
            print(f"  [Expert B] 백테스트 오류: {e}")
            return None

    @staticmethod
    def _score_backtest(stats):
        """통합 점수: 승률 40% + 평균수익률 × 10 - MDD 패널티"""
        if not stats:
            return -9999.0
        return stats['win_rate'] * 0.4 + stats['avg_ret'] * 10 - stats['mdd'] * 0.1

    def _log_expert_ab_result(self, patches_applied, before, after, kept):
        """Expert A/B 결과를 algorithm_update_log.json에 기록"""
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'algorithm_update_log.json')
        entry = {
            'timestamp': datetime.datetime.now().isoformat(),
            'type': 'ExpertAB_자동개선',
            'patches_applied': patches_applied,
            'kept': kept,
            'before': {k: round(v, 4) if isinstance(v, float) else v for k, v in before.items()},
            'after': {k: round(v, 4) if isinstance(v, float) else v for k, v in after.items()},
        }
        existing = []
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = [existing]
            except Exception:
                existing = []
        existing.append(entry)
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    # --- AI 헬퍼 ---

    def _call_ai_fresh(self, prompt):
        """Gemini AI에 독립 세션으로 단일 호출 (대화 컨텍스트 오염 방지)"""
        if not self.analyzer.ai_enabled:
            return None
        genai_lib = self.analyzer.genai_library
        model_name = self.analyzer.model_name
        api_key = self.analyzer.gemini_api_key
        wait_times = [30, 60]
        for attempt in range(3):
            try:
                if genai_lib == 'genai':
                    import google.genai as _genai
                    client = _genai.Client(api_key=api_key)
                    fresh = client.chats.create(model=model_name)
                    response = fresh.send_message(prompt)
                elif genai_lib == 'generativeai':
                    import google.generativeai as _genai
                    _genai.configure(api_key=api_key)
                    model = _genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                else:
                    return None
                return self.analyzer._normalize_ai_response(response)
            except Exception as e:
                if '429' in str(e) and attempt < 2:
                    time.sleep(wait_times[attempt])
                    continue
                print(f"  [AI] 호출 오류: {e}")
                return None
        return None

    def _extract_signal_functions(self):
        """analyzer.py에서 신호 감지 함수 코드 추출"""
        import ast as _ast
        code = self._read_analyzer()
        lines = code.split('\n')
        target_funcs = {
            'detect_volume_spike', 'is_taj_mahal_signal', 'detect_stoch_mfi_rebound',
            'detect_divergence', 'detect_bb_squeeze', 'detect_macd_golden_cross',
            'calculate_entry_price', 'calculate_holding_targets',
        }
        result = {}
        try:
            tree = _ast.parse(code)
            for node in _ast.walk(tree):
                if isinstance(node, _ast.FunctionDef) and node.name in target_funcs:
                    result[node.name] = '\n'.join(lines[node.lineno - 1:node.end_lineno])
        except Exception:
            pass
        return result

    def _parse_expert_a_patches(self, text):
        """Expert A JSON 응답에서 패치 목록 파싱 및 안전성 검증"""
        import re, ast as _ast
        if not text:
            return []
        match = re.search(r'\{[\s\S]*\}', text)
        if not match:
            return []
        try:
            data = json.loads(match.group())
        except Exception:
            # JSON 파싱 실패 시 코드블록 내 JSON 재탐색
            try:
                code_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
                if not code_match:
                    return []
                data = json.loads(code_match.group(1))
            except Exception:
                return []

        allowed = {
            'detect_volume_spike', 'is_taj_mahal_signal', 'detect_stoch_mfi_rebound',
            'detect_divergence', 'detect_bb_squeeze', 'detect_macd_golden_cross',
            'calculate_entry_price', 'calculate_holding_targets',
        }
        valid = []
        current_code = self._read_analyzer()
        for p in data.get('patches', []):
            func = p.get('function', '')
            old = p.get('old_code', '')
            new = p.get('new_code', '')
            reason = p.get('reason', '')
            if func not in allowed:
                print(f"  [Expert A] 허용되지 않는 함수 '{func}' 스킵")
                continue
            if not old or not new or old == new:
                continue
            if old not in current_code:
                print(f"  [Expert A] '{func}' old_code 불일치 — 스킵")
                continue
            # 문법 검증
            test_code = current_code.replace(old, new, 1)
            try:
                _ast.parse(test_code)
            except SyntaxError as e:
                print(f"  [Expert A] '{func}' 문법 오류 ({e}) — 스킵")
                continue
            valid.append({'function': func, 'reason': reason, 'old_code': old, 'new_code': new})
        return valid

    def _apply_ai_patches(self, patches):
        """AI 패치를 analyzer.py에 적용, 적용된 patch 목록 반환"""
        code = self._read_analyzer()
        applied = []
        for p in patches:
            if p['old_code'] not in code:
                continue
            code = code.replace(p['old_code'], p['new_code'], 1)
            applied.append(p)
            print(f"  ✎ 적용: {p['function']} — {p['reason']}")
        if applied:
            self._write_analyzer(code)
        return applied

    def expert_ab_cycle(self, signal_perf, optimize_started):
        """
        Expert A (Gemini 투자분석전문가) → Expert B (백테스트 검증전문가) 자동 사이클

        agent/agent_stock.md, agent/agent_backtest.md 기반:
        - Expert A: Gemini AI가 신호 성과 데이터와 현재 코드를 분석하여 개선안 제안
        - Expert B: 경량 백테스트로 Before/After 성과를 객관적으로 비교 검증
        - 성과 향상 시 채택, 미향상 시 자동 rollback
        """
        sample_size = self.base_config.get('EXPERT_AB_SAMPLE_SIZE', 200)
        periods = self.base_config.get('EXPERT_AB_PERIODS', 8)
        # Expert A/B는 파라미터 최적화 종료 후 독립 실행 — time_limit_seconds 체크 불필요
        # (GitHub Actions timeout-minutes: 360 이 보호막 역할)

        print("\n" + "=" * 72)
        print("  [Expert A] 40년 경력 투자분석전문가 — 알고리즘 검토 시작")
        print("=" * 72)

        signals = signal_perf.get('signals', {})
        weak_threshold = self.base_config.get('WEAK_SIGNAL_WIN_RATE_THRESHOLD', 45)

        if not signals:
            print("[Expert A] 신호 성과 데이터 없음 — 사이클 생략")
            return

        # 전체 신호 성과 요약 (약세·강세 모두 Expert A에게 제공)
        sig_summary = "\n".join(
            f"  - {k}: 승률 {v['win_rate']:.1f}%, 평균 {v.get('avg_return', 0):+.2f}%, {v['total_count']}건"
            for k, v in sorted(signals.items(), key=lambda x: x[1]['win_rate'])
        )
        print(f"[Expert A] 신호 성과 현황:\n{sig_summary}")

        # ── Expert A: Gemini AI로 코드 개선안 도출 ──────────────────────
        proposed_patches = []
        expert_a_analysis = ""
        ai_used = self.analyzer.ai_enabled

        if ai_used:
            func_codes = self._extract_signal_functions()
            func_text = "\n\n".join(
                f"### {name}\n```python\n{code}\n```"
                for name, code in func_codes.items()
            )

            prompt_a = f"""당신은 40년 경력의 최고 주식투자 전문가입니다. 누적 수익 1000억원 이상을 달성했으며, 차트 중심의 기술적 분석이 특기입니다.

아래는 현재 코스피 자동매매 시스템의 매수 신호별 실제 성과(최근 30일 실제 추천 기준)입니다:

[신호별 성과]
{sig_summary}

[현재 신호 감지 함수들]
{func_text}

[임무]
위 성과 데이터를 전문가 관점에서 분석하고, 승률이 낮거나 수익률이 마이너스인 신호를 개선하는 최소한의 코드 수정안을 제안하세요.

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "analysis": "전문가 분석 내용 (한국어, 2-3문장)",
  "patches": [
    {{
      "function": "수정할 함수명",
      "reason": "수정 이유 (한국어, 1문장)",
      "old_code": "교체할 기존 코드 블록 (위 함수 코드에서 찾을 수 있는 정확한 문자열, 들여쓰기 포함)",
      "new_code": "새 코드 블록 (들여쓰기 포함)"
    }}
  ]
}}

[제약 조건]
- 수정 가능 함수: detect_volume_spike, is_taj_mahal_signal, detect_stoch_mfi_rebound, detect_divergence, detect_bb_squeeze, detect_macd_golden_cross
- 변경은 최소화 (조건 1-2개 추가/강화 수준)
- 기존 함수 시그니처와 반환값 타입(bool) 유지
- old_code는 반드시 위 함수 코드에서 그대로 찾을 수 있는 문자열
- 성과가 좋은 신호(승률 60% 이상)는 수정하지 말 것"""

            print("\n[Expert A] Gemini AI에 코드 개선 요청 중...")
            ai_text = self._call_ai_fresh(prompt_a)

            if ai_text:
                # 분석 내용 출력
                import re
                m = re.search(r'"analysis"\s*:\s*"([^"]+)"', ai_text)
                if m:
                    expert_a_analysis = m.group(1)
                    print(f"  Expert A 분석: {expert_a_analysis}")

                proposed_patches = self._parse_expert_a_patches(ai_text)
                if proposed_patches:
                    print(f"  Expert A 제안 패치 {len(proposed_patches)}건 검증 통과:")
                    for p in proposed_patches:
                        print(f"    ✎ {p['function']}: {p['reason']}")
                else:
                    print("  Expert A AI 패치 파싱 실패 → 규칙 기반으로 전환")
                    ai_used = False
            else:
                print("  Expert A AI 호출 실패 → 규칙 기반으로 전환")
                ai_used = False

        # AI 패치 없을 경우: 규칙 기반 패치 (fallback)
        if not proposed_patches:
            print("[Expert A] 규칙 기반 패치 적용 시도...")
            code = self._read_analyzer()
            weak_signals = {
                k: v for k, v in signals.items()
                if v.get('total_count', 0) >= 3 and v.get('win_rate', 100) < weak_threshold
            }
            rule_patches = []
            if '거래량 급증' in weak_signals:
                code2, ok = self._patch_volume_spike_bullish(code)
                if ok:
                    rule_patches.append({'function': 'detect_volume_spike',
                                         'reason': '규칙기반: 양봉 확인 조건 추가 (패닉 매도 제외)',
                                         'old_code': '', 'new_code': '', '_code': code2})
            if '바닥권 반등 신호(BB 하단)' in weak_signals:
                base = rule_patches[-1]['_code'] if rule_patches else code
                code2, ok = self._patch_taj_mahal_rsi_35(base)
                if ok:
                    rule_patches.append({'function': 'is_taj_mahal_signal',
                                         'reason': '규칙기반: RSI 과매도 기준 40 → 35 강화',
                                         'old_code': '', 'new_code': '', '_code': code2})
            if '과매도 반등 신호' in weak_signals:
                base = rule_patches[-1]['_code'] if rule_patches else code
                code2, ok = self._patch_stoch_mfi_volume(base)
                if ok:
                    rule_patches.append({'function': 'detect_stoch_mfi_rebound',
                                         'reason': '규칙기반: 거래량 1.2배 확인 조건 추가',
                                         'old_code': '', 'new_code': '', '_code': code2})

            if not rule_patches:
                print("[Expert A] 적용 가능한 패치 없음 — 사이클 종료")
                return

            proposed_patches = rule_patches
            print(f"  규칙 기반 패치 {len(proposed_patches)}건 준비 완료")

        # ── Expert B: Before 백테스트 ────────────────────────────────────
        # 항상 최신 analyzer.py를 로드하도록 캐시 초기화
        import sys
        for _mod in ['analyzer', 'backtester']:
            if _mod in sys.modules:
                del sys.modules[_mod]
        print(f"\n[Expert B] 40년 경력 백테스트 검증전문가 — Before 백테스트 시작")
        print(f"  (KOSPI {sample_size}종목 × {periods}구간, 현재 analyzer.py 기준)")
        before_stats = self.run_quick_backtest_stats(sample_size=sample_size, periods=periods)
        if not before_stats:
            print("[Expert B] Before 백테스트 실패 — 사이클 중단")
            return
        print(
            f"  Before: 총 {before_stats['total']}건 | 승률 {before_stats['win_rate']:.1f}% "
            f"| 평균 {before_stats['avg_ret']:+.2f}% | Sharpe {before_stats['sharpe']:.2f} "
            f"| MDD -{before_stats['mdd']:.1f}%"
        )

        # ── Expert A 패치 적용 ───────────────────────────────────────────
        self._backup_analyzer()

        if ai_used:
            # AI 패치: _apply_ai_patches 사용
            applied_patches = self._apply_ai_patches(proposed_patches)
        else:
            # 규칙 기반: 최종 code를 직접 기록
            final_code = proposed_patches[-1].get('_code', '')
            if final_code:
                self._write_analyzer(final_code)
                applied_patches = proposed_patches
            else:
                applied_patches = []

        if not applied_patches:
            print("[Expert A] 패치 적용 실패 — 사이클 중단")
            self._restore_analyzer()
            return

        patch_desc = [f"{p['function']}: {p['reason']}" for p in applied_patches]
        print(f"\n[Expert A] 총 {len(applied_patches)}건 패치 적용 완료")

        # ── Expert B: After 백테스트 ─────────────────────────────────────
        # 패치된 analyzer.py를 반영하려면 Python 모듈 캐시를 초기화해야 함
        import sys
        for _mod in ['analyzer', 'backtester']:
            if _mod in sys.modules:
                del sys.modules[_mod]
        print(f"\n[Expert B] After 백테스트 실행 중 (패치 적용 후)...")
        after_stats = self.run_quick_backtest_stats(sample_size=sample_size, periods=periods)
        if not after_stats:
            print("[Expert B] After 백테스트 실패 — rollback")
            self._restore_analyzer()
            return
        print(
            f"  After:  총 {after_stats['total']}건 | 승률 {after_stats['win_rate']:.1f}% "
            f"| 평균 {after_stats['avg_ret']:+.2f}% | Sharpe {after_stats['sharpe']:.2f} "
            f"| MDD -{after_stats['mdd']:.1f}%"
        )

        # ── Expert B: 정량 비교 → 채택/롤백 결정 ───────────────────────
        before_score = self._score_backtest(before_stats)
        after_score = self._score_backtest(after_stats)
        print(f"\n[Expert B] 종합 점수: Before {before_score:.2f}  →  After {after_score:.2f}")

        kept = after_score > before_score
        if kept:
            print("  ✅ 성과 향상 확인 — Expert A 개선안 채택")
        else:
            print("  ❌ 성과 미향상 또는 하락 — Expert A 개선안 롤백")
            self._restore_analyzer()

        # Expert B AI 총평 (로그용, 결정에는 영향 없음)
        if self.analyzer.ai_enabled:
            prompt_b = f"""당신은 40년 경력의 주식 백테스트 전문가입니다.

[Expert A 개선 내용]
{chr(10).join(patch_desc)}

[Expert A 분석]
{expert_a_analysis}

[Before 백테스트 결과]
- 총 거래수: {before_stats['total']}건
- 승률: {before_stats['win_rate']:.1f}%
- 평균 수익률: {before_stats['avg_ret']:+.2f}%
- Sharpe: {before_stats['sharpe']:.2f}
- MDD: -{before_stats['mdd']:.1f}%

[After 백테스트 결과]
- 총 거래수: {after_stats['total']}건
- 승률: {after_stats['win_rate']:.1f}%
- 평균 수익률: {after_stats['avg_ret']:+.2f}%
- Sharpe: {after_stats['sharpe']:.2f}
- MDD: -{after_stats['mdd']:.1f}%

[최종 결정]: {"채택" if kept else "롤백"}

위 결과에 대한 전문가 총평을 2-3문장으로 간략히 작성해주세요."""
            review = self._call_ai_fresh(prompt_b)
            if review:
                print(f"\n  [Expert B 총평] {review.strip()[:300]}")

        self._log_expert_ab_result(patch_desc, before_stats, after_stats, kept=kept)
        print("=" * 72)

    # ------------------------------------------------------------------
    # 9. Auto Evolution — agent_auto 기반 전문가 협업 3사이클 루프
    # ------------------------------------------------------------------

    def _prompt_agent_search(self, sig_summary, func_text):
        """agent_search: 현재 시스템에 없는 신규 투자 방법론 탐색 요청"""
        return f"""당신은 40년 주식·ETF 시장 흐름 분석 전문가입니다. 검증된 외부 방법론을 발굴·도입하는 것이 특기입니다.

[현재 시스템 신호별 성과]
{sig_summary}

[현재 구현된 신호 함수 목록]
{', '.join(func_text.keys())}

[임무]
현재 시스템에 없는 새로운 매수 신호 또는 필터링 로직을 1~2개 제안하세요.
제안은 아래 카테고리 중 하나여야 합니다:
- 모멘텀 전략 (듀얼 모멘텀, RS 등)
- 변동성 기반 (ATR 포지션 사이징 등)
- 거래량 분석 (OBV, VWAP 등)
- 계절성·패턴

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "new_methods": [
    {{
      "name": "신호명",
      "category": "카테고리",
      "description": "방법론 설명 (2문장)",
      "implementation_hint": "현재 analyzer.py 신호 함수에 추가 가능한 구체적 조건 (1문장)"
    }}
  ]
}}"""

    def _prompt_agent_stock(self, sig_summary, func_text, search_proposals, feedback, cycle):
        """agent_stock: 주식 알고리즘 분석 및 개선 제안 (사이클별 피드백 반영)"""
        feedback_section = ""
        if feedback:
            feedback_section = f"""
[이전 사이클({cycle-1}) agent_backtest 피드백]
{feedback}

위 피드백을 반드시 반영하여 수정된 제안을 작성하세요.
"""
        search_section = ""
        if search_proposals:
            search_section = f"""
[agent_search 신규 방법론 제안]
{search_proposals}

위 신규 방법론 중 현실적으로 적용 가능한 것이 있으면 반영하세요.
"""
        return f"""당신은 40년 경력 최고 주식투자 전문가입니다. 누적 수익 1000억원 이상을 달성했으며, 차트 기반 기술적 분석이 특기입니다.

[현재 시스템 신호별 성과 — 사이클 {cycle}]
{sig_summary}

[현재 신호 감지 함수들]
{chr(10).join(f"### {name}" + chr(10) + "```python" + chr(10) + code + chr(10) + "```" for name, code in func_text.items())}
{search_section}{feedback_section}
[임무]
위 성과 데이터를 분석하여 승률이 낮거나 수익률이 마이너스인 신호를 개선하는 최소한의 코드 수정안을 제안하세요.
이전 사이클의 거부 피드백이 있다면 반드시 반영하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "analysis": "전문가 분석 (한국어, 2-3문장)",
  "cycle": {cycle},
  "patches": [
    {{
      "function": "수정할 함수명",
      "reason": "수정 이유 (한국어, 1문장)",
      "old_code": "교체할 기존 코드 블록 (들여쓰기 포함, 정확한 문자열)",
      "new_code": "새 코드 블록 (들여쓰기 포함)"
    }}
  ]
}}

[제약 조건]
- 수정 가능 함수: detect_volume_spike, is_taj_mahal_signal, detect_stoch_mfi_rebound, detect_divergence, detect_bb_squeeze, detect_macd_golden_cross, calculate_entry_price, calculate_holding_targets
- calculate_entry_price 수정 시: 진입가 산출 로직(entry 계산, basis 문자열, stop_loss/target 계산)만 수정 가능. 반환값 키(entry, basis, stop_loss, target, target_basis) 유지 필수
- calculate_holding_targets 수정 시: 보유종목 손절가(stop_loss, stop_basis)·목표가(target, target_basis) 계산 로직만 수정 가능. 반환값 키(stop_loss, stop_basis, target, target_basis) 유지 필수
- 변경은 최소화 (조건 1-2개 추가/강화 수준), 기존 반환값 타입(bool 또는 dict) 유지
- 성과가 좋은 신호(승률 60% 이상)는 수정하지 말 것
- old_code는 반드시 위 함수 코드에서 그대로 찾을 수 있는 문자열"""

    def _prompt_agent_etf(self, sig_summary, search_proposals, feedback, cycle):
        """agent_etf: ETF 전략 분석 및 strategy_config 파라미터 개선 제안"""
        feedback_section = f"\n[이전 사이클({cycle-1}) 피드백]\n{feedback}\n위 피드백을 반영하세요." if feedback else ""
        search_section = f"\n[agent_search 신규 방법론]\n{search_proposals}\n적용 가능한 것이 있으면 반영하세요." if search_proposals else ""
        return f"""당신은 40년 한국·미국 ETF 시장 전문가입니다. 차트 분석 기반 ETF 종목 선정과 포트폴리오 최적화가 특기입니다.

[현재 시스템 신호별 성과 — 사이클 {cycle}]
{sig_summary}
{search_section}{feedback_section}
[임무]
ETF 투자 관점에서 아래 두 가지를 제안하세요.

1. strategy_config.json 파라미터 개선
대상: TRAILING_STOP_PCT, TRAILING_STOP_ACTIVATE_PCT, PROFIT_TARGET_PCT, ATR_STOP_MULTIPLIER, ATR_TARGET_MULTIPLIER, MAX_HARD_STOP_PCT

2. calculate_entry_price 함수의 진입가 산출 로직 개선
현재 로직: BB하단+SMA50 지지선 기반 진입, 손절=진입가×(1-TRAILING_STOP_PCT), 목표=BB중단 or +8%
ETF 특성(낮은 변동성, 추세 추종)에 맞게 진입 조건이나 손절·목표가 비율을 더 적합하게 개선하는 방안을 제안하세요.

3. calculate_holding_targets 함수의 보유종목 손절가·목표가 로직 개선
현재 로직: 손절=매수 후 최고가×(1-TRAILING_STOP_PCT), 목표=BBU(BB상단) or 현재가+8%
ETF 보유 시 더 넓은 손절 기준이나 추세 기반 목표가 조정이 필요한지 제안하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "analysis": "ETF 관점 분석 (한국어, 2문장)",
  "cycle": {cycle},
  "param_suggestions": [
    {{
      "param": "파라미터명",
      "current": "현재값",
      "suggested": "제안값",
      "reason": "이유 (1문장)"
    }}
  ],
  "entry_price_patch": {{
    "function": "calculate_entry_price",
    "reason": "ETF 특성 반영 진입가 로직 개선 (1문장)",
    "old_code": "교체할 기존 코드 블록 (정확한 문자열, 없으면 null)",
    "new_code": "새 코드 블록 (없으면 null)"
  }},
  "holding_targets_patch": {{
    "function": "calculate_holding_targets",
    "reason": "ETF 보유 시 손절가·목표가 기준 개선 (1문장)",
    "old_code": "교체할 기존 코드 블록 (정확한 문자열, 없으면 null)",
    "new_code": "새 코드 블록 (없으면 null)"
  }}
}}"""

    def _prompt_agent_backtest(self, cycle, stock_analysis, etf_suggestions,
                                before_stats, after_stats, patch_desc, kept):
        """agent_backtest: Before/After 백테스트 결과 검증 및 피드백 생성"""
        etf_section = f"\n[agent_etf 파라미터 제안]\n{etf_suggestions}" if etf_suggestions else ""
        return f"""당신은 40년 주식·ETF 백테스트 전문가입니다. 어떤 전략이든 반드시 데이터로 검증하며, 과최적화와 통계 불충분을 엄격히 경계합니다.

[사이클 {cycle} 검증]

[agent_stock 분석]
{stock_analysis}
{etf_section}

[패치 내용]
{chr(10).join(f"  - {p}" for p in patch_desc)}

[Before 백테스트]
- 거래수: {before_stats['total']}건 | 승률: {before_stats['win_rate']:.1f}% | 평균: {before_stats['avg_ret']:+.2f}% | Sharpe: {before_stats['sharpe']:.2f} | MDD: -{before_stats['mdd']:.1f}%

[After 백테스트]
- 거래수: {after_stats['total']}건 | 승률: {after_stats['win_rate']:.1f}% | 평균: {after_stats['avg_ret']:+.2f}% | Sharpe: {after_stats['sharpe']:.2f} | MDD: -{after_stats['mdd']:.1f}%

[최종 결정]: {"✅ 채택" if kept else "❌ 롤백"}

[임무]
1. 채택/롤백 결정에 대한 정량적 근거를 설명하세요.
2. 거부된 경우: agent_stock이 다음 사이클에서 반드시 반영해야 할 구체적 개선 방향을 제시하세요.
3. 채택된 경우: 다음 사이클에서 추가로 개선할 수 있는 항목을 제안하세요.
4. 샘플 수({before_stats['total']}건)가 50건 미만이면 통계 신뢰도 경고를 포함하세요.

2-4문장으로 간결하게 한국어로 작성하세요."""

    def auto_evolution_cycle(self, signal_perf, optimize_started):
        """
        agent_auto 기반 전문가 협업 3사이클 자동 진화 루프

        흐름:
          STEP 1. agent_search  — 신규 투자 방법론 탐색
          STEP 2-A. agent_stock — 주식 알고리즘 개선 제안 (사이클마다 피드백 반영)
          STEP 2-B. agent_etf   — ETF 파라미터 개선 제안 (병렬)
          STEP 3. agent_backtest — Before/After 검증, 채택/롤백 결정 + 피드백
          → 최소 3사이클 반복 후 최종 확정
        """
        sample_size = self.base_config.get('EXPERT_AB_SAMPLE_SIZE', 200)
        periods = self.base_config.get('EXPERT_AB_PERIODS', 8)
        max_cycles = 3  # 최소 3사이클

        signals = signal_perf.get('signals', {})
        if not signals:
            print("[Auto Evolution] 신호 성과 데이터 없음 — 사이클 생략")
            return

        sig_summary = "\n".join(
            f"  - {k}: 승률 {v['win_rate']:.1f}%, 평균 {v.get('avg_return', 0):+.2f}%, {v['total_count']}건"
            for k, v in sorted(signals.items(), key=lambda x: x[1]['win_rate'])
        )

        print("\n" + "=" * 72)
        print("  [Auto Evolution] agent_auto 기반 전문가 협업 시작")
        print(f"  최소 {max_cycles}사이클 실행 예정")
        print("=" * 72)

        # ── STEP 1: agent_search — 신규 방법론 탐색 ─────────────────────
        func_text = self._extract_signal_functions()
        search_proposals = ""
        if self.analyzer.ai_enabled:
            print("\n[STEP 1] agent_search — 신규 투자 방법론 탐색 중...")
            prompt_search = self._prompt_agent_search(sig_summary, func_text)
            search_raw = self._call_ai_fresh(prompt_search)
            if search_raw:
                import re, json as _json
                m = re.search(r'\{[\s\S]*\}', search_raw)
                if m:
                    try:
                        search_data = _json.loads(m.group())
                        methods = search_data.get('new_methods', [])
                        if methods:
                            lines = []
                            for mt in methods:
                                lines.append(f"  [{mt.get('category','')}] {mt.get('name','')}: {mt.get('description','')} → {mt.get('implementation_hint','')}")
                            search_proposals = "\n".join(lines)
                            print(f"  agent_search 제안 {len(methods)}건:")
                            print(search_proposals)
                    except Exception:
                        pass
            if not search_proposals:
                print("  agent_search 결과 없음 — 기존 방법론 기반으로 진행")
        else:
            print("\n[STEP 1] agent_search — AI 비활성화, 스킵")

        # ── STEP 2~4: 3사이클 반복 ──────────────────────────────────────
        backtest_feedback = ""
        best_cycle_kept = False

        for cycle in range(1, max_cycles + 1):
            print(f"\n{'─'*72}")
            print(f"  [사이클 {cycle}/{max_cycles}]")
            print(f"{'─'*72}")

            # STEP 2-A: agent_stock
            proposed_patches = []
            stock_analysis = ""
            if self.analyzer.ai_enabled:
                print(f"\n[사이클 {cycle}] STEP 2-A: agent_stock — 주식 알고리즘 분석 중...")
                prompt_stock = self._prompt_agent_stock(
                    sig_summary, func_text, search_proposals, backtest_feedback, cycle
                )
                stock_raw = self._call_ai_fresh(prompt_stock)
                if stock_raw:
                    import re
                    m = re.search(r'"analysis"\s*:\s*"([^"]+)"', stock_raw)
                    if m:
                        stock_analysis = m.group(1)
                        print(f"  agent_stock 분석: {stock_analysis}")
                    proposed_patches = self._parse_expert_a_patches(stock_raw)
                    if proposed_patches:
                        print(f"  agent_stock 제안 패치 {len(proposed_patches)}건:")
                        for p in proposed_patches:
                            print(f"    ✎ {p['function']}: {p['reason']}")
                    else:
                        print("  agent_stock 패치 파싱 실패 → 규칙 기반 fallback")

            # STEP 2-B: agent_etf (병렬 — AI 호출 순차 처리)
            etf_suggestions = ""
            if self.analyzer.ai_enabled:
                print(f"\n[사이클 {cycle}] STEP 2-B: agent_etf — ETF 파라미터 분석 중...")
                prompt_etf = self._prompt_agent_etf(
                    sig_summary, search_proposals, backtest_feedback, cycle
                )
                etf_raw = self._call_ai_fresh(prompt_etf)
                if etf_raw:
                    import re, json as _json
                    m = re.search(r'\{[\s\S]*\}', etf_raw)
                    if m:
                        try:
                            etf_data = _json.loads(m.group())
                            etf_analysis = etf_data.get('analysis', '')
                            suggestions = etf_data.get('param_suggestions', [])
                            if etf_analysis:
                                print(f"  agent_etf 분석: {etf_analysis}")
                            if suggestions:
                                etf_lines = [f"  {s['param']}: {s['current']} → {s['suggested']} ({s['reason']})" for s in suggestions]
                                etf_suggestions = "\n".join(etf_lines)
                                print(f"  agent_etf 파라미터 제안:")
                                print(etf_suggestions)
                            # calculate_entry_price 패치 제안 추출
                            ep_patch = etf_data.get('entry_price_patch', {})
                            if ep_patch and ep_patch.get('old_code') and ep_patch.get('new_code'):
                                proposed_patches.append({
                                    'function': 'calculate_entry_price',
                                    'reason': ep_patch.get('reason', 'agent_etf: ETF 진입가 로직 개선'),
                                    'old_code': ep_patch['old_code'],
                                    'new_code': ep_patch['new_code'],
                                })
                                print(f"  agent_etf calculate_entry_price 패치 제안 수신: {ep_patch.get('reason','')}")
                            # calculate_holding_targets 패치 제안 추출
                            ht_patch = etf_data.get('holding_targets_patch', {})
                            if ht_patch and ht_patch.get('old_code') and ht_patch.get('new_code'):
                                proposed_patches.append({
                                    'function': 'calculate_holding_targets',
                                    'reason': ht_patch.get('reason', 'agent_etf: ETF 보유 손절·목표 로직 개선'),
                                    'old_code': ht_patch['old_code'],
                                    'new_code': ht_patch['new_code'],
                                })
                                print(f"  agent_etf calculate_holding_targets 패치 제안 수신: {ht_patch.get('reason','')}")
                        except Exception:
                            pass

            # AI 패치 없으면 규칙 기반 fallback
            if not proposed_patches:
                print(f"[사이클 {cycle}] 규칙 기반 패치 시도...")
                code = self._read_analyzer()
                weak_threshold = self.base_config.get('WEAK_SIGNAL_WIN_RATE_THRESHOLD', 45)
                weak_signals = {
                    k: v for k, v in signals.items()
                    if v.get('total_count', 0) >= 3 and v.get('win_rate', 100) < weak_threshold
                }
                rule_patches = []
                if '거래량 급증' in weak_signals:
                    code2, ok = self._patch_volume_spike_bullish(code)
                    if ok:
                        rule_patches.append({'function': 'detect_volume_spike',
                                             'reason': '규칙기반: 양봉 확인 조건 추가',
                                             'old_code': '', 'new_code': '', '_code': code2})
                if '바닥권 반등 신호(BB 하단)' in weak_signals:
                    base = rule_patches[-1]['_code'] if rule_patches else code
                    code2, ok = self._patch_taj_mahal_rsi_35(base)
                    if ok:
                        rule_patches.append({'function': 'is_taj_mahal_signal',
                                             'reason': '규칙기반: RSI 기준 40→35 강화',
                                             'old_code': '', 'new_code': '', '_code': code2})
                if not rule_patches:
                    print(f"[사이클 {cycle}] 적용 가능한 패치 없음 — 이 사이클 스킵")
                    continue
                proposed_patches = rule_patches

            # STEP 3: agent_backtest — Before 백테스트
            import sys
            for _mod in ['analyzer', 'backtester']:
                if _mod in sys.modules:
                    del sys.modules[_mod]
            print(f"\n[사이클 {cycle}] STEP 3: agent_backtest — Before 백테스트...")
            before_stats = self.run_quick_backtest_stats(sample_size=sample_size, periods=periods)
            if not before_stats:
                print(f"[사이클 {cycle}] Before 백테스트 실패 — 스킵")
                continue
            print(
                f"  Before: {before_stats['total']}건 | 승률 {before_stats['win_rate']:.1f}% "
                f"| 평균 {before_stats['avg_ret']:+.2f}% | Sharpe {before_stats['sharpe']:.2f} "
                f"| MDD -{before_stats['mdd']:.1f}%"
            )

            # 패치 적용
            self._backup_analyzer()
            if all('_code' not in p for p in proposed_patches):
                applied_patches = self._apply_ai_patches(proposed_patches)
            else:
                final_code = proposed_patches[-1].get('_code', '')
                if final_code:
                    self._write_analyzer(final_code)
                    applied_patches = proposed_patches
                else:
                    applied_patches = []

            if not applied_patches:
                print(f"[사이클 {cycle}] 패치 적용 실패 — 스킵")
                self._restore_analyzer()
                continue

            patch_desc = [f"{p['function']}: {p['reason']}" for p in applied_patches]
            print(f"  패치 {len(applied_patches)}건 적용 완료")

            # After 백테스트
            import sys
            for _mod in ['analyzer', 'backtester']:
                if _mod in sys.modules:
                    del sys.modules[_mod]
            print(f"  After 백테스트 실행 중...")
            after_stats = self.run_quick_backtest_stats(sample_size=sample_size, periods=periods)
            if not after_stats:
                print(f"[사이클 {cycle}] After 백테스트 실패 — rollback")
                self._restore_analyzer()
                continue
            print(
                f"  After:  {after_stats['total']}건 | 승률 {after_stats['win_rate']:.1f}% "
                f"| 평균 {after_stats['avg_ret']:+.2f}% | Sharpe {after_stats['sharpe']:.2f} "
                f"| MDD -{after_stats['mdd']:.1f}%"
            )

            # 채택/롤백 결정
            before_score = self._score_backtest(before_stats)
            after_score = self._score_backtest(after_stats)
            kept = after_score > before_score
            print(f"\n  [agent_backtest] 점수: Before {before_score:.2f} → After {after_score:.2f}")
            if kept:
                print(f"  ✅ 사이클 {cycle} 채택 — 개선 확인")
                best_cycle_kept = True
            else:
                print(f"  ❌ 사이클 {cycle} 롤백 — 성과 미향상")
                self._restore_analyzer()

            # agent_backtest AI 피드백 생성 (다음 사이클에 반영)
            if self.analyzer.ai_enabled:
                prompt_bt = self._prompt_agent_backtest(
                    cycle, stock_analysis, etf_suggestions,
                    before_stats, after_stats, patch_desc, kept
                )
                bt_feedback = self._call_ai_fresh(prompt_bt)
                if bt_feedback:
                    backtest_feedback = bt_feedback.strip()
                    print(f"\n  [agent_backtest 피드백 → 다음 사이클 반영]\n  {backtest_feedback[:400]}")

            self._log_expert_ab_result(patch_desc, before_stats, after_stats, kept=kept)

            # 최종 사이클 함수 코드 갱신 (다음 사이클 분석 기준)
            func_text = self._extract_signal_functions()

        print("\n" + "=" * 72)
        print(f"  [Auto Evolution 완료] {max_cycles}사이클 종료 — "
              f"{'최소 1건 채택됨' if best_cycle_kept else '모든 사이클 롤백'}")
        print("=" * 72)

    # ------------------------------------------------------------------
    # 10. 메인 최적화 루틴
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

        # ── 6. 추가 파라미터 최적화 (실제 구현) ─────────────────────────
        additional_params = self.optimize_additional_parameters(recs, current_results, optimize_started)

        # ── 6-B. US 주식 파라미터 최적화 ────────────────────────────────
        us_params = self.optimize_us_parameters(optimize_started)

        # ── 6-C. Auto Evolution — agent_auto 기반 전문가 협업 3사이클 ──────
        if self.base_config.get('EXPERT_AB_ENABLED', True):
            self.auto_evolution_cycle(signal_perf, optimize_started)
        else:
            print("\n[Auto Evolution] EXPERT_AB_ENABLED=False — 사이클 비활성화")

        # ── 7. 점진적 학습 적용 ──────────────────────────────────────────
        proposed_config = copy.deepcopy(self.base_config)
        proposed_config['TRAILING_STOP_PCT'] = best_stop
        proposed_config['TIER1_WIN_RATE'] = best_tier1
        proposed_config.update(additional_params)
        proposed_config.update(us_params)

        # 샘플 수 기반 동적 learning_rate (샘플 많을수록 더 적극적 반영)
        if len(recs) >= 30:
            learning_rate = 0.4
        elif len(recs) >= 15:
            learning_rate = 0.3
        else:
            learning_rate = 0.15
        print(f"\n[점진적 학습 적용] (샘플 {len(recs)}개 → learning_rate={learning_rate})")
        gradual_config = self.apply_gradual_learning(self.base_config, proposed_config, learning_rate=learning_rate)
        
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
    optimizer.process_search_backlog()
    optimizer.optimize()
