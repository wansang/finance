"""
merge_batches.py
배치 병렬 optimize 결과를 합산하여:
  - searchBacklog_history.json 업데이트
  - strategy_config.json 승인 변경사항 반영
  - searchBacklog.json에서 처리된 항목 제거
  - 배치 임시 파일 삭제
"""
import json
import os
import glob
import datetime


def merge():
    backlog_file  = 'searchBacklog.json'
    history_file  = 'searchBacklog_history.json'
    config_file   = 'strategy_config.json'

    # ── 배치 결과 파일 탐색 ───────────────────────────────────────────
    history_files = sorted(glob.glob('searchBacklog_history_batch_*.json'))
    changes_files = sorted(glob.glob('approved_changes_batch_*.json'))

    if not history_files:
        print("[merge] 배치 결과 파일 없음 — 스킵")
        return

    print(f"[merge] 배치 파일 {len(history_files)}개 발견")

    # ── 1. history 합산 ───────────────────────────────────────────────
    history = []
    if os.path.exists(history_file):
        try:
            history = json.load(open(history_file, encoding='utf-8'))
        except Exception:
            history = []

    all_processed_entries = []
    for hf in history_files:
        try:
            entries = json.load(open(hf, encoding='utf-8'))
            all_processed_entries.extend(entries)
            print(f"  {hf}: {len(entries)}건")
        except Exception as e:
            print(f"  {hf}: 오류 — {e}")

    history.extend(all_processed_entries)
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"[merge] history 총 {len(history)}건 저장")

    # ── 2. 승인 변경사항 합산 → strategy_config.json 반영 ────────────
    # 파라미터 허용 범위: (min, max). None은 한쪽 경계 없음.
    PARAM_BOUNDS = {
        'TREND_TEMPLATE_PEAK_FACTOR':  (0.10, 0.95),
        'TIER1_WIN_RATE':              (30,   85),
        'TIER2_WIN_RATE':              (25,   75),
        'RS_MIN_BEAR_DEFENSE':         (-0.5, 0.3),
        'VALIDATE_MIN_HISTORY':        (50,   500),
        'VALIDATE_MAX_HOLD_DAYS':      (5,    90),
        'TRAILING_STOP_PCT':           (0.01, 0.15),
        'TRAILING_STOP_ACTIVATE_PCT':  (0.01, 0.40),
        'MIN_AVG_VOLUME':              (1000, 300000),
        'SMA50':                       (20,   70),
        'SMA150':                      (100,  200),
        'SMA200':                      (150,  250),
        'RSI_LENGTH':                  (5,    30),
        'MFI_LENGTH':                  (5,    30),
        'VOL_AVG_WINDOW':              (5,    50),
        'STOCH_RSI_LENGTH':            (5,    50),
        'STOCH_K':                     (2,    21),
        'STOCH_D':                     (2,    21),
        'PROFIT_TARGET_PCT':           (0.03, 0.60),
        'RS_LOOKBACK_BEAR':            (5,    120),
    }

    def validate_param(key, value, current_value):
        """파라미터 값이 허용 범위 내인지 검증. 범위 벗어나면 current_value 반환."""
        if key not in PARAM_BOUNDS:
            return value
        lo, hi = PARAM_BOUNDS[key]
        try:
            val = float(value)
        except (TypeError, ValueError):
            return value
        if (lo is not None and val < lo) or (hi is not None and val > hi):
            print(f"  [경고] {key}={value} 허용 범위({lo}~{hi}) 초과 → 현재값 {current_value} 유지")
            return current_value
        return value

    all_approved = {}
    for cf in changes_files:
        try:
            changes = json.load(open(cf, encoding='utf-8'))
            all_approved.update(changes)
        except Exception as e:
            print(f"  {cf}: 오류 — {e}")

    if all_approved:
        config = json.load(open(config_file, encoding='utf-8'))
        # 범위 검증 후 적용
        validated = {}
        for k, v in all_approved.items():
            validated[k] = validate_param(k, v, config.get(k, v))
        all_approved = validated
        config.update(all_approved)
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"[merge] strategy_config.json 업데이트: {list(all_approved.keys())}")

        # algorithm_update_log.json 기록
        log_file = 'algorithm_update_log.json'
        log = []
        if os.path.exists(log_file):
            try:
                log = json.load(open(log_file, encoding='utf-8'))
            except Exception:
                log = []
        log.append({
            'updated_at': datetime.datetime.now().isoformat(),
            'source': 'merge_batches',
            'approved_changes': all_approved,
            'batch_count': len(history_files),
        })
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    else:
        print("[merge] 승인된 변경사항 없음")

    # ── 3. searchBacklog.json에서 처리된 항목 제거 ────────────────────
    processed_names = {
        e.get('method', {}).get('방법론명', '')
        for e in all_processed_entries
    }
    backlog = []
    if os.path.exists(backlog_file):
        try:
            backlog = json.load(open(backlog_file, encoding='utf-8'))
        except Exception:
            backlog = []

    remaining = [
        e for e in backlog
        if e.get('method', {}).get('방법론명', '') not in processed_names
    ]
    with open(backlog_file, 'w', encoding='utf-8') as f:
        json.dump(remaining, f, ensure_ascii=False, indent=2)
    removed = len(backlog) - len(remaining)
    print(f"[merge] backlog: {len(backlog)}건 → {len(remaining)}건 ({removed}건 제거)")

    # ── 4. 배치 임시 파일 삭제 ────────────────────────────────────────
    for f in history_files + changes_files:
        os.remove(f)
        print(f"[merge] 삭제: {f}")

    # ── 5. evolve 잡을 위한 backlog 실행 요약 저장 ───────────────────
    approved_entries = [
        e for e in all_processed_entries
        if e.get('validation_result', {}).get('stock', {}).get('verdict') == 'approved'
        or e.get('validation_result', {}).get('etf', {}).get('verdict') == 'approved'
    ]
    rejected_entries = [
        e for e in all_processed_entries
        if e.get('validation_result', {}).get('stock', {}).get('verdict') == 'rejected'
        or e.get('validation_result', {}).get('etf', {}).get('verdict') == 'rejected'
    ]
    run_summary = {
        'total_backlog': len(backlog),
        'total_validated': len(all_processed_entries),
        'remaining': len(remaining),
        'approved_count': len(approved_entries),
        'rejected_count': len(rejected_entries),
        'approved_changes': all_approved,
        'entries': all_processed_entries,
    }
    with open('_backlog_run_summary.json', 'w', encoding='utf-8') as f:
        json.dump(run_summary, f, ensure_ascii=False, indent=2)
    print(f"[merge] backlog 실행 요약 저장: _backlog_run_summary.json "
          f"(처리 {len(all_processed_entries)}건, 채택 {len(approved_entries)}건, 거부 {len(rejected_entries)}건)")

    print("[merge] 완료")


if __name__ == '__main__':
    merge()
