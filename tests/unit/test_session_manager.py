"""
session_manager.py 유닛 테스트
- 캐시 TTL 검증
- 캐시 hit/miss/eviction
- 스레드 안전성
"""

import time
import threading
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

import pytest


@pytest.fixture(autouse=True)
def reset_cache():
    """매 테스트마다 캐시 초기화"""
    from src.auth.session_manager import _session_cache, _cache_lock
    with _cache_lock:
        _session_cache.clear()
    yield
    with _cache_lock:
        _session_cache.clear()


@pytest.fixture
def sm():
    """session_manager 모듈"""
    import src.auth.session_manager as mod
    return mod


# ─────────────────────────────────────────
# CachedSession 테스트
# ─────────────────────────────────────────

class TestCachedSession:
    def test_is_valid_fresh(self, sm):
        """방금 생성된 세션은 유효"""
        session = sm.CachedSession(
            oauth_token="token", sign_key="key",
            cookies={}, created_at=time.time()
        )
        assert sm._is_valid(session) is True

    def test_is_valid_expired(self, sm):
        """TTL 초과 세션은 무효"""
        session = sm.CachedSession(
            oauth_token="token", sign_key="key",
            cookies={}, created_at=time.time() - sm.CACHE_TTL - 1
        )
        assert sm._is_valid(session) is False


# ─────────────────────────────────────────
# 캐시 조회 테스트
# ─────────────────────────────────────────

class TestCacheOperations:
    def test_get_cached_session_miss(self, sm):
        """캐시 미스 → None"""
        assert sm.get_cached_session("unknown_user") is None

    def test_get_cached_session_hit(self, sm):
        """캐시 히트"""
        session = sm.CachedSession(
            oauth_token="test_token", sign_key="test_key",
            cookies={"a": "b"}, created_at=time.time()
        )
        with sm._cache_lock:
            sm._session_cache["testuser"] = session

        result = sm.get_cached_session("testuser")
        assert result is not None
        assert result.oauth_token == "test_token"

    def test_get_cached_session_expired_eviction(self, sm):
        """만료된 캐시 → 자동 삭제 후 None"""
        session = sm.CachedSession(
            oauth_token="old_token", sign_key="old_key",
            cookies={}, created_at=time.time() - sm.CACHE_TTL - 100
        )
        with sm._cache_lock:
            sm._session_cache["testuser"] = session

        result = sm.get_cached_session("testuser")
        assert result is None
        # 캐시에서 제거되었는지 확인
        with sm._cache_lock:
            assert "testuser" not in sm._session_cache

    def test_invalidate_cache(self, sm):
        """특정 사용자 캐시 삭제"""
        session = sm.CachedSession(
            oauth_token="token", sign_key="key",
            cookies={}, created_at=time.time()
        )
        with sm._cache_lock:
            sm._session_cache["testuser"] = session

        sm.invalidate_cache("testuser")
        assert sm.get_cached_session("testuser") is None

    def test_invalidate_nonexistent(self, sm):
        """존재하지 않는 캐시 삭제 시 에러 없음"""
        sm.invalidate_cache("nobody")  # 에러 없이 통과

    def test_clear_all_cache(self, sm):
        """전체 캐시 초기화"""
        for i in range(5):
            session = sm.CachedSession(
                oauth_token=f"token{i}", sign_key=f"key{i}",
                cookies={}, created_at=time.time()
            )
            with sm._cache_lock:
                sm._session_cache[f"user{i}"] = session

        sm.clear_all_cache()
        with sm._cache_lock:
            assert len(sm._session_cache) == 0


# ─────────────────────────────────────────
# 스레드 안전성 테스트
# ─────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_cache_access(self, sm):
        """다수 스레드에서 동시 캐시 접근 → 데이터 손상 없음"""
        errors = []

        def writer(user_id):
            try:
                session = sm.CachedSession(
                    oauth_token=f"token_{user_id}",
                    sign_key=f"key_{user_id}",
                    cookies={}, created_at=time.time()
                )
                with sm._cache_lock:
                    sm._session_cache[user_id] = session
                # 즉시 조회
                result = sm.get_cached_session(user_id)
                if result is None:
                    errors.append(f"{user_id}: 저장 직후 조회 실패")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(f"user_{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"스레드 안전성 실패: {errors}"
