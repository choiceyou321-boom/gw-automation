"""
공용 인증 미들웨어
- JWT 쿠키 기반 사용자 인증
- app.py, routes.py 등에서 공통 사용
"""

from fastapi import HTTPException, Request


def get_current_user(request: Request) -> dict | None:
    """JWT 쿠키에서 현재 사용자 정보 추출. 미인증이면 None."""
    from src.auth.jwt_utils import verify_token
    from src.auth.user_db import get_user

    token = request.cookies.get("auth_token")
    if not token:
        return None

    payload = verify_token(token)
    if not payload:
        return None

    user = get_user(payload["gw_id"])
    return user


def require_auth(request: Request) -> dict:
    """인증 필수. 미인증이면 401 에러."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user
