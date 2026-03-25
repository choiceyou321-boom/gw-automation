"""
handlers.py 멀티유저 Lock 테스트
- _get_user_lock 동일 gw_id → 동일 Lock
- 다른 gw_id → 다른 Lock
- 스레드 안전성
"""

import threading

import pytest


@pytest.fixture(autouse=True)
def reset_locks():
    """매 테스트마다 Lock 딕셔너리 초기화"""
    from src.chatbot import handlers as mod
    mod._user_locks.clear()
    yield
    mod._user_locks.clear()


@pytest.fixture
def get_lock():
    """_get_user_lock 함수"""
    from src.chatbot.handlers import _get_user_lock
    return _get_user_lock


# ─────────────────────────────────────────
# Lock 반환 테스트
# ─────────────────────────────────────────

class TestGetUserLock:
    def test_same_id_same_lock(self, get_lock):
        """같은 gw_id에 대해 동일 Lock 반환"""
        lock1 = get_lock("tgjeon")
        lock2 = get_lock("tgjeon")
        assert lock1 is lock2

    def test_different_id_different_lock(self, get_lock):
        """다른 gw_id에 대해 다른 Lock 반환"""
        lock_a = get_lock("user_a")
        lock_b = get_lock("user_b")
        assert lock_a is not lock_b

    def test_returns_threading_lock(self, get_lock):
        """반환 타입이 threading.Lock"""
        lock = get_lock("testuser")
        assert isinstance(lock, type(threading.Lock()))

    def test_lock_is_functional(self, get_lock):
        """Lock이 실제 잠금/해제 동작"""
        lock = get_lock("testuser")
        assert lock.acquire(blocking=False) is True
        # 이미 잠긴 상태에서 non-blocking acquire → False
        assert lock.acquire(blocking=False) is False
        lock.release()
        # 해제 후 다시 acquire 가능
        assert lock.acquire(blocking=False) is True
        lock.release()


# ─────────────────────────────────────────
# 스레드 안전성 테스트
# ─────────────────────────────────────────

class TestLockThreadSafety:
    def test_concurrent_get_lock(self, get_lock):
        """여러 스레드에서 동시에 같은 gw_id로 Lock 요청 → 모두 동일 Lock"""
        results = []
        errors = []

        def worker():
            try:
                lock = get_lock("shared_user")
                results.append(id(lock))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"스레드 안전성 실패: {errors}"
        # 모든 스레드가 같은 Lock 인스턴스를 받았는지 확인
        assert len(set(results)) == 1
