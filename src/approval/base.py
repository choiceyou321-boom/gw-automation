"""
전자결재 자동화 -- 기본 클래스 + 공통 유틸
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional
from playwright.sync_api import Page, BrowserContext, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("approval_automation")

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# 스크린샷 저장 디렉토리
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 3  # 초


def _js_str(s) -> str:
    """Python 문자열을 JS 문자열 리터럴로 안전하게 변환 (인젝션 방지).
    json.dumps()로 따옴표/백슬래시/특수문자를 올바르게 이스케이프.
    반환값: "escaped_string" (큰따옴표 포함)
    """
    return json.dumps(str(s))

# OBTDataGrid React fiber 접근 JS 헬퍼
_GET_GRID_IFACE_JS = """
(() => {
    const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
    if (!el) return null;
    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
    if (!fk) return null;
    let f = el[fk];
    for (let i = 0; i < 3 && f; i++) f = f.return;
    if (!f || !f.stateNode || !f.stateNode.state) return null;
    return f.stateNode.state.interface || null;
})()
"""



def _save_debug(page: Page, name: str):
    """디버그용 스크린샷 저장"""
    try:
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 저장 실패: {e}")


def _parse_project_text(text: str) -> dict:
    """
    프로젝트 코드도움 드롭다운 텍스트를 파싱.

    형식 예: "GS-25-0088. [종로] 메디빌더 음향공사"
              "GS-25-0031. [단양] 고수동굴"

    Returns:
        {"code": "GS-25-0088", "name": "[종로] 메디빌더 음향공사", "full_text": "GS-25-0088. [종로] 메디빌더 음향공사"}
    """
    text = text.strip()
    # "코드. 이름" 형식 분리
    if ". " in text:
        parts = text.split(". ", 1)
        code = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
    else:
        code = ""
        name = text
    return {"code": code, "name": name, "full_text": text}





class ApprovalBaseMixin:
    """공통 유틸리티 메서드 (mixin)"""

    def __init__(self, page: Page, context: BrowserContext = None):
        self.page = page
        self.context = context
        # 다이얼로그 자동 수락 (한 번만 등록)
        page.on("dialog", lambda d: d.accept())

    # ─────────────────────────────────────────
    # 공통 유틸: 세션/팝업/검증
    # ─────────────────────────────────────────

    def _check_session_valid(self) -> bool:
        """세션이 유효한지 확인 (로그인 페이지로 리다이렉트 여부)"""
        try:
            url = self.page.url.lower()
            if "/login" in url:
                logger.error("세션 만료: 로그인 페이지로 리다이렉트됨")
                return False
            return True
        except Exception as e:
            logger.debug("세션 유효성 확인 실패: %s", e)
            return False

    def _dismiss_obt_alert(self):
        """
        OBTAlert 다이얼로그 닫기.
        OBTAlert_dimmed 오버레이가 열려 있으면 모든 클릭을 차단하므로
        자동화 시작 전에 반드시 처리해야 한다.

        GW는 모듈을 iframe 안에서 렌더링하므로, page.frames를 순회하여
        각 frame에서 frame.locator().click()으로 클릭한다.

        [중요] frame.locator().click() → Playwright이 프레임↔메인페이지 좌표 변환 자동 처리
               isTrusted=true 실제 브라우저 이벤트 → GW React 정상 처리
               JS getBoundingClientRect() 좌표 + page.mouse.click() → 프레임 로컬 좌표로 인한 오클릭
        """
        page = self.page
        # 방법 1: JS로 OBTPortal 내 버튼 직접 클릭 (overlay hit-test 우회)
        # OBTAlert_dimmed 자체가 클릭을 차단하므로 Playwright click 대신 JS 사용
        try:
            result = page.evaluate("""() => {
                const portals = document.querySelectorAll('[class*="OBTPortal"]');
                for (const portal of portals) {
                    const dimmed = portal.querySelector('[class*="OBTAlert_dimmed"], [class*="OBTAlert"][class*="dimmed"]');
                    if (!dimmed) continue;
                    // '취소'를 '확인'보다 먼저 시도: "이전 작성 중인 결의서" 알림에서
                    // "확인"(=이전 문서 불러오기) 대신 "취소"(=새 폼 시작)를 선택해야
                    // GW가 이전 임시저장 문서를 로딩하지 않고 overlay를 즉시 제거함
                    const targetTexts = ['저장안함', '취소', '닫기', 'OK', '확인'];
                    const btns = portal.querySelectorAll('button');
                    for (const t of targetTexts) {
                        for (const btn of btns) {
                            if (btn.textContent.trim() === t) {
                                btn.click();
                                return '클릭: ' + t;
                            }
                        }
                    }
                    // 폴백: 마지막 버튼
                    if (btns.length > 0) {
                        btns[btns.length - 1].click();
                        return '폴백클릭: ' + btns[btns.length - 1].textContent.trim();
                    }
                }
                return null;
            }""")
            if result:
                logger.info(f"OBTAlert JS 클릭 완료: {result}")
                # overlay가 실제로 DOM에서 제거될 때까지 대기 (최대 5초)
                try:
                    page.wait_for_selector(
                        '[class*="OBTAlert_dimmed"]',
                        state="detached",
                        timeout=5000,
                    )
                    logger.info("OBTAlert_dimmed 오버레이 제거 확인")
                except Exception:
                    # 이미 없거나 타임아웃 → 700ms 고정 대기 후 계속
                    page.wait_for_timeout(700)
                return
        except Exception as e:
            logger.debug(f"OBTAlert JS 처리 실패: {e}")

        # 방법 2: frame 순회 + Playwright click (force=True)
        try:
            for frame in page.frames:
                try:
                    alert_loc = frame.locator('[class*="OBTAlert"][class*="dimmed"]')
                    if alert_loc.count() == 0:
                        continue
                    logger.info(f"OBTAlert 감지(frame): url={frame.url[:80]}")
                    portal = frame.locator('[class*="OBTPortal"]')
                    for btn_text in ['저장안함', '확인', 'OK', '닫기']:
                        try:
                            btn = portal.locator(f'button:has-text("{btn_text}")').last
                            if btn.count() > 0 and btn.is_visible(timeout=500):
                                btn.click(timeout=2000, force=True)
                                page.wait_for_timeout(700)
                                logger.info(f"OBTAlert 버튼 클릭 완료: '{btn_text}'")
                                return
                        except Exception:
                            continue
                    try:
                        all_btns = portal.locator('button').all()
                        if all_btns:
                            all_btns[-1].click(timeout=2000, force=True)
                            page.wait_for_timeout(700)
                            logger.info("OBTAlert 폴백 버튼 클릭 완료")
                            return
                    except Exception:
                        pass
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"OBTAlert 처리 실패: {e}")

    def _close_popups(self):
        """열린 팝업 페이지 자동 닫기 + OBTAlert 오버레이 처리"""
        # OBTAlert dimmed 오버레이 먼저 처리 (모든 클릭을 차단하므로 최우선)
        self._dismiss_obt_alert()
        if not self.context:
            return
        try:
            main_page = self.page
            for p in self.context.pages:
                if p != main_page:
                    try:
                        p_url = p.url or ""
                        if "popup" in p_url or p_url == "about:blank":
                            p.close()
                            logger.debug(f"팝업 닫기: {p_url[:60]}")
                    except Exception:
                        pass
        except Exception:
            pass

    def _close_open_modals(self):
        """열린 OBTDialog/OBTDialog2 모달을 모두 닫기 (취소/닫기 버튼 또는 Escape 반복)
        - OBTDialog2_dialogRootOpen: 기존 모달
        - OBTDialog_dialogRoot open: invoice modal 등 OBTDialog 계열
        """
        page = self.page
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                # OBTDialog2 + OBTDialog(invoice modal) 모두 감지
                open_count = (
                    page.locator(".OBTDialog2_dialogRootOpen__3PExr").count()
                    + page.locator(".obtdialog.open").count()
                )
                if open_count == 0:
                    break
                logger.info(f"열린 모달 {open_count}개 감지 (시도 {attempt+1})")
                # 취소/닫기 버튼 찾기 (OBTDialog2 → OBTDialog 순)
                closed = False
                for sel in [
                    ".OBTDialog2_dialogRootOpen__3PExr button:has-text('취소')",
                    ".OBTDialog2_dialogRootOpen__3PExr button:has-text('닫기')",
                    ".OBTDialog2_dialogRootOpen__3PExr [class*='closeBtn']",
                    ".obtdialog.open button:has-text('취소')",
                    ".obtdialog.open button:has-text('닫기')",
                    ".obtdialog.open [class*='closeBtn']",
                ]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=500):
                            btn.click(force=True)
                            page.wait_for_timeout(500)
                            logger.info(f"모달 닫기: {sel}")
                            closed = True
                            break
                    except Exception:
                        continue
                if not closed:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                    logger.info("모달 Escape 키로 닫기")
            except Exception as e:
                logger.debug(f"모달 닫기 시도 {attempt+1} 실패: {e}")
                break

    def _validate_required_fields(self, data: dict, required_keys: list[str], form_name: str) -> Optional[dict]:
        """
        필수 필드 검증. 누락 시 에러 dict 반환, 통과 시 None.
        """
        missing = [k for k in required_keys if not data.get(k)]
        if missing:
            # 키 -> 한국어 라벨 변환
            label_map = {
                "title": "제목", "date": "지출일", "amount": "금액",
                "project": "프로젝트", "vendor_name": "거래처명",
                "work_date": "날짜", "reason": "사유",
                "destination": "방문처", "purpose": "사유/목적",
                "start_time": "시작시간", "end_time": "종료시간",
            }
            labels = [label_map.get(k, k) for k in missing]
            msg = f"{form_name} 작성에 필요한 정보가 부족합니다: {', '.join(labels)}"
            return {"success": False, "message": msg}
        return None

    # ─────────────────────────────────────────
    # 결재선 설정
    # ─────────────────────────────────────────

    def _navigate_to_approval_home(self):
        """전자결재 모듈 HOME으로 이동 (세션 확인 포함)"""
        page = self.page

        # 세션 만료 확인
        if not self._check_session_valid():
            raise RuntimeError("세션이 만료되었습니다.")

        # 로그인 직후 팝업이 열리는 시간 대기
        self.page.wait_for_timeout(2000)
        self._close_popups()

        navigated = False

        # 방법 1: 전자결재 모듈 아이콘 클릭 (span.module-link.EA)
        ea_link = page.locator("span.module-link.EA").first
        try:
            if ea_link.is_visible(timeout=5000):
                ea_link.click(force=True)
                logger.info("전자결재 모듈 클릭")
                page.wait_for_timeout(2000)
                # 네비게이션 직후 GW가 "작성 중인 문서 저장 여부" OBTAlert를 띄울 수 있음
                self._dismiss_obt_alert()
            else:
                raise PlaywrightTimeout("전자결재 모듈 링크 미발견")
        except Exception:
            # 폴백: GW 내부 탭에서 "전자결재" 클릭
            try:
                page.locator("text=전자결재").first.click(force=True)
                page.wait_for_timeout(2000)
                self._dismiss_obt_alert()
            except Exception:
                pass

        # 결재 HOME 확인 (span.tit 결재 HOME 또는 결재작성 버튼으로 판단)
        def _check_approval_home_loaded(timeout_ms: int = 15000) -> bool:
            """결재 HOME 로드 여부 확인 (OR 셀렉터 -- 단일 타임아웃)"""
            try:
                # Playwright OR 로케이터: 어느 하나라도 보이면 성공
                loc = page.locator(
                    "span.tit:has-text('결재 HOME'), "
                    "button:has-text('결재작성'), "
                    "span.OBTButton_labelText__1s2qO:has-text('결재작성')"
                ).first
                loc.wait_for(state="visible", timeout=timeout_ms)
                logger.info("전자결재 HOME 확인 (결재 HOME / 결재작성 버튼)")
                return True
            except Exception:
                pass
            # 폴백: text= 방식
            try:
                page.wait_for_selector("text=결재 HOME", timeout=min(timeout_ms // 2, 5000))
                logger.info("전자결재 HOME 확인 (text=결재 HOME)")
                return True
            except Exception:
                return False

        _save_debug(page, "00_after_ea_click")  # 디버그: EA 클릭 직후 스크린샷
        if _check_approval_home_loaded(30000):
            navigated = True
        else:
            if not self._check_session_valid():
                raise RuntimeError("세션이 만료되었습니다.")
            logger.warning(f"결재 HOME 텍스트 미발견 (방법 1) — 현재 URL: {page.url[:80]}")

        # 방법 2: GW 내부 탭 "전자결재" 클릭 (로그인 직후 HR 페이지에 있는 경우)
        if not navigated:
            try:
                tab_selectors = [
                    "li.tab-item:has-text('전자결재')",
                    "div.tab-item:has-text('전자결재')",
                    "li:has-text('전자결재')",
                ]
                for sel in tab_selectors:
                    try:
                        tab = page.locator(sel).first
                        if tab.is_visible(timeout=2000):
                            tab.click(force=True)
                            logger.info(f"GW 내부 탭 클릭: {sel}")
                            page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue

                if _check_approval_home_loaded(15000):
                    logger.info("결재 HOME 도달 (내부 탭 클릭)")
                    navigated = True
                else:
                    logger.warning("내부 탭 클릭 후에도 결재 HOME 미발견")
            except Exception:
                logger.warning("내부 탭 클릭 실패")

        # 방법 3: URL 직접 네비게이션 (확인된 전자결재 HOME URL: /#/EA/)
        if not navigated:
            try:
                approval_home_url = f"{GW_URL}/#/EA/"
                page.goto(approval_home_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                logger.info("전자결재 URL 직접 이동 (HPM0110)")
                if _check_approval_home_loaded(12000):
                    logger.info("결재 HOME 도달 (HPM0110 URL)")
                    navigated = True
                else:
                    logger.warning("HPM0110 URL 이동 후 결재 HOME 미발견")
            except Exception as e:
                logger.warning(f"HPM0110 URL 이동 실패: {e}")

        # 방법 4: 최후 폴백 -- 기존 해시 라우팅
        if not navigated:
            try:
                page.goto(f"{GW_URL}/#/app/approval", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                logger.info("전자결재 URL 직접 이동 (legacy 경로)")
                if _check_approval_home_loaded(8000):
                    navigated = True
            except Exception as e:
                logger.warning(f"legacy 경로 이동 실패: {e}")

        self._close_popups()
        _save_debug(page, "01_approval_home")

    def _click_write_approval(self):
        """결재작성 버튼 클릭 (결재 HOME -> 결재작성 페이지)"""
        page = self.page

        # 결재작성 버튼 (사이드바 상단 파란 버튼)
        for selector in [
            "button:has-text('결재작성')",
            "a:has-text('결재작성')",
            "div:has-text('결재작성') >> visible=true",
            "text=결재작성",
        ]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    btn.click(force=True)
                    logger.info("결재작성 버튼 클릭")
                    self.page.wait_for_timeout(1000)
                    return
            except Exception:
                continue

        logger.warning("결재작성 버튼 미발견, 현재 페이지에서 양식 검색 시도")


    def _wait_for_form_load(self):
        """양식 폼 로드 대기 (URL 변경 + input 요소 확인, 재시도 포함)"""
        page = self.page

        self._close_popups()

        # URL에 양식 페이지 포함될 때까지 대기 (APB1020=지출결의서 양식)
        # 주의: **/HP/** 패턴은 HPM0110(양식 선택 페이지)도 매칭하므로 APB1020 사용
        try:
            page.wait_for_url("**/APB1020/**", timeout=15000)
            logger.info(f"결재작성 페이지 로드 확인: {page.url[:100]}")
        except PlaywrightTimeout:
            # 세션 만료 확인
            if not self._check_session_valid():
                raise RuntimeError("세션이 만료되었습니다.")
            # APB1020 패턴 실패해도 팝업으로 열렸을 수 있으므로 계속 진행
            logger.warning(f"APB1020 URL 대기 타임아웃, 현재: {page.url[:100]}")
        except Exception:
            logger.warning(f"URL 대기 중 오류, 현재: {page.url[:100]}")

        self._close_popups()

        # 제목 필드가 보이는지 확인 (최대 20초, 재시도)
        form_loaded = False
        for attempt in range(2):
            try:
                page.locator("th:has-text('제목')").first.wait_for(state="visible", timeout=10000)
                logger.info("양식 필드 로드 완료")
                form_loaded = True
                break
            except PlaywrightTimeout:
                if attempt == 0:
                    logger.info("양식 로드 재시도 중...")
                    self._close_popups()
                    page.wait_for_timeout(2000)

        if not form_loaded:
            _save_debug(page, "error_form_not_loaded")
            raise RuntimeError("양식 로드 실패: 제목 필드를 찾을 수 없습니다. 네트워크 상태를 확인해주세요.")

        _save_debug(page, "02_form_loaded")


    def _fill_field_by_label(self, label: str, value: str) -> bool:
        """
        테이블 라벨(th) 기반 필드 채우기
        DOM 구조: table.OBTFormPanel_table > tr > th(라벨) + td(input)
        """
        page = self.page
        try:
            # th에서 라벨 텍스트 찾기
            th_el = page.locator("th").filter(has_text=label).first
            if not th_el.is_visible(timeout=2000):
                return False

            # th의 형제 td에서 input 찾기
            td_el = th_el.locator("xpath=following-sibling::td").first
            if not td_el.is_visible():
                return False

            inp = td_el.locator("input:visible").first
            if inp.is_visible():
                inp.click(force=True)
                inp.fill("")
                inp.fill(str(value))
                logger.info(f"필드 '{label}' 입력: {value}")
                return True
        except Exception as e:
            logger.debug(f"필드 '{label}' 입력 실패: {e}")
        return False

    def _fill_field_by_placeholder(self, placeholder: str, value: str) -> bool:
        """placeholder 기반 필드 채우기"""
        page = self.page
        try:
            inp = page.locator(f"input[placeholder='{placeholder}']").first
            if inp.is_visible(timeout=2000):
                inp.click(force=True)
                inp.fill("")
                inp.fill(str(value))
                logger.info(f"필드 ph='{placeholder}' 입력: {value}")
                return True
        except Exception as e:
            logger.debug(f"필드 ph='{placeholder}' 입력 실패: {e}")
        return False


    def _save_draft(self) -> dict:
        """보관(임시저장) -- 인라인 보관 버튼 또는 결재상신->팝업->보관 흐름"""
        page = self.page

        self._close_popups()

        # ── 1차: 인라인 보관 버튼 찾기 ──
        save_btn = None
        for selector in [
            "div.topBtn:has-text('보관')",
            "button:has-text('보관')",
        ]:
            try:
                candidates = page.locator(selector).all()
                for candidate in candidates:
                    if candidate.is_visible(timeout=1500):
                        btn_text = candidate.inner_text().strip()
                        if btn_text == "보관":
                            save_btn = candidate
                            logger.info(f"인라인 보관 버튼 발견: {selector}")
                            break
                if save_btn:
                    break
            except Exception:
                continue

        if save_btn:
            # 인라인 보관 (기존 흐름)
            _save_debug(page, "04_before_save")
            save_btn.click(force=True)
            return self._wait_save_result(page)

        # ── 2차: 결재상신 클릭 -> 팝업 열림 -> 팝업에서 보관 ──
        logger.info("인라인 보관 버튼 없음 -- 결재상신->팝업->보관 흐름 시도")
        submit_btn = None
        for selector in [
            "button:has-text('결재상신')",
            "div.topBtn:has-text('결재상신')",
            "button:has-text('상신')",
        ]:
            try:
                candidates = page.locator(selector).all()
                for candidate in candidates:
                    if candidate.is_visible(timeout=1500):
                        submit_btn = candidate
                        logger.info(f"결재상신 버튼 발견: {selector}")
                        break
                if submit_btn:
                    break
            except Exception:
                continue

        if not submit_btn:
            _save_debug(page, "error_no_save_btn")
            return {"success": False, "message": "보관/결재상신 버튼을 찾을 수 없습니다."}

        # 열린 모달 모두 닫기 (dimClicker 차단 방지)
        self._close_open_modals()
        page.wait_for_timeout(500)
        _save_debug(page, "04_before_submit_popup")

        # 결재상신 클릭 -> 팝업 대기 (JS 직접 클릭으로 dimClicker 우회)
        context = page.context
        popup_page = None
        try:
            logger.info("결재상신 클릭 -> 팝업 대기 (expect_page)")
            with context.expect_page(timeout=15000) as popup_info:
                # dimClicker 우회: DOM에서 직접 결재상신 버튼 찾아 클릭
                page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.trim().includes('결재상신') && btn.offsetParent !== null) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                page.wait_for_timeout(500)
            popup_page = popup_info.value
            popup_page.wait_for_load_state("domcontentloaded", timeout=10000)
            logger.info(f"결재상신 팝업 열림: {popup_page.url[:80]}")
        except Exception as e:
            logger.warning(f"팝업 대기 실패: {e}")
            # 팝업이 안 열리면 context.pages에서 찾기
            self.page.wait_for_timeout(2000)
            for p in context.pages:
                if p != page and "popup" in p.url:
                    popup_page = p
                    break

        if not popup_page:
            # 검증 오류 다이얼로그 또는 도움 모달 확인
            try:
                # 1. "검증결과가 부적합" 텍스트
                validation_msg = page.locator("text=검증결과가 부적합").first
                if validation_msg.is_visible(timeout=1000):
                    self._close_open_modals()
                    _save_debug(page, "error_validation_failed")
                    return {"success": False, "message": "검증 부적합: 예산/프로젝트 미입력 항목이 있습니다."}
            except Exception:
                pass
            try:
                # 2. 프로젝트코드도움/거래처코드도움 모달 (검증 실패로 자동 열림)
                help_modal = page.locator("text=프로젝트코드도움, text=거래처코드도움").first
                if help_modal.is_visible(timeout=1000):
                    self._close_open_modals()
                    _save_debug(page, "error_validation_help_modal")
                    return {"success": False, "message": "검증 부적합: 그리드 필수 항목(프로젝트/거래처)이 미입력 상태입니다. 세금계산서 연동이 필요할 수 있습니다."}
            except Exception:
                pass
            _save_debug(page, "error_expense_no_popup_after_submit")
            return {"success": False, "message": "결재상신 팝업이 열리지 않았습니다."}

        _save_debug(popup_page, "04b_popup_opened")

        # 팝업에서 보관 버튼 클릭
        return self._save_draft_in_popup(popup_page)

    def _wait_save_result(self, target_page) -> dict:
        """보관 클릭 후 결과 대기 (공통)"""
        try:
            target_page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            logger.warning("보관 후 네트워크 대기 타임아웃")
            self.page.wait_for_timeout(3000)
        except Exception:
            self.page.wait_for_timeout(3000)

        # 에러 다이얼로그 확인
        try:
            error_msg = target_page.locator("div.alert-message, div.error-message, .OBTAlert_message").first
            if error_msg.is_visible(timeout=2000):
                text = error_msg.inner_text()
                logger.error(f"보관 에러 메시지: {text}")
                _save_debug(target_page, "error_save_response")
                return {"success": False, "message": f"보관 중 오류가 발생했습니다: {text}"}
        except Exception:
            pass

        _save_debug(target_page, "05_after_save")
        logger.info("보관(임시저장) 완료")
        return {"success": True, "message": "임시보관문서에 저장되었습니다. (상신 전 상태)"}

    # ─────────────────────────────────────────
    # 양식별 작성 메서드 (스텁)
    # ─────────────────────────────────────────


    def _check_field_has_value(self, label: str, expected: str) -> bool:
        """필드에 값이 입력되었는지 확인"""
        try:
            th_el = self.page.locator(f"th:has-text('{label}')").first
            td_el = th_el.locator("xpath=following-sibling::td").first
            inp = td_el.locator("input:visible").first
            return inp.input_value() == expected
        except Exception:
            return False

