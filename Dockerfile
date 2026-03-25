# ─────────────────────────────────────────
# GW 자동화 챗봇 Dockerfile
# Playwright + Chromium 포함 (headless 브라우저 자동화)
# ─────────────────────────────────────────

# Python 3.12 slim (Debian Bookworm 기반 — Playwright 공식 지원)
FROM python:3.12-slim-bookworm

# 비-root 유저 생성 (보안)
RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser appuser

# Playwright 의존 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chromium 의존성
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    # 폰트 (한글 포함)
    fonts-nanum \
    fonts-nanum-coding \
    fontconfig \
    # 기타
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리
WORKDIR /app

# 의존성 먼저 설치 (캐시 최적화)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium 설치 (시스템 패키지는 위 apt-get에서 처리 완료)
RUN playwright install chromium && \
    chmod -R 755 /root/.cache/ms-playwright 2>/dev/null || true

# 앱 코드 복사
COPY . .

# 데이터/로그 디렉토리 생성 + 권한
RUN mkdir -p data/chatbot data/approval_screenshots data/tmp logs && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app/data

# Playwright 캐시 appuser에게 복사
RUN if [ -d /root/.cache/ms-playwright ]; then \
    mkdir -p /home/appuser/.cache && \
    cp -r /root/.cache/ms-playwright /home/appuser/.cache/ && \
    chown -R appuser:appuser /home/appuser/.cache; \
    fi

# 비-root 유저로 전환
USER appuser

# 포트 노출
EXPOSE 51749

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:51749/health || exit 1

# 실행
CMD ["python", "run_chatbot.py"]
