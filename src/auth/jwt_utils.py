"""
JWT 토큰 유틸리티
- 챗봇 로그인 세션 관리용 (GW 인증과는 별개)
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / "config" / ".env")

logger = logging.getLogger("jwt_utils")

# JWT 설정
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET 환경변수가 설정되지 않았습니다. "
        "config/.env 파일에 JWT_SECRET=<랜덤문자열>을 추가해주세요. "
        "생성 예시: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24


def create_token(gw_id: str, name: str) -> str:
    """JWT 토큰 생성 (24시간 만료)"""
    payload = {
        "gw_id": gw_id,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict | None:
    """
    JWT 토큰 검증.
    유효하면 payload dict, 아니면 None.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT 만료")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"JWT 검증 실패: {e}")
        return None
