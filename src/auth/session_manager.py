"""
GW 세션 관리자
- 사용자별 oAuthToken/signKey 인메모리 캐시 (TTL 2시간)
- 캐시 미스 시 Playwright 로그인 → 쿠키 추출 → 캐시
- create_api(gw_id) → 해당 사용자의 MeetingRoomAPI 인스턴스 반환
"""
from __future__ import annotations

import time
import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger("session_manager")

# 캐시 TTL: 2시간
CACHE_TTL = 2 * 60 * 60


@dataclass
class CachedSession:
    """캐시된 GW 세션 정보"""
    oauth_token: str
    sign_key: str
    cookies: dict
    created_at: float


# 사용자별 세션 캐시 {gw_id: CachedSession} + 스레드 안전 Lock
_session_cache: dict[str, CachedSession] = {}
_cache_lock = threading.Lock()

# 사용자별 로그인 Lock — 동일 사용자의 동시 Playwright 로그인 방지
_login_locks: dict[str, threading.Lock] = {}
_login_locks_guard = threading.Lock()


def _is_valid(session: CachedSession) -> bool:
    """캐시가 아직 유효한지 확인"""
    return (time.time() - session.created_at) < CACHE_TTL


def get_cached_session(gw_id: str) -> CachedSession | None:
    """캐시된 세션 반환. 만료되었으면 None."""
    with _cache_lock:
        session = _session_cache.get(gw_id)
        if session and _is_valid(session):
            logger.info(f"세션 캐시 히트: {gw_id}")
            return session
        if session:
            logger.info(f"세션 캐시 만료: {gw_id}")
            del _session_cache[gw_id]
        return None


def _login_and_cache(gw_id: str, gw_pw: str) -> CachedSession:
    """Playwright 로그인 → 쿠키 추출 → 캐시에 저장"""
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.meeting.reservation_api import _extract_auth_cookies

    logger.info(f"GW 로그인 시작: {gw_id}")

    pw = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )
        oauth_token, sign_key, cookie_dict = _extract_auth_cookies(context)
        close_session(browser)
    finally:
        pw.stop()

    cached = CachedSession(
        oauth_token=oauth_token,
        sign_key=sign_key,
        cookies=cookie_dict,
        created_at=time.time(),
    )
    with _cache_lock:
        _session_cache[gw_id] = cached
    logger.info(f"세션 캐시 저장: {gw_id}")
    return cached


def create_api(gw_id: str, company_info: dict = None):
    """
    사용자의 MeetingRoomAPI 인스턴스 생성.
    캐시 히트 시 기존 세션 사용, 미스 시 Playwright 로그인.

    반환: (api, cleanup)
    """
    from src.auth.user_db import get_decrypted_password, get_company_info
    from src.meeting.reservation_api import MeetingRoomAPI

    # 캐시 확인 (Lock 밖에서 먼저 체크 — 캐시 히트 시 Lock 불필요)
    session = get_cached_session(gw_id)
    if not session:
        # per-user Lock으로 동시 Playwright 로그인 방지
        with _login_locks_guard:
            if gw_id not in _login_locks:
                _login_locks[gw_id] = threading.Lock()
            login_lock = _login_locks[gw_id]
        with login_lock:
            # Lock 획득 후 다시 캐시 확인 (다른 스레드가 이미 로그인했을 수 있음)
            session = get_cached_session(gw_id)
            if not session:
                gw_pw = get_decrypted_password(gw_id)
                if not gw_pw:
                    raise RuntimeError(f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다.")
                session = _login_and_cache(gw_id, gw_pw)

    # companyInfo 결정
    if company_info is None:
        company_info = get_company_info(gw_id)

    api = MeetingRoomAPI(
        oauth_token=session.oauth_token,
        sign_key=session.sign_key,
        cookies=session.cookies,
        company_info=company_info,
    )
    # 세션 재인증에 필요한 gw_id 주입
    api._gw_id = gw_id

    def cleanup():
        api.close()

    return api, cleanup


def refresh_session(gw_id: str) -> CachedSession:
    """
    캐시 무효화 후 재로그인하여 새 세션 반환 (public API).
    reservation_api._refresh_session() 등 외부에서 사용.
    """
    from src.auth.user_db import get_decrypted_password
    invalidate_cache(gw_id)
    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        raise RuntimeError(f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다.")
    return _login_and_cache(gw_id, gw_pw)


def invalidate_cache(gw_id: str):
    """특정 사용자 캐시 삭제"""
    with _cache_lock:
        if gw_id in _session_cache:
            del _session_cache[gw_id]
            logger.info(f"세션 캐시 삭제: {gw_id}")


def clear_all_cache():
    """전체 캐시 초기화"""
    with _cache_lock:
        _session_cache.clear()
    logger.info("전체 세션 캐시 초기화")
