"""
전자결재 자동화 -- 기본 클래스 + 공통 유틸
"""

import os
import logging
from pathlib import Path
from playwright.sync_api import Page, BrowserContext, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("approval_automation")

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# 스크린샷 저장 디렉토리
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 3  # 초

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
        except Exception:
            return False

    def _close_popups(self):
        """열린 팝업 페이지 자동 닫기"""
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

    def _validate_required_fields(self, data: dict, required_keys: list[str], form_name: str) -> dict | None:
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
            else:
                raise PlaywrightTimeout("전자결재 모듈 링크 미발견")
        except Exception:
            # 폴백: GW 내부 탭에서 "전자결재" 클릭
            try:
                page.locator("text=전자결재").first.click(force=True)
                page.wait_for_timeout(2000)
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

        if _check_approval_home_loaded(30000):
            navigated = True
        else:
            if not self._check_session_valid():
                raise RuntimeError("세션이 만료되었습니다.")
            logger.warning("결재 HOME 텍스트 미발견 (방법 1)")

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

        # 방법 3: URL 직접 네비게이션 (HPM0110 = 전자결재 홈, 확인된 URL)
        if not navigated:
            try:
                approval_home_url = f"{GW_URL}/#/HP/HPM0110/HPM0110"
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
            th_el = page.locator(f"th:has-text('{label}')").first
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

        _save_debug(page, "04_before_submit_popup")

        # 결재상신 클릭 -> 팝업 대기
        context = page.context
        popup_page = None
        try:
            with context.expect_page(timeout=10000) as popup_info:
                submit_btn.click(force=True)
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
            _save_debug(page, "error_no_popup")
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

