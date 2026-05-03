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
    all_approved = {}
    for cf in changes_files:
        try:
            changes = json.load(open(cf, encoding='utf-8'))
            all_approved.update(changes)
        except Exception as e:
            print(f"  {cf}: 오류 — {e}")

    if all_approved:
        config = json.load(open(config_file, encoding='utf-8'))
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

    print("[merge] 완료")


if __name__ == '__main__':
    merge()
