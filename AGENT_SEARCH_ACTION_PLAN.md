# agent_search Github Action

# 목적
- agent_search 역할(신규 투자 방법론 탐색 및 backlog 저장)을 Github Action에서 바로 실행할 수 있도록 한다.
- 검색 결과는 즉시 agent_stock/agent_etf에 의뢰하지 않고, searchBacklog.json에 저장한다.
- optimize(주말) 실행 시 backlog를 불러와 agent_stock/agent_etf/agent_backtest가 검증 및 시스템 반영을 시도한다.

# 구현 개요
- 신규 워크플로우(.github/workflows/agent_search.yml) 추가
- 실행 스크립트(agent_search_run.py) 추가: agent_search 역할만 수행, 결과를 searchBacklog.json에 append
- optimize.py에서 backlog 처리 로직 추가

# 파일 목록
- .github/workflows/agent_search.yml
- agent_search_run.py
- searchBacklog.json (자동 생성/append)
- optimizer.py (backlog 처리 로직 추가)

# 주요 동작
1. Github Action에서 agent_search.yml 실행 → agent_search_run.py 실행
2. agent_search_run.py는 agent_search 역할에 따라 신규 방법론 탐색 및 searchBacklog.json에 저장
3. optimize.py는 주말 실행 시 searchBacklog.json의 backlog를 agent_stock/agent_etf/agent_backtest에 전달하여 검증/반영

# 주의
- agent_search_run.py는 agent_stock/agent_etf에 직접 의뢰하지 않는다.
- optimize.py만 backlog를 소비한다.
