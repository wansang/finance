# agent_system 역할 및 전문성

1. 본 agent_system은 40년 경력의 주식 및 ETF 트레이딩 시스템 설계 전문가의 노하우를 바탕으로 한다.
2. 다양한 회사의 시스템 설계 점검 및 고도화 전략을 추천해온 경험이 있다.
3. 시스템의 설계, 구조, 효율, 보안, 확장성 등 모든 방면을 점검한다.
4. 필요시 외부 전문가(퀀트, AI, 백엔드, 인프라 등)와 협업하여 최적의 솔루션을 도출한다.
5. agent_system이 점검·설계한 시스템은 무결점(Zero Defect) 품질을 목표로 한다.

---

이 문서는 전체 에이전트 시스템(구조, 역할, 연동 방식 등)에 대한 설계 및 운영 가이드입니다.
각 agent(예: agent_stock, agent_etf, agent_search, agent_auto 등)와의 관계, 데이터 흐름, 백로그/히스토리 관리, 외부 연동(GitHub Actions, Google Scheduler 등) 정책을 기술합니다.

## 주요 내용 예시
- 에이전트 시스템 구조도
- 각 agent 역할 및 호출 흐름
- 백로그/히스토리 관리 정책
- 외부 워크플로우(스케줄러, Actions) 연동 방식
- 확장/운영 가이드

(필요한 세부 내용은 자유롭게 추가/수정하세요)

---

## 1. 에이전트 시스템 구조도 (예시)

```mermaid
flowchart TD
	Main(Main System) -->|API| AgentStock
	Main -->|API| AgentETF
	Main -->|API| AgentSearch
	Main -->|API| AgentAuto
	AgentStock <-->|데이터| DB[(DB/스토리지)]
	AgentETF <--> DB
	AgentSearch <--> DB
	AgentAuto <--> DB
	Main <-->|워크플로우| Ext[외부 시스템 (GitHub Actions, Google Scheduler 등)]
```

## 2. 각 agent 역할 및 호출 흐름

- **agent_stock**: 주식 종목 데이터 수집, 분석, 신호 생성, 주문 연동
- **agent_etf**: ETF 데이터 수집, 분석, 신호 생성, 주문 연동
- **agent_search**: 전략/종목/ETF 탐색 및 추천, 백로그 관리
- **agent_auto**: 자동화된 반복 작업(스케줄러, 배치 등) 실행

호출 흐름 예시:
1. Main System이 agent_search에 전략 탐색 요청
2. agent_search가 DB에서 데이터 조회 및 분석
3. 결과를 Main System에 반환, 필요시 agent_stock/agent_etf에 신호 전달
4. 외부 워크플로우(스케줄러, Actions)와 연동하여 자동화

## 3. 데이터 흐름 및 저장소

- 모든 agent는 DB/스토리지(예: json, DB, csv 등)와 연동
- 데이터 흐름: 입력(시장 데이터, 사용자 요청) → 처리(분석/탐색/신호) → 출력(추천, 주문, 알림)
- 백로그/히스토리: searchBacklog.json, searchBacklog_history.json 등으로 관리

## 4. 백로그/히스토리 관리 정책

- 모든 전략/탐색/신호 기록은 백로그(json/csv)로 저장
- 주요 변경 이력은 searchBacklog_history.json, algorithm_update_log.json 등으로 관리
- 주기적 백업 및 무결성 점검 권장

## 5. 외부 워크플로우 연동 예시

- **GitHub Actions**: 코드 변경 시 자동 테스트/배포, 워크플로우 트리거
- **Google Scheduler**: 정기적(예: 매일 09:00)으로 agent_search/agent_auto 실행
- 연동 스크립트 예시: google-scheduler/ 폴더 내 shell, js 파일 참고

## 6. 확장/운영 가이드

- 신규 agent 추가 시 구조도/호출 흐름/데이터 흐름에 반영
- 장애 발생 시 로그(algorithm_update_log.json 등) 및 알림(notifier.py) 활용
- 보안: 외부 연동 시 인증/권한 관리, 민감 정보 분리
- 버전 관리: 주요 정책/구조 변경 시 update_log, update_report, summary 등 기록

---

실제 운영 환경/정책에 맞게 세부 내용을 계속 보완하세요.
---

## [전문가 관점 다각도 점검 항목]

### 1. 구조적 완성도
- 시스템 구조도에 에러 핸들링/장애 복구 흐름 추가 권장
- 데이터 저장소 유형(관계형, NoSQL, 파일 등) 및 백업/복구 정책 명시

### 2. 효율성 및 확장성
- agent 간 인터페이스(API/메시지 포맷 등) 명세화
- 대용량 데이터 처리(멀티프로세싱, 비동기 등) 및 확장 전략 구체화

### 3. 보안 및 운영
- 외부 연동(GitHub Actions, Google Scheduler 등) 시 인증/권한 관리, 민감 정보 암호화/분리 저장 정책 명확화
- 로그/모니터링 체계(notifier.py, monitor.py 등)와 장애 발생 시 자동 알림/복구 시나리오 구체화

### 4. 품질 및 무결성
- 백로그/히스토리 관리에 데이터 무결성 체크(해시, 검증 로직 등)와 주기적 점검/알림 체계 추가
- 테스트/배포 자동화(GitHub Actions) 시 테스트 커버리지, 롤백 정책 포함

### 5. 운영/유지보수 가이드
- 실시간 모니터링, 장애 대응 매뉴얼, 주요 로그/이벤트 예시, 버전 관리 정책(릴리즈 노트, 변경 이력 관리 등) 구체화

---

위 항목을 참고해 시스템 설계/운영 가이드를 지속적으로 보완하면, 실전에서 신뢰받는 전문가 수준의 시스템을 구축할 수 있습니다.
