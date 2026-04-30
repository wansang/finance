"""
agent_search_run.py
------------------
신규 투자 방법론 탐색(agent_search 역할)만 수행하고,
결과를 searchBacklog.json에 append 저장한다.

- agent_stock/agent_etf에 직접 의뢰하지 않는다.
- optimize.py에서 backlog를 소비한다.
"""

import json
import os
import datetime
from agent.agent_search import run_agent_search

BACKLOG_FILE = 'searchBacklog.json'


# 중복제거를 위한 함수: backlog/history에서 이미 있는 방법론명은 제외
def load_existing_method_names():
    names = set()
    for fname in ['searchBacklog.json', 'searchBacklog_history.json']:
        if os.path.exists(fname):
            with open(fname, 'r', encoding='utf-8') as f:
                try:
                    items = json.load(f)
                    for entry in items:
                        method = entry.get('method', {})
                        name = method.get('방법론명')
                        if name:
                            names.add(name)
                except Exception:
                    continue
    return names

def append_to_backlog(entry):
    if os.path.exists(BACKLOG_FILE):
        with open(BACKLOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = []
    data.append(entry)
    with open(BACKLOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    # agent_search 역할 실행 (실제 구현은 agent/agent_search.py에 위임)
    results = run_agent_search()
    now = datetime.datetime.now().isoformat()
    existing_names = load_existing_method_names()
    added = 0
    for r in results:
        name = r.get('방법론명')
        if name and name not in existing_names:
            entry = {
                "searched_at": now,
                "method": r
            }
            append_to_backlog(entry)
            added += 1
    print(f"{added}건의 신규 방법론이 backlog에 저장되었습니다. (중복 제외)")

if __name__ == "__main__":
    main()
