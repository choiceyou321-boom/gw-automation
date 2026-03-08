"""
그룹웨어 로그인 및 세션 관리 모듈
- Playwright 기반 브라우저 자동화
- 세션 저장/복원으로 반복 로그인 회피
"""

import os
import json
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from dotenv import load_dotenv

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

# .env 로드
load_dotenv(CONFIG_DIR / ".env")

# 로깅 설정
LOGS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "gw-automation.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("auth")

# 설정값
GW_URL = os.getenv("GW_URL", "https://gw.glowseoul.co.kr")
GW_USER_ID = os.getenv("GW_USER_ID")
GW_USER_PW = os.getenv("GW_USER_PW")
SESSION_FILE = DATA_DIR / "session_state.json"


def _ensure_dirs():
    """필요한 디렉토리 생성"""
    DATA_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)


def _get_session_file(user_id: str = None) -> Path:
    """사용자별 세션 파일 경로 반환"""
    if user_id:
        sessions_dir = DATA_DIR / "sessions"
        sessions_dir.mkdir(exist_ok=True)
        return sessions_dir / f"session_{user_id}.json"
    return SESSION_FILE  # 기존 호환


def login_and_get_context(
    playwright_instance=None,
    headless: bool = True,
    user_id: str = None,
    user_pw: str = None,
) -> tuple[Browser, BrowserContext, Page]:
    """
    그룹웨어에 로그인하고 (browser, context, page) 튜플 반환.
    저장된 세션이 있으면 복원 시도 → 실패 시 재로그인.

    user_id, user_pw: 지정 시 해당 사용자로 로그인. None이면 .env 기본값.
    """
    _ensure_dirs()

    # 로그인 계정 결정
    login_id = user_id or GW_USER_ID
    login_pw = user_pw or GW_USER_PW
    session_file = _get_session_file(user_id)

    if playwright_instance is None:
        pw = sync_playwright().start()
    else:
        pw = playwright_instance

    browser = pw.chromium.launch(headless=headless)

    # 세션 복원 시도
    if session_file.exists():
        logger.info(f"저장된 세션으로 복원 시도... ({login_id})")
        try:
            context = browser.new_context(storage_state=str(session_file))
            page = context.new_page()
            page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 로그인 상태 확인 - 로그인 페이지로 리다이렉트 안 되면 성공
            if "/login" not in page.url.lower() and _check_logged_in(page):
                logger.info(f"세션 복원 성공 ({login_id})")
                return browser, context, page
            else:
                logger.info("세션 만료, 재로그인 필요")
                page.close()
                context.close()
        except Exception as e:
            logger.warning(f"세션 복원 실패: {e}")

    # 새로 로그인
    context = browser.new_context()
    page = context.new_page()
    _do_login(page, login_id=login_id, login_pw=login_pw)

    # 세션 저장
    context.storage_state(path=str(session_file))
    logger.info(f"세션 저장 완료 ({login_id})")

    return browser, context, page


def _dump_page_debug(page: Page, label: str):
    """디버그용: 스크린샷 + input 요소 정보 저장"""
    try:
        DATA_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(DATA_DIR / f"debug_{label}.png"))
        # 페이지 내 모든 input 요소 정보 수집
        inputs_info = page.evaluate("""() => {
            const inputs = document.querySelectorAll('input');
            return Array.from(inputs).map(el => ({
                id: el.id,
                name: el.name,
                type: el.type,
                placeholder: el.placeholder,
                disabled: el.disabled,
                visible: el.offsetParent !== null,
                value: el.value,
                className: el.className,
            }));
        }""")
        logger.info(f"[{label}] 페이지 input 요소들: {json.dumps(inputs_info, ensure_ascii=False, indent=2)}")
        # 파일로도 저장
        with open(DATA_DIR / f"debug_{label}_inputs.json", "w", encoding="utf-8") as f:
            json.dump(inputs_info, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"디버그 정보 수집 실패: {e}")


def _do_login(page: Page, login_id: str = None, login_pw: str = None):
    """
    실제 로그인 수행
    더존 Amaranth10 로그인 구조:
    - #reqCompCd: 회사코드 (disabled, 'glowseoul' 사전입력)
    - #reqLoginId: 아이디 입력
    - #reqLoginPw: 비밀번호 입력
    - 아이디 입력 후 엔터 → 비밀번호 화면 전환될 수 있음
    """
    # 로그인 계정 결정
    uid = login_id or GW_USER_ID
    upw = login_pw or GW_USER_PW

    logger.info(f"로그인 시작: {GW_URL} (user={uid})")
    page.goto(f"{GW_URL}/#/login", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # Step 1: 아이디 입력
    id_input = page.locator("#reqLoginId")
    try:
        id_input.wait_for(state="visible", timeout=5000)
    except Exception:
        _dump_page_debug(page, "id_not_found")
        raise RuntimeError("ID 입력 필드(#reqLoginId)를 찾을 수 없습니다")

    id_input.fill(uid)
    logger.info(f"ID 입력 완료: {uid}")

    # 아이디 입력 후 엔터 (2단계 로그인: 엔터 치면 PW 화면으로 전환)
    id_input.press("Enter")
    page.wait_for_timeout(2000)

    # Step 2: 비밀번호 입력
    pw_input = page.locator("#reqLoginPw")
    try:
        pw_input.wait_for(state="visible", timeout=5000)
    except Exception:
        # 폴백: type=password 셀렉터
        pw_input = page.locator('input[type="password"]').first
        try:
            pw_input.wait_for(state="visible", timeout=3000)
        except Exception:
            _dump_page_debug(page, "pw_not_found")
            raise RuntimeError("PW 입력 필드를 찾을 수 없습니다")

    pw_input.fill(upw)
    logger.info("PW 입력 완료")

    # 비밀번호 입력 후 엔터로 로그인
    pw_input.press("Enter")

    # 로그인 완료 대기
    page.wait_for_timeout(5000)

    if _check_logged_in(page):
        logger.info(f"로그인 성공! (user={uid})")
    else:
        _dump_page_debug(page, "login_failed")
        raise RuntimeError("로그인 실패 - data/debug_login_failed.png 확인")


def _find_element(page: Page, selectors: list[str], must_be_enabled: bool = True):
    """여러 셀렉터 중 첫 번째 매칭 요소 반환 (disabled 요소 건너뜀)"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1000):
                if must_be_enabled and not el.is_enabled(timeout=500):
                    logger.info(f"셀렉터 '{sel}' → 찾았지만 disabled, 건너뜀")
                    continue
                logger.info(f"셀렉터 '{sel}' → 매칭 성공")
                return el
        except Exception:
            continue
    return None


def _find_enabled_text_input(page: Page):
    """JS로 enabled 상태인 text input을 직접 찾기"""
    try:
        idx = page.evaluate("""() => {
            const inputs = document.querySelectorAll('input[type="text"]');
            for (let i = 0; i < inputs.length; i++) {
                if (!inputs[i].disabled && inputs[i].id !== 'reqCompCd') {
                    return i;
                }
            }
            return -1;
        }""")
        if idx >= 0:
            return page.locator('input[type="text"]').nth(idx)
    except Exception as e:
        logger.warning(f"JS text input 탐색 실패: {e}")
    return None


def _check_logged_in(page: Page) -> bool:
    """로그인 상태 확인"""
    url = page.url.lower()
    # 로그인 페이지가 아니면 성공으로 판단
    if "/login" in url:
        return False
    # 메인 페이지 요소 확인
    try:
        # 일반적인 GNB/사용자 정보 영역 확인
        page.locator(".user-info, .gnb, .lnb, .main-content, #app").first.wait_for(
            timeout=3000
        )
        return True
    except Exception:
        return False  # 확인 실패 시 로그인 안 된 것으로 처리


def close_session(browser: Browser):
    """브라우저 세션 종료"""
    try:
        browser.close()
        logger.info("브라우저 세션 종료")
    except Exception as e:
        logger.warning(f"세션 종료 중 오류: {e}")
