"""
공용 테스트 fixture
- 임시 DB, 환경변수, 테스트용 Fernet 키 등
"""

import os
import tempfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet


# ── 테스트용 환경변수 (실제 .env 로딩 차단) ──

TEST_JWT_SECRET = "test_jwt_secret_key_for_unit_tests_only"
TEST_FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch, tmp_path):
    """모든 테스트에서 환경변수를 테스트용으로 덮어쓰기"""
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_FERNET_KEY)
    # GW TLS 검증 비활성화 (테스트 환경)
    monkeypatch.setenv("GW_SKIP_TLS_VERIFY", "true")


@pytest.fixture
def tmp_db_path(tmp_path):
    """임시 SQLite DB 경로 반환"""
    return tmp_path / "test.db"


@pytest.fixture
def fernet():
    """테스트용 Fernet 인스턴스"""
    return Fernet(TEST_FERNET_KEY.encode())
