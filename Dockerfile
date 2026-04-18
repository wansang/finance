FROM python:3.9-slim

WORKDIR /app

# 필수 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# 환경 변수 기본값 설정
ENV TELEGRAM_TOKEN=""
ENV TELEGRAM_CHAT_ID=""
ENV GITHUB_PAT=""
ENV GEMINI_API_KEY=""

# 요구사항 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 봇 실행
CMD ["python3", "bot.py"]
