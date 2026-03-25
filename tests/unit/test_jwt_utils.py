"""
jwt_utils.py 유닛 테스트
- JWT 토큰 생성/검증
- 만료 처리
- 잘못된 토큰 처리
"""

import time
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

import jwt
import pytest


@pytest.fixture
def jwt_mod(monkeypatch):
    """JWT 모듈을 테스트 시크릿으로 로드"""
    # jwt_utils는 import 시점에 JWT_SECRET을 검증하므로
    # conftest에서 이미 환경변수 설정됨
    import importlib
    import src.auth.jwt_utils as mod
    # 모듈 리로드로 테스트 시크릿 적용
    monkeypatch.setattr(mod, "JWT_SECRET", "test_jwt_secret_key_for_unit_tests_only")
    return mod


class TestCreateToken:
    def test_create_token_returns_string(self, jwt_mod):
        """토큰 생성 시 문자열 반환"""
        token = jwt_mod.create_token("testuser", "테스트유저")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_token_payload(self, jwt_mod):
        """토큰 payload에 gw_id, name 포함"""
        token = jwt_mod.create_token("testuser", "테스트유저")
        payload = jwt.decode(token, "test_jwt_secret_key_for_unit_tests_only", algorithms=["HS256"])
        assert payload["gw_id"] == "testuser"
        assert payload["name"] == "테스트유저"
        assert "exp" in payload
        assert "iat" in payload

    def test_create_token_expiry(self, jwt_mod):
        """토큰 만료 시간이 24시간 후"""
        token = jwt_mod.create_token("user", "유저")
        payload = jwt.decode(token, "test_jwt_secret_key_for_unit_tests_only", algorithms=["HS256"])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        # 만료 시간이 23~25시간 사이인지 확인
        delta = exp - now
        assert timedelta(hours=23) < delta < timedelta(hours=25)


class TestVerifyToken:
    def test_verify_valid_token(self, jwt_mod):
        """유효한 토큰 검증 성공"""
        token = jwt_mod.create_token("testuser", "테스트유저")
        payload = jwt_mod.verify_token(token)
        assert payload is not None
        assert payload["gw_id"] == "testuser"
        assert payload["name"] == "테스트유저"

    def test_verify_expired_token(self, jwt_mod):
        """만료된 토큰 → None"""
        # 이미 만료된 토큰 직접 생성
        payload = {
            "gw_id": "expireduser",
            "name": "만료유저",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=25),
        }
        token = jwt.encode(payload, "test_jwt_secret_key_for_unit_tests_only", algorithm="HS256")
        result = jwt_mod.verify_token(token)
        assert result is None

    def test_verify_invalid_token(self, jwt_mod):
        """잘못된 토큰 → None"""
        result = jwt_mod.verify_token("invalid.token.string")
        assert result is None

    def test_verify_wrong_secret(self, jwt_mod):
        """다른 시크릿으로 서명된 토큰 → None"""
        payload = {
            "gw_id": "user",
            "name": "유저",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, "wrong_secret_key", algorithm="HS256")
        result = jwt_mod.verify_token(token)
        assert result is None

    def test_verify_empty_token(self, jwt_mod):
        """빈 토큰 → None"""
        result = jwt_mod.verify_token("")
        assert result is None

    def test_verify_none_like_token(self, jwt_mod):
        """None-like 토큰 → None"""
        result = jwt_mod.verify_token("null")
        assert result is None
