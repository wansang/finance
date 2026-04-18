# 텔레그램 봇 배포 가이드

## 목차
1. [로컬 실행](#로컬-실행)
2. [Railway.app 배포](#railwayapp-배포-권장)
3. [Docker로 실행](#docker로-실행)

---

## 로컬 실행

```bash
# 환경 변수 설정
export TELEGRAM_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# 봇 실행
python bot.py
```

---

## Railway.app 배포 (권장) ⭐

**Railway.app**은 무료 크레딧($5/월)으로 24/7 봇을 운영할 수 있습니다.

### 1단계: Railway 계정 생성
- https://railway.app 방문
- GitHub로 로그인

### 2단계: 새 프로젝트 생성
1. "New Project" → "Deploy from GitHub"
2. `wansang/finance` 리포지토리 선택
3. 배포 대기

### 3단계: 환경 변수 설정
Railway 대시보드에서 "Variables" 탭으로 이동:
```
TELEGRAM_TOKEN = your_token_here
TELEGRAM_CHAT_ID = your_chat_id_here
GITHUB_PAT = your_github_token
GEMINI_API_KEY = your_gemini_key
```

### 4단계: 배포 완료
- Railway가 자동으로 `Dockerfile`을 인식해 배포 시작
- 배포 완료 후 24/7 실행됨
- 데이터(holdngs.json, watchlist.json)는 GitHub에 자동 저장

---

## Docker로 실행

### 로컬에서 Docker로 테스트:
```bash
# .env 파일 생성
echo "TELEGRAM_TOKEN=your_token" > .env
echo "TELEGRAM_CHAT_ID=your_id" >> .env
echo "GITHUB_PAT=your_pat" >> .env
echo "GEMINI_API_KEY=your_key" >> .env

# Docker Compose로 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f stock-bot

# 중지
docker-compose down
```

---

## 다른 배포 옵션

### Render.com (무료, 단 비활성 상태 중지)
- https://render.com
- GitHub 연결 후 서비스 생성
- Dockerfile 자동 감지
- 무료이지만 15분 비활성 시 중지

### Fly.io (무료 옵션)
- https://fly.io
- `flyctl launch` 명령어로 배포
- 무료 크레디트 포함

---

## 문제 해결

### 봇이 응답 안 함
1. TELEGRAM_TOKEN이 정확한지 확인
2. 봇이 실제로 배포되었는지 확인
3. 배포 로그 확인

### 데이터가 저장 안 됨
- 배포 서비스에서 / 호스팅 중인 폴더로 매핑 확인
- GitHub 리포지토리에 파일이 커밋되었는지 확인

---

## 추천 설정

**24/7 무중단 운영**:
1. ✅ Railway.app ($5 무료 크레딧)
2. ✅ GitHub Actions (analyze 워크플로우)
3. ✅ 자동 커밋 (변경사항 저장)

