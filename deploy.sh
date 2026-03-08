#!/bin/bash
# ─────────────────────────────────────────
# GW 자동화 챗봇 배포 스크립트
# 사용법: ./deploy.sh [start|stop|restart|build|logs|status|ssl]
# ─────────────────────────────────────────

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[deploy]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# 환경 변수 파일 확인
check_env() {
    if [ ! -f "config/.env" ]; then
        error "config/.env 파일이 없습니다. config/.env.example을 복사하고 값을 채워주세요.\n  cp config/.env.example config/.env"
    fi
    # 필수 변수 확인
    source config/.env 2>/dev/null || true
    [ -z "$GEMINI_API_KEY" ]  && error "GEMINI_API_KEY가 config/.env에 없습니다."
    [ -z "$JWT_SECRET_KEY" ]  && error "JWT_SECRET_KEY가 config/.env에 없습니다."
    [ -z "$ENCRYPTION_KEY" ]  && error "ENCRYPTION_KEY가 config/.env에 없습니다."
    log "환경 변수 확인 완료"
}

# SSL 자체 서명 인증서 생성 (개발/테스트용)
cmd_ssl_self_signed() {
    log "자체 서명 SSL 인증서 생성 (테스트용)..."
    mkdir -p nginx/ssl
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout nginx/ssl/privkey.pem \
        -out nginx/ssl/fullchain.pem \
        -subj "/C=KR/ST=Seoul/L=Seoul/O=GlowSeoul/CN=localhost"
    log "인증서 생성 완료: nginx/ssl/"
    warn "운영 환경에서는 Let's Encrypt 인증서를 사용하세요."
}

# Let's Encrypt 인증서 발급 (운영용)
cmd_ssl_letsencrypt() {
    read -p "도메인명 입력 (예: bot.yourdomain.com): " DOMAIN
    [ -z "$DOMAIN" ] && error "도메인을 입력해주세요."
    read -p "이메일 입력: " EMAIL
    [ -z "$EMAIL" ] && error "이메일을 입력해주세요."

    log "Let's Encrypt 인증서 발급: $DOMAIN"
    docker run --rm -p 80:80 \
        -v "$(pwd)/nginx/ssl:/etc/letsencrypt/live/$DOMAIN" \
        certbot/certbot certonly \
        --standalone --agree-tos --no-eff-email \
        -m "$EMAIL" -d "$DOMAIN"
    log "인증서 발급 완료"
}

# 빌드
cmd_build() {
    check_env
    log "Docker 이미지 빌드 중..."
    docker compose build --no-cache
    log "빌드 완료"
}

# 시작
cmd_start() {
    check_env
    # SSL 인증서 확인
    if [ ! -f "nginx/ssl/fullchain.pem" ] || [ ! -f "nginx/ssl/privkey.pem" ]; then
        warn "SSL 인증서가 없습니다. 자체 서명 인증서를 생성합니다."
        cmd_ssl_self_signed
    fi
    log "서비스 시작..."
    docker compose up -d
    log "시작 완료!"
    echo ""
    echo "  웹 챗봇:  https://localhost"
    echo "  API 문서: https://localhost/docs"
    echo "  로그:     ./deploy.sh logs"
}

# 중지
cmd_stop() {
    log "서비스 중지..."
    docker compose down
    log "중지 완료"
}

# 재시작
cmd_restart() {
    cmd_stop
    cmd_start
}

# 로그
cmd_logs() {
    SERVICE="${2:-app}"
    docker compose logs -f "$SERVICE"
}

# 상태
cmd_status() {
    docker compose ps
}

# 업데이트 (git pull + 재빌드 + 재시작)
cmd_update() {
    log "최신 코드 가져오기..."
    git pull
    cmd_build
    log "서비스 재시작..."
    docker compose up -d --force-recreate
    log "업데이트 완료"
}

# 명령 분기
case "${1:-help}" in
    start)        cmd_start ;;
    stop)         cmd_stop ;;
    restart)      cmd_restart ;;
    build)        cmd_build ;;
    logs)         cmd_logs "$@" ;;
    status)       cmd_status ;;
    update)       cmd_update ;;
    ssl-test)     cmd_ssl_self_signed ;;
    ssl-prod)     cmd_ssl_letsencrypt ;;
    *)
        echo "사용법: ./deploy.sh [명령]"
        echo ""
        echo "  start       서비스 시작 (SSL 없으면 자동 생성)"
        echo "  stop        서비스 중지"
        echo "  restart     재시작"
        echo "  build       Docker 이미지 빌드"
        echo "  logs [app|nginx]  로그 보기 (기본: app)"
        echo "  status      서비스 상태 확인"
        echo "  update      코드 업데이트 + 재빌드 + 재시작"
        echo "  ssl-test    자체 서명 SSL 인증서 생성 (테스트용)"
        echo "  ssl-prod    Let's Encrypt 인증서 발급 (운영용)"
        ;;
esac
