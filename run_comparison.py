"""
B전문가 검증: A전문가 개선 전/후 성과 비교 자동 실행 스크립트
- 현재 개선된 analyzer.py (RSI≤35, 다이버전스 RSI≤40, 거래량1.2배, 52주신고가신호) vs 이전 베이스라인
- 결과를 algorithm_update_report.py 와 별도로 backtest_results.md에 기록
"""

import datetime
import os
import sys
import json

from backtester import Backtester

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(BASE_DIR, 'backtest_results.md')
LOG_FILE = os.path.join(BASE_DIR, 'algorithm_update_log.json')


def calc_stats_from_df(df_results, avg_hold_days=20):
    if df_results is None or df_results.empty:
        return {"총거래수": 0, "승률": "N/A", "평균수익률": "N/A", "MDD": "N/A", "Sharpe": "N/A"}

    import pandas as pd
    total = len(df_results)
    wins = (df_results['Return(%)'] > 0).sum()
    win_rate = wins / total * 100
    avg_ret = df_results['Return(%)'].mean()
    std_ret = df_results['Return(%)'].std()

    rets_seq = df_results['Return(%)'].tolist()
    equity = 1.0; peak_eq = 1.0; mdd = 0.0
    for r in rets_seq:
        equity *= (1 + r / 100)
        if equity > peak_eq:
            peak_eq = equity
        dd = (peak_eq - equity) / peak_eq * 100
        if dd > mdd:
            mdd = dd

    annual_factor = (250 / max(avg_hold_days, 1)) ** 0.5
    risk_free = 3.5 / (250 / max(avg_hold_days, 1))
    sharpe = ((avg_ret - risk_free) / std_ret * annual_factor) if std_ret > 0 else 0.0

    loss_flags = [1 if r <= 0 else 0 for r in rets_seq]
    max_consec = curr_c = 0
    for lf in loss_flags:
        curr_c = curr_c + 1 if lf else 0
        if curr_c > max_consec:
            max_consec = curr_c

    return {
        "총거래수": total,
        "승률": f"{win_rate:.1f}% ({wins}승 {total-wins}패)",
        "평균수익률": f"{avg_ret:+.2f}%",
        "MDD": f"-{mdd:.2f}%",
        "Sharpe(연율화)": f"{sharpe:.2f}",
        "최대연속손실": f"{max_consec}연속",
        "신뢰도": "높음 ✅" if total >= 80 else "보통 ⚠️" if total >= 30 else "낮음 ❌",
    }


def save_section(title, stats, notes=""):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [f"\n---\n", f"## {title}\n", f"**실행일시**: {timestamp}\n\n",
             "| 지표 | 값 |\n|------|------|\n"]
    for k, v in stats.items():
        lines.append(f"| {k} | {v} |\n")
    if notes:
        lines.append(f"\n**비고**: {notes}\n")
    with open(RESULTS_FILE, 'a', encoding='utf-8') as f:
        f.writelines(lines)


def run_backtest(label):
    print(f"\n{'='*60}")
    print(f"  B전문가 검증 백테스트: {label}")
    print(f"{'='*60}")
    bt = Backtester()
    df = bt.run_walkforward_backtest(periods=8, interval_weeks=6)
    bt.print_summary(df, label)
    return df


def update_log(before_stats, after_stats):
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "type": "A전문가_알고리즘_개선",
        "changes": [
            "is_taj_mahal_signal: RSI 과매도 기준 40→35 강화",
            "is_taj_mahal_signal: 거래량 필터 0.8배→1.2배 강화",
            "detect_divergence: RSI 과매도 기준 45→40 강화",
            "detect_volume_spike: 기준 2.5배→2.0배 완화 (신호 민감도 조정)",
            "detect_52week_high_breakout: 신규 신호 추가 (52주신고가95%+거래량1.5배+양봉)",
            "check_signals: 신호 8번 52주신고가 돌파 추가",
        ],
        "before": {k: str(v) for k, v in before_stats.items()},
        "after": {k: str(v) for k, v in after_stats.items()},
        "expert_cycle": "A분석→코드수정→B백테스트검증",
    }
    existing = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.append(entry)
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"\n✅ algorithm_update_log.json 업데이트 완료")


def main():
    # ─── 이전 베이스라인 수치 (이전 세션 backtest_results.md 에서 확인된 값) ─────
    before_stats = {
        "총거래수": 191,
        "승률": "54.5% (104승 87패)",
        "평균수익률": "+1.51%",
        "MDD": "-80.53%",
        "Sharpe(연율화)": "0.47",
        "신뢰도": "높음 ✅",
    }

    print("\n" + "="*60)
    print("  📊 B전문가 검증 시작: A전문가 개선 알고리즘 백테스트")
    print("  개선 내용:")
    print("    1. 타지마할 신호 RSI 기준: 40 → 35")
    print("    2. 타지마할 신호 거래량 필터: 0.8배 → 1.2배")
    print("    3. RSI 다이버전스 과매도 기준: 45 → 40")
    print("    4. 거래량 급증 기준: 2.5배 → 2.0배 (민감도 조정)")
    print("    5. 52주 신고가 돌파 신호 추가 (신규)")
    print("="*60)

    df_after = run_backtest("A전문가 개선후 — BB+RSI강화+52주신고가")
    after_stats = calc_stats_from_df(df_after)

    # ─── 비교 리포트 저장 ───────────────────────────────────────────────────
    if not os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
            f.write("# 전략별 백테스트 결과\n\n")

    save_section(
        "【B전문가 검증】 A전문가 개선 후 — BB+RSI강화+52주신고가 신호 추가",
        after_stats,
        notes=(
            "개선 내용: ① 타지마할 RSI≤40→35 ② 거래량필터 0.8배→1.2배 "
            "③ 다이버전스 RSI≤45→40 ④ 거래량급증 2.5배→2.0배 ⑤ 52주신고가 신호 신규 추가"
        )
    )

    # ─── 개선 전/후 비교 출력 ─────────────────────────────────────────────
    print("\n" + "="*60)
    print("  📊 B전문가 검증 결과 비교")
    print("="*60)
    print(f"  {'지표':<20} {'이전(베이스라인)':<25} {'이후(A전문가 개선)':<25}")
    print(f"  {'-'*70}")
    for k in ["총거래수", "승률", "평균수익률", "MDD", "Sharpe(연율화)", "신뢰도"]:
        bv = str(before_stats.get(k, "N/A"))
        av = str(after_stats.get(k, "N/A"))
        print(f"  {k:<20} {bv:<25} {av:<25}")

    # ─── 로그 업데이트 ─────────────────────────────────────────────────────
    update_log(before_stats, after_stats)

    # ─── Git 커밋 ──────────────────────────────────────────────────────────
    print("\n  📦 Git 커밋 중...")
    after_summary = f"승률:{after_stats.get('승률','?')} 평균:{after_stats.get('평균수익률','?')} MDD:{after_stats.get('MDD','?')} Sharpe:{after_stats.get('Sharpe(연율화)','?')}"
    os.system(f'cd {BASE_DIR} && git add analyzer.py backtest_results.md algorithm_update_log.json run_comparison.py && '
              f'git commit -m "feat: A전문가 알고리즘 개선 + B전문가 백테스트 검증 [{after_summary}]" && '
              f'git push origin main')
    print("  ✅ Git 커밋 완료")
    print("\n✅ B전문가 검증 사이클 완료")


if __name__ == '__main__':
    main()
