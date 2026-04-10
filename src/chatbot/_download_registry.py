"""
다운로드 파일 소유권 추적 레지스트리.

app.py와 handlers.py 양쪽에서 임포트 가능한 공유 모듈.
원형 임포트 방지를 위해 분리.
"""

import threading
import uuid
from datetime import datetime
from pathlib import Path

_tokens: dict[str, dict] = {}
_lock = threading.Lock()
_TOKEN_TTL = 86400  # 24시간


def register(file_path: str, gw_id: str) -> str:
    """파일에 대한 다운로드 토큰 발급 (소유자 gw_id 포함)"""
    token = str(uuid.uuid4())
    with _lock:
        _tokens[token] = {
            "path": str(file_path),
            "gw_id": gw_id,
            "created": datetime.now(),
        }
    return token


def validate(token: str, gw_id: str) -> str | None:
    """
    토큰 검증 후 파일 경로 반환 (실패 시 None).
    - 토큰 미존재: None
    - TTL 만료: None (토큰 삭제)
    - gw_id 불일치: None
    """
    now = datetime.now()
    with _lock:
        info = _tokens.get(token)
        if not info:
            return None
        if (now - info["created"]).total_seconds() > _TOKEN_TTL:
            _tokens.pop(token, None)
            return None
        if info["gw_id"] != gw_id:
            return None
        return info["path"]


def cleanup_expired():
    """만료된 토큰 일괄 정리"""
    now = datetime.now()
    with _lock:
        expired = [
            t for t, info in _tokens.items()
            if (now - info["created"]).total_seconds() > _TOKEN_TTL
        ]
        for t in expired:
            _tokens.pop(t, None)
