"""
FastAPI 인증 통합 테스트
- 로그인/로그아웃 플로우
- JWT 쿠키 기반 인증 미들웨어
- 보호된 엔드포인트 접근 제어
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def user_db_setup(tmp_path, monkeypatch):
    """user_db를 임시 DB로 격리"""
    import src.auth.user_db as udb
    monkeypatch.setattr(udb, "_db_initialized", False)
    monkeypatch.setattr(udb, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(udb, "DATA_DIR", tmp_path)
    # 테스트 사용자 등록
    udb.register("testuser", "testpw123", "테스트유저", "사원")
    return udb


@pytest.fixture
def chat_db_setup(tmp_path, monkeypatch):
    """chat_db를 임시 DB로 격리"""
    import src.chatbot.chat_db as cdb
    monkeypatch.setattr(cdb, "_db_initialized", False)
    monkeypatch.setattr(cdb, "DB_PATH", tmp_path / "chat.db")
    monkeypatch.setattr(cdb, "DATA_DIR", tmp_path)
    return cdb


@pytest.fixture
def fund_db_setup(tmp_path, monkeypatch):
    """fund_db를 임시 DB로 격리"""
    import src.fund_table.db as fdb
    monkeypatch.setattr(fdb, "_db_initialized", False)
    monkeypatch.setattr(fdb, "DB_PATH", tmp_path / "fund.db")
    monkeypatch.setattr(fdb, "DATA_DIR", tmp_path)
    return fdb


@pytest.fixture
def client(user_db_setup, chat_db_setup, fund_db_setup, monkeypatch):
    """FastAPI TestClient (GW 실제 연동 차단)"""
    # Playwright/GW 로그인을 모킹
    monkeypatch.setenv("ADMIN_GW_IDS", "testuser")

    from src.chatbot.app import app
    return TestClient(app)


# ─────────────────────────────────────────
# 로그인/로그아웃
# ─────────────────────────────────────────

class TestLoginFlow:
    def test_login_success(self, client):
        """정상 로그인 → JWT 쿠키 설정"""
        resp = client.post("/auth/login", json={"gw_id": "testuser", "gw_pw": "testpw123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "로그인 성공"
        assert data["user"]["gw_id"] == "testuser"
        # 쿠키에 auth_token이 설정되어야 함
        assert "auth_token" in resp.cookies

    def test_login_wrong_password(self, client):
        """잘못된 비밀번호 → 401"""
        resp = client.post("/auth/login", json={"gw_id": "testuser", "gw_pw": "wrongpw"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        """존재하지 않는 사용자 → 401"""
        resp = client.post("/auth/login", json={"gw_id": "nobody", "gw_pw": "pw"})
        assert resp.status_code == 401

    def test_logout(self, client):
        """로그아웃 → 쿠키 제거"""
        # 먼저 로그인
        client.post("/auth/login", json={"gw_id": "testuser", "gw_pw": "testpw123"})
        # 로그아웃
        resp = client.post("/auth/logout")
        assert resp.status_code == 200


# ─────────────────────────────────────────
# 보호된 엔드포인트
# ─────────────────────────────────────────

class TestProtectedEndpoints:
    def _login(self, client):
        """로그인 후 쿠키 설정된 client 반환"""
        client.post("/auth/login", json={"gw_id": "testuser", "gw_pw": "testpw123"})
        return client

    def test_me_authenticated(self, client):
        """인증된 사용자 → /auth/me 성공"""
        self._login(client)
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["gw_id"] == "testuser"

    def test_me_unauthenticated(self, client):
        """미인증 → /auth/me 실패"""
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_sessions_authenticated(self, client):
        """인증된 사용자 → 세션 목록 조회"""
        self._login(client)
        resp = client.get("/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_sessions_unauthenticated(self, client):
        """미인증 → 세션 목록 조회 실패"""
        resp = client.get("/sessions")
        assert resp.status_code == 401
