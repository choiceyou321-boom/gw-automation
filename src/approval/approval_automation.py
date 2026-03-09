"""
전자결재 자동 작성 모듈 (Playwright 기반)
- 지출결의서 양식 자동 채우기
- 결재상신 지원
- 에러 핸들링: 재시도, 타임아웃, 세션 만료 대응

Phase 0 DOM 탐색 결과 반영 (2026-03-01):
- 네비게이션: span.module-link.EA → 추천양식 "[프로젝트]지출결의서" 직접 클릭
- URL 패턴: /#/HP/APB1020/APB1020?...formDTp=APB1020_00001&formId=255
- 양식 테이블: table.OBTFormPanel_table__1fRyk
- 필드 접근: th 라벨 → 형제 td 내 input (placeholder 기반)
- 액션 버튼: "결재상신" / "상신" (div.topBtn)
"""
import os
import time
import logging
from pathlib import Path
from playwright.sync_api import Page, BrowserContext, TimeoutError as PlaywrightTimeout
from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients

logger = logging.getLogger("approval_automation")

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

# 스크린샷 저장 디렉토리 (모듈 로드 시 한 번만 생성)
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 3  # 초

# OBTDataGrid React fiber를 통한 그리드 API 접근 JS 헬퍼 (세션 XI 발견)
# 접근 경로: .OBTDataGrid_grid__22Vfl → __reactFiber → depth 3 → stateNode.state.interface
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


class ApprovalAutomation:
    """전자결재 폼 자동화 클래스"""

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
            # 키 → 한국어 라벨 변환
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

    def set_approval_line(self, page: Page, approval_line: dict) -> bool:
        """
        결재선 동적 설정 (GW 결재선 팝업 조작)

        GW 결재선 UI 흐름:
        1. "결재선" 또는 "결재선 설정" 버튼 클릭 → 팝업 열림
        2. 기존 결재선 초기화 (선택적)
        3. 결재자 검색 입력 → 선택 → 결재 단계 지정
        4. 확인 버튼 클릭

        Args:
            page: 결재 양식 페이지 (팝업 포함)
            approval_line: {
                "drafter": "auto",      # 기안자 (auto=현재 로그인 사용자)
                "agree": "신동관",       # 검토자 (선택)
                "final": "최기영",       # 최종 승인자
                "cc": ["재무전략팀"],    # 수신참조 (선택)
            }

        Returns:
            bool: 설정 성공 여부 (실패해도 기본 결재선 유지)
        """
        if not approval_line:
            return False

        # 기안자는 자동 (로그인 사용자) — 건너뜀
        agree = approval_line.get("agree", "")
        final = approval_line.get("final", "")
        cc_list = approval_line.get("cc", [])

        # 결재선 설정 버튼 탐색
        line_btn = None
        for selector in [
            "div.topBtn:has-text('결재선')",
            "button:has-text('결재선')",
            "a:has-text('결재선')",
            "span:has-text('결재선')",
            "[title*='결재선']",
        ]:
            try:
                candidates = page.locator(selector).all()
                for c in candidates:
                    if c.is_visible(timeout=1000):
                        txt = (c.inner_text() or "").strip()
                        if "결재선" in txt:
                            line_btn = c
                            break
                if line_btn:
                    break
            except Exception:
                continue

        if not line_btn:
            logger.warning("결재선 버튼을 찾을 수 없음 — 기본 결재선 유지")
            return False

        # 결재선 팝업 열기
        pages_before = set(self.context.pages) if self.context else set()
        try:
            line_btn.click(force=True)
            logger.info("결재선 버튼 클릭")
        except Exception as e:
            logger.warning(f"결재선 버튼 클릭 실패: {e}")
            return False

        # 팝업 또는 동적 레이어 대기
        line_page = None
        if self.context:
            for _ in range(10):
                current_pages = set(self.context.pages)
                new_pages = current_pages - pages_before
                for p in new_pages:
                    try:
                        if p.url and p.url != "about:blank":
                            line_page = p
                            break
                    except Exception:
                        continue
                if line_page:
                    break
                page.wait_for_timeout(500)

        # 팝업이 없으면 현재 페이지의 레이어/모달로 처리
        target = line_page or page

        if line_page:
            try:
                line_page.wait_for_load_state("domcontentloaded", timeout=8000)
                line_page.on("dialog", lambda d: d.accept())
            except Exception:
                pass

        logger.info(f"결재선 팝업/레이어 대상: {target.url[:60] if target else 'none'}")

        # 결재자 추가 헬퍼
        def _add_approver(name: str, role: str) -> bool:
            """결재자 검색 후 추가"""
            if not name or name == "auto":
                return True

            # 검색 입력란 찾기
            search_input = None
            for sel in [
                "input[placeholder*='이름']",
                "input[placeholder*='성명']",
                "input[placeholder*='검색']",
                "input[type='text']:visible",
            ]:
                try:
                    inp = target.locator(sel).first
                    if inp.is_visible(timeout=2000):
                        search_input = inp
                        break
                except Exception:
                    continue

            if not search_input:
                logger.warning(f"결재선 검색 입력란 미발견 ({role}: {name})")
                return False

            try:
                search_input.click()
                search_input.fill(name)
                search_input.press("Enter")
                target.wait_for_timeout(1000)

                # 검색 결과에서 이름 클릭
                result_el = target.locator(f"text={name}").first
                if result_el.is_visible(timeout=3000):
                    result_el.click(force=True)
                    logger.info(f"결재선 {role} 추가: {name}")
                    target.wait_for_timeout(500)
                    return True
            except Exception as e:
                logger.warning(f"결재선 {role} '{name}' 추가 실패: {e}")
            return False

        # 검토자 추가
        if agree:
            _add_approver(agree, "검토자")

        # 최종 승인자 추가
        if final:
            _add_approver(final, "최종승인자")

        # 수신참조 추가
        for cc_name in cc_list:
            _add_approver(cc_name, f"수신참조({cc_name})")

        # 확인 버튼 클릭
        for sel in ["button:has-text('확인')", "button:has-text('저장')", "button:has-text('적용')"]:
            try:
                btn = target.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click(force=True)
                    logger.info("결재선 확인 버튼 클릭")
                    target.wait_for_timeout(500)
                    break
            except Exception:
                continue

        # 팝업이면 닫기
        if line_page:
            try:
                if not line_page.is_closed():
                    line_page.close()
            except Exception:
                pass

        return True

    def set_cc_recipients(self, page: Page, cc_list: list[str]) -> bool:
        """
        수신참조(CC) 자동 설정

        Args:
            page: 결재 양식 페이지
            cc_list: 수신참조 이름/팀명 목록

        Returns:
            bool: 설정 성공 여부
        """
        if not cc_list:
            return True

        # 수신참조 버튼 탐색
        cc_btn = None
        for selector in [
            "div.topBtn:has-text('수신참조')",
            "button:has-text('수신참조')",
            "a:has-text('수신참조')",
            "[title*='수신참조']",
            "div.topBtn:has-text('참조')",
            "button:has-text('참조')",
        ]:
            try:
                candidates = page.locator(selector).all()
                for c in candidates:
                    if c.is_visible(timeout=1000):
                        cc_btn = c
                        break
                if cc_btn:
                    break
            except Exception:
                continue

        if not cc_btn:
            logger.warning("수신참조 버튼 미발견 — 수신참조 설정 스킵")
            return False

        try:
            cc_btn.click(force=True)
            page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"수신참조 버튼 클릭 실패: {e}")
            return False

        # 각 수신참조 대상 추가
        success_count = 0
        for cc_name in cc_list:
            try:
                # 검색 입력
                search_input = page.locator("input[placeholder*='검색'], input[placeholder*='이름'], input[type='text']:visible").first
                if search_input.is_visible(timeout=2000):
                    search_input.fill(cc_name)
                    search_input.press("Enter")
                    page.wait_for_timeout(1000)

                    # 결과 클릭
                    result = page.locator(f"text={cc_name}").first
                    if result.is_visible(timeout=2000):
                        result.click(force=True)
                        page.wait_for_timeout(500)
                        success_count += 1
                        logger.info(f"수신참조 추가: {cc_name}")
            except Exception as e:
                logger.warning(f"수신참조 '{cc_name}' 추가 실패: {e}")

        # 확인
        for sel in ["button:has-text('확인')", "button:has-text('저장')"]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click(force=True)
                    break
            except Exception:
                continue

        logger.info(f"수신참조 설정 완료: {success_count}/{len(cc_list)}개")
        return success_count > 0

    # ─────────────────────────────────────────
    # 지출결의서
    # ─────────────────────────────────────────

    def create_expense_report(self, data: dict) -> dict:
        """
        지출결의서 작성 (인라인 폼 기반, 재시도 포함)

        GW에서 지출결의서는 인라인 폼으로만 열리며 (팝업 아님),
        인라인 폼에는 '보관' 버튼이 없고 '결재상신' 버튼만 존재합니다.
        이 메서드는 필드 채우기까지 수행하고, save_mode에 따라 동작합니다:
        - save_mode="verify" (기본): 필드 작성 검증만 수행, 실제 저장/상신 안 함
        - save_mode="submit": 결재상신 실행 (실제 결재 상신됨, 주의)

        Args:
            data: {
                "title": "결의서 제목",           # 필수
                "date": "2026-03-01",             # 증빙일자 (YYYY-MM-DD)
                "receipt_date": "2026-03-01",     # 증빙일자 (date와 동일, 우선)
                "description": "내용 설명",       # 선택
                "project": "GS-25-0088",          # 프로젝트 코드 또는 이름 일부 (상단+하단 모두 입력)
                "items": [                        # 지출내역 그리드
                    {
                        "item": "항목명",         # or "content"
                        "amount": 100000,         # or "supply_amount" (공급가액)
                        "tax_amount": 10000,      # 부가세 (선택)
                        "vendor": "거래처명",     # 선택
                    }
                ],
                "evidence_type": "세금계산서",    # 증빙유형
                "attachment_path": "/path.pdf",   # 첨부파일 경로 (선택)
                "auto_capture_budget": True,      # 예실대비현황 스크린샷 자동 캡처+첨부 (선택)
                "save_mode": "verify",            # "verify" | "submit"
            }
        Returns:
            {"success": bool, "message": str}
        """
        # 필수 필드 검증
        validation = self._validate_required_fields(data, ["title"], "지출결의서")
        if validation:
            return validation

        # 세션 확인
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        save_mode = data.get("save_mode", "draft")

        # draft 모드: 팝업 기반 보관 흐름 (인라인 폼에는 보관 버튼이 없음)
        if save_mode == "draft":
            return self._create_expense_report_via_popup(data)

        # submit / verify: 기존 인라인 폼 흐름
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()

                # 1. 전자결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 추천양식에서 지출결의서 클릭 (인라인 폼)
                self._click_expense_form()

                # 3. 양식 로드 대기
                self._wait_for_form_load()

                # 4. 필드 채우기
                self._fill_expense_fields(data)

                # 4-1. 결재선 커스텀 설정
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "지출결의서")
                    self.set_approval_line(self.page, resolved_line)

                # 4-2. 수신참조 설정
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "지출결의서")
                    self.set_cc_recipients(self.page, resolved_cc)

                # 5. 저장/검증
                if save_mode == "submit":
                    result = self._submit_inline_form()
                else:
                    # verify: 필드 작성 검증만 (실제 저장 없음)
                    result = self._verify_expense_fields(data)

                return result

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"지출결의서 작성 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(self.page, f"error_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}
                    self._close_popups()
                    time.sleep(RETRY_DELAY)

            except Exception as e:
                last_error = e
                logger.error(f"지출결의서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        _save_debug(self.page, "error_final")
        return {"success": False, "message": f"지출결의서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def _create_expense_report_via_popup(self, data: dict) -> dict:
        """
        지출결의서 보관 흐름 (인라인 폼 → 결재상신 → 팝업 → 보관)

        지출결의서는 결재작성에서 인라인 폼으로 열리므로:
        1. 전자결재 HOME → 추천양식 클릭 → 인라인 폼 로드
        2. _fill_expense_fields(data)로 22단계 필드 채우기
        3. 결재선/수신참조 설정
        4. 결재상신 클릭 → 새 팝업 감지
        5. 팝업에서 보관 버튼 클릭
        """
        if not self.context:
            return {"success": False, "message": "BrowserContext가 필요합니다. (팝업 기반 보관)"}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            popup_page = None
            try:
                self._close_popups()

                # 1. 전자결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 추천양식에서 지출결의서 클릭 → 인라인 폼 로드
                self._click_expense_form()
                self._wait_for_form_load()

                # 3. 인라인 폼 필드 채우기 (22단계)
                self._fill_expense_fields(data)
                _save_debug(self.page, "expense_draft_01_fields_filled")

                # 4. 결재선 커스텀 설정
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "지출결의서")
                    self.set_approval_line(self.page, resolved_line)

                # 5. 수신참조 설정
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "지출결의서")
                    self.set_cc_recipients(self.page, resolved_cc)

                # 6. 검증결과 확인 (부적합이면 결재상신 팝업이 열리지 않음)
                try:
                    validation_cell = self.page.locator("text=적합").first
                    if validation_cell.is_visible(timeout=2000):
                        cell_text = validation_cell.inner_text().strip()
                        if "부적합" in cell_text:
                            logger.warning("검증결과 '부적합' — 결재상신 팝업이 열리지 않을 수 있습니다")
                            _save_debug(self.page, "error_validation_fail")
                        else:
                            logger.info(f"검증결과 확인: {cell_text}")
                except Exception:
                    logger.info("검증결과 셀 미발견 (계속 진행)")

                # 7. 결재상신 클릭 → 팝업 대기
                # dialog 핸들러: GW가 confirm/alert를 띄울 수 있음
                dialog_messages = []

                def _handle_dialog(dialog):
                    msg = dialog.message
                    dialog_messages.append(msg)
                    logger.info(f"결재상신 dialog 감지: {msg[:100]}")
                    dialog.accept()

                self.page.on("dialog", _handle_dialog)

                # 결재상신 버튼 찾기 (div.topBtn 우선, button 폴백)
                submit_btn = None
                for sel in [
                    "div.topBtn:has-text('결재상신')",
                    "button:has-text('결재상신')",
                    "[class*='topBtn']:has-text('결재상신')",
                    "text=결재상신",
                ]:
                    loc = self.page.locator(sel).first
                    try:
                        if loc.is_visible(timeout=2000):
                            submit_btn = loc
                            logger.info(f"결재상신 버튼 발견: {sel}")
                            break
                    except Exception:
                        continue
                if not submit_btn:
                    _save_debug(self.page, "error_no_submit_btn")
                    return {"success": False, "message": "결재상신 버튼을 찾을 수 없습니다."}

                # expect_page로 팝업 감지 (결재상신 → 새 창)
                popup_page = None
                try:
                    with self.context.expect_page(timeout=15000) as new_page_info:
                        submit_btn.scroll_into_view_if_needed()
                        time.sleep(0.3)
                        submit_btn.click()
                        logger.info("결재상신 클릭 → 팝업 대기 (expect_page)")
                    popup_page = new_page_info.value
                    logger.info(f"결재상신 팝업 감지: {popup_page.url[:100]}")
                except Exception as e:
                    logger.warning(f"expect_page 팝업 감지 실패: {e}")

                # expect_page 실패 시 폴링 폴백
                if not popup_page:
                    pages_before = set(id(p) for p in self.context.pages)
                    # 이미 클릭했으므로 다시 클릭 시도
                    try:
                        submit_btn.click()
                        logger.info("결재상신 재클릭 → 폴링 대기")
                    except Exception:
                        pass
                    for _ in range(20):
                        time.sleep(0.5)
                        for p in self.context.pages:
                            try:
                                if id(p) in pages_before or p.is_closed():
                                    continue
                                popup_page = p
                                logger.info(f"결재상신 팝업 감지 (폴링): {p.url[:100]}")
                                break
                            except Exception:
                                continue
                        if popup_page:
                            break

                # dialog 핸들러 제거
                self.page.remove_listener("dialog", _handle_dialog)

                if not popup_page:
                    _save_debug(self.page, "error_expense_no_popup_after_submit")
                    # dialog 메시지가 있으면 검증 오류로 판단
                    if dialog_messages:
                        return {"success": False, "message": f"결재상신 검증 오류: {'; '.join(dialog_messages[:3])}"}
                    # 부적합 오류 모달 확인 ("검증결과가 부적합인" 텍스트)
                    try:
                        error_modal = self.page.locator("text=부적합").first
                        if error_modal.is_visible(timeout=2000):
                            # 오류 내용 추출 — 다양한 패턴 포함
                            error_text = self.page.evaluate("""() => {
                                const els = document.querySelectorAll('div, span, li, p, td');
                                const errors = [];
                                const PATTERNS = ['입력해주세요', '오류 내용', '필수', '부적합', '미입력', '확인하세요'];
                                for (const el of els) {
                                    const t = el.textContent?.trim() || '';
                                    if (t.length > 3 && t.length < 200 && PATTERNS.some(p => t.includes(p))) {
                                        errors.push(t.substring(0, 100));
                                    }
                                }
                                // 중복 제거 후 반환
                                return [...new Set(errors)].slice(0, 10).join('; ');
                            }""")
                            if not error_text:
                                # 패턴 미매칭 시 모달 전체 텍스트 캡처
                                error_text = self.page.evaluate("""() => {
                                    const modal = document.querySelector(
                                        '[class*="modal"], [class*="dialog"], [class*="popup"], [role="dialog"]'
                                    );
                                    return modal ? modal.textContent?.trim().substring(0, 300) : '(오류 내용 추출 실패)';
                                }""")
                            # 닫기 버튼 클릭
                            try:
                                close_btn = self.page.locator("button:has-text('닫기')").first
                                if close_btn.is_visible(timeout=1000):
                                    close_btn.click()
                            except Exception:
                                pass
                            return {"success": False, "message": f"검증 부적합: {error_text[:300]}"}
                    except Exception:
                        pass
                    # 일반 모달 오류 확인
                    try:
                        modal_text = self.page.evaluate("""() => {
                            let text = '';
                            document.querySelectorAll('[class*="modal"], [class*="dialog"], [role="dialog"]').forEach(el => {
                                if (el.offsetParent !== null) {
                                    text = el.textContent?.trim()?.substring(0, 300) || '';
                                }
                            });
                            return text;
                        }""")
                        if modal_text:
                            return {"success": False, "message": f"결재상신 오류 모달: {modal_text[:150]}"}
                    except Exception:
                        pass
                    return {"success": False, "message": "결재상신 후 팝업이 열리지 않았습니다."}

                # 팝업 로드 대기 (SPA 렌더링 완료까지)
                popup_page.on("dialog", lambda d: d.accept())
                try:
                    popup_page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                # SPA 컨텐츠 로드 대기: div.topBtn (보관/상신 버튼 영역) 출현 확인
                try:
                    popup_page.locator("div.topBtn").first.wait_for(
                        state="visible", timeout=20000
                    )
                    logger.info("팝업 SPA 컨텐츠 로드 완료 (div.topBtn 감지)")
                except Exception:
                    logger.warning("팝업 div.topBtn 대기 타임아웃 — 계속 진행")
                    time.sleep(3)
                logger.info(f"결재상신 팝업 열림: {popup_page.url[:100]}")
                _save_debug(popup_page, "expense_draft_02_popup_opened")

                # 8. 팝업에서 보관 버튼 클릭
                result = self._save_draft_in_popup(popup_page)
                return result

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"지출결의서 보관 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                if popup_page:
                    _save_debug(popup_page, f"error_expense_popup_timeout{attempt}")
                if attempt < MAX_RETRIES:
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다."}
                    self._close_popups()
                    time.sleep(RETRY_DELAY)
            except RuntimeError as e:
                return {"success": False, "message": str(e)}
            except Exception as e:
                last_error = e
                logger.error(f"지출결의서 보관 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if popup_page:
                    _save_debug(popup_page, f"error_expense_popup_{attempt}")
                if attempt < MAX_RETRIES:
                    self._close_popups()
                    time.sleep(RETRY_DELAY)
            finally:
                # 팝업 정리 (실패 시)
                if popup_page and not popup_page.is_closed():
                    try:
                        popup_page.close()
                    except Exception:
                        pass

        return {"success": False, "message": f"지출결의서 보관 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def _fill_expense_popup_title(self, popup_page, title: str):
        """팝업 지출결의서 제목 입력"""
        try:
            inputs = popup_page.locator("input[type='text']:visible, input:not([type]):visible").all()
            for inp in inputs:
                val = inp.input_value()
                # 기본 제목 패턴: "[지출결의서]PM팀_전태규_"
                if "[지출결의서]" in val or "지출결의서" in val:
                    inp.click()
                    inp.fill(title)
                    logger.info(f"팝업 제목 입력: {title}")
                    return
            # 패턴 매칭 실패 시 4번째 input 시도 (제목 필드 위치)
            if len(inputs) >= 4:
                inp = inputs[3]
                inp.click()
                inp.fill(title)
                logger.info(f"팝업 제목 입력 (인덱스): {title}")
        except Exception as e:
            logger.warning(f"팝업 제목 입력 실패: {e}")

    def _fill_expense_popup_body(self, popup_page, data: dict):
        """
        팝업 지출결의서 dzEditor 본문 필드 채우기

        mapping_key로 식별되는 dze_external_data_area 입력 필드의 value 속성을
        HTML 문자열 교체 방식으로 수정
        """
        import re

        # 에디터 HTML 가져오기
        current_html = ""
        for _ in range(10):
            try:
                current_html = popup_page.evaluate(
                    "(n) => { try { return getEditorHTMLCodeIframe(n); } catch(e) { return ''; } }", 0
                )
            except Exception:
                current_html = ""
            if current_html and len(current_html) >= 100:
                break
            time.sleep(1)

        if not current_html or len(current_html) < 100:
            logger.warning("에디터 HTML 로드 실패, 본문 필드 건너뜀")
            return

        logger.info(f"에디터 HTML 가져옴: {len(current_html)} chars")
        modified = current_html

        # mapping_key별 value 교체 헬퍼
        def replace_mapping_value(html, key, new_value):
            """mapping_key="key" 인 input의 value 속성을 교체"""
            pattern = rf'(mapping_key\s*=\s*"{re.escape(key)}"[^>]*\s+value\s*=\s*")[^"]*(")'
            result = re.sub(pattern, lambda m: m.group(1) + str(new_value) + m.group(2), html, count=1)
            # value가 mapping_key보다 앞에 올 수도 있음
            if result == html:
                pattern2 = rf'(value\s*=\s*")[^"]*("[^>]*mapping_key\s*=\s*"{re.escape(key)}")'
                result = re.sub(pattern2, lambda m: m.group(1) + str(new_value) + m.group(2), html, count=1)
            return result

        # 기본정보 필드 (자동 매핑 — 프로젝트만 수동 설정)
        project = data.get("project", "")
        if project:
            modified = replace_mapping_value(modified, "pjtName", project)
            logger.info(f"프로젝트(pjtName): {project}")

        # 총합계
        total = data.get("total_amount", 0)
        if total:
            total_str = f"{int(total):,}"
            modified = replace_mapping_value(modified, "sumAm", total_str)
            modified = replace_mapping_value(modified, "totSumAm", total_str)
            modified = replace_mapping_value(modified, "totSupAm", total_str)
            logger.info(f"총합계(sumAm): {total_str}")

        # 용도별합계 그리드 (첫 행)
        items = data.get("items", [])
        if items:
            item = items[0]
            amount = item.get("amount", 0)
            item_name = item.get("item", "")
            amount_str = f"{int(amount):,}" if amount else ""

            modified = replace_mapping_value(modified, "summarySeq", "1")
            modified = replace_mapping_value(modified, "rmkDc", item_name)
            modified = replace_mapping_value(modified, "supAm", amount_str)

            logger.info(f"그리드 항목: {item_name}, 금액: {amount_str}")

        # description은 본문 하단 비고 영역에 기입 가능하지만 현재 생략

        # HTML 설정
        if modified != current_html:
            try:
                popup_page.evaluate(
                    "(args) => { setEditorHTMLCodeIframe(args[0], args[1]); }",
                    [modified, 0]
                )
                logger.info("에디터 HTML 설정 완료")
            except Exception as e:
                logger.warning(f"setEditorHTMLCodeIframe 실패: {e}")
        else:
            logger.info("에디터 HTML 변경 없음")

    def _verify_expense_fields(self, data: dict) -> dict:
        """인라인 폼 필드 작성 검증 (save_mode="verify" 전용, 실제 저장 없음)"""
        page = self.page
        _save_debug(page, "04_before_verify")

        # 제목 필드 검증
        try:
            title_th = page.locator("th").filter(has_text="제목").first
            title_td = title_th.locator("xpath=following-sibling::td").first
            title_inp = title_td.locator("input").first
            actual_title = title_inp.input_value()
            expected_title = data.get("title", "")
            if expected_title and expected_title in actual_title:
                logger.info(f"제목 검증 OK: {actual_title}")
            else:
                logger.warning(f"제목 불일치: expected={expected_title}, actual={actual_title}")
        except Exception as e:
            logger.warning(f"제목 검증 실패: {e}")

        # 페이지 이탈 검증 (HP URL 유지)
        if "/HP/" not in page.url:
            _save_debug(page, "error_page_escaped")
            return {"success": False, "message": f"페이지 이탈 감지: {page.url[:80]}"}

        _save_debug(page, "05_verify_complete")
        logger.info("지출결의서 작성 검증 완료 (인라인 모드)")
        return {"success": True, "message": "지출결의서 작성 완료 (인라인 폼, 보관은 팝업에서만 가능)"}

    def _submit_inline_form(self) -> dict:
        """인라인 폼에서 결재상신 실행"""
        page = self.page
        _save_debug(page, "04_before_submit")

        # 결재상신 버튼 찾기 (div.topBtn 우선)
        submit_btn = None
        for sel in [
            "div.topBtn:has-text('결재상신')",
            "button:has-text('결재상신')",
            "[class*='topBtn']:has-text('결재상신')",
        ]:
            loc = page.locator(sel).first
            try:
                if loc.is_visible(timeout=2000):
                    submit_btn = loc
                    break
            except Exception:
                continue
        if not submit_btn:
            return {"success": False, "message": "결재상신 버튼을 찾을 수 없습니다."}

        submit_btn.scroll_into_view_if_needed()
        time.sleep(0.3)
        submit_btn.click()
        logger.info("결재상신 클릭")
        time.sleep(3)

        # 검증 오류 모달 확인
        try:
            # z-index 높은 모달 텍스트 확인
            modal_text = page.evaluate("""() => {
                let text = '';
                document.querySelectorAll('*').forEach(el => {
                    const z = parseInt(getComputedStyle(el).zIndex) || 0;
                    if (z > 1000 && z < 5000 && el.offsetParent !== null) {
                        text = el.textContent?.trim()?.substring(0, 300) || '';
                    }
                });
                return text;
            }""")
            if modal_text and '확인' in modal_text:
                logger.warning(f"결재상신 검증 오류: {modal_text[:100]}")
                return {"success": False, "message": f"결재상신 검증 오류: {modal_text[:100]}"}
        except Exception:
            pass

        _save_debug(page, "05_after_submit")
        return {"success": True, "message": "결재상신 완료"}

    def _navigate_to_approval_home(self):
        """전자결재 모듈 HOME으로 이동 (세션 확인 포함)"""
        page = self.page

        # 세션 만료 확인
        if not self._check_session_valid():
            raise RuntimeError("세션이 만료되었습니다.")

        # 로그인 직후 팝업이 열리는 시간 대기
        time.sleep(2)
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
            """결재 HOME 로드 여부 확인 (OR 셀렉터 — 단일 타임아웃)"""
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

        # 방법 4: 최후 폴백 — 기존 해시 라우팅
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
        """결재작성 버튼 클릭 (결재 HOME → 결재작성 페이지)"""
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
                    time.sleep(1)
                    return
            except Exception:
                continue

        logger.warning("결재작성 버튼 미발견, 현재 페이지에서 양식 검색 시도")

    def _click_expense_form(self):
        """결재작성 → 지출결의서 양식 선택 (인라인 폼)"""
        page = self.page

        def _try_click_form(phase: str) -> bool:
            """양식 링크 클릭 후 URL 변경 확인 (HPM0110에서 벗어나는지)"""
            for keyword in ["[프로젝트]지출결의서", "프로젝트]지출", "지출결의서"]:
                try:
                    links = page.locator(f"text={keyword}").all()
                    for link in links:
                        if link.is_visible():
                            link.click(force=True)
                            logger.info(f"양식 클릭 ({phase}): '{keyword}'")
                            # 클릭 후 URL 변경 대기 (SPA 네비게이션)
                            try:
                                page.wait_for_url("**/APB1020/**", timeout=8000)
                                logger.info(f"양식 페이지 이동 확인: {page.url[:100]}")
                                return True
                            except Exception:
                                # URL 변경 안 됨 → 클릭 재시도
                                logger.warning(f"양식 클릭 후 URL 미변경 (여전히 {page.url[:80]})")
                                # 한 번 더 클릭 시도 (SPA 렌더링 지연 대응)
                                try:
                                    page.wait_for_timeout(1000)
                                    link2 = page.locator(f"text={keyword}").first
                                    if link2.is_visible():
                                        link2.click(force=True)
                                        page.wait_for_url("**/APB1020/**", timeout=8000)
                                        logger.info(f"양식 페이지 재클릭 이동 확인: {page.url[:100]}")
                                        return True
                                except Exception:
                                    pass
                except Exception:
                    continue
            return False

        # 1차: 현재 페이지에서 양식 바로 찾기
        if _try_click_form("현재 페이지"):
            return

        # 2차: 결재작성 버튼 클릭 후 양식 검색
        logger.info("현재 페이지에 양식 없음 → 결재작성 클릭")
        self._click_write_approval()
        page.wait_for_timeout(1500)  # 결재작성 페이지 렌더링 대기

        if _try_click_form("결재작성 경유"):
            return

        _save_debug(page, "error_expense_form_not_found")
        raise Exception("지출결의서 양식을 찾을 수 없습니다.")

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

    def _fill_expense_fields(self, data: dict):
        """
        지출결의서 필드 채우기

        Phase 0에서 확인된 필드 구조:
        - 테이블 0 (상단): 회계단위, 회계처리일자, 품의서, 첨부파일, 프로젝트, 전표구분, 제목, 자금집행
        - 지출내역 그리드: 용도, 내용, 거래처, 공급가액, 부가세, ...
        - 테이블 7 (하단): 증빙일자, 지급요청일, 사원, 은행/계좌, 예금주, 사용부서, 프로젝트, 예산

        Task #4 추가 필드:
        - project: 프로젝트 코드도움 (상단 + 하단 테이블 모두 입력)
        - receipt_date: 증빙일자 (YYYY-MM-DD)
        - evidence_type: 증빙유형 ('세금계산서'|'계산서내역'|'카드사용내역'|'현금영수증')
        - attachment_path: 첨부파일 경로 (로컬 파일 또는 스크린샷)
        - auto_capture_budget: True이면 예실대비현황 스크린샷 캡처 후 첨부파일로 자동 업로드

        22단계 확장 (세션 VIII):
        - usage_code: 용도코드 (예: "5020"=외주공사비, 그리드 용도 셀)
        - budget_keyword: 예산과목 검색어 (예: "경량", 2xxx 코드만 선택)
        - payment_request_date: 지급요청일 (YYYY-MM-DD, 하단 날짜피커)
        - accounting_date: 회계처리일자 (YYYY-MM-DD, 세금계산서 발행월 일치 필요)
        - 검증결과 "적합" 확인 (부적합 시 툴팁으로 미비사항 추출)
        """
        page = self.page
        title = data.get("title", "")
        items = data.get("items", [])

        # 1. 프로젝트 코드도움 입력 (상단, y≈292)
        project = data.get("project", "")
        if project:
            self._fill_project_code(project, y_hint=292)
            _save_debug(page, "03a_after_project_top")

            # 프로젝트 입력 후 페이지 이탈 검증 (Enter→예산관리 네비게이션 방지)
            time.sleep(0.3)
            current_url = page.url
            if "/HP/" not in current_url:
                logger.warning(f"프로젝트 입력 후 페이지 이탈 감지: {current_url}")
                _save_debug(page, "03a_page_escaped")
                # 결재 홈 → 양식 재진입 복구
                try:
                    page.goto("https://gw.glowseoul.co.kr/#/app/approval")
                    page.wait_for_load_state("networkidle", timeout=10000)
                    logger.info("결재 홈으로 복구 완료 — 양식 재작성 필요")
                except Exception as e:
                    logger.error(f"페이지 복구 실패: {e}")

        # 2. 제목 입력 (th="제목" → td > input)
        if title:
            self._fill_field_by_label("제목", title)

        # 3. 제목 못 찾았으면 좌표 기반 (rect y=332 영역)
        if title and not self._check_field_has_value("제목", title):
            try:
                title_inputs = page.locator("table.OBTFormPanel_table__1fRyk input[type='text']:visible").all()
                for inp in title_inputs:
                    val = inp.get_attribute("value") or ""
                    ph = inp.get_attribute("placeholder") or ""
                    if not val and not ph:
                        box = inp.bounding_box()
                        if box and 310 < box["y"] < 360:
                            inp.fill(title)
                            logger.info(f"제목 입력 (좌표 기반): {title}")
                            break
            except Exception:
                pass

        _save_debug(page, "03_after_title")

        # 4. 증빙유형 → 세금계산서 모달 (그리드 수동 입력보다 먼저!)
        #    세금계산서 선택 시 그리드가 자동으로 채워짐
        evidence_type = data.get("evidence_type", "")
        invoice_selected = False
        if evidence_type:
            _is_invoice_type = evidence_type in ("세금계산서", "계산서", "계산서내역")
            if _is_invoice_type:
                # 계산서내역 버튼 → DOM 모달 ("매입(세금)계산서 내역") 열림
                # 그리드 렌더링 실패 시 최대 3회 재시도
                _invoice_row_count = 0
                for _inv_attempt in range(3):
                    if _inv_attempt > 0:
                        logger.warning(f"인보이스 재선택 시도 {_inv_attempt + 1}/3 — 그리드 비어 있음")
                        # 이전 시도에서 모달이 남아있을 수 있으므로 확인 후 닫기
                        try:
                            leftover = page.locator("text=매입(세금)계산서 내역").first
                            if leftover.is_visible(timeout=500):
                                page.locator("button:has-text('취소')").last.click(force=True)
                                time.sleep(0.5)
                        except Exception:
                            pass

                    self._click_evidence_type_button(evidence_type)
                    time.sleep(1)
                    _modal_invoice_selected = False
                    try:
                        _modal_invoice_selected = self._select_invoice_in_modal(
                            vendor=data.get("invoice_vendor", ""),
                            amount=data.get("invoice_amount"),
                            date_from=data.get("invoice_date", ""),
                            date_to=data.get("invoice_date", ""),
                        )
                    except Exception as e:
                        logger.warning(f"세금계산서 모달 선택 실패: {e}")

                    if not _modal_invoice_selected:
                        # 모달 선택 자체 실패 — 재시도해도 의미 없음
                        logger.warning("세금계산서 모달 선택 실패 — 재시도 중단")
                        break

                    # 인보이스 선택 후 그리드 렌더링 대기 (최대 5초)
                    for _wait in range(10):
                        _invoice_row_count = page.evaluate("""() => {
                            const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                            if (!el) return 0;
                            const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                            if (!fk) return 0;
                            let f = el[fk];
                            for (let i = 0; i < 3 && f; i++) f = f.return;
                            const iface = f?.stateNode?.state?.interface;
                            return (iface && typeof iface.getRowCount === 'function') ? iface.getRowCount() : 0;
                        }""")
                        if _invoice_row_count > 0:
                            logger.info(f"그리드 렌더링 완료: {_invoice_row_count}행 (시도 {_inv_attempt + 1}/3)")
                            break
                        time.sleep(0.5)
                    else:
                        logger.warning(f"그리드 렌더링 타임아웃 (5초) — 시도 {_inv_attempt + 1}/3")

                    if _invoice_row_count > 0:
                        invoice_selected = True
                        break
                    # 그리드가 비어 있으면 다음 시도로

                if invoice_selected:
                    _save_debug(page, "03c2_after_invoice_select")
                else:
                    if _invoice_row_count == 0 and _modal_invoice_selected:
                        logger.error("인보이스 선택 후 그리드 행 없음 (3회 재시도 모두 실패) — 검증 부적합 발생 가능")
                    _save_debug(page, "03c2_after_invoice_select")
            else:
                # 세금계산서가 아닌 증빙유형 (카드, 현금영수증 등) → 버튼만 클릭
                self._click_evidence_type_button(evidence_type)
                _save_debug(page, "03c_after_evidence")

        # 5. 지출내역 그리드 수동 입력 (세금계산서 미선택 시만)
        if items and not invoice_selected:
            self._fill_grid_items(items)
            _save_debug(page, "03b_after_grid")

        # 6. 증빙일자 입력 (하단 테이블, y=857)
        receipt_date = data.get("receipt_date", "") or data.get("date", "")
        if receipt_date:
            self._fill_receipt_date(receipt_date)
            _save_debug(page, "03d_after_receipt_date")

        # 7. 하단 테이블 프로젝트 코드도움 입력 (y≈857 근처, 테이블 7)
        if project:
            self._fill_project_code_bottom(project)
            _save_debug(page, "03d2_after_project_bottom")

        # 8. 첨부파일 업로드 (수동 경로 지정)
        attachment_path = data.get("attachment_path", "")
        if attachment_path:
            self._upload_attachment(attachment_path)
            _save_debug(page, "03e_after_attachment")

        # 9. 예실대비현황 자동 캡처 후 첨부 (auto_capture_budget=True 시)
        if data.get("auto_capture_budget") and not attachment_path:
            self._capture_and_attach_budget_screenshot()
            _save_debug(page, "03f_after_budget_capture")

        # ─────────────────────────────────────────
        # 10~22. 용도코드 → 예산과목 → 날짜 → 검증결과 (22단계 확장)
        # ─────────────────────────────────────────

        # 10. 용도코드 입력 — OBTDataGrid React interface API 사용 (세션 XI 개선)
        #     기존: window.gridView (null) → 좌표 클릭 폴백
        #     개선: React fiber → OBTDataGrid interface → setValue/getColumns
        usage_code = data.get("usage_code", "")
        if usage_code:
            try:
                # OBTDataGrid interface로 행 수 + 컬럼 정보 확인
                grid_info = page.evaluate("""() => {
                    const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                    if (!el) return null;
                    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                    if (!fk) return null;
                    let f = el[fk];
                    for (let i = 0; i < 3 && f; i++) f = f.return;
                    const iface = f?.stateNode?.state?.interface;
                    if (!iface || typeof iface.getRowCount !== 'function') return null;
                    const rowCount = iface.getRowCount();
                    const cols = iface.getColumns().map(c => ({name: c.name, header: c.header || ''}));
                    return {rowCount, cols};
                }""")

                if grid_info:
                    row_count = grid_info["rowCount"]
                    cols = grid_info["cols"]
                    logger.info(f"OBTDataGrid 행 수: {row_count}, 컬럼: {[c['header'] for c in cols[:10]]}")

                    # row_count == 0이면 렌더링이 아직 완료되지 않은 것 — 최대 3초 추가 대기
                    if row_count == 0:
                        logger.warning("step 10 진입 시 그리드 행 없음 — 렌더링 대기 (최대 3초)")
                        for _extra_wait in range(6):
                            time.sleep(0.5)
                            row_count = page.evaluate("""() => {
                                const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                if (!el) return 0;
                                const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                if (!fk) return 0;
                                let f = el[fk];
                                for (let i = 0; i < 3 && f; i++) f = f.return;
                                const iface = f?.stateNode?.state?.interface;
                                return (iface && typeof iface.getRowCount === 'function') ? iface.getRowCount() : 0;
                            }""")
                            if row_count > 0:
                                logger.info(f"step 10 추가 대기 후 그리드 행 확인: {row_count}행 ({(_extra_wait+1)*0.5:.1f}초)")
                                break
                        else:
                            logger.error("step 10 추가 대기 3초 후에도 그리드 행 없음")

                    # 용도 컬럼 찾기
                    usage_col = None
                    for c in cols:
                        if "용도" in c.get("header", "") or "usage" in c.get("name", "").lower():
                            usage_col = c
                            break
                    # cols는 초기 evaluate에서 가져온 것이므로 row_count 재조회 후 재확인 불필요
                    # (컬럼 목록은 row_count와 무관하게 동일)

                    if row_count == 0:
                        # 그리드 행이 없으면 용도코드 입력 불가 — 인보이스 재선택 실패 후 여기까지 도달한 경우
                        logger.error(
                            "그리드 행 없음 (row_count=0) — 용도코드 입력 불가, "
                            "인보이스 선택 후 그리드 렌더링이 완료되지 않았습니다. "
                            "검증 부적합 발생 가능"
                        )
                    elif usage_col and row_count > 0:
                        # OBTDataGrid interface의 setValue로 직접 셀 값 설정 시도
                        # 자동완성 트리거를 위해 셀 포커스 + 키보드 입력 방식 유지
                        filled_count = 0
                        for row_idx in range(row_count):
                            try:
                                # interface.setSelection으로 셀 포커스
                                page.evaluate(f"""() => {{
                                    const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                    let f = el[fk];
                                    for (let i = 0; i < 3; i++) f = f.return;
                                    const iface = f.stateNode.state.interface;
                                    iface.setSelection({{ rowIndex: {row_idx}, columnName: '{usage_col["name"]}' }});
                                    iface.focus();
                                }}""")
                                time.sleep(0.3)

                                # 편집 input에 용도코드 입력 (자동완성 트리거)
                                page.keyboard.type(str(usage_code), delay=30)
                                time.sleep(0.3)
                                page.keyboard.press("Enter")
                                time.sleep(0.5)  # 자동완성 반영 및 그리드 상태 업데이트 대기
                                filled_count += 1
                            except Exception:
                                continue

                        logger.info(f"용도코드 '{usage_code}' 입력: {filled_count}/{row_count}행")
                        # 용도코드 입력 완료 후 그리드 검증 상태 반영 대기
                        time.sleep(0.5)
                    else:
                        logger.warning(f"용도 컬럼 미발견 (cols: {[c['header'] for c in cols[:5]]})")
                else:
                    logger.warning("OBTDataGrid interface 미발견 — 용도코드 입력 건너뜀")

                _save_debug(page, "10_after_usage_code")
            except Exception as e:
                logger.warning(f"용도코드 입력 실패: {e}")

        # 10-1. 지급요청일도 그리드 행별 입력 (부적합 "N번 행의 지급요청일등(값)" 방지)
        #       OBTDataGrid interface로 셀 포커스 후 키보드 입력
        payment_request_date = data.get("payment_request_date", "")
        if payment_request_date and usage_code:
            try:
                clean_date = payment_request_date.replace("-", "")
                grid_info = page.evaluate("""() => {
                    const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                    if (!el) return null;
                    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                    if (!fk) return null;
                    let f = el[fk];
                    for (let i = 0; i < 3 && f; i++) f = f.return;
                    const iface = f?.stateNode?.state?.interface;
                    if (!iface || typeof iface.getRowCount !== 'function') return null;
                    const rowCount = iface.getRowCount();
                    const cols = iface.getColumns().map(c => ({name: c.name, header: c.header || ''}));
                    return {rowCount, cols};
                }""")

                if grid_info:
                    # 지급요청일 컬럼 찾기
                    pay_col = None
                    for c in grid_info["cols"]:
                        raw_h = c.get("header", "")
                        if isinstance(raw_h, dict):
                            raw_h = raw_h.get("text", "")
                        h = str(raw_h).replace(" ", "")
                        if "지급요청" in h or "지급일" in h or "payDate" in c.get("name", "").lower():
                            pay_col = c
                            break

                    if pay_col and grid_info["rowCount"] > 0:
                        filled_count = 0
                        for row_idx in range(grid_info["rowCount"]):
                            try:
                                page.evaluate(f"""() => {{
                                    const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                    let f = el[fk];
                                    for (let i = 0; i < 3; i++) f = f.return;
                                    const iface = f.stateNode.state.interface;
                                    iface.setSelection({{ rowIndex: {row_idx}, columnName: '{pay_col["name"]}' }});
                                    iface.focus();
                                }}""")
                                time.sleep(0.2)
                                page.keyboard.type(clean_date, delay=20)
                                time.sleep(0.2)
                                page.keyboard.press("Tab")
                                time.sleep(0.2)
                                filled_count += 1
                            except Exception:
                                continue
                        logger.info(f"지급요청일 '{payment_request_date}' 그리드 입력: {filled_count}/{grid_info['rowCount']}행")
                    else:
                        logger.warning("지급요청일 컬럼 미발견")
                _save_debug(page, "10_1_after_payment_date_grid")
            except Exception as e:
                logger.warning(f"지급요청일 그리드 입력 실패: {e}")

        # 11. 용도코드 입력 후 동적 예산 필드 출현 대기
        #     (용도코드 입력 시 하단에 예산과목/예산화계단위/예산프로젝트 필드 동적 생성)
        budget_keyword = data.get("budget_keyword", "")
        if usage_code and budget_keyword:
            time.sleep(1.0)  # 동적 필드 렌더링 대기
            _save_debug(page, "11_after_usage_code_dynamic_fields")

            # 12~17. 예산과목 선택 (공통 예산잔액 조회 팝업)
            try:
                from src.approval.budget_helpers import select_budget_code
                budget_result = select_budget_code(
                    page=page,
                    project_keyword=project.split(". ")[-1].split("]")[-1].strip() if project else "",
                    budget_keyword=budget_keyword,
                )
                if budget_result["success"]:
                    logger.info(f"예산과목 설정 완료: {budget_result['budget_code']}. {budget_result['budget_name']}")
                else:
                    logger.warning(f"예산과목 설정 실패: {budget_result['message']}")
                _save_debug(page, "17_after_budget_code")
            except Exception as e:
                logger.error(f"예산과목 선택 예외: {e}")

        # 18~19. 지급요청일 선택 (하단 날짜피커)
        payment_request_date = data.get("payment_request_date", "")
        if payment_request_date:
            try:
                clean_date = payment_request_date.replace("-", "")
                # "지급요청일" 라벨 옆의 날짜 input 찾기
                date_inputs = page.locator(
                    "input.OBTDatePickerRebuild_inputYMD__PtxMy, "
                    "input[class*='OBTDatePickerRebuild_inputYMD']"
                ).all()
                filled = False
                for inp in date_inputs:
                    try:
                        if not inp.is_visible():
                            continue
                        box = inp.bounding_box()
                        if not box:
                            continue
                        # 지급요청일: 증빙일자(y≈857)보다 오른쪽 또는 약간 아래 (x≈870~930, y≈855~870)
                        # 증빙일자와 구분: x 위치로 판별 (지급요청일은 x>800)
                        if box["y"] > 800 and box["x"] > 750:
                            inp.click(force=True)
                            inp.fill(clean_date)
                            inp.press("Tab")
                            logger.info(f"지급요청일 입력: {payment_request_date}")
                            filled = True
                            break
                    except Exception:
                        continue

                if not filled:
                    # 폴백: 캘린더 아이콘 직접 클릭 방식
                    # "지급요청일" 텍스트 옆 캘린더 아이콘
                    try:
                        label = page.locator("th:has-text('지급요청일'), td:has-text('지급요청일')").first
                        if label.is_visible(timeout=2000):
                            cal_icon = label.locator("xpath=following::button[1]")
                            if cal_icon.is_visible(timeout=1000):
                                cal_icon.click()
                                time.sleep(0.5)
                                # 날짜 피커에서 날짜 선택 (오늘 날짜 또는 지정 날짜)
                                # YYYY-MM-DD에서 일(day) 추출
                                day = str(int(payment_request_date.split("-")[-1]))
                                day_cell = page.locator(f"td:has-text('{day}')").first
                                if day_cell.is_visible(timeout=3000):
                                    day_cell.click()
                                    logger.info(f"지급요청일 캘린더 선택: {payment_request_date}")
                                    filled = True
                    except Exception:
                        pass

                if not filled:
                    logger.warning(f"지급요청일 입력 실패: {payment_request_date}")
                _save_debug(page, "19_after_payment_request_date")
            except Exception as e:
                logger.warning(f"지급요청일 처리 중 오류: {e}")

        # 20~21. 회계처리일자 변경 (상단, 세금계산서 발행월과 일치 필요)
        accounting_date = data.get("accounting_date", "")
        if accounting_date:
            try:
                clean_date = accounting_date.replace("-", "")
                # 상단 "회계처리일자" 날짜 input (y<200 영역)
                date_inputs = page.locator(
                    "input.OBTDatePickerRebuild_inputYMD__PtxMy, "
                    "input[class*='OBTDatePickerRebuild_inputYMD']"
                ).all()
                filled = False
                for inp in date_inputs:
                    try:
                        if not inp.is_visible():
                            continue
                        box = inp.bounding_box()
                        if not box:
                            continue
                        # 회계처리일자: 상단 영역 (y < 200)
                        if box["y"] < 200:
                            inp.click(force=True)
                            inp.fill(clean_date)
                            inp.press("Tab")
                            logger.info(f"회계처리일자 변경: {accounting_date}")
                            filled = True
                            break
                    except Exception:
                        continue

                if not filled:
                    # 폴백: "회계처리일자" 라벨 기반
                    try:
                        label = page.locator(
                            "th:has-text('회계처리일자'), "
                            "td:has-text('회계처리일자'), "
                            "span:has-text('회계처리일자')"
                        ).first
                        if label.is_visible(timeout=2000):
                            date_inp = label.locator("xpath=following::input[1]")
                            if date_inp.is_visible(timeout=1000):
                                date_inp.click(force=True)
                                date_inp.fill(clean_date)
                                date_inp.press("Tab")
                                logger.info(f"회계처리일자 변경 (라벨 폴백): {accounting_date}")
                                filled = True
                    except Exception:
                        pass

                if not filled:
                    logger.warning(f"회계처리일자 변경 실패: {accounting_date}")

                time.sleep(0.5)  # 검증결과 갱신 대기
                _save_debug(page, "21_after_accounting_date")
            except Exception as e:
                logger.warning(f"회계처리일자 처리 중 오류: {e}")

        # 22. 검증결과 확인 ("적합" / "부적합")
        try:
            time.sleep(0.5)  # 검증 결과 갱신 완료 대기
            validation_text = ""
            # 그리드 마지막 열 "검증결과" 셀 텍스트 확인
            validation_selectors = [
                "div[class*='rg-cell']:has-text('적합')",
                "td:has-text('적합')",
                "span:has-text('적합')",
                "div[class*='rg-cell']:has-text('부적합')",
                "td:has-text('부적합')",
            ]
            for sel in validation_selectors:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        validation_text = el.inner_text(timeout=1000).strip()
                        break
                except Exception:
                    continue

            if "적합" in validation_text and "부적합" not in validation_text:
                logger.info(f"검증결과: 적합 ✓")
            elif "부적합" in validation_text:
                # 부적합 시 셀 호버 → 툴팁으로 미비 사항 확인
                tooltip_text = ""
                try:
                    el = page.locator(
                        "div[class*='rg-cell']:has-text('부적합'), "
                        "td:has-text('부적합'), "
                        "span:has-text('부적합')"
                    ).first
                    if el.is_visible(timeout=1000):
                        el.hover()
                        time.sleep(0.5)
                        # 툴팁 텍스트 추출 (title 속성 또는 동적 tooltip div)
                        tooltip_text = el.get_attribute("title") or ""
                        if not tooltip_text:
                            tooltip_el = page.locator(
                                "div[class*='tooltip'], "
                                "div[class*='Tooltip'], "
                                "div[role='tooltip']"
                            ).first
                            try:
                                if tooltip_el.is_visible(timeout=2000):
                                    tooltip_text = tooltip_el.inner_text(timeout=1000).strip()
                            except Exception:
                                pass
                except Exception:
                    pass
                logger.warning(f"검증결과: 부적합 ✗ — {tooltip_text or '미비 사항 확인 필요'}")
            else:
                logger.info("검증결과 셀을 찾을 수 없음 (용도코드/예산과목 미입력 시 정상)")

            _save_debug(page, "22_after_validation_check")
        except Exception as e:
            logger.debug(f"검증결과 확인 중 오류: {e}")

    # ─────────────────────────────────────────
    # 지출내역 그리드 입력
    # ─────────────────────────────────────────

    # 그리드 컬럼 헤더 텍스트 → 인덱스 매핑 (0-based, 체크박스 제외)
    # ─────────────────────────────────────────
    # Task #4: 프로젝트 코드도움 / 증빙유형 / 증빙일자 / 첨부파일
    # ─────────────────────────────────────────

    def _fill_project_code(self, project: str, y_hint: float = None):
        """
        프로젝트 코드도움 모달 기반 입력.

        GW OBT 위젯 동작:
        1. placeholder="프로젝트코드도움" input 클릭 → "프로젝트코드도움" 모달 열림
        2. 모달 검색어 필드에 키워드 입력 → Enter 또는 돋보기 클릭
        3. 필터된 결과에서 행 클릭 → 확인

        Args:
            project: 프로젝트 코드 또는 이름 일부 (예: '메디빌더', 'GS-25-0088')
            y_hint: 특정 y좌표 근처 input 선택 시 사용 (None이면 첫 번째 visible)
        """
        page = self.page

        # 1. 프로젝트 input 클릭 → 모달 트리거
        try:
            all_proj_inputs = page.locator("input[placeholder='프로젝트코드도움']").all()
            proj_input = None

            if y_hint is not None:
                best_dist = float("inf")
                for inp in all_proj_inputs:
                    try:
                        box = inp.bounding_box()
                        if box:
                            dist = abs(box["y"] - y_hint)
                            if dist < best_dist:
                                best_dist = dist
                                proj_input = inp
                    except Exception:
                        continue
            else:
                for inp in all_proj_inputs:
                    try:
                        if inp.is_visible(timeout=1000):
                            proj_input = inp
                            break
                    except Exception:
                        continue

            if proj_input and proj_input.is_visible(timeout=3000):
                proj_input.click()
                time.sleep(0.3)
                proj_input.click(click_count=3)  # 전체 선택
                time.sleep(0.2)
                page.keyboard.type(project, delay=80)
                logger.info(f"프로젝트 검색어 입력: {project}")
        except Exception as e:
            logger.warning(f"프로젝트 input 클릭 실패: {e}")
            return False

        # 2. "프로젝트코드도움" 모달 대기
        time.sleep(1)
        modal_visible = False
        try:
            title_el = page.locator("text=프로젝트코드도움").first
            if title_el.is_visible(timeout=3000):
                modal_visible = True
                logger.info("프로젝트코드도움 모달 열림")
        except Exception:
            pass

        if not modal_visible:
            # 모달이 안 열린 경우 — input에서 Enter 시도
            try:
                proj_input.press("Enter")
                time.sleep(1)
                title_el = page.locator("text=프로젝트코드도움").first
                if title_el.is_visible(timeout=3000):
                    modal_visible = True
            except Exception:
                pass

        if not modal_visible:
            logger.warning("프로젝트코드도움 모달 미열림")
            return False

        # 3. 모달 내 검색어 확인 + 돋보기(조회) 버튼 클릭
        try:
            # JS로 모달 컨테이너 내부의 검색 input 찾기 (OBTDialog2 overlay 문제 회피)
            modal_search_idx = page.evaluate("""() => {
                // "프로젝트코드도움" 텍스트를 포함하는 다이얼로그 컨테이너 찾기
                const allEls = document.querySelectorAll('[class*="OBTDialog"], [class*="modal"], [role="dialog"]');
                for (const container of allEls) {
                    if (!container.textContent.includes('프로젝트코드도움')) continue;
                    const inputs = container.querySelectorAll('input:not([disabled])');
                    for (const inp of inputs) {
                        if (inp.type === 'text' || inp.type === '') {
                            // 모달 전체 input 중 인덱스 반환
                            const allInputs = [...document.querySelectorAll('input')];
                            return allInputs.indexOf(inp);
                        }
                    }
                }
                // 폴백: "검색어" 라벨 근처 input
                const labels = document.querySelectorAll('label, span, td');
                for (const lbl of labels) {
                    if (lbl.textContent.trim() === '검색어') {
                        const parent = lbl.closest('tr') || lbl.parentElement;
                        if (parent) {
                            const inp = parent.querySelector('input:not([disabled])');
                            if (inp) {
                                const allInputs = [...document.querySelectorAll('input')];
                                return allInputs.indexOf(inp);
                            }
                        }
                    }
                }
                return -1;
            }""")

            modal_search = None
            if modal_search_idx >= 0:
                modal_search = page.locator("input").nth(modal_search_idx)
                current_val = modal_search.input_value()
                if project.lower() not in current_val.lower():
                    modal_search.click(force=True)
                    modal_search.fill(project)
                logger.info(f"모달 검색어: {modal_search.input_value()}")
            else:
                logger.warning("모달 내 검색 input을 찾지 못함")

            # 돋보기(조회) 버튼 클릭
            # DOM 확인: OBTConditionPanel_searchButton 클래스, img[src*='search'] 포함
            search_btn_clicked = False

            # 방법 1: OBTConditionPanel_searchButton 클래스 (정확한 셀렉터)
            try:
                search_btn = page.locator("button[class*='searchButton']")
                if search_btn.first.is_visible(timeout=2000):
                    search_btn.first.click()
                    search_btn_clicked = True
                    logger.info("프로젝트 돋보기 클릭 (searchButton 클래스)")
            except Exception:
                pass

            # 방법 2: 검색 아이콘 이미지를 포함하는 버튼
            if not search_btn_clicked:
                try:
                    icon_btn = page.locator("button:has(img[src*='search'])")
                    if icon_btn.first.is_visible(timeout=1500):
                        icon_btn.first.click()
                        search_btn_clicked = True
                        logger.info("프로젝트 돋보기 클릭 (img[src*='search'])")
                except Exception:
                    pass

            # 방법 3: 검색 input과 같은 y에 있는 소형 버튼
            if not search_btn_clicked and modal_search:
                try:
                    search_box = modal_search.bounding_box()
                    if search_box:
                        btns = page.locator("button").all()
                        for btn in btns:
                            box = btn.bounding_box()
                            if not box:
                                continue
                            # 같은 y (±10px), 검색 input 오른쪽, 소형
                            if (abs(box["y"] - search_box["y"]) < 15
                                    and box["x"] > search_box["x"] + search_box["width"] - 10
                                    and box["width"] < 40 and box["height"] < 40):
                                btn.click()
                                search_btn_clicked = True
                                logger.info(f"프로젝트 돋보기 클릭 (input 옆, x={box['x']:.0f} y={box['y']:.0f})")
                                break
                except Exception:
                    pass

            if not search_btn_clicked and modal_search:
                modal_search.press("Enter")
                logger.info("프로젝트 검색 Enter 폴백")

            time.sleep(1.5)
        except Exception as e:
            logger.warning(f"모달 검색 실패: {e}")

        _save_debug(page, "proj_modal_search_result")

        # 4. 검색 결과에서 첫 번째 데이터 행 더블클릭 (좌표 기반)
        # OBTGrid는 canvas 기반이라 DOM 행 요소가 없음 → 모달 제목 기준 상대좌표 사용
        selected = False
        try:
            title_box = page.locator("text=프로젝트코드도움").first.bounding_box()
            if title_box:
                # 모달 레이아웃: 제목(y) → 검색바(+35) → 헤더(+65) → 첫 데이터 행(+85)
                first_row_x = title_box["x"] + 200  # 모달 중앙
                first_row_y = title_box["y"] + 95    # 첫 데이터 행 중앙

                # 더블클릭으로 행 선택 (사용자 확인: 더블클릭 = 선택 + 모달 닫기)
                page.mouse.dblclick(first_row_x, first_row_y)
                logger.info(f"프로젝트 첫 행 더블클릭: ({first_row_x:.0f}, {first_row_y:.0f})")
                selected = True
                time.sleep(1.0)
        except Exception as e:
            logger.warning(f"프로젝트 좌표 더블클릭 실패: {e}")

        # 5. 모달이 아직 열려있으면 확인 버튼 클릭
        if selected:
            modal_still_open = False
            try:
                modal_still_open = page.locator("text=프로젝트코드도움").first.is_visible(timeout=1500)
            except Exception:
                pass

            if modal_still_open:
                # 확인 버튼 클릭
                try:
                    cancel_btns = page.locator("button:has-text('취소')").all()
                    confirm_btns = page.locator("button:has-text('확인')").all()
                    clicked = False
                    for cb in cancel_btns:
                        cb_box = cb.bounding_box()
                        if not cb_box:
                            continue
                        for btn in confirm_btns:
                            b_box = btn.bounding_box()
                            if b_box and abs(b_box["y"] - cb_box["y"]) < 15:
                                btn.click()
                                logger.info(f"프로젝트 모달 확인 클릭 (y={b_box['y']:.0f})")
                                clicked = True
                                break
                        if clicked:
                            break
                    if not clicked:
                        page.locator("button:has-text('확인')").last.click()
                        logger.info("프로젝트 모달 확인 클릭 (폴백)")
                    time.sleep(0.5)
                except Exception:
                    pass
            else:
                logger.info("프로젝트 더블클릭으로 모달 자동 닫힘")
        else:
            try:
                page.locator("button:has-text('취소')").last.click()
                time.sleep(0.3)
            except Exception:
                pass
            logger.warning("프로젝트 좌표 선택 실패")

        # 6. 모달 닫힘 대기
        for _ in range(10):
            try:
                if not page.locator("text=프로젝트코드도움").first.is_visible(timeout=200):
                    break
            except Exception:
                break
            time.sleep(0.3)

        return selected

    def _click_evidence_type_button(self, evidence_type: str):
        """
        증빙유형 버튼 클릭 (그리드 상단).

        지원 유형 및 DOM 좌표 (form_frame_buttons.json 기준):
        - '세금계산서' / '계산서내역': x=1476, y=373
        - '카드사용내역': x=1384, y=373
        - '현금영수증': x=1557, y=373

        Args:
            evidence_type: '세금계산서', '계산서내역', '카드사용내역', '현금영수증'
        """
        page = self.page

        # 버튼 텍스트 정규화
        type_map = {
            "세금계산서": "계산서내역",
            "계산서": "계산서내역",
            "계산서내역": "계산서내역",
            "카드": "카드사용내역",
            "카드사용": "카드사용내역",
            "카드사용내역": "카드사용내역",
            "현금영수증": "현금영수증",
            "현금": "현금영수증",
        }
        btn_text = type_map.get(evidence_type, evidence_type)

        # 버튼 좌표 (DOM 데이터 기준)
        coord_map = {
            "계산서내역": (1476, 373),
            "카드사용내역": (1384, 373),
            "현금영수증": (1557, 373),
        }

        # 방법 1: 텍스트 기반으로 모든 요소 타입 검색 (button, div, span, a 등)
        # GW 탭은 button이 아닐 수 있음
        selectors = [
            f"text='{btn_text}'",
            f"button:has-text('{btn_text}')",
            f"div:has-text('{btn_text}')",
            f"span:has-text('{btn_text}')",
            f"a:has-text('{btn_text}')",
        ]
        # 지출내역 헤더 y 기준점 (fullscreen 호환)
        grid_y_min, grid_y_max = 200, 600  # 넉넉한 기본 범위
        try:
            header_el = page.locator("text='지출내역'").first
            if header_el.is_visible(timeout=1000):
                hbox = header_el.bounding_box()
                if hbox:
                    grid_y_min = hbox["y"] - 10
                    grid_y_max = hbox["y"] + 120
        except Exception:
            pass

        for sel in selectors:
            try:
                elements = page.locator(sel).all()
                for el in elements:
                    if el.is_visible():
                        box = el.bounding_box()
                        if not box:
                            continue
                        # 지출내역 탭 영역 + 크기 필터
                        if grid_y_min < box["y"] < grid_y_max and box["width"] < 200:
                            el_text = el.inner_text().strip()
                            if btn_text in el_text:
                                el.click()
                                logger.info(f"증빙유형 버튼 클릭: '{btn_text}' (sel={sel}, y={box['y']:.0f})")
                                return True
            except Exception:
                continue

        # 방법 2: get_by_text (정확한 텍스트 매칭)
        try:
            el = page.get_by_text(btn_text, exact=True).first
            if el.is_visible(timeout=2000):
                box = el.bounding_box()
                if box and box["y"] > 300:
                    el.click()
                    logger.info(f"증빙유형 버튼 클릭 (get_by_text): '{btn_text}' (y={box['y']:.0f})")
                    return True
        except Exception:
            pass

        # 방법 3: 좌표 폴백
        coords = coord_map.get(btn_text)
        if coords:
            try:
                page.mouse.click(*coords)
                logger.info(f"증빙유형 버튼 클릭 (좌표 {coords}): '{btn_text}'")
                return True
            except Exception as e:
                logger.warning(f"증빙유형 좌표 클릭 실패: {e}")

        logger.warning(f"증빙유형 버튼 미발견: '{evidence_type}'")
        return False

    def _select_invoice_in_modal(
        self,
        vendor: str = "",
        amount: float = None,
        date_from: str = "",
        date_to: str = "",
    ) -> bool:
        """
        계산서내역 DOM 모달("매입(세금)계산서 내역")에서 세금계산서를 검색/선택.

        계산서내역 버튼 클릭 후 같은 페이지에 오버레이 모달이 열림 (window.open 아님).
        모달 구조:
        - 제목: "매입(세금)계산서 내역"
        - 사업장, 작성일자 (시작~종료)
        - 미반영/반영완료 탭
        - 테이블: 작성일자, 거래처, 사업자번호, 수신메일, 공급가액, 세액, 합계금액, ...
        - 체크박스로 행 선택
        - 취소/확인 버튼
        """
        import datetime as _dt

        page = self.page

        def _norm(d: str, fmt: str = "%Y%m%d") -> str:
            """날짜 문자열 정규화 (YYYY-MM-DD / YYYYMMDD / YYYY.MM.DD → 지정 포맷)"""
            d = d.replace("-", "").replace(".", "")[:8]
            if fmt == "%Y-%m-%d" and len(d) == 8:
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            return d

        # 기본 기간: ±6개월 (3개월에서 확장 — 분기 지연 발행 계산서 대응)
        today = _dt.date.today()
        if not date_from:
            start = (today.replace(day=1) - _dt.timedelta(days=180)).replace(day=1)
            date_from = start.strftime("%Y-%m-%d")
        else:
            date_from = _norm(date_from, "%Y-%m-%d")
        if not date_to:
            next_m = today.replace(day=28) + _dt.timedelta(days=4)
            date_to = (next_m.replace(day=1) - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            date_to = _norm(date_to, "%Y-%m-%d")

        logger.info(f"계산서 모달 검색 — vendor='{vendor}' amount={amount} 기간={date_from}~{date_to}")

        # ── 모달 표시 대기 ──
        # "매입(세금)계산서 내역" 제목이 보일 때까지 대기
        modal_visible = False
        for _ in range(20):  # 최대 5초
            try:
                title_el = page.locator("text=매입(세금)계산서 내역").first
                if title_el.is_visible(timeout=250):
                    modal_visible = True
                    break
            except Exception:
                pass
            time.sleep(0.25)

        if not modal_visible:
            logger.warning("계산서 모달 미표시")
            _save_debug(page, "invoice_modal_not_found")
            return False

        logger.info("계산서 모달 표시 확인")

        # ── 모달 내 날짜 설정 ──
        # 모달의 "작성일자" 날짜 필드: "매입(세금)계산서 내역" 제목 아래 영역
        # JavaScript로 모달 내 date input을 직접 찾아서 설정
        try:
            date_set = page.evaluate(f"""() => {{
                // 모달 내 date input 찾기 (maxlength 8 또는 10, 모달 영역 내)
                const allInputs = document.querySelectorAll('input[type="text"]');
                const dateInputs = [];
                for (const inp of allInputs) {{
                    const rect = inp.getBoundingClientRect();
                    // 모달 영역 (화면 중앙, y 100~250 근처)
                    if (rect.y > 100 && rect.y < 300 && rect.x > 300 && rect.x < 900) {{
                        const ml = inp.maxLength;
                        const val = inp.value || '';
                        // 날짜 형식 (YYYY-MM-DD 또는 YYYYMMDD)
                        if ((ml == 8 || ml == 10 || ml == -1) && /\\d/.test(val)) {{
                            dateInputs.push(inp);
                        }}
                    }}
                }}
                return dateInputs.length;
            }}""")
            logger.info(f"모달 내 날짜 input 수: {date_set}")
        except Exception:
            pass

        # 날짜 입력: 모달 내 "작성일자" 레이블 옆 input들
        try:
            # "작성일자" 텍스트 근처의 날짜 input 찾기
            date_label = page.locator("text=작성일자").first
            if date_label.is_visible(timeout=2000):
                # 작성일자 옆의 날짜 range — 부모 컨테이너 내 input 찾기
                parent = date_label.locator("xpath=ancestor::div[1]")
                date_inputs = parent.locator("input").all()
                if not date_inputs or len(date_inputs) < 2:
                    # 더 넓은 범위: 같은 행/div 내 input
                    parent = date_label.locator("xpath=ancestor::div[2]")
                    date_inputs = parent.locator("input").all()

                if len(date_inputs) >= 2:
                    # 시작일
                    date_inputs[0].triple_click()
                    date_inputs[0].fill(date_from)
                    date_inputs[0].press("Tab")
                    time.sleep(0.3)
                    # 종료일
                    date_inputs[1].triple_click()
                    date_inputs[1].fill(date_to)
                    date_inputs[1].press("Tab")
                    logger.info(f"모달 기간 설정: {date_from}~{date_to}")
                else:
                    logger.warning(f"모달 날짜 input 부족: {len(date_inputs)}개")
            else:
                logger.warning("'작성일자' 레이블 미발견")
        except Exception as e:
            logger.warning(f"모달 날짜 설정 실패: {e}")

        # ── 조회 버튼 클릭 ──
        # 모달 내 "조회" 버튼 또는 돋보기 아이콘 버튼 클릭
        search_clicked = False
        try:
            for sel in [
                "button:has-text('조회')",
                "button:has-text('검색')",
                "button[class*='search']",
                "button[class*='Search']",
                "button[title*='조회']",
                "button[title*='검색']",
                "span:has-text('조회') >> xpath=ancestor::button",
            ]:
                try:
                    btns = page.locator(sel).all()
                    for btn in btns:
                        box = btn.bounding_box()
                        if not box:
                            continue
                        # 모달 영역 내 (y: 150~350)
                        if 100 < box["y"] < 400 and 100 < box["x"] < 1400:
                            if btn.is_visible():
                                btn.click(force=True)
                                logger.info(f"모달 조회 버튼 클릭: {sel}")
                                search_clicked = True
                                break
                    if search_clicked:
                        break
                except Exception:
                    continue
        except Exception:
            pass

        if not search_clicked:
            # 폴백: Enter 키
            try:
                page.keyboard.press("Enter")
                logger.info("모달 조회 — Enter 키")
            except Exception:
                pass

        # 결과 로드 대기
        time.sleep(2)
        _save_debug(page, "invoice_modal_search_result")

        # ── 미반영 탭 확인 ──
        try:
            tab = page.locator("text=미반영").first
            if tab.is_visible(timeout=1000):
                tab.click(force=True)
                time.sleep(0.5)
        except Exception:
            pass

        # ── 결과 테이블에서 행 선택 (체크박스 클릭) ──
        # GW 모달의 체크박스는 커스텀 컴포넌트 (OBTCheckBox)일 수 있음
        # → input[type=checkbox], div[class*='check'], label 등 다양한 셀렉터 시도
        selected = False

        # ── 방법 0: OBTDataGrid React Fiber API로 모달 내 그리드 첫 행 선택 ──
        logger.info("방법 0: OBTDataGrid React Fiber — 모달 내 그리드 첫 행 선택 시도")
        try:
            react_selected = page.evaluate("""() => {
                // 모달 영역 내 OBTDataGrid 찾기
                const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl');
                for (const grid of grids) {
                    const rect = grid.getBoundingClientRect();
                    // 모달은 화면 상단~중간 (y: 100~700), 전체 화면이 아닌 오버레이
                    if (rect.y < 100 || rect.y > 700) continue;

                    // React Fiber 키 찾기
                    const fKey = Object.keys(grid).find(k => k.startsWith('__reactFiber'));
                    if (!fKey) continue;
                    let node = grid[fKey];

                    // interface 탐색 (depth 최대 10)
                    for (let i = 0; i < 10; i++) {
                        if (!node) break;
                        if (node.stateNode && node.stateNode.state && node.stateNode.state.interface) {
                            const iface = node.stateNode.state.interface;
                            if (typeof iface.getRowCount === 'function') {
                                const rowCount = iface.getRowCount();
                                if (rowCount > 0) {
                                    // 첫 번째 데이터 행 선택
                                    iface.setSelection({ rowIndex: 0, columnIndex: 0 });
                                    iface.focus({ rowIndex: 0, columnIndex: 0 });
                                    if (typeof iface.commit === 'function') iface.commit();
                                    return { success: true, rowCount: rowCount };
                                } else {
                                    return { success: false, rowCount: 0 };
                                }
                            }
                        }
                        // child 우선, 없으면 sibling
                        node = node.child || node.sibling || node.return;
                    }
                }
                return { success: false, rowCount: -1 };
            }""")

            if react_selected and react_selected.get("success"):
                logger.info(f"방법 0 성공: OBTDataGrid 첫 행 선택 (전체 {react_selected.get('rowCount')}행)")
                selected = True
                time.sleep(0.5)
            elif react_selected and react_selected.get("rowCount") == 0:
                logger.warning("방법 0: 모달 그리드 데이터 없음 (0건)")
                # 데이터 없는 경우 취소
                try:
                    page.locator("button:has-text('취소')").last.click(force=True)
                except Exception:
                    pass
                return False
            else:
                logger.info(f"방법 0 미적용 (결과: {react_selected}) → 기존 방법으로 폴백")
        except Exception as e:
            logger.info(f"방법 0 예외 (무시): {e}")

        if not selected:
            # 방법 1: JavaScript로 모달 영역 내 체크박스 요소 직접 탐색
            checkbox_count = 0
            try:
                checkbox_count = page.evaluate("""() => {
                    // 모달 영역(y < 650) 내 체크박스 역할 요소 찾기
                    let count = 0;
                    const elems = document.querySelectorAll(
                        'input[type="checkbox"], [role="checkbox"], [class*="checkbox"], [class*="Checkbox"]'
                    );
                    for (const el of elems) {
                        const rect = el.getBoundingClientRect();
                        if (rect.y > 150 && rect.y < 650 && rect.x < 200) {
                            count++;
                        }
                    }
                    return count;
                }""")
                logger.info(f"JS 체크박스 탐지: {checkbox_count}개")
            except Exception:
                pass

            # 방법 2: 다양한 체크박스 셀렉터 시도
            cb_selectors = [
                "input[type='checkbox']",
                "[role='checkbox']",
                "div[class*='checkbox']",
                "div[class*='Checkbox']",
                "div[class*='check']",
                "label[class*='check']",
                "span[class*='check']",
            ]
            modal_checkboxes = []
            for sel in cb_selectors:
                try:
                    all_cbs = page.locator(sel).all()
                    for cb in all_cbs:
                        try:
                            box = cb.bounding_box()
                            # 모달 영역 내 (y: 180~600, x: < 200)
                            if box and 180 < box["y"] < 600 and box["x"] < 200:
                                modal_checkboxes.append((box["y"], cb))
                        except Exception:
                            continue
                    if modal_checkboxes:
                        logger.info(f"체크박스 셀렉터 매칭: {sel} ({len(modal_checkboxes)}개)")
                        break
                except Exception:
                    continue

            # 방법 3: 체크박스를 못 찾으면 모달 기준 상대 좌표로 폴백
            if not modal_checkboxes:
                logger.info("셀렉터로 체크박스 미발견 — 모달 기준 상대 좌표 클릭")
                # "데이터가 존재하지 않습니다" 확인
                try:
                    no_data = page.locator("text=데이터가 존재하지 않습니다").first
                    if no_data.is_visible(timeout=1000):
                        logger.warning("계산서 모달: 데이터가 존재하지 않습니다")
                        try:
                            page.locator("button:has-text('취소')").last.click(force=True)
                        except Exception:
                            pass
                        return False
                except Exception:
                    pass

                # 건수 확인
                try:
                    count_text = page.evaluate("""() => {
                        const all = document.querySelectorAll('*');
                        for (const e of all) {
                            const t = e.textContent?.trim() || '';
                            const rect = e.getBoundingClientRect();
                            if (/^\\d+건$/.test(t) && rect.width < 80 && rect.height < 30) {
                                return t;
                            }
                        }
                        return '';
                    }""")
                    if count_text:
                        logger.info(f"모달 건수: {count_text}")
                except Exception:
                    pass

                # 모달 제목 위치 기준으로 상대 좌표 계산
                # 제목 "매입(세금)계산서 내역" 위치를 기준점으로 사용
                try:
                    title_box = page.locator("text=매입(세금)계산서 내역").first.bounding_box()
                    if title_box:
                        modal_x = title_box["x"]  # 모달 왼쪽 x
                        modal_top = title_box["y"]  # 모달 상단 y
                        # 첫 데이터 행 체크박스: 제목으로부터 약 +215px 아래, 모달 좌측 +10px
                        # ★ +185는 헤더 전체선택 체크박스 → +215로 첫 데이터 행만 선택
                        cb_x = modal_x + 10
                        # 뷰포트 높이 조회 후 비례 보정 (1920×1080 기준 215px)
                        try:
                            viewport_height = page.viewport_size["height"] if page.viewport_size else 1080
                        except Exception:
                            viewport_height = 1080
                        base_offset = 215
                        scale = viewport_height / 1080
                        cb_offset = max(180, min(260, int(base_offset * scale)))
                        cb_y = modal_top + cb_offset
                        logger.info(f"체크박스 좌표: modal_top={modal_top:.0f}, offset={cb_offset}px (scale={scale:.2f})")
                        page.mouse.click(cb_x, cb_y)
                        time.sleep(0.3)
                        _save_debug(page, "invoice_modal_coord_click")
                        logger.info(f"체크박스 상대 좌표 클릭 (1건): ({cb_x:.0f}, {cb_y:.0f}) (제목 기준)")
                        selected = True
                    else:
                        raise ValueError("모달 제목 위치 미확인")
                except Exception as e:
                    # 최종 폴백: JavaScript로 첫 번째 테이블 행 찾기
                    logger.warning(f"상대 좌표 실패: {e}, JS 폴백 시도")
                    try:
                        first_row = page.evaluate("""() => {
                            const trs = document.querySelectorAll('tr');
                            for (const tr of trs) {
                                const rect = tr.getBoundingClientRect();
                                const text = tr.textContent || '';
                                if (rect.height > 20 && rect.height < 50 && text.includes('20') && rect.y > 200) {
                                    return {x: rect.x + 15, y: rect.y + rect.height/2};
                                }
                            }
                            return null;
                        }""")
                        if first_row:
                            page.mouse.click(first_row["x"], first_row["y"])
                            logger.info(f"체크박스 JS 폴백 클릭: ({first_row['x']:.0f}, {first_row['y']:.0f})")
                            selected = True
                    except Exception:
                        pass
                    if not selected:
                        _save_debug(page, "invoice_modal_coord_click")
                        logger.warning("계산서 체크박스 클릭 실패")
            else:
                # 체크박스 정렬 (y 순서)
                modal_checkboxes.sort(key=lambda x: x[0])

                # 헤더 체크박스 제외 (첫 번째와 두 번째 y 차이가 15px 이상이면 헤더)
                data_checkboxes = [cb for _, cb in modal_checkboxes]
                if len(modal_checkboxes) > 1 and (modal_checkboxes[1][0] - modal_checkboxes[0][0]) > 15:
                    data_checkboxes = [cb for _, cb in modal_checkboxes[1:]]
                    logger.info(f"헤더 제외 → 데이터 체크박스 {len(data_checkboxes)}개")

                # vendor/amount 매칭
                for cb in data_checkboxes:
                    try:
                        row = cb.locator("xpath=ancestor::tr[1]")
                        rt = row.inner_text().strip()
                        if "데이터가 존재하지 않습니다" in rt or rt.startswith("합계"):
                            continue
                        vendor_ok = (not vendor) or (vendor in rt)
                        amount_ok = True
                        if amount is not None:
                            import re as _re
                            nums = [int(n.replace(",", "")) for n in _re.findall(r"[\d,]+", rt)
                                    if n.replace(",", "").isdigit() and len(n.replace(",", "")) >= 3]
                            amount_ok = any(abs(a - int(amount)) < max(1000, int(amount) * 0.01) for a in nums)
                        if vendor_ok and amount_ok:
                            cb.click(force=True)
                            logger.info(f"계산서 체크박스 선택: {rt[:60]}")
                            selected = True
                            break
                    except Exception:
                        continue
                if not selected and data_checkboxes:
                    try:
                        data_checkboxes[0].click(force=True)
                        logger.info("계산서 첫 행 체크박스 선택")
                        selected = True
                    except Exception as e:
                        logger.warning(f"첫 행 체크박스 선택 실패: {e}")

        _save_debug(page, "invoice_modal_row_selected")

        if not selected:
            logger.warning("계산서 모달에서 선택할 행이 없습니다")
            # 모달 취소 (선택 없이 닫기)
            try:
                page.locator("button:has-text('취소')").last.click(force=True)
                time.sleep(0.5)
            except Exception:
                pass
            # 계산서내역 버튼이 활성화된 상태로 남을 수 있으므로 다시 클릭해 비활성화 시도
            try:
                for sel in [
                    "button:has-text('계산서내역')",
                    "span:has-text('계산서내역')",
                    "div:has-text('계산서내역'):visible",
                ]:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=500):
                        btn.click(force=True)
                        logger.info("계산서내역 버튼 재클릭 (비활성화)")
                        time.sleep(0.3)
                        break
            except Exception:
                pass
            return False

        # ── 확인 버튼 클릭 ──
        # 모달 하단의 "확인" 버튼 (파란색) — 모달 제목 기준 상대 위치
        confirmed = False
        try:
            # "취소"와 "확인" 버튼은 나란히 있음. 취소 옆의 확인 버튼 찾기
            cancel_btn = page.locator("button:has-text('취소')").all()
            for cb in cancel_btn:
                try:
                    cb_box = cb.bounding_box()
                    if not cb_box:
                        continue
                    # 모달 하단의 취소 버튼 (제목과 같은 x 영역)
                    confirm_btns = page.locator("button:has-text('확인')").all()
                    for btn in confirm_btns:
                        b_box = btn.bounding_box()
                        if b_box and abs(b_box["y"] - cb_box["y"]) < 10:
                            # 같은 행의 확인 버튼
                            btn.click()
                            logger.info(f"모달 확인 버튼 클릭 (y={b_box['y']:.0f})")
                            confirmed = True
                            break
                    if confirmed:
                        break
                except Exception:
                    continue
        except Exception:
            pass

        if not confirmed:
            # 폴백: 모달 내 마지막 확인 버튼 (force 없이)
            try:
                page.locator("button:has-text('확인')").last.click()
                logger.info("모달 확인 버튼 클릭 (last 폴백)")
                confirmed = True
            except Exception:
                pass

        # 모달 닫힘 대기 (제목이 사라질 때까지, 최대 10초)
        modal_closed = False
        for _ in range(20):
            try:
                title_el = page.locator("text=매입(세금)계산서 내역").first
                if not title_el.is_visible(timeout=200):
                    modal_closed = True
                    break
            except Exception:
                modal_closed = True
                break
            time.sleep(0.5)

        if modal_closed:
            logger.info("계산서 모달 닫힘 확인")
        else:
            logger.warning("계산서 모달이 아직 열려있음 — X 버튼으로 닫기 시도")
            try:
                # X 닫기 버튼 클릭
                close_btn = page.locator("button:has-text('×'), button[class*='close']").first
                if close_btn.is_visible(timeout=1000):
                    close_btn.click(force=True)
                    time.sleep(1)
            except Exception:
                pass

        # 그리드 반영 대기
        time.sleep(2)
        _save_debug(page, "03c3_after_invoice_applied")
        logger.info("계산서 모달 → 그리드 반영 완료")
        return selected

    def _fill_project_code_bottom(self, project: str) -> bool:
        """
        하단 테이블(테이블 7) 프로젝트 코드도움 입력.

        상단 _fill_project_code와 동일한 모달 기반 방식 사용.
        y_hint=900으로 하단 input을 타겟합니다.

        Args:
            project: 프로젝트 코드 또는 이름 일부
        Returns:
            True if 입력 성공
        """
        return self._fill_project_code(project, y_hint=900)

    def search_project_codes(self, keyword: str, max_results: int = 10) -> list[dict]:
        """
        프로젝트 코드도움 자동완성 위젯에서 키워드로 검색 후 결과 목록 반환.

        사용 목적: 챗봇에서 사용자가 "메디빌더"라고 입력하면
        정식 프로젝트명(GS-25-0088. [종로] 메디빌더 등)을 검색해 확인을 받기 위함.

        흐름:
        1. 지출결의서 폼 열기
        2. 프로젝트 코드도움 input에 keyword 입력
        3. 자동완성 드롭다운 목록 텍스트 모두 추출
        4. 드롭다운 닫기 (ESC)
        5. 결과 리스트 반환 [{code, name, full_text}, ...]

        Args:
            keyword: 검색 키워드 (예: '메디빌더', 'GS-25')
            max_results: 최대 반환 개수
        Returns:
            [{"code": "GS-25-0088", "name": "[종로] 메디빌더", "full_text": "GS-25-0088. [종로] 메디빌더"}, ...]
        """
        page = self.page
        results = []

        try:
            # 지출결의서 폼으로 이동 (아직 열려있지 않으면 열기)
            try:
                page.wait_for_selector(
                    "input[placeholder='프로젝트코드도움']",
                    timeout=3000,
                    state="visible",
                )
            except Exception:
                self._navigate_to_expense_form()
                page.wait_for_selector(
                    "input[placeholder='프로젝트코드도움']",
                    timeout=10000,
                    state="visible",
                )

            # 상단 프로젝트 코드도움 input 찾기 (y < 500)
            all_proj_inputs = page.locator("input[placeholder='프로젝트코드도움']").all()
            proj_input = None
            for inp in all_proj_inputs:
                try:
                    box = inp.bounding_box()
                    if box and box["y"] < 500 and inp.is_visible(timeout=1000):
                        proj_input = inp
                        break
                except Exception:
                    continue

            if not proj_input:
                logger.warning("프로젝트 코드도움 input을 찾을 수 없음")
                return []

            # 기존 값 지우고 키워드 입력 (delay로 자동완성 트리거)
            proj_input.click(force=True)
            proj_input.fill("")
            proj_input.type(keyword, delay=80)
            logger.info(f"프로젝트 검색 키워드 입력: {keyword}")

            # 자동완성 드롭다운 대기 (최대 3초)
            dropdown_selectors = [
                "ul[class*='autocomplete'] li",
                "div[class*='OBTAutoComplete'] li",
                "div[class*='suggest'] li",
                "div[class*='dropdown-list'] li",
                "ul[role='listbox'] li",
                "div[role='listbox'] div[role='option']",
                "li[class*='item']",
                ".autocomplete-item",
            ]
            dropdown_items = None
            for sel in dropdown_selectors:
                try:
                    locator = page.locator(sel)
                    if locator.first.is_visible(timeout=2000):
                        dropdown_items = locator.all()
                        logger.info(f"드롭다운 발견: {sel} ({len(dropdown_items)}개)")
                        break
                except Exception:
                    continue

            if not dropdown_items:
                logger.info("드롭다운 없음 - Enter로 현재 값 확인 시도")
                # Enter로 현재 선택된 값 확인
                proj_input.press("Escape")
                return []

            # 드롭다운 항목 텍스트 추출
            for item in dropdown_items[:max_results]:
                try:
                    text = item.inner_text().strip()
                    if not text:
                        continue
                    # "GS-25-0088. [종로] 메디빌더" 형식 파싱
                    parsed = _parse_project_text(text)
                    results.append(parsed)
                except Exception:
                    continue

            logger.info(f"프로젝트 검색 결과 {len(results)}건: {[r['full_text'] for r in results]}")

        except Exception as e:
            logger.warning(f"프로젝트 코드 검색 실패: {e}")
        finally:
            # 드롭다운 닫기
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

        return results

    def _capture_and_attach_budget_screenshot(self) -> bool:
        """
        예실대비현황(상세) 스크린샷을 캡처하여 지출결의서 첨부파일 영역에 자동 업로드.

        흐름:
        1. 하단 예산 영역(테이블 7)으로 스크롤
        2. 화면 캡처 (PNG)
        3. 상단 첨부파일 영역으로 스크롤 후 파일 업로드

        Returns:
            True if 캡처 + 업로드 모두 성공
        """
        page = self.page

        # 1. 스크린샷 캡처
        screenshot_path = self.capture_budget_status_screenshot()
        if not screenshot_path:
            logger.warning("예실대비현황 스크린샷 캡처 실패")
            return False

        logger.info(f"예실대비현황 스크린샷 캡처 완료: {screenshot_path}")

        # 2. 상단으로 스크롤 후 첨부파일 업로드
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
        except Exception:
            pass

        success = self._upload_attachment(screenshot_path)
        if success:
            logger.info("예실대비현황 스크린샷 첨부파일 업로드 완료")
        else:
            logger.warning("예실대비현황 스크린샷 첨부파일 업로드 실패")
        return success

    def _fill_receipt_date(self, date_str: str):
        """
        증빙일자 입력 (하단 테이블, OBTDatePicker).

        DOM: x=763, y=857, className=OBTDatePickerRebuild_inputYMD
        형식: YYYY-MM-DD (입력 후 8자리 YYYYMMDD로 자동 변환됨)

        Args:
            date_str: '2026-03-01' 형식
        """
        page = self.page

        # YYYY-MM-DD → YYYYMMDD 변환 (GW 날짜 필드 형식)
        clean_date = date_str.replace("-", "")

        # selector로 찾기: 하단 영역(y>800)의 OBTDatePicker input
        try:
            date_inputs = page.locator(
                "input.OBTDatePickerRebuild_inputYMD__PtxMy, "
                "input[class*='OBTDatePickerRebuild_inputYMD']"
            ).all()
            for inp in date_inputs:
                if inp.is_visible():
                    box = inp.bounding_box()
                    if box and box["y"] > 800:  # 하단 테이블 (증빙일자)
                        inp.click(force=True)
                        inp.fill(clean_date)
                        inp.press("Tab")
                        logger.info(f"증빙일자 입력: {date_str}")
                        return True
        except Exception as e:
            logger.debug(f"증빙일자 selector 입력 실패: {e}")

        # 폴백 2: th="증빙일자" 인접 td 내 input 탐색 (뷰포트 크기 무관)
        for sel in [
            "th:has-text('증빙일자') + td input",
            "th:has-text('증빙일자') ~ td input",
            "td:has-text('증빙일자') input",
            "input[placeholder*='일자']",
            "input[class*='DatePicker']",
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1500):
                    el.click(force=True)
                    el.fill(clean_date)
                    el.press("Tab")
                    logger.info(f"증빙일자 입력 (셀렉터 폴백 '{sel}'): {date_str}")
                    return True
            except Exception:
                continue

        # 최종 폴백: 좌표 기반 (x=763, y=857)
        try:
            logger.warning("증빙일자 셀렉터 모두 실패, 좌표 폴백: (763, 857)")
            page.mouse.click(763, 857)
            page.keyboard.type(clean_date)
            page.keyboard.press("Tab")
            logger.info(f"증빙일자 입력 (좌표 763,857): {date_str}")
            return True
        except Exception as e:
            logger.warning(f"증빙일자 좌표 입력 실패: {e}")
        return False

    def _upload_attachment(self, file_path: str) -> bool:
        """
        첨부파일 업로드.

        GW 첨부파일 구조:
        - input[type=file][id=uploadFile] (hidden) — setInputFiles로 직접 처리
        - 또는 placeholder="파일을 첨부해주세요" input 옆 버튼 클릭

        Args:
            file_path: 업로드할 파일의 로컬 절대 경로
        Returns:
            True if 업로드 성공
        """
        page = self.page
        import pathlib
        p = pathlib.Path(file_path)
        if not p.exists():
            logger.warning(f"첨부파일 없음: {file_path}")
            return False

        # 방법 1: hidden file input에 직접 파일 설정
        try:
            file_input = page.locator("input[type='file']#uploadFile, input[type='file'][name='uploadFile']").first
            file_input.set_input_files(str(p))
            logger.info(f"첨부파일 업로드 (hidden input): {p.name}")
            return True
        except Exception:
            pass

        # 방법 2: "선택" 버튼 클릭 → file chooser 처리
        try:
            with page.expect_file_chooser() as fc_info:
                # "선택" 버튼: x=1865, y=246 (DOM 데이터 기준)
                sel_btns = page.locator("button:has-text('선택')").all()
                clicked = False
                for btn in sel_btns:
                    if btn.is_visible():
                        box = btn.bounding_box()
                        if box and 230 < box["y"] < 270:
                            btn.click(force=True)
                            logger.info(f"첨부 '선택' 버튼 클릭 (y={box['y']:.0f})")
                            clicked = True
                            break
                if not clicked:
                    # 추가 셀렉터 시도 (y 범위 확장 + 다른 텍스트)
                    for extra_sel in [
                        "button:has-text('선택')",
                        "button:has-text('파일선택')",
                        "button:has-text('첨부')",
                        "[title='파일선택']",
                        "[title='선택']",
                        "input[type='file'] + button",
                        "label[for='uploadFile']",
                    ]:
                        try:
                            extra_btn = page.locator(extra_sel).first
                            if extra_btn.is_visible(timeout=1500):
                                extra_btn.click(force=True)
                                logger.info(f"첨부 버튼 클릭 (확장 셀렉터 '{extra_sel}')")
                                clicked = True
                                break
                        except Exception:
                            continue
                if not clicked:
                    # 최종 폴백: 좌표 기반
                    logger.warning("첨부 선택 버튼 셀렉터 모두 실패, 좌표 폴백: (1865, 246)")
                    page.mouse.click(1865, 246)

            file_chooser = fc_info.value
            file_chooser.set_files(str(p))
            logger.info(f"첨부파일 업로드 (file chooser): {p.name}")
            return True
        except Exception as e:
            logger.warning(f"첨부파일 업로드 실패: {e}")

        return False

    # ─────────────────────────────────────────
    # 예실대비현황 스크린샷 캡처
    # ─────────────────────────────────────────

    def capture_budget_status_screenshot(self, output_path: str = None) -> str | None:
        """
        예실대비현황 화면 스크린샷 캡처.

        GW 예실대비현황: 지출결의서 양식 내 예산 잔액 현황 테이블
        - 하단 테이블 7 영역 (y > 800) 포함
        - full_page=False로 현재 화면만 캡처

        Args:
            output_path: 저장 경로 (None이면 자동 생성)
        Returns:
            저장된 파일 경로 (str) 또는 None
        """
        page = self.page
        if output_path is None:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(SCREENSHOT_DIR / f"budget_status_{ts}.png")

        try:
            # 하단 예산 영역으로 스크롤
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        try:
            page.screenshot(path=output_path, full_page=False)
            logger.info(f"예실대비현황 스크린샷 저장: {output_path}")
            return output_path
        except Exception as e:
            logger.warning(f"스크린샷 캡처 실패: {e}")
            return None

    # 실제 DOM: 체크박스 | 용도 | 내용 | 거래처 | 공급가액 | 부가세 | 합계액 | 증빙 | 증빙번호 ...
    GRID_COL_MAP = {
        "용도": 0,
        "내용": 1,
        "거래처": 2,
        "공급가액": 3,
        "부가세": 4,
        "합계액": 5,
        "증빙": 6,
        "증빙번호": 7,
    }

    # data.items 키 → 그리드 컬럼 매핑
    ITEM_KEY_TO_COL = {
        "usage": "용도",       # 용도 (계정과목 코드도움)
        "content": "내용",     # 내용 (텍스트)
        "vendor": "거래처",    # 거래처 (텍스트)
        "supply_amount": "공급가액",  # 공급가액 (숫자)
        "tax_amount": "부가세",       # 부가세 (숫자)
        # 합계액은 자동 계산
        "item": "내용",        # 호환: agent.py의 "item" → "내용"
        "amount": "공급가액",  # 호환: agent.py의 "amount" → "공급가액"
        "note": "내용",        # 호환: "note"도 내용에 매핑
    }

    def _fill_grid_items(self, items: list[dict]):
        """
        지출내역 그리드에 항목 입력

        그리드는 RealGrid(realgridjs) 커스텀 컴포넌트:
        - 셀 클릭 → 편집 모드 활성화 → input 나타남 → 값 입력 → Tab/Enter로 확정
        - "추가" 버튼으로 새 행 추가 (DOM 기준 x=1808, y=373)
        - 첫 번째 행은 이미 존재 (빈 행)
        - RealGrid API 우선 시도, 실패 시 좌표 기반 폴백

        Args:
            items: [
                {"item": "항목명", "amount": 100000},  # 간단 형식 (agent.py 호환)
                {"content": "내용", "vendor": "거래처", "supply_amount": 50000, "tax_amount": 5000},  # 상세 형식
            ]
        """
        if not items:
            return

        logger.info(f"지출내역 그리드 입력 시작: {len(items)}개 항목")

        for row_idx, item_data in enumerate(items):
            # 첫 행은 이미 있음, 2번째부터 "추가" 버튼 클릭
            if row_idx > 0:
                self._click_grid_add_button()
                time.sleep(1)

            # 각 필드 입력
            filled_count = 0
            for key, value in item_data.items():
                if not value:
                    continue

                col_name = self.ITEM_KEY_TO_COL.get(key)
                if not col_name:
                    continue

                col_idx = self.GRID_COL_MAP.get(col_name)
                if col_idx is None:
                    continue

                success = self._fill_grid_cell(row_idx, col_idx, col_name, str(value))
                if success:
                    filled_count += 1

            logger.info(f"그리드 행 {row_idx}: {filled_count}개 필드 입력")

        logger.info("지출내역 그리드 입력 완료")

    def _click_grid_add_button(self):
        """그리드 "추가" 버튼 클릭하여 새 행 추가"""
        page = self.page

        # 지출내역 헤더 y 기준으로 동적 범위 계산 (fullscreen 호환)
        grid_y_min, grid_y_max = 300, 500  # 기본 범위
        try:
            header_el = page.locator("text='지출내역'").first
            if header_el.is_visible(timeout=1000):
                hbox = header_el.bounding_box()
                if hbox:
                    grid_y_min = hbox["y"] - 20
                    grid_y_max = hbox["y"] + 150
        except Exception:
            pass

        # 방법 1: 텍스트 기반 버튼 탐색 (y 범위 동적 적용)
        for selector in [
            "button:has-text('추가')",
            "button:has-text('행추가')",
            "[title='추가']",
            "[title='행추가']",
            "button.add-row",
            "text=추가",
        ]:
            try:
                btns = page.locator(selector).all()
                for btn in btns:
                    if btn.is_visible():
                        box = btn.bounding_box()
                        if box and grid_y_min < box["y"] < grid_y_max:
                            btn.click(force=True)
                            logger.info(f"그리드 '추가' 버튼 클릭 (sel='{selector}', y={box['y']:.0f})")
                            return True
            except Exception:
                continue

        # 방법 2: 지출내역 그리드 컨테이너 내 추가 버튼 탐색
        for container_sel in [
            "div.OBTDataGrid_grid__22Vfl",
            "div[class*='OBTDataGrid']",
            "div[class*='grid-container']",
            "div[class*='gridContainer']",
        ]:
            try:
                container = page.locator(container_sel).first
                if container.is_visible(timeout=1000):
                    add_btn = container.locator("button:has-text('추가'), button:has-text('행추가')").first
                    if add_btn.is_visible(timeout=1000):
                        add_btn.click(force=True)
                        logger.info(f"그리드 '추가' 버튼 클릭 (컨테이너 내부 '{container_sel}')")
                        return True
            except Exception:
                continue

        # 최종 폴백: DOM 데이터 기준 좌표 (x=1808, y=373)
        try:
            logger.warning("그리드 '추가' 버튼 셀렉터 모두 실패, 좌표 폴백: (1808, 373)")
            page.mouse.click(1808, 373)
            logger.info("그리드 '추가' 버튼 클릭 (좌표 폴백 x=1808, y=373)")
            return True
        except Exception as e:
            logger.warning(f"그리드 '추가' 좌표 폴백도 실패: {e}")

        logger.warning("그리드 '추가' 버튼을 찾지 못했습니다")
        return False

    def _fill_grid_cell(self, row_idx: int, col_idx: int, col_name: str, value: str) -> bool:
        """
        그리드 셀에 값 입력

        RealGrid 동작:
        1. 셀 영역 클릭 → 편집 모드 활성화
        2. 활성화된 input/textarea에 값 입력
        3. Tab 키로 다음 셀 이동 (값 확정)

        Args:
            row_idx: 행 인덱스 (0-based)
            col_idx: 열 인덱스 (0-based, 체크박스 제외)
            col_name: 열 이름 (로깅용)
            value: 입력할 값
        """
        page = self.page

        try:
            # 방법 1: RealGrid JavaScript API로 값 직접 설정
            # RealGrid는 canvas 기반으로 표준 DOM 접근이 불가하므로 JS API 우선
            if self._fill_grid_cell_via_realgrid_api(row_idx, col_idx, col_name, value):
                return True

            # 방법 2: div[role="row"] 기반 탐색 (일부 그리드)
            grid_rows = page.locator("div[role='row']").all()

            if not grid_rows or row_idx >= len(grid_rows):
                logger.debug(f"그리드 행 {row_idx} 찾기 실패 (총 {len(grid_rows)}행)")
                return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

            row = grid_rows[row_idx]
            # 체크박스 td 건너뛰기: col_idx + 1 (또는 +2 if 확장 아이콘)
            cells = row.locator("td, div[role='gridcell']").all()

            # 체크박스 + 확장아이콘 2개 건너뛰기
            actual_col = col_idx + 2
            if actual_col >= len(cells):
                actual_col = col_idx + 1

            if actual_col >= len(cells):
                logger.debug(f"셀 인덱스 초과: row={row_idx}, col={actual_col}, total={len(cells)}")
                return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

            cell = cells[actual_col]
            return self._activate_and_fill_cell(cell, col_name, value)

        except Exception as e:
            logger.debug(f"그리드 셀 입력 실패 (row={row_idx}, col={col_name}): {e}")
            return self._fill_grid_cell_by_position(row_idx, col_idx, col_name, value)

    def _fill_grid_cell_via_realgrid_api(
        self, row_idx: int, col_idx: int, col_name: str, value: str
    ) -> bool:
        """
        RealGrid JavaScript API를 통해 그리드 셀 값 직접 설정.

        RealGrid API 패턴:
        - window.gridView (또는 첫 번째 GridView 인스턴스)를 찾아서
        - gridView.setValue(itemIndex, fieldName, value) 또는
        - gridView.setValues(itemIndex, {fieldName: value}) 호출

        컬럼 필드명은 RealGrid 설정에 따라 달라질 수 있음:
        '내용', 'content', 'CONT', 'col_1' 등 다양
        """
        page = self.page

        # RealGrid 컬럼 인덱스 → 필드명 매핑 (실제 그리드 설정에 따라 달라짐)
        # 좌표 클릭으로 셀을 활성화한 뒤 편집 input에 type하는 방식이 더 안전
        try:
            result = page.evaluate(f"""
            (function() {{
                // RealGrid 인스턴스 찾기
                const gridNames = ['gridView', 'grid', 'expenseGrid', 'detailGrid'];
                let gv = null;
                for (const name of gridNames) {{
                    if (window[name] && typeof window[name].setCurrent === 'function') {{
                        gv = window[name];
                        break;
                    }}
                }}
                if (!gv) return false;

                // 셀 포커스 이동 (itemIndex, columnIndex)
                try {{
                    gv.setCurrent({{ itemIndex: {row_idx}, column: {col_idx + 1} }});
                    return true;
                }} catch(e) {{
                    return false;
                }}
            }})()
            """)

            if result:
                # 편집 모드 input에 값 입력
                active_input = page.locator("input:focus, textarea:focus").first
                if active_input.is_visible(timeout=1000):
                    active_input.fill(str(value))
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (RealGrid API): {value}")
                    return True
        except Exception as e:
            logger.debug(f"RealGrid API 시도 실패 ({col_name}): {e}")

        return False

    def _activate_and_fill_cell(self, cell, col_name: str, value: str) -> bool:
        """셀 클릭하여 활성화 → input에 값 입력"""
        page = self.page

        try:
            # 1. 셀 클릭 → 편집 모드 활성화
            cell.click(force=True)
            time.sleep(0.5)

            # 2. 활성화된 input 찾기 (셀 내부 또는 페이지 전체에서)
            # RealGrid는 활성 셀에 overlay input을 동적으로 생성
            inp = cell.locator("input:visible, textarea:visible").first
            try:
                if inp.is_visible(timeout=1000):
                    inp.fill("")
                    inp.fill(value)
                    # Tab으로 값 확정
                    inp.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력: {value}")
                    return True
            except Exception:
                pass

            # 3. 셀 내부에 input이 없으면 포커스된 input 찾기
            # OBTGrid가 overlay input을 사용하는 경우
            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (focus): {value}")
                    return True
            except Exception:
                pass

            # 4. 더블클릭 시도 (일부 그리드는 더블클릭으로 편집)
            cell.dblclick(force=True)
            time.sleep(0.5)

            inp = cell.locator("input:visible, textarea:visible").first
            try:
                if inp.is_visible(timeout=1000):
                    inp.fill("")
                    inp.fill(value)
                    inp.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (dblclick): {value}")
                    return True
            except Exception:
                pass

            logger.debug(f"그리드 '{col_name}' 셀 활성화 후 input 미발견")
            return False

        except Exception as e:
            logger.debug(f"그리드 셀 활성화 실패 ({col_name}): {e}")
            return False

    def _fill_grid_cell_by_position(self, row_idx: int, col_idx: int, col_name: str, value: str) -> bool:
        """
        그리드 셀을 좌표 기반으로 입력 (폴백)

        DOM 탐색 데이터 기준 좌표:
        - 그리드 첫 행 y ~ 345
        - 행 높이 ~ 28px
        - 컬럼 x 좌표: 용도~560, 내용~680, 거래처~850, 공급가액~960, 부가세~1070, 합계액~1140
        """
        page = self.page

        # 컬럼별 x 좌표 (중심점, 스크린샷 기준)
        col_x_map = {
            0: 560,   # 용도
            1: 680,   # 내용
            2: 850,   # 거래처
            3: 960,   # 공급가액
            4: 1070,  # 부가세
            5: 1140,  # 합계액
        }

        x = col_x_map.get(col_idx)
        if x is None:
            return False

        # 행별 y 좌표: 첫 행 ~345, 행 높이 ~28
        y = 345 + (row_idx * 28)

        try:
            # 좌표 클릭으로 셀 활성화
            page.mouse.click(x, y)
            time.sleep(0.5)

            # 활성화된 input 찾기
            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (좌표): {value}")
                    return True
            except Exception:
                pass

            # 더블클릭 시도
            page.mouse.dblclick(x, y)
            time.sleep(0.5)

            active_input = page.locator("input:focus, textarea:focus").first
            try:
                if active_input.is_visible(timeout=1000):
                    active_input.fill("")
                    active_input.fill(value)
                    active_input.press("Tab")
                    logger.info(f"그리드 '{col_name}' 입력 (좌표 dblclick): {value}")
                    return True
            except Exception:
                pass

            logger.debug(f"그리드 '{col_name}' 좌표 기반 입력도 실패")
            return False

        except Exception as e:
            logger.debug(f"그리드 좌표 입력 실패 ({col_name}): {e}")
            return False

    def _check_field_has_value(self, label: str, expected: str) -> bool:
        """필드에 값이 입력되었는지 확인"""
        try:
            th_el = self.page.locator(f"th:has-text('{label}')").first
            td_el = th_el.locator("xpath=following-sibling::td").first
            inp = td_el.locator("input:visible").first
            return inp.input_value() == expected
        except Exception:
            return False

    def _save_draft(self) -> dict:
        """보관(임시저장) — 인라인 보관 버튼 또는 결재상신→팝업→보관 흐름"""
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

        # ── 2차: 결재상신 클릭 → 팝업 열림 → 팝업에서 보관 ──
        logger.info("인라인 보관 버튼 없음 — 결재상신→팝업→보관 흐름 시도")
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

        # 결재상신 클릭 → 팝업 대기
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
            time.sleep(2)
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
            time.sleep(3)
        except Exception:
            time.sleep(3)

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

    def create_vendor_registration(self, data: dict) -> dict:
        """
        [회계팀] 국내 거래처등록 신청서 작성 + 보관
        ※ 이 양식은 팝업 창으로 열리므로 팝업 기반 흐름 사용

        Args:
            data: {
                "title": "제목",
                "vendor_name": "거래처명(상호)",
                "ceo_name": "대표자명",
                "business_number": "사업자등록번호 (000-00-00000)",
                "business_type": "업태",
                "business_item": "종목",
                "address": "사업장주소",
                "contact_name": "담당자명",
                "contact_phone": "담당자 연락처",
                "contact_email": "담당자 이메일 (선택)",
                "bank_name": "은행명",
                "account_number": "계좌번호",
                "account_holder": "예금주",
                "note": "비고 (선택)",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # 필수 필드 검증
        validation = self._validate_required_fields(data, ["title"], "거래처등록")
        if validation:
            return validation

        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        if not self.context:
            return {"success": False, "message": "BrowserContext가 필요합니다. (팝업 감지용)"}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            popup_page = None
            try:
                self._close_popups()

                # 1. 전자결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 양식 선택 → 팝업 창 열기
                popup_page = self._open_form_popup("국내 거래처")

                # 3. 팝업에서 필드 채우기
                self._fill_vendor_fields_in_popup(popup_page, data)

                # 3-1. 결재선 커스텀 설정 (data에 approval_line 키 있을 때)
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "거래처등록")
                    self.set_approval_line(popup_page, resolved_line)

                # 3-2. 수신참조 설정 (data에 cc 키 있을 때)
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "거래처등록")
                    self.set_cc_recipients(popup_page, resolved_cc)

                # 4. 팝업에서 보관
                result = self._save_draft_in_popup(popup_page)

                return result

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"거래처등록 작성 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(self.page, f"error_vendor_timeout{attempt}")
                if popup_page:
                    _save_debug(popup_page, f"error_vendor_popup_timeout{attempt}")
                if attempt < MAX_RETRIES:
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}
                    self._close_popups()
                    time.sleep(RETRY_DELAY)
            except RuntimeError as e:
                return {"success": False, "message": str(e)}
            except Exception as e:
                last_error = e
                logger.error(f"거래처등록 작성 오류 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"error_vendor_{attempt}")
                if popup_page:
                    _save_debug(popup_page, f"error_vendor_popup_{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        _save_debug(self.page, "error_vendor_final")
        return {"success": False, "message": f"거래처등록 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def _click_form_by_keyword(self, *keywords: str):
        """
        양식 찾기: 추천양식 직접 클릭 → 실패 시 결재작성 → 양식 검색
        """
        page = self.page

        # 방법 1: 추천양식에서 직접 텍스트 클릭
        for keyword in keywords:
            try:
                links = page.locator(f"text={keyword}").all()
                for link in links:
                    if link.is_visible():
                        link.click(force=True)
                        logger.info(f"추천양식에서 클릭: '{keyword}'")
                        return
            except Exception:
                continue

        # 방법 2: "결재작성" 메뉴 클릭 → 양식 검색
        logger.info("추천양식에서 못 찾음, 결재작성으로 검색 시도")
        try:
            # 결재작성 버튼/링크 클릭
            for selector in [
                "text=결재작성",
                "a:has-text('결재작성')",
                "span:has-text('결재작성')",
            ]:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=3000):
                        btn.click(force=True)
                        logger.info("결재작성 클릭")
                        time.sleep(3)
                        break
                except Exception:
                    continue

            # 양식 검색 입력란 찾기
            search_input = None
            for selector in [
                "input[placeholder*='검색']",
                "input[placeholder*='양식']",
                "input[type='text']",
            ]:
                try:
                    candidates = page.locator(selector).all()
                    for inp in candidates:
                        if inp.is_visible():
                            search_input = inp
                            break
                    if search_input:
                        break
                except Exception:
                    continue

            if search_input:
                # 첫 번째 키워드로 검색
                search_input.click()
                search_input.fill(keywords[0])
                search_input.press("Enter")
                logger.info(f"양식 검색: '{keywords[0]}'")
                time.sleep(2)

                # 검색 결과에서 클릭
                for keyword in keywords:
                    try:
                        result = page.locator(f"text={keyword}").first
                        if result.is_visible(timeout=3000):
                            result.click(force=True)
                            logger.info(f"검색 결과에서 클릭: '{keyword}'")
                            return
                    except Exception:
                        continue

            _save_debug(page, "error_form_search_failed")
        except Exception as e:
            logger.error(f"양식 검색 실패: {e}")

        raise RuntimeError(f"양식을 찾을 수 없습니다: {keywords}")

    # ─────────────────────────────────────────
    # 팝업 기반 양식 작성 (거래처등록 등)
    # ─────────────────────────────────────────

    def _open_form_popup(self, search_term: str) -> Page:
        """
        결재작성 페이지에서 양식을 검색하고 팝업 창을 열어 반환

        흐름:
        1. 결재작성 페이지(UBA6000)로 이동
        2. 검색 입력란에 search_term 입력 후 Enter
        3. 검색 결과 첫 번째 항목 클릭 → Enter
        4. 새 팝업 페이지 감지 및 반환

        Args:
            search_term: 양식 검색어 (예: "국내 거래처")
        Returns:
            팝업 Page 객체
        """
        page = self.page

        # 현재 열린 페이지 목록 기록 (팝업 감지용)
        pages_before = set(self.context.pages)

        # 1. 전자결재 HOME → 결재작성 클릭 (UBA6000 URL은 HR 모듈로 변경되어 사용 불가)
        self._navigate_to_approval_home()
        self._click_write_approval()
        page.wait_for_timeout(1500)

        logger.info(f"결재작성 페이지 이동: {page.url[:100]}")
        _save_debug(page, "vendor_01_form_select_page")

        # 2. 양식 검색 입력란 찾기 (결재작성 페이지 기준)
        search_input = None
        for selector in [
            "input[placeholder*='카테고리 또는 양식명']",
            "input[placeholder*='양식명']",
            "input[placeholder*='양식']",
            "input[placeholder*='검색']",
            "input[placeholder*='Search']",
            # placeholder 없는 경우: 결재작성 페이지의 첫 번째 텍스트 input
            "input[type='text']:visible",
            "input:visible",
        ]:
            try:
                candidates = page.locator(selector).all()
                for inp in candidates:
                    if not inp.is_visible():
                        continue
                    readonly = inp.get_attribute("readonly")
                    disabled = inp.get_attribute("disabled")
                    if readonly is None and disabled is None:
                        search_input = inp
                        logger.info(f"검색 input 발견: selector={selector}")
                        break
                if search_input:
                    break
            except Exception:
                continue

        if not search_input:
            _save_debug(page, "error_vendor_no_search_input")
            raise RuntimeError("양식 검색 입력란을 찾을 수 없습니다.")

        # 3. 검색어 입력 + Enter → 결과 로드 대기
        search_input.click()
        search_input.fill(search_term)
        search_input.press("Enter")
        logger.info(f"양식 검색: '{search_term}'")
        # 검색 결과 로드 대기 (networkidle 또는 최대 3초)
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            page.wait_for_timeout(1500)

        _save_debug(page, "vendor_02_search_result")

        # 4. 검색 결과에서 항목 클릭 (search_term 기반)
        result_clicked = False
        click_keywords = [search_term]
        # search_term에서 부분 키워드 추출 (예: "[프로젝트]지출결의서" → "지출결의서")
        if "]" in search_term:
            click_keywords.append(search_term.split("]")[-1])
        # 거래처등록 호환성 유지
        if "거래처" in search_term:
            click_keywords.extend(["[회계팀] 국내 거래처등록 신청서", "국내 거래처등록", "거래처등록"])
        # 지출결의서 키워드 추가 (검색 시 "[프로젝트]지출결의서" 등 결과 대응)
        if "지출결의서" in search_term:
            click_keywords.extend(["[프로젝트]지출결의서", "지출결의서"])

        for keyword in click_keywords:
            try:
                results = page.locator(f"text={keyword}").all()
                for result in results:
                    if result.is_visible():
                        result.click(force=True)
                        logger.info(f"검색 결과 클릭: '{keyword}'")
                        result_clicked = True
                        break
                if result_clicked:
                    break
            except Exception:
                continue

        if not result_clicked:
            _save_debug(page, "error_no_search_result")
            raise RuntimeError(f"검색 결과에서 양식을 찾을 수 없습니다: '{search_term}'")

        time.sleep(1)

        # 5. Enter 키 → 팝업 열기
        page.keyboard.press("Enter")
        logger.info("Enter 키 눌러 팝업 열기 시도")

        # 6. 새 팝업 페이지 감지 (최대 15초 대기)
        popup_page = None
        for _ in range(30):
            time.sleep(0.5)
            current_pages = set(self.context.pages)
            new_pages = current_pages - pages_before
            for p in new_pages:
                try:
                    p_url = p.url or ""
                    # 팝업 URL 패턴 확인
                    if "popup" in p_url or "formId" in p_url or "eap" in p_url:
                        popup_page = p
                        break
                    # about:blank이 아닌 새 페이지도 후보
                    if p_url and p_url != "about:blank":
                        popup_page = p
                        break
                except Exception:
                    continue
            if popup_page:
                break

        if not popup_page:
            _save_debug(page, "error_vendor_no_popup")
            raise RuntimeError("양식 팝업이 열리지 않았습니다. 검색 결과를 다시 확인해주세요.")

        # 팝업 로드 대기
        try:
            popup_page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            time.sleep(3)

        # 다이얼로그 자동 수락 등록
        popup_page.on("dialog", lambda d: d.accept())

        logger.info(f"팝업 열림: {popup_page.url[:100]}")
        _save_debug(popup_page, "vendor_03_popup_opened")

        return popup_page

    def _fill_vendor_fields_in_popup(self, popup_page: Page, data: dict):
        """
        팝업 페이지에서 거래처등록 필드 채우기

        제목: 기본값 "[국내]신규 거래처등록 요청(거래처명)"에서 (거래처명)만 교체
        본문: dzeditor_0 iframe 내부 테이블 셀에 각 정보를 직접 기입
              (기존 양식 구조를 유지하며 해당 셀만 수정)

        본문 테이블 구조 (Table 2):
        R2: 소속 | 본부/팀 | 성명 | (빈칸)
        R3: 거래처정보 (□매출/□매입) 헤더
        R4: 사업자등록번호 | ex)000-00-00000 | 상호명 | (빈칸)
        R5: 대표자명 | (빈칸) | 수신자이메일 | (빈칸)
        R6: 은행명 | 매출거래처인 경우... (colspan=3)
        R7: 계좌번호 | 매출거래처인 경우... (colspan=3)
        R8: 예금주 | 매출거래처인 경우... (colspan=3)
        R9: 비고 | (빈칸) (colspan=3)
        """
        vendor_name = data.get("vendor_name", "")

        # 1. 제목 — (거래처명) 부분만 업체명으로 교체
        try:
            inputs = popup_page.locator("input[type='text']:visible, input:not([type]):visible").all()
            for inp in inputs:
                val = inp.input_value()
                if "(거래처명)" in val:
                    new_title = val.replace("(거래처명)", vendor_name or "(거래처명)")
                    inp.click()
                    inp.fill(new_title)
                    logger.info(f"팝업 제목 교체: {val} → {new_title}")
                    break
        except Exception as e:
            logger.warning(f"팝업 제목 교체 실패: {e}")

        _save_debug(popup_page, "vendor_04_after_title")

        # 2. 본문 — dzeditor_0 iframe 내부 테이블 셀에 정보 기입
        self._fill_vendor_body_cells(popup_page, data)

        _save_debug(popup_page, "vendor_05_after_body")

    def _fill_vendor_body_cells(self, popup_page: Page, data: dict):
        """
        dzEditor API(setEditorHTMLCodeIframe)를 사용하여 본문 기입

        동작 방식:
        1. getEditorHTMLCodeIframe(0)으로 현재 HTML 가져오기
        2. 양식 HTML에서 placeholder 텍스트를 실제 값으로 교체
        3. setEditorHTMLCodeIframe(html, 0)으로 설정
        → dzEditor 내부 상태에 반영되므로 보관 시 정상 저장됨
        """
        import re

        # 1. 현재 에디터 HTML 가져오기 (로딩 대기 포함)
        current_html = ""
        for wait_try in range(10):
            try:
                current_html = popup_page.evaluate(
                    "(n) => { try { return getEditorHTMLCodeIframe(n); } catch(e) { return ''; } }",
                    0
                )
            except Exception as e:
                logger.warning(f"getEditorHTMLCodeIframe 실패: {e}")
                current_html = ""
            if current_html and len(current_html) >= 100:
                break
            time.sleep(1)

        if not current_html or len(current_html) < 100:
            logger.warning(f"에디터 HTML이 비어있음 (길이: {len(current_html)}), 대기 후에도 로딩 안됨")
            return

        logger.info(f"에디터 HTML 가져옴: {len(current_html)} chars")
        modified = current_html

        # 2. placeholder 텍스트 교체
        # 사업자등록번호: "ex) 000-00-00000"
        biz_num = data.get("business_number", "")
        if biz_num:
            modified = modified.replace("ex) 000-00-00000", biz_num)
            logger.info(f"사업자등록번호: {biz_num}")

        # 소속: "본부 / 팀"
        dept = data.get("department", "")
        if dept:
            modified = modified.replace("본부 / 팀", dept)
            logger.info(f"소속: {dept}")

        # 빈 셀 교체 헬퍼: 라벨 뒤 빈 td의 <p><br></p> → <p>값</p>
        # API HTML에는 태그 사이 줄바꿈/탭이 포함되므로 \s* 필수
        def _replace_empty_cell(html, label, value):
            """라벨 td 다음 빈 td(<p><br></p>)에 값 기입"""
            pattern = rf'(>{re.escape(label)}</p>\s*</td>\s*)(<td[^>]*>\s*)(<p[^>]*>)<br>(</p>\s*</td>)'
            # replacement에서 역참조 사용을 위해 함수형 교체
            def repl(m):
                return m.group(1) + m.group(2) + m.group(3) + value + m.group(4)
            return re.sub(pattern, repl, html, count=1, flags=re.DOTALL)

        def _replace_placeholder_cell(html, label, placeholder, value):
            """라벨 td 다음 td에서 placeholder 텍스트를 값으로 교체"""
            pattern = rf'(>{re.escape(label)}</p>\s*</td>\s*)(<td[^>]*>\s*)(<p[^>]*>){re.escape(placeholder)}(<br>)?(</p>\s*</td>)'
            def repl(m):
                return m.group(1) + m.group(2) + m.group(3) + value + m.group(5)
            return re.sub(pattern, repl, html, count=1, flags=re.DOTALL)

        # 상호명 빈 셀
        vendor_name = data.get("vendor_name", "")
        if vendor_name:
            modified = _replace_empty_cell(modified, "상호명", vendor_name)
            logger.info(f"상호명: {vendor_name}")

        # 대표자명 빈 셀
        ceo = data.get("ceo_name", "")
        if ceo:
            modified = _replace_empty_cell(modified, "대표자명", ceo)
            logger.info(f"대표자명: {ceo}")

        # 성명 빈 셀
        applicant = data.get("applicant_name", "")
        if applicant:
            modified = _replace_empty_cell(modified, "성명", applicant)
            logger.info(f"성명: {applicant}")

        # 수신자이메일 빈 셀
        email = data.get("contact_email", "")
        if email:
            modified = _replace_empty_cell(modified, "이메일", email)
            logger.info(f"수신자이메일: {email}")

        # 은행명 (placeholder 교체)
        bank = data.get("bank_name", "")
        if bank:
            modified = _replace_placeholder_cell(
                modified, "은행명", "매출거래처인 경우 기입하지 않음.", bank
            )
            logger.info(f"은행명: {bank}")

        # 계좌번호
        account = data.get("account_number", "")
        if account:
            modified = _replace_placeholder_cell(
                modified, "계좌번호", "매출거래처인 경우 기입하지 않음.", account
            )
            logger.info(f"계좌번호: {account}")

        # 예금주
        holder = data.get("account_holder", "")
        if holder:
            modified = _replace_placeholder_cell(
                modified, "예금주", "매출거래처인 경우 기입하지 않음.", holder
            )
            logger.info(f"예금주: {holder}")

        # 비고 빈 셀
        note = data.get("note", "")
        if note:
            modified = _replace_empty_cell(modified, "비고", note)
            logger.info(f"비고: {note}")

        # 거래처정보 체크박스 (매출/매입)
        trade_type = data.get("trade_type", "매입")
        if trade_type == "매출":
            modified = re.sub(
                r'(<input type="checkbox">)(</span><span[^>]*>\s*매출)',
                r'<input type="checkbox" checked>\2',
                modified, count=1
            )
        elif trade_type == "매입":
            modified = re.sub(
                r'(<input type="checkbox">)(</span><span[^>]*>\s*매입)',
                r'<input type="checkbox" checked>\2',
                modified, count=1
            )
        elif trade_type in ("매출/매입", "둘다"):
            modified = modified.replace(
                '<input type="checkbox">',
                '<input type="checkbox" checked>',
            )
        logger.info(f"거래처 유형: {trade_type}")

        # 3. setEditorHTMLCodeIframe(html, 0)으로 설정
        try:
            popup_page.evaluate(
                "(args) => { setEditorHTMLCodeIframe(args[0], args[1]); }",
                [modified, 0]
            )
            logger.info("setEditorHTMLCodeIframe 호출 성공")
        except Exception as e:
            logger.error(f"setEditorHTMLCodeIframe 실패: {e}")
            return

        time.sleep(1)

        # 4. 검증: 설정된 HTML에 값이 포함되는지 확인
        try:
            verify = popup_page.evaluate("(n) => getEditorHTMLCodeIframe(n)", 0)
            if vendor_name and vendor_name not in verify:
                logger.warning("검증 실패: 상호명이 설정된 HTML에 없음")
            else:
                logger.info("본문 설정 검증 완료")
        except Exception as e:
            logger.warning(f"본문 검증 중 오류: {e}")

    def _fill_editor_content_in_popup(self, popup_page: Page, text: str):
        """
        팝업 페이지의 dzEditor (contentEditable/iframe) 본문에 텍스트 입력

        Args:
            popup_page: 팝업 Page 객체
            text: 입력할 본문 텍스트
        """
        html_text = text.replace("\n", "<br>")

        # 방법 1: contentEditable div 직접 찾기
        try:
            editor = popup_page.locator("div[contenteditable='true']").first
            if editor.is_visible(timeout=3000):
                editor.click()
                popup_page.evaluate(f"""
                    const el = document.querySelector("[contenteditable='true']");
                    if (el) {{ el.innerHTML = `{html_text}`; }}
                """)
                logger.info("팝업 본문 입력 완료 (contentEditable)")
                return
        except Exception:
            pass

        # 방법 2: iframe 내부 editor
        try:
            iframe = popup_page.locator("iframe").first
            if iframe.is_visible(timeout=3000):
                frame = iframe.content_frame()
                if frame:
                    body = frame.locator("body[contenteditable='true'], div[contenteditable='true']").first
                    if body.is_visible(timeout=2000):
                        body.click()
                        frame.evaluate(f"""
                            const el = document.querySelector('[contenteditable]') || document.body;
                            el.innerHTML = `{html_text}`;
                        """)
                        logger.info("팝업 본문 입력 완료 (iframe)")
                        return
        except Exception:
            pass

        # 방법 3: 키보드 입력 폴백
        try:
            popup_page.keyboard.press("Tab")
            time.sleep(0.5)
            for line in text.split("\n"):
                popup_page.keyboard.type(line)
                popup_page.keyboard.press("Enter")
            logger.info("팝업 본문 입력 완료 (키보드)")
        except Exception as e:
            logger.warning(f"팝업 본문 입력 실패: {e}")

    def _save_draft_in_popup(self, popup_page: Page) -> dict:
        """
        팝업 페이지에서 "보관" 버튼 클릭하여 임시저장

        Args:
            popup_page: 팝업 Page 객체
        Returns:
            {"success": bool, "message": str}
        """
        # "보관" 버튼 찾기 — 팝업 상단 div.topBtn 중 텍스트 "보관"
        save_btn = None
        try:
            top_btns = popup_page.locator("div.topBtn").all()
            for btn in top_btns:
                if btn.is_visible(timeout=2000):
                    btn_text = btn.inner_text().strip()
                    if btn_text == "보관":
                        save_btn = btn
                        logger.info("팝업 보관 버튼 발견: div.topBtn")
                        break
        except Exception:
            pass

        # 폴백: 다른 selector 시도
        if not save_btn:
            for selector in [
                "button:has-text('보관')",
                "a:has-text('보관')",
                "span:has-text('보관')",
            ]:
                try:
                    candidates = popup_page.locator(selector).all()
                    for candidate in candidates:
                        if candidate.is_visible(timeout=1000):
                            btn_text = candidate.inner_text().strip()
                            if btn_text == "보관":
                                save_btn = candidate
                                logger.info(f"팝업 보관 버튼 발견 (폴백): {selector}")
                                break
                    if save_btn:
                        break
                except Exception:
                    continue

        if not save_btn:
            _save_debug(popup_page, "error_vendor_no_save_btn")
            return {"success": False, "message": "팝업에서 보관 버튼을 찾을 수 없습니다."}

        _save_debug(popup_page, "vendor_06_before_save")

        save_btn.click(force=True)

        # 보관 후 결과 대기
        try:
            popup_page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            logger.warning("팝업 보관 후 네트워크 대기 타임아웃")
            time.sleep(3)
        except Exception:
            time.sleep(3)

        # 에러 메시지 확인
        try:
            error_msg = popup_page.locator("div.alert-message, div.error-message, .OBTAlert_message").first
            if error_msg.is_visible(timeout=2000):
                text = error_msg.inner_text()
                logger.error(f"팝업 보관 에러: {text}")
                _save_debug(popup_page, "error_vendor_save_response")
                return {"success": False, "message": f"보관 중 오류: {text}"}
        except Exception:
            pass  # 에러 없음 = 정상

        # 팝업이 자동으로 닫혔는지 확인
        try:
            if popup_page.is_closed():
                logger.info("팝업 자동 닫힘 — 보관 완료")
        except Exception:
            pass

        _save_debug(popup_page, "vendor_07_after_save")
        logger.info("거래처등록 보관(임시저장) 완료")
        return {"success": True, "message": "거래처등록 신청서가 임시보관되었습니다. (상신 전 상태)"}

    def _fill_vendor_fields(self, data: dict):
        """
        거래처등록 필드 채우기
        - 상단: 제목 (th 라벨 기반)
        - 본문: dzEditor contentEditable 영역에 거래처 정보 입력
        """
        page = self.page
        title = data.get("title", "")

        # 1. 제목 입력
        if title:
            self._fill_field_by_label("제목", title)
            # 폴백
            if not self._check_field_has_value("제목", title):
                self._fill_field_by_placeholder("제목", title)

        _save_debug(page, "03_vendor_after_title")

        # 2. 본문 영역 (dzEditor contentEditable)에 거래처 정보 입력
        vendor_info = self._build_vendor_body_text(data)
        if vendor_info:
            self._fill_editor_content(vendor_info)

        _save_debug(page, "03b_vendor_after_body")

    def _build_vendor_body_text(self, data: dict) -> str:
        """거래처 정보를 본문 텍스트로 구성"""
        lines = []

        field_map = [
            ("vendor_name", "거래처명(상호)"),
            ("ceo_name", "대표자명"),
            ("business_number", "사업자등록번호"),
            ("business_type", "업태"),
            ("business_item", "종목"),
            ("address", "사업장주소"),
            ("contact_name", "담당자명"),
            ("contact_phone", "담당자 연락처"),
            ("contact_email", "담당자 이메일"),
            ("bank_name", "은행명"),
            ("account_number", "계좌번호"),
            ("account_holder", "예금주"),
            ("note", "비고"),
        ]

        for key, label in field_map:
            value = data.get(key, "")
            if value:
                lines.append(f"{label}: {value}")

        return "\n".join(lines)

    def _fill_editor_content(self, text: str):
        """dzEditor (contentEditable) 본문 영역에 텍스트 입력"""
        page = self.page

        # dzEditor 본문 영역 찾기 (여러 selector 시도)
        editor = None
        for selector in [
            "div[contenteditable='true']",
            "div.dzEditor",
            "div[class*='editor'] div[contenteditable]",
            "iframe",  # iframe 내부 editor일 수도 있음
        ]:
            try:
                candidate = page.locator(selector).first
                if candidate.is_visible(timeout=3000):
                    if selector == "iframe":
                        # iframe 내부의 contentEditable
                        frame = candidate.content_frame()
                        if frame:
                            body = frame.locator("body[contenteditable='true'], div[contenteditable='true']").first
                            if body.is_visible(timeout=2000):
                                body.click()
                                # 줄바꿈을 위해 HTML로 입력
                                html_text = text.replace("\n", "<br>")
                                frame.evaluate(f"document.querySelector('[contenteditable]').innerHTML = `{html_text}`")
                                logger.info("본문 입력 완료 (iframe)")
                                return
                    else:
                        editor = candidate
                        break
            except Exception:
                continue

        if editor:
            try:
                editor.click()
                # HTML로 줄바꿈 처리
                html_text = text.replace("\n", "<br>")
                page.evaluate(f"""
                    const el = document.querySelector("[contenteditable='true']");
                    if (el) {{ el.innerHTML = `{html_text}`; }}
                """)
                logger.info("본문 입력 완료 (contentEditable)")
                return
            except Exception as e:
                logger.warning(f"contentEditable 입력 실패: {e}")

        # 최종 폴백: 키보드 입력
        try:
            # Tab 등으로 본문 영역으로 이동 시도
            page.keyboard.press("Tab")
            time.sleep(0.5)
            for line in text.split("\n"):
                page.keyboard.type(line)
                page.keyboard.press("Enter")
            logger.info("본문 입력 완료 (키보드)")
        except Exception as e:
            logger.warning(f"본문 키보드 입력도 실패: {e}")

    # ─────────────────────────────────────────
    # 임시보관문서 열기 + 결재상신 E2E
    # ─────────────────────────────────────────

    # 임시보관문서함 URL (cleanup에서 검증된 패턴)
    DRAFT_URL = f"{GW_URL}/#/UB/UB/UBA0000?appCode=approval&viewType=list&menuCode=UBD9999&subMenuCode=UBA1060"
    # 폴백용 URL
    DRAFT_URL_ALT = f"{GW_URL}/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1020"

    def open_draft_and_submit(self, doc_title: str = None, dry_run: bool = False) -> dict:
        """
        임시보관문서함에서 문서 1건을 열고 결재상신까지 E2E 수행.

        Args:
            doc_title: 열려는 문서 제목 (None이면 첫 번째 문서)
            dry_run: True면 상신 버튼을 찾기만 하고 클릭 안 함 (테스트용)
        Returns:
            {"success": bool, "message": str, "doc_title": str}
        """
        if not self.context:
            return {"success": False, "message": "BrowserContext가 필요합니다. (팝업 감지용)"}

        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        page = self.page
        self._close_popups()

        try:
            # ── 1단계: 임시보관문서함 이동 ──
            logger.info("[1/4] 임시보관문서함 이동")

            # 전자결재 모듈 진입 후 사이드바에서 임시보관문서 클릭
            draft_loaded = False

            # 방법 1: 전자결재 모듈 이동 → 사이드바 클릭
            self._navigate_to_approval_home()
            try:
                draft_link = page.locator("text=임시보관문서").first
                if draft_link.is_visible(timeout=5000):
                    draft_link.click(force=True)
                    logger.info("사이드바 '임시보관문서' 클릭")
                    page.wait_for_timeout(2000)
                    draft_loaded = True
            except Exception:
                logger.debug("사이드바 임시보관문서 클릭 실패")

            # 방법 2: URL 직접 이동 (기본)
            if not draft_loaded:
                page.goto(self.DRAFT_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

            # 방법 3: 폴백 URL
            # 임시보관문서 페이지 확인 (제목 행이 있거나 "임시보관문서" 텍스트가 보이는지)
            try:
                page.wait_for_selector(
                    "text=임시보관문서",
                    timeout=5000,
                )
            except Exception:
                logger.info("임시보관문서 텍스트 미발견 → 폴백 URL 시도")
                page.goto(self.DRAFT_URL_ALT, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)

            # 리스트 로드 대기
            try:
                page.wait_for_selector(
                    "div.titDiv .title span, div.titDiv .title, [data-orbit-component='OBTTooltip'] span",
                    timeout=10000,
                )
                logger.info("임시보관문서 리스트 로드 완료 (titDiv 감지)")
            except PlaywrightTimeout:
                logger.debug("titDiv 셀렉터 대기 타임아웃 — networkidle 폴백")
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeout:
                    pass

            _save_debug(page, "draft_01_list")

            # ── 2단계: 문서 클릭 ──
            logger.info("[2/4] 문서 클릭")
            popup_page = self._click_draft_document(doc_title)

            if not popup_page:
                _save_debug(page, "draft_error_no_popup")
                return {"success": False, "message": "임시보관문서를 열 수 없습니다. 목록을 확인해주세요."}

            # 팝업 SPA 렌더링 대기 (Loading 스피너 완료까지)
            try:
                popup_page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            # 추가: 문서 내용 로드 대기 (topBtn, 결재선, 제목 등)
            for wait_sel in ["div.topBtn", "text=상신", "text=보관", "th:has-text('제목')"]:
                try:
                    popup_page.wait_for_selector(wait_sel, timeout=8000)
                    logger.info(f"팝업 로드 확인: {wait_sel}")
                    break
                except Exception:
                    continue

            # 팝업에서 문서 제목 읽기
            opened_title = ""
            try:
                opened_title = popup_page.title() or popup_page.url
            except Exception:
                pass

            _save_debug(popup_page, "draft_02_popup_opened")

            # ── 3단계: 상신 버튼 찾기 ──
            logger.info("[3/4] 상신 버튼 탐색")
            submit_btn = self._find_submit_button(popup_page)

            if not submit_btn:
                _save_debug(popup_page, "draft_error_no_submit_btn")
                return {
                    "success": False,
                    "message": "상신 버튼을 찾을 수 없습니다. 문서 상태를 확인해주세요.",
                    "doc_title": opened_title,
                }

            # dry_run 모드: 버튼 확인만 하고 종료
            if dry_run:
                btn_text = submit_btn.inner_text().strip()
                logger.info(f"[dry_run] 상신 버튼 확인: '{btn_text}' — 클릭 안 함")
                return {
                    "success": True,
                    "message": f"[dry_run] 상신 버튼 확인 완료: '{btn_text}'. 실제 상신하려면 dry_run=False로 호출하세요.",
                    "doc_title": opened_title,
                }

            # ── 4단계: 결재상신 클릭 ──
            logger.info("[4/4] 결재상신 클릭")
            result = self._click_submit_button(popup_page, submit_btn)

            result["doc_title"] = opened_title
            return result

        except PlaywrightTimeout as e:
            logger.error(f"임시보관문서 상신 타임아웃: {e}")
            _save_debug(page, "draft_error_timeout")
            return {"success": False, "message": f"타임아웃 발생: {e}"}
        except Exception as e:
            logger.error(f"임시보관문서 상신 오류: {e}", exc_info=True)
            _save_debug(page, "draft_error")
            return {"success": False, "message": f"오류 발생: {e}"}

    def _click_draft_document(self, doc_title: str = None):
        """
        임시보관문서함에서 문서를 클릭하고 팝업 Page를 반환.

        WEHAGO 임시보관문서 리스트 DOM 구조:
          div.titDiv.h-box > div.OBTTooltip_root__3Hfed.title > span (문서 제목)
        OBTDataGrid가 아닌 일반 div 기반 리스트 뷰.

        클릭 전략:
        1. context.expect_page() + 더블클릭 (가장 안정적)
        2. WEHAGO 전용 셀렉터 + 폴링 기반 팝업 감지
        3. bounding box 기반 더블클릭
        """
        page = self.page

        def _setup_popup(popup_page):
            """팝업 페이지 초기화"""
            try:
                popup_page.wait_for_load_state("domcontentloaded", timeout=15000)
                popup_page.on("dialog", lambda d: d.accept())
            except Exception:
                pass
            return popup_page

        def _try_expect_page_click(el, label: str, dblclick: bool = True):
            """context.expect_page() + 클릭으로 팝업 안정적 감지"""
            try:
                text = (el.text_content(timeout=1000) or "").strip()
                logger.info(f"문서 {'더블' if dblclick else ''}클릭 시도 ({label}): '{text[:60]}'")
                with self.context.expect_page(timeout=10000) as new_page_info:
                    if dblclick:
                        el.dblclick(force=True)
                    else:
                        el.click(force=True)
                popup_page = new_page_info.value
                logger.info(f"팝업 감지 성공 ({label}): {popup_page.url[:80]}")
                return _setup_popup(popup_page)
            except Exception as e:
                logger.debug(f"expect_page 실패 ({label}): {e}")
            return None

        def _try_polling_click(el, label: str, dblclick: bool = True):
            """폴링 기반 팝업 감지 (expect_page 실패 시 폴백)"""
            pages_before = set(id(p) for p in self.context.pages)
            try:
                text = (el.text_content(timeout=1000) or "").strip()
                if dblclick:
                    el.dblclick(force=True)
                else:
                    el.click(force=True)
                logger.info(f"문서 {'더블' if dblclick else ''}클릭 ({label}): '{text[:60]}'")
            except Exception as e:
                logger.debug(f"클릭 실패 ({label}): {e}")
                return None

            # 팝업 감지 (최대 10초)
            for _ in range(20):
                for p in self.context.pages:
                    try:
                        if id(p) in pages_before or p.is_closed():
                            continue
                        p_url = p.url or ""
                        if p_url and p_url != "about:blank":
                            logger.info(f"팝업 감지 (폴링, {label}): {p_url[:80]}")
                            return _setup_popup(p)
                    except Exception:
                        continue
                time.sleep(0.5)
            return None

        # ── 대상 요소 찾기 ──
        target_el = None
        wehago_selectors = [
            "div.titDiv .title span",
            "div.titDiv .title",
            "div.titDiv",
        ]

        for sel in wehago_selectors:
            try:
                elements = page.locator(sel).all()
                if not elements:
                    continue

                for el in elements:
                    try:
                        if not el.is_visible(timeout=1000):
                            continue
                        el_text = (el.text_content(timeout=1000) or "").strip()
                        if not el_text:
                            continue
                        # doc_title 매칭 또는 첫 번째 요소
                        if doc_title:
                            if doc_title in el_text or el_text in doc_title:
                                target_el = el
                                break
                        else:
                            target_el = el
                            break
                    except Exception:
                        continue
                if target_el:
                    break
            except Exception:
                continue

        # doc_title로 텍스트 검색 폴백
        if not target_el and doc_title:
            try:
                el = page.locator(f"text={doc_title}").first
                if el.is_visible(timeout=2000):
                    target_el = el
            except Exception:
                pass

        # ── 클릭 시도 (대상 요소 발견 시) ──
        if target_el:
            # 1) expect_page + 더블클릭
            result = _try_expect_page_click(target_el, "WEHAGO 더블클릭", dblclick=True)
            if result:
                return result

            # 2) expect_page + 싱글클릭
            result = _try_expect_page_click(target_el, "WEHAGO 싱글클릭", dblclick=False)
            if result:
                return result

            # 3) 폴링 + 더블클릭
            result = _try_polling_click(target_el, "WEHAGO 폴링 더블클릭", dblclick=True)
            if result:
                return result

        # ── bounding box 기반 더블클릭 (셀렉터로 찾았지만 클릭이 안 먹히는 경우) ──
        for sel in wehago_selectors:
            try:
                el = page.locator(sel).first
                if not el.is_visible(timeout=1000):
                    continue
                box = el.bounding_box()
                if not box:
                    continue
                logger.info(f"bounding box 더블클릭: ({box['x']:.0f}, {box['y']:.0f})")
                pages_before = set(id(p) for p in self.context.pages)
                page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                time.sleep(1)
                for p in self.context.pages:
                    try:
                        if id(p) in pages_before or p.is_closed():
                            continue
                        p_url = p.url or ""
                        if p_url and p_url != "about:blank":
                            logger.info(f"팝업 감지 (bounding box): {p_url[:80]}")
                            return _setup_popup(p)
                    except Exception:
                        continue
                # 팝업 없으면 추가 대기
                for _ in range(14):
                    time.sleep(0.5)
                    for p in self.context.pages:
                        try:
                            if id(p) in pages_before or p.is_closed():
                                continue
                            if (p.url or "") not in ("", "about:blank"):
                                return _setup_popup(p)
                        except Exception:
                            continue
            except Exception:
                continue

        # ── JS evaluate 최종 시도: 더블클릭 이벤트 디스패치 ──
        try:
            title_found = page.evaluate("""() => {
                const spans = document.querySelectorAll('div.titDiv .title span');
                for (const span of spans) {
                    if (span.offsetParent && span.textContent.trim().length > 0) {
                        const evt = new MouseEvent('dblclick', {bubbles: true, cancelable: true, view: window});
                        span.dispatchEvent(evt);
                        return span.textContent.trim().substring(0, 60);
                    }
                }
                return null;
            }""")
            if title_found:
                logger.info(f"문서 더블클릭 (JS dispatch): '{title_found}'")
                pages_before_js = set(id(p) for p in self.context.pages)
                for _ in range(20):
                    time.sleep(0.5)
                    for p in self.context.pages:
                        try:
                            if id(p) in pages_before_js or p.is_closed():
                                continue
                            if (p.url or "") not in ("", "about:blank"):
                                return _setup_popup(p)
                        except Exception:
                            continue
        except Exception as e:
            logger.debug(f"JS dispatch 클릭 실패: {e}")

        logger.error("모든 클릭 방법 실패 — 임시보관문서 열기 불가")
        return None

    def _find_submit_button(self, doc_page: "Page"):
        """
        팝업 문서 페이지에서 결재상신 버튼을 찾아 반환.

        우선순위:
        1. div.topBtn:has-text('상신')  ← 실제 GW 패턴
        2. div.topBtn:has-text('결재상신')
        3. button:has-text('상신')
        """
        # div.topBtn 방식 (실제 GW 패턴)
        try:
            top_btns = doc_page.locator("div.topBtn").all()
            for btn in top_btns:
                try:
                    if not btn.is_visible(timeout=1000):
                        continue
                    txt = btn.inner_text().strip()
                    if txt in ("상신", "결재상신", "수정 후 상신"):
                        logger.info(f"상신 버튼 발견 (div.topBtn): '{txt}'")
                        return btn
                except Exception:
                    continue
        except Exception:
            pass

        # 폴백: button/a 태그
        for selector in [
            "button:has-text('결재상신')",
            "button:has-text('상신')",
            "a:has-text('상신')",
            "span:has-text('상신')",
        ]:
            try:
                candidates = doc_page.locator(selector).all()
                for c in candidates:
                    if c.is_visible(timeout=1000):
                        txt = c.inner_text().strip()
                        if "상신" in txt:
                            logger.info(f"상신 버튼 발견 (폴백 '{selector}'): '{txt}'")
                            return c
            except Exception:
                continue

        return None

    def _click_submit_button(self, doc_page: "Page", submit_btn) -> dict:
        """
        결재상신 버튼 클릭 후 결과 확인.

        Returns:
            {"success": bool, "message": str}
        """
        _save_debug(doc_page, "draft_03_before_submit")

        try:
            submit_btn.click(force=True)
            logger.info("결재상신 버튼 클릭 완료")
        except Exception as e:
            return {"success": False, "message": f"상신 버튼 클릭 실패: {e}"}

        # 상신 후 확인 다이얼로그 처리 (이미 page.on("dialog") 등록됨)
        # 네트워크 안정 대기
        try:
            doc_page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            logger.warning("상신 후 networkidle 타임아웃 — 계속 진행")
            time.sleep(3)
        except Exception:
            time.sleep(3)

        _save_debug(doc_page, "draft_04_after_submit")

        # 에러 메시지 확인
        try:
            error_el = doc_page.locator(
                "div.alert-message, div.error-message, .OBTAlert_message, div[class*='error']"
            ).first
            if error_el.is_visible(timeout=2000):
                err_text = error_el.inner_text().strip()
                logger.error(f"상신 후 에러 메시지: {err_text}")
                return {"success": False, "message": f"상신 중 오류: {err_text}"}
        except Exception:
            pass

        # 성공 시 팝업이 닫히거나 URL이 변경됨
        try:
            if doc_page.is_closed():
                logger.info("상신 완료 — 팝업 자동 닫힘")
                return {"success": True, "message": "결재상신이 완료되었습니다."}
        except Exception:
            pass

        # URL 변화 확인 (상신 완료 시 목록으로 이동하는 경우)
        current_url = ""
        try:
            current_url = doc_page.url
        except Exception:
            pass

        if "popup" not in current_url.lower() or doc_page.is_closed():
            return {"success": True, "message": "결재상신이 완료되었습니다."}

        # 상신 완료 텍스트 확인
        try:
            body_text = doc_page.inner_text("body")
            if any(kw in body_text for kw in ["상신 완료", "결재상신이 완료", "문서가 상신"]):
                return {"success": True, "message": "결재상신이 완료되었습니다."}
        except Exception:
            pass

        return {"success": True, "message": "결재상신 버튼을 클릭했습니다. 결과를 확인해주세요."}

    def create_proof_issuance(self, data: dict) -> dict:
        """
        [회계팀] 증빙발행 신청서 작성

        전자결재 양식 (인라인 폼).
        결재작성 → "[회계팀] 증빙발행 신청서" 검색 → 선택

        Args:
            data: {
                "title": "제목",                      # 필수
                "issue_type": "세금계산서",            # 발행구분
                "vendor_name": "발행처",               # 거래처명
                "business_number": "사업자번호",
                "supply_amount": 공급가액,
                "tax_amount": 세액,
                "issue_date": "YYYY-MM-DD",
                "item_description": "품목/내용",
                "note": "비고",
                "save_mode": "submit",
            }
        Returns:
            {"success": bool, "message": str}
        """
        validation = self._validate_required_fields(data, ["title"], "증빙발행신청서")
        if validation:
            return validation

        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        page = self.page
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()
                self._navigate_to_approval_home()
                self._click_write_approval()
                page.wait_for_timeout(1500)

                # 증빙발행 검색 및 클릭
                form_found = False
                for search_kw in ["증빙발행", "[회계팀] 증빙발행"]:
                    try:
                        for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                            try:
                                inp = page.locator(sel).first
                                if inp.is_visible(timeout=2000):
                                    inp.fill(search_kw)
                                    inp.press("Enter")
                                    page.wait_for_timeout(2000)
                                    break
                            except Exception:
                                continue

                        for click_kw in ["[회계팀] 증빙발행 신청서", "증빙발행 신청서", "증빙발행"]:
                            link = page.locator(f"text={click_kw}").first
                            if link.is_visible(timeout=2000):
                                link.click(force=True)
                                page.wait_for_timeout(3000)
                                form_found = True
                                logger.info(f"증빙발행 신청서 클릭: {click_kw}")
                                break
                        if form_found:
                            break
                    except Exception:
                        continue

                if not form_found:
                    raise Exception("증빙발행 신청서 양식을 찾을 수 없습니다.")

                # 양식 로드 대기 (제목 필드 확인)
                try:
                    page.locator("th:has-text('제목')").first.wait_for(state="visible", timeout=10000)
                except Exception:
                    raise Exception("증빙발행 신청서 양식 로드 실패")

                # 필드 채우기
                field_map = [
                    ("제목", data.get("title", "")),
                    ("발행구분", data.get("issue_type", "")),
                    ("발행처", data.get("vendor_name", "")),
                    ("사업자번호", data.get("business_number", "")),
                    ("공급가액", str(data.get("supply_amount", "")) if data.get("supply_amount") else ""),
                    ("세액", str(data.get("tax_amount", "")) if data.get("tax_amount") else ""),
                    ("발행일", data.get("issue_date", "")),
                    ("품목", data.get("item_description", "")),
                    ("내용", data.get("item_description", "")),
                    ("비고", data.get("note", "")),
                ]
                for label, value in field_map:
                    if value:
                        self._fill_field_by_label(label, value)

                # 결재선 설정
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "증빙발행")
                    self.set_approval_line(page, resolved_line)

                save_mode = data.get("save_mode", "verify")
                if save_mode == "submit":
                    result = self._submit_inline_form()
                    return result
                elif save_mode == "draft":
                    return self._create_proof_issuance_draft(data)
                else:
                    _save_debug(page, "proof_issuance_verify")
                    return {"success": True, "message": "증빙발행 신청서 필드 작성이 완료되었습니다. 내용을 확인 후 상신해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"증빙발행 신청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                last_error = e
                logger.error(f"증빙발행 신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        return {"success": False, "message": f"증빙발행 신청서 작성 실패: {str(last_error)}"}

    def _create_proof_issuance_draft(self, _data: dict) -> dict:
        """증빙발행 신청서 임시보관 (draft 모드)"""
        # TODO: 팝업 기반 보관 흐름 구현 (증빙발행 DOM 탐색 후)
        return {"success": False, "message": "증빙발행 임시보관은 아직 지원되지 않습니다. save_mode='submit'으로 시도해주세요."}

    def _click_advance_payment_form(self, form_type: str = "요청서"):
        """
        선급금 요청서/정산서 양식 선택 (인라인 폼)

        formId=181 URL 직접 접근 시도 (요청서), 실패 시 검색 폴백.
        정산서는 formId 미확인이므로 검색으로만 진입.

        Args:
            form_type: "요청서" 또는 "정산서"
        """
        page = self.page

        # 요청서: formId=181 URL 직접 접근 시도
        if form_type == "요청서":
            try:
                direct_url = (
                    f"{GW_URL}/#/HP/APB1020/APB1020"
                    f"?specialLnb=Y&moduleCode=HP&menuCode=APB1020&formId=181"
                )
                page.goto(direct_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                try:
                    page.wait_for_url("**/APB1020/**", timeout=8000)
                    logger.info(f"선급금 요청서 URL 직접 이동 성공: {page.url[:100]}")
                    return
                except Exception:
                    logger.warning(f"선급금 요청서 URL 직접 이동 후 APB1020 미확인: {page.url[:80]}")
            except Exception as e:
                logger.warning(f"선급금 요청서 URL 직접 이동 실패: {e}")

        # 검색 키워드 설정
        if form_type == "요청서":
            keywords = ["[본사]선급금 요청서", "선급금 요청서", "선급금"]
        else:
            keywords = ["[본사]선급금 정산서", "선급금 정산서", "선급금정산"]

        def _try_click_form(phase: str) -> bool:
            for keyword in keywords:
                try:
                    links = page.locator(f"text={keyword}").all()
                    for link in links:
                        if link.is_visible():
                            link.click(force=True)
                            logger.info(f"선급금 {form_type} 양식 클릭 ({phase}): '{keyword}'")
                            try:
                                page.wait_for_url("**/APB1020/**", timeout=8000)
                                logger.info(f"양식 페이지 이동 확인: {page.url[:100]}")
                                return True
                            except Exception:
                                logger.warning(f"양식 클릭 후 URL 미변경 (여전히 {page.url[:80]})")
                                try:
                                    page.wait_for_timeout(1000)
                                    link2 = page.locator(f"text={keyword}").first
                                    if link2.is_visible():
                                        link2.click(force=True)
                                        page.wait_for_url("**/APB1020/**", timeout=8000)
                                        logger.info(f"양식 페이지 재클릭 이동 확인: {page.url[:100]}")
                                        return True
                                except Exception:
                                    pass
                except Exception:
                    continue
            return False

        # 1차: 현재 페이지에서 양식 바로 찾기
        if _try_click_form("현재 페이지"):
            return

        # 2차: 결재작성 버튼 클릭 후 양식 검색
        logger.info(f"현재 페이지에 선급금 {form_type} 양식 없음 → 결재작성 클릭")
        self._click_write_approval()
        page.wait_for_timeout(1500)

        if _try_click_form("결재작성 경유"):
            return

        _save_debug(page, f"error_advance_payment_{form_type}_not_found")
        raise Exception(f"선급금 {form_type} 양식을 찾을 수 없습니다.")

    def _fill_advance_payment_fields(self, data: dict, form_type: str = "요청서"):
        """
        선급금 요청서/정산서 필드 채우기

        지출결의서와 동일한 인라인 폼 구조 (APB1020 화면).
        요청서 필드: 제목, 프로젝트, 요청사유, 은행명, 계좌번호, 예금주, 금액 (그리드)
        정산서 필드: 제목, 프로젝트, 정산내역, 선급금액, 사용금액, 반환금액

        Args:
            data: 양식 데이터 딕셔너리
            form_type: "요청서" 또는 "정산서"
        """
        page = self.page
        title = data.get("title", "")
        project = data.get("project", "")

        # 1. 프로젝트 코드도움 입력 (상단)
        if project:
            self._fill_project_code(project, y_hint=292)
            _save_debug(page, "adv_03a_after_project_top")

            # 프로젝트 입력 후 페이지 이탈 검증
            time.sleep(0.3)
            current_url = page.url
            if "/HP/" not in current_url:
                logger.warning(f"프로젝트 입력 후 페이지 이탈 감지: {current_url}")
                _save_debug(page, "adv_03a_page_escaped")

        # 2. 제목 입력
        if title:
            self._fill_field_by_label("제목", title)
        _save_debug(page, "adv_03_after_title")

        # 3. 양식별 텍스트 필드 채우기
        if form_type == "요청서":
            # 요청서 필드 맵: (라벨, data 키)
            field_map = [
                ("요청사유", "purpose"),
                ("은행명", "bank_name"),
                ("계좌번호", "account_number"),
                ("예금주", "account_holder"),
            ]
        else:
            # 정산서 필드 맵
            field_map = [
                ("정산내역", "description"),
                ("선급금액", "original_amount"),
                ("사용금액", "used_amount"),
                ("반환금액", "return_amount"),
            ]

        for label, key in field_map:
            val = data.get(key)
            if val is not None and str(val).strip():
                self._fill_field_by_label(label, str(val))

        # 4. 금액 그리드 입력 (요청서: 금액 항목을 그리드에 입력)
        if form_type == "요청서":
            amount = data.get("amount")
            vendor_name = data.get("vendor_name", "")
            if amount is not None:
                items = [{
                    "item": data.get("purpose", "선급금"),
                    "amount": amount,
                    "vendor": vendor_name,
                }]
                self._fill_grid_items(items)
                _save_debug(page, "adv_03b_after_grid")

        # 5. 지급요청일 / 증빙일자 입력
        payment_date = data.get("payment_date", "") or data.get("receipt_date", "") or data.get("date", "")
        if payment_date:
            self._fill_receipt_date(payment_date)
            _save_debug(page, "adv_03d_after_date")

        # 6. 하단 프로젝트 코드도움 입력
        if project:
            self._fill_project_code_bottom(project)
            _save_debug(page, "adv_03d2_after_project_bottom")

        # 7. 첨부파일 업로드
        attachment_path = data.get("attachment_path", "")
        if attachment_path:
            self._upload_attachment(attachment_path)
            _save_debug(page, "adv_03e_after_attachment")

        logger.info(f"선급금 {form_type} 필드 채우기 완료")

    def create_advance_payment_request(self, data: dict) -> dict:
        """
        [본사]선급금 요청서 작성 (인라인 폼 기반, 재시도 포함)

        지출결의서와 동일한 APB1020 인라인 폼 구조.
        formId=181 URL 직접 접근 후 필드 채우기.
        - save_mode="verify" (기본): 필드 작성 검증만 수행
        - save_mode="submit": 결재상신 실행
        - save_mode="draft": 팝업 기반 보관 (인라인 폼에 보관 버튼 없음)

        Args:
            data: {
                "title": "제목",                    # 필수
                "project": "프로젝트 (코드도움)",    # 선택
                "vendor_name": "거래처명",           # 선택
                "amount": 요청금액(숫자),             # 선택
                "payment_date": "지급요청일 (YYYY-MM-DD)",  # 선택
                "purpose": "요청사유",               # 선택
                "bank_name": "은행명",               # 선택
                "account_number": "계좌번호",        # 선택
                "account_holder": "예금주",          # 선택
                "attachment_path": "/path.pdf",      # 첨부파일 경로 (선택)
                "save_mode": "verify",               # "verify" | "submit" | "draft"
            }
        Returns:
            {"success": bool, "message": str}
        """
        # 필수 필드 검증
        validation = self._validate_required_fields(data, ["title"], "선급금요청")
        if validation:
            return validation

        # 세션 확인
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        save_mode = data.get("save_mode", "verify")

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()

                # 1. 전자결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 선급금 요청서 양식 클릭 (인라인 폼)
                self._click_advance_payment_form(form_type="요청서")

                # 3. 양식 로드 대기
                self._wait_for_form_load()

                # 4. 필드 채우기
                self._fill_advance_payment_fields(data, form_type="요청서")

                # 4-1. 결재선 커스텀 설정
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "선급금요청")
                    self.set_approval_line(self.page, resolved_line)

                # 4-2. 수신참조 설정
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "선급금요청")
                    self.set_cc_recipients(self.page, resolved_cc)

                # 5. 저장/검증
                if save_mode == "submit":
                    result = self._submit_inline_form()
                elif save_mode == "draft":
                    # 인라인 폼에는 보관 버튼이 없으므로 verify로 처리
                    logger.warning("선급금 요청서 draft 모드: 인라인 폼에 보관 버튼 없음 → verify로 처리")
                    result = self._verify_expense_fields(data)
                else:
                    # verify: 필드 작성 검증만
                    result = self._verify_expense_fields(data)

                return result

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"선급금 요청서 작성 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(self.page, f"adv_req_error_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}
                    self._close_popups()
                    time.sleep(RETRY_DELAY)

            except Exception as e:
                last_error = e
                logger.error(f"선급금 요청서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"adv_req_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        _save_debug(self.page, "adv_req_error_final")
        return {"success": False, "message": f"선급금 요청서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def create_advance_payment_settlement(self, data: dict) -> dict:
        """
        [본사]선급금 정산서 작성 (인라인 폼 기반, 재시도 포함)

        지출결의서와 동일한 APB1020 인라인 폼 구조.
        formId 미확인 → 검색으로 진입.
        - save_mode="verify" (기본): 필드 작성 검증만 수행
        - save_mode="submit": 결재상신 실행
        - save_mode="draft": verify로 처리 (인라인 폼에 보관 버튼 없음)

        Args:
            data: {
                "title": "제목",                    # 필수
                "project": "프로젝트 (코드도움)",    # 선택
                "vendor_name": "거래처명",           # 선택
                "original_amount": 선급금액(숫자),   # 선택
                "used_amount": 사용금액(숫자),        # 선택
                "return_amount": 반환금액(숫자),      # 선택 (자동계산 가능)
                "description": "정산내역",           # 선택
                "attachment_path": "/path.pdf",      # 첨부파일 경로 (선택)
                "save_mode": "verify",               # "verify" | "submit" | "draft"
            }
        Returns:
            {"success": bool, "message": str}
        """
        # 필수 필드 검증
        validation = self._validate_required_fields(data, ["title"], "선급금정산")
        if validation:
            return validation

        # 세션 확인
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        save_mode = data.get("save_mode", "verify")

        # return_amount 자동 계산 (미입력 시)
        if not data.get("return_amount"):
            orig = data.get("original_amount")
            used = data.get("used_amount")
            if orig is not None and used is not None:
                try:
                    data = dict(data)  # 원본 수정 방지
                    data["return_amount"] = int(orig) - int(used)
                    logger.info(f"반환금액 자동 계산: {orig} - {used} = {data['return_amount']}")
                except Exception:
                    pass

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()

                # 1. 전자결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 선급금 정산서 양식 클릭 (인라인 폼)
                self._click_advance_payment_form(form_type="정산서")

                # 3. 양식 로드 대기
                self._wait_for_form_load()

                # 4. 필드 채우기
                self._fill_advance_payment_fields(data, form_type="정산서")

                # 4-1. 결재선 커스텀 설정
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "선급금정산")
                    self.set_approval_line(self.page, resolved_line)

                # 4-2. 수신참조 설정
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "선급금정산")
                    self.set_cc_recipients(self.page, resolved_cc)

                # 5. 저장/검증
                if save_mode == "submit":
                    result = self._submit_inline_form()
                elif save_mode == "draft":
                    logger.warning("선급금 정산서 draft 모드: 인라인 폼에 보관 버튼 없음 → verify로 처리")
                    result = self._verify_expense_fields(data)
                else:
                    result = self._verify_expense_fields(data)

                return result

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"선급금 정산서 작성 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(self.page, f"adv_sett_error_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}
                    self._close_popups()
                    time.sleep(RETRY_DELAY)

            except Exception as e:
                last_error = e
                logger.error(f"선급금 정산서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"adv_sett_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        _save_debug(self.page, "adv_sett_error_final")
        return {"success": False, "message": f"선급금 정산서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def create_overtime_request(self, data: dict) -> dict:
        """
        연장근무신청서 작성 (근태관리 모듈)

        근태관리 모듈 경로:
        - 결재작성 → "연장근무신청서" 검색 → 선택 (formId=43)
        - 또는 근태관리 > 근태신청 > 연장근무신청서 직접 이동

        Args:
            data: {
                "title": "제목",               # 필수 (표시용, 실제 폼 제목 필드 없을 수 있음)
                "work_date": "YYYY-MM-DD",     # 근무일
                "start_time": "HH:MM",         # 시작시간
                "end_time": "HH:MM",           # 종료시간
                "reason": "사유",               # 비고/사유
                "work_type": "연장근무",        # 근무구분 (조기근무/연장근무/휴일근무, 기본: 연장근무)
                "save_mode": "submit",          # "submit" | "verify"
            }
        Returns:
            {"success": bool, "message": str}
        """
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        page = self.page
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()
                self._navigate_to_approval_home()

                # 결재작성 클릭
                self._click_write_approval()
                page.wait_for_timeout(1500)

                # 연장근무신청서 검색 및 선택
                search_keywords = ["연장근무신청서", "연장근무"]
                form_found = False
                for kw in search_keywords:
                    try:
                        # 검색창 입력
                        for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                            try:
                                inp = page.locator(sel).first
                                if inp.is_visible(timeout=2000):
                                    inp.fill(kw)
                                    inp.press("Enter")
                                    page.wait_for_timeout(1500)
                                    break
                            except Exception:
                                continue
                        # 결과 클릭
                        link = page.locator("text=연장근무신청서").first
                        if link.is_visible(timeout=3000):
                            link.click(force=True)
                            page.wait_for_timeout(3000)
                            form_found = True
                            logger.info("연장근무신청서 양식 클릭 완료")
                            break
                    except Exception:
                        continue

                if not form_found:
                    raise Exception("연장근무신청서 양식을 찾을 수 없습니다.")

                # 필드 채우기
                work_date = data.get("work_date", "")
                start_time = data.get("start_time", "")
                end_time = data.get("end_time", "")
                reason = data.get("reason", "")
                work_type = data.get("work_type", "연장근무")

                # 근무구분 선택 (라디오 또는 선택 버튼)
                if work_type:
                    for sel in [f"text={work_type}", f"input[value='{work_type}']"]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.click(force=True)
                                logger.info(f"근무구분 선택: {work_type}")
                                break
                        except Exception:
                            continue

                # 날짜 입력
                for label in ["연장근무시작일", "근무일", "시작일"]:
                    try:
                        if self._fill_field_by_label(label, work_date):
                            logger.info(f"날짜 필드 '{label}' 입력: {work_date}")
                            break
                    except Exception:
                        continue

                # 시작/종료 시간
                for label in ["시작시간", "시작"]:
                    try:
                        if start_time and self._fill_field_by_label(label, start_time):
                            logger.info(f"시작시간 입력: {start_time}")
                            break
                    except Exception:
                        continue

                for label in ["종료시간", "종료"]:
                    try:
                        if end_time and self._fill_field_by_label(label, end_time):
                            logger.info(f"종료시간 입력: {end_time}")
                            break
                    except Exception:
                        continue

                # 비고/사유
                if reason:
                    for label in ["비고", "사유", "내용"]:
                        try:
                            if self._fill_field_by_label(label, reason):
                                logger.info(f"사유 입력: {reason}")
                                break
                        except Exception:
                            continue

                save_mode = data.get("save_mode", "verify")
                if save_mode == "submit":
                    # 신청완료 버튼 클릭
                    for btn_text in ["신청완료", "저장", "상신", "완료"]:
                        try:
                            btn = page.locator(f"button:has-text('{btn_text}')").first
                            if btn.is_visible(timeout=2000):
                                btn.click(force=True)
                                page.wait_for_timeout(2000)
                                logger.info(f"연장근무신청서 신청완료 클릭: {btn_text}")
                                return {"success": True, "message": "연장근무신청서가 신청 완료되었습니다."}
                        except Exception:
                            continue
                    return {"success": False, "message": "신청완료 버튼을 찾을 수 없습니다. 화면을 확인해주세요."}
                else:
                    # verify 모드: 필드 채우기만 확인
                    _save_debug(page, "overtime_verify")
                    return {"success": True, "message": "연장근무신청서 필드 작성이 완료되었습니다. 내용을 확인 후 신청해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"연장근무신청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                last_error = e
                logger.error(f"연장근무신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        return {"success": False, "message": f"연장근무신청서 작성 실패: {str(last_error)}"}

    def create_outside_work_request(self, data: dict) -> dict:
        """
        외근신청서(당일) 작성 (근태관리 모듈)

        Args:
            data: {
                "title": "제목",
                "work_date": "YYYY-MM-DD",
                "destination": "방문처",
                "purpose": "외근사유/업무내용",
                "start_time": "HH:MM",         # 선택
                "end_time": "HH:MM",           # 선택
                "work_type": "종일외근",        # 외근구분 (종일외근/외근후출근/출근후외근)
                "transport": "대중교통",         # 교통수단 (선택)
                "save_mode": "submit",
            }
        Returns:
            {"success": bool, "message": str}
        """
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        page = self.page
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()
                self._navigate_to_approval_home()
                self._click_write_approval()
                page.wait_for_timeout(1500)

                # 외근신청서 검색 및 선택
                form_found = False
                for kw in ["외근신청서", "외근신청서(당일)", "외근"]:
                    try:
                        for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                            try:
                                inp = page.locator(sel).first
                                if inp.is_visible(timeout=2000):
                                    inp.fill(kw)
                                    inp.press("Enter")
                                    page.wait_for_timeout(1500)
                                    break
                            except Exception:
                                continue
                        link = page.locator("text=외근신청서").first
                        if link.is_visible(timeout=3000):
                            link.click(force=True)
                            page.wait_for_timeout(3000)
                            form_found = True
                            logger.info("외근신청서 양식 클릭 완료")
                            break
                    except Exception:
                        continue

                if not form_found:
                    raise Exception("외근신청서 양식을 찾을 수 없습니다.")

                # 필드 채우기
                work_date = data.get("work_date", "")
                destination = data.get("destination", "")
                purpose = data.get("purpose", "")
                start_time = data.get("start_time", "")
                end_time = data.get("end_time", "")
                work_type = data.get("work_type", "")
                transport = data.get("transport", "")

                # 외근구분 선택
                if work_type:
                    for sel in [f"text={work_type}", f"input[value='{work_type}']"]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.click(force=True)
                                logger.info(f"외근구분 선택: {work_type}")
                                break
                        except Exception:
                            continue

                # 날짜
                for label in ["외근기간", "외근일", "날짜"]:
                    try:
                        if work_date and self._fill_field_by_label(label, work_date):
                            logger.info(f"날짜 입력: {work_date}")
                            break
                    except Exception:
                        continue

                # 시간
                if start_time:
                    for label in ["시작시간", "출발시간"]:
                        try:
                            if self._fill_field_by_label(label, start_time):
                                break
                        except Exception:
                            continue
                if end_time:
                    for label in ["종료시간", "복귀시간"]:
                        try:
                            if self._fill_field_by_label(label, end_time):
                                break
                        except Exception:
                            continue

                # 방문처/교통수단/업무내용
                if destination:
                    for label in ["방문처", "목적지"]:
                        try:
                            if self._fill_field_by_label(label, destination):
                                break
                        except Exception:
                            continue
                if transport:
                    for label in ["교통수단"]:
                        try:
                            if self._fill_field_by_label(label, transport):
                                break
                        except Exception:
                            continue
                if purpose:
                    for label in ["업무내용", "외근사유", "내용", "사유"]:
                        try:
                            if self._fill_field_by_label(label, purpose):
                                break
                        except Exception:
                            continue

                save_mode = data.get("save_mode", "verify")
                if save_mode == "submit":
                    for btn_text in ["저장", "신청완료", "상신", "완료"]:
                        try:
                            btn = page.locator(f"button:has-text('{btn_text}')").first
                            if btn.is_visible(timeout=2000):
                                btn.click(force=True)
                                page.wait_for_timeout(2000)
                                logger.info(f"외근신청서 저장 클릭: {btn_text}")
                                return {"success": True, "message": "외근신청서가 신청 완료되었습니다."}
                        except Exception:
                            continue
                    return {"success": False, "message": "저장 버튼을 찾을 수 없습니다. 화면을 확인해주세요."}
                else:
                    _save_debug(page, "outside_work_verify")
                    return {"success": True, "message": "외근신청서 필드 작성이 완료되었습니다. 내용을 확인 후 신청해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"외근신청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                last_error = e
                logger.error(f"외근신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        return {"success": False, "message": f"외근신청서 작성 실패: {str(last_error)}"}

    def create_referral_bonus_request(self, data: dict) -> dict:
        """
        사내추천비 자금 요청서 작성

        전자결재 양식. 결재작성 → "사내추천비" 검색 → "사내추천비 지급 요청서" 선택.

        Args:
            data: {
                "title": "제목",
                "recommended_person": "추천대상자",
                "recommender": "추천인",
                "amount": 요청금액,
                "purpose": "사용목적",
                "description": "상세내용 (선택)",
                "save_mode": "submit",
            }
        Returns:
            {"success": bool, "message": str}
        """
        validation = self._validate_required_fields(data, ["title"], "사내추천비요청서")
        if validation:
            return validation

        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        page = self.page
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()
                self._navigate_to_approval_home()
                self._click_write_approval()
                page.wait_for_timeout(1500)

                # 사내추천비 검색 및 클릭
                form_found = False
                for search_kw in ["사내추천비"]:
                    try:
                        for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                            try:
                                inp = page.locator(sel).first
                                if inp.is_visible(timeout=2000):
                                    inp.fill(search_kw)
                                    inp.press("Enter")
                                    page.wait_for_timeout(2000)
                                    break
                            except Exception:
                                continue

                        for click_kw in ["사내추천비 지급 요청서", "사내추천비지급요청서", "사내추천비"]:
                            link = page.locator(f"text={click_kw}").first
                            if link.is_visible(timeout=2000):
                                link.click(force=True)
                                page.wait_for_timeout(3000)
                                form_found = True
                                logger.info(f"사내추천비 요청서 클릭: {click_kw}")
                                break
                        if form_found:
                            break
                    except Exception:
                        continue

                if not form_found:
                    raise Exception("사내추천비 지급 요청서 양식을 찾을 수 없습니다.")

                # 양식 로드 대기
                try:
                    page.locator("th:has-text('제목')").first.wait_for(state="visible", timeout=10000)
                except Exception:
                    raise Exception("사내추천비 요청서 양식 로드 실패")

                # 필드 채우기
                field_map = [
                    ("제목", data.get("title", "")),
                    ("추천대상자", data.get("recommended_person", "")),
                    ("추천인", data.get("recommender", "")),
                    ("요청금액", str(data.get("amount", "")) if data.get("amount") else ""),
                    ("금액", str(data.get("amount", "")) if data.get("amount") else ""),
                    ("사용목적", data.get("purpose", "")),
                    ("상세내용", data.get("description", "")),
                    ("내용", data.get("description", "")),
                ]
                for label, value in field_map:
                    if value:
                        self._fill_field_by_label(label, value)

                # 결재선 설정
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "사내추천비")
                    self.set_approval_line(page, resolved_line)

                save_mode = data.get("save_mode", "verify")
                if save_mode == "submit":
                    result = self._submit_inline_form()
                    return result
                else:
                    _save_debug(page, "referral_bonus_verify")
                    return {"success": True, "message": "사내추천비 요청서 필드 작성이 완료되었습니다. 내용을 확인 후 상신해주세요."}

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"사내추천비 요청서 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                last_error = e
                logger.error(f"사내추천비 요청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        return {"success": False, "message": f"사내추천비 요청서 작성 실패: {str(last_error)}"}

    def create_form(self, form_key: str, data: dict) -> dict:
        """
        양식 키로 적절한 작성 메서드를 라우팅

        Args:
            form_key: FORM_TEMPLATES 키 (예: "지출결의서", "거래처등록")
            data: 양식별 데이터 딕셔너리
        Returns:
            {"success": bool, "message": str}
        """
        # 양식 키 → 메서드 매핑
        method_map = {
            "지출결의서": self.create_expense_report,
            "거래처등록": self.create_vendor_registration,
            "증빙발행": self.create_proof_issuance,
            "선급금요청": self.create_advance_payment_request,
            "선급금정산": self.create_advance_payment_settlement,
            "연장근무": self.create_overtime_request,
            "외근신청": self.create_outside_work_request,
            "사내추천비": self.create_referral_bonus_request,
        }

        method = method_map.get(form_key)
        if not method:
            return {"success": False, "message": f"지원하지 않는 양식입니다: {form_key}"}

        return method(data)
