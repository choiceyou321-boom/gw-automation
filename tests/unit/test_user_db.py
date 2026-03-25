"""
user_db.py 유닛 테스트
- Fernet 암호화/복호화
- 사용자 CRUD
- 결재선 설정 (approval_config)
"""

import sqlite3
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet


# ── DB 격리를 위한 fixture ──

@pytest.fixture
def user_db(tmp_path, monkeypatch):
    """격리된 user_db 모듈 (임시 DB 사용)"""
    # _db_initialized 리셋
    import src.auth.user_db as mod
    monkeypatch.setattr(mod, "_db_initialized", False)
    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    return mod


# ─────────────────────────────────────────
# Fernet 암호화 테스트
# ─────────────────────────────────────────

class TestFernet:
    def test_get_fernet_success(self, user_db):
        """ENCRYPTION_KEY가 있으면 Fernet 인스턴스 반환"""
        f = user_db._get_fernet()
        assert isinstance(f, Fernet)

    def test_get_fernet_missing_key(self, user_db, monkeypatch):
        """ENCRYPTION_KEY가 없으면 RuntimeError"""
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
            user_db._get_fernet()

    def test_encrypt_decrypt_roundtrip(self, user_db):
        """암호화 → 복호화 라운드트립"""
        f = user_db._get_fernet()
        original = "my_secret_password_123!"
        encrypted = f.encrypt(original.encode()).decode()
        decrypted = f.decrypt(encrypted.encode()).decode()
        assert decrypted == original
        assert encrypted != original


# ─────────────────────────────────────────
# 사용자 CRUD 테스트
# ─────────────────────────────────────────

class TestUserCRUD:
    def test_register_success(self, user_db):
        """정상 회원가입"""
        result = user_db.register("testuser", "password123", "테스트유저", "사원")
        assert result["success"] is True
        assert "완료" in result["message"]

    def test_register_duplicate(self, user_db):
        """중복 아이디 등록 실패"""
        user_db.register("testuser", "pw1", "유저1")
        result = user_db.register("testuser", "pw2", "유저2")
        assert result["success"] is False
        assert "이미 등록" in result["message"]

    def test_verify_login_success(self, user_db):
        """정상 로그인"""
        user_db.register("logintest", "correct_pw", "로그인테스트")
        result = user_db.verify_login("logintest", "correct_pw")
        assert result is not None
        assert result["gw_id"] == "logintest"
        assert result["name"] == "로그인테스트"

    def test_verify_login_wrong_password(self, user_db):
        """비밀번호 불일치 시 None"""
        user_db.register("logintest", "correct_pw", "유저")
        result = user_db.verify_login("logintest", "wrong_pw")
        assert result is None

    def test_verify_login_nonexistent_user(self, user_db):
        """존재하지 않는 사용자 로그인 시 None"""
        result = user_db.verify_login("nouser", "pw")
        assert result is None

    def test_get_user(self, user_db):
        """사용자 정보 조회"""
        user_db.register("getuser", "pw", "조회유저", "팀장")
        user = user_db.get_user("getuser")
        assert user["gw_id"] == "getuser"
        assert user["name"] == "조회유저"
        assert user["position"] == "팀장"

    def test_get_user_nonexistent(self, user_db):
        """존재하지 않는 사용자 조회 시 None"""
        assert user_db.get_user("nobody") is None

    def test_update_profile(self, user_db):
        """프로필 업데이트"""
        user_db.register("updateuser", "pw", "원래이름")
        result = user_db.update_profile("updateuser", name="새이름", position="과장")
        assert result["success"] is True

        user = user_db.get_user("updateuser")
        assert user["name"] == "새이름"
        assert user["position"] == "과장"

    def test_update_profile_disallowed_field(self, user_db):
        """허용되지 않은 필드는 무시"""
        user_db.register("updateuser", "pw", "이름")
        result = user_db.update_profile("updateuser", gw_pw_encrypted="hack")
        assert result["success"] is False

    def test_delete_user(self, user_db):
        """사용자 삭제"""
        user_db.register("deluser", "pw", "삭제유저")
        result = user_db.delete_user("deluser")
        assert result["success"] is True
        assert user_db.get_user("deluser") is None

    def test_delete_user_nonexistent(self, user_db):
        """존재하지 않는 사용자 삭제 시 실패"""
        result = user_db.delete_user("nobody")
        assert result["success"] is False

    def test_list_users(self, user_db):
        """전체 사용자 목록 조회"""
        user_db.register("user1", "pw1", "유저1")
        user_db.register("user2", "pw2", "유저2")
        users = user_db.list_users()
        assert len(users) == 2
        ids = [u["gw_id"] for u in users]
        assert "user1" in ids
        assert "user2" in ids

    def test_get_decrypted_password(self, user_db):
        """비밀번호 복호화 조회"""
        user_db.register("pwuser", "my_secret_pw", "비번유저")
        decrypted = user_db.get_decrypted_password("pwuser")
        assert decrypted == "my_secret_pw"

    def test_get_decrypted_password_nonexistent(self, user_db):
        """존재하지 않는 사용자 비밀번호 조회 시 None"""
        assert user_db.get_decrypted_password("nobody") is None


# ─────────────────────────────────────────
# 결재선 설정 테스트
# ─────────────────────────────────────────

class TestApprovalConfig:
    def test_get_empty_config(self, user_db):
        """설정 없는 사용자의 결재선 조회 → 빈 dict"""
        user_db.register("configuser", "pw", "설정유저")
        config = user_db.get_approval_config("configuser")
        assert config == {}

    def test_set_and_get_config(self, user_db):
        """결재선 설정 저장 후 조회"""
        user_db.register("configuser", "pw", "설정유저")
        config_data = {
            "default": {"agree": "신동관", "final": "최기영"},
            "간단": {"final": "최기영"},
        }
        result = user_db.set_approval_config("configuser", config_data)
        assert result["success"] is True

        loaded = user_db.get_approval_config("configuser")
        assert loaded["default"]["agree"] == "신동관"
        assert loaded["간단"]["final"] == "최기영"

    def test_set_config_nonexistent_user(self, user_db):
        """존재하지 않는 사용자에게 설정 저장 시 실패"""
        result = user_db.set_approval_config("nobody", {"default": {}})
        assert result["success"] is False

    def test_get_company_info(self, user_db):
        """companyInfo 반환"""
        user_db.register("compuser", "pw", "회사유저")
        user_db.update_profile("compuser", emp_seq="1234", dept_seq="5678")
        info = user_db.get_company_info("compuser")
        assert info["empSeq"] == "1234"
        assert info["deptSeq"] == "5678"
        assert info["compSeq"] == "1000"

    def test_get_company_info_nonexistent(self, user_db):
        """존재하지 않는 사용자의 companyInfo → 빈 dict"""
        info = user_db.get_company_info("nobody")
        assert info == {}
