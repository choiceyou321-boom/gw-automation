"""
전자결재 자동화 -- 기타 양식 mixin (선급금, 연장근무, 외근, 추천장려금 등)
"""

import os
import logging
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from src.approval.base import GW_URL, MAX_RETRIES, RETRY_DELAY, SCREENSHOT_DIR, _save_debug
from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients

logger = logging.getLogger("approval_automation")


class OtherFormsMixin:
    """기타 전자결재 양식"""

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
                # 전자결재 HOME으로 먼저 이동 후 지출결의서 양식 열기
                self._navigate_to_approval_home()
                self._click_expense_form()
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


    def create_proof_issuance(self, data: dict) -> dict:
        """
        [회계팀] 증빙발행 신청서 작성

        전자결재 양식 (인라인 폼).
        결재작성 -> "[회계팀] 증빙발행 신청서" 검색 -> 선택

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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
            except Exception as e:
                last_error = e
                logger.error(f"증빙발행 신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        return {"success": False, "message": f"증빙발행 신청서 작성 실패: {str(last_error)}"}

    def _create_proof_issuance_draft(self, _data: dict) -> dict:
        """
        증빙발행 신청서 임시보관 (draft 모드)

        인라인 폼에는 '보관' 버튼이 없으므로
        결재상신 클릭 -> 팝업 열림 -> 팝업에서 '보관' 버튼 클릭 흐름으로 처리.
        (지출결의서 _create_expense_report_via_popup 패턴과 동일)

        호출 시점: create_proof_issuance()에서 필드 채우기 완료 후.
        """
        if not self.context:
            return {"success": False, "message": "BrowserContext가 필요합니다. (팝업 기반 보관)"}

        page = self.page
        popup_page = None

        try:
            # dialog 핸들러: GW가 confirm/alert를 띄울 수 있음
            dialog_messages = []

            def _handle_dialog(dialog):
                msg = dialog.message
                dialog_messages.append(msg)
                logger.info(f"[증빙발행 보관] dialog 감지: {msg[:100]}")
                dialog.accept()

            page.on("dialog", _handle_dialog)

            # ── 1단계: 결재상신 버튼 찾기 ──
            logger.info("[증빙발행 보관 1/3] 결재상신 버튼 탐색")
            submit_btn = None
            for sel in [
                "div.topBtn:has-text('결재상신')",
                "button:has-text('결재상신')",
                "[class*='topBtn']:has-text('결재상신')",
                "text=결재상신",
            ]:
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=2000):
                        submit_btn = loc
                        logger.info(f"결재상신 버튼 발견: {sel}")
                        break
                except Exception:
                    continue

            if not submit_btn:
                _save_debug(page, "proof_draft_error_no_submit_btn")
                return {"success": False, "message": "결재상신 버튼을 찾을 수 없습니다."}

            # ── 2단계: 결재상신 클릭 -> 팝업 대기 ──
            logger.info("[증빙발행 보관 2/3] 결재상신 클릭 -> 팝업 대기")

            # expect_page로 팝업 감지
            try:
                with self.context.expect_page(timeout=15000) as new_page_info:
                    submit_btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    submit_btn.click()
                    logger.info("결재상신 클릭 -> 팝업 대기 (expect_page)")
                popup_page = new_page_info.value
                logger.info(f"결재상신 팝업 감지: {popup_page.url[:100]}")
            except Exception as e:
                logger.warning(f"expect_page 팝업 감지 실패: {e}")

            # expect_page 실패 시 폴링 폴백
            if not popup_page:
                pages_before = set(id(p) for p in self.context.pages)
                try:
                    submit_btn.click()
                    logger.info("결재상신 재클릭 -> 폴링 대기")
                except Exception:
                    pass
                for _ in range(20):
                    page.wait_for_timeout(500)
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
            page.remove_listener("dialog", _handle_dialog)

            if not popup_page:
                _save_debug(page, "proof_draft_error_no_popup")
                # dialog 메시지가 있으면 검증 오류로 판단
                if dialog_messages:
                    return {"success": False, "message": f"결재상신 검증 오류: {'; '.join(dialog_messages[:3])}"}
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
                logger.warning("팝업 div.topBtn 대기 타임아웃 -- 계속 진행")
                page.wait_for_timeout(3000)

            _save_debug(popup_page, "proof_draft_02_popup_opened")

            # ── 3단계: 팝업에서 보관 버튼 클릭 ──
            logger.info("[증빙발행 보관 3/3] 팝업 보관 버튼 클릭")

            save_btn = None
            # 팝업 상단 div.topBtn 중 텍스트 "보관"
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
                _save_debug(popup_page, "proof_draft_error_no_save_btn")
                return {"success": False, "message": "팝업에서 보관 버튼을 찾을 수 없습니다."}

            _save_debug(popup_page, "proof_draft_03_before_save")
            save_btn.click(force=True)
            logger.info("팝업 보관 버튼 클릭 완료")

            # 보관 후 결과 대기
            try:
                popup_page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeout:
                logger.warning("팝업 보관 후 네트워크 대기 타임아웃")
                page.wait_for_timeout(3000)
            except Exception:
                page.wait_for_timeout(3000)

            # 에러 메시지 확인
            try:
                error_msg = popup_page.locator(
                    "div.alert-message, div.error-message, .OBTAlert_message"
                ).first
                if error_msg.is_visible(timeout=2000):
                    text = error_msg.inner_text()
                    logger.error(f"증빙발행 보관 에러: {text}")
                    _save_debug(popup_page, "proof_draft_error_save_response")
                    return {"success": False, "message": f"보관 중 오류: {text}"}
            except Exception:
                pass  # 에러 없음 = 정상

            # 팝업이 자동으로 닫혔는지 확인
            try:
                if popup_page.is_closed():
                    logger.info("팝업 자동 닫힘 -- 보관 완료")
            except Exception:
                pass

            _save_debug(popup_page, "proof_draft_04_after_save")
            logger.info("증빙발행 신청서 보관(임시저장) 완료")
            return {"success": True, "message": "증빙발행 신청서가 임시보관되었습니다. (상신 전 상태)"}

        except PlaywrightTimeout as e:
            logger.error(f"증빙발행 보관 타임아웃: {e}")
            if popup_page:
                _save_debug(popup_page, "proof_draft_error_timeout")
            return {"success": False, "message": f"증빙발행 보관 타임아웃: {e}"}
        except Exception as e:
            logger.error(f"증빙발행 보관 실패: {e}", exc_info=True)
            if popup_page:
                _save_debug(popup_page, "proof_draft_error")
            return {"success": False, "message": f"증빙발행 보관 오류: {e}"}
        finally:
            # 팝업 정리 (실패 시)
            if popup_page and not popup_page.is_closed():
                try:
                    popup_page.close()
                except Exception:
                    pass

    def _click_advance_payment_form(self, form_type: str = "요청서"):
        """
        선급금 요청서/정산서 양식 선택 (인라인 폼)

        formId=181 URL 직접 접근 시도 (요청서), 실패 시 검색 폴백.
        정산서는 formId 미확인이므로 검색으로만 진입.

        Args:
            form_type: "요청서" 또는 "정산서"
        """
        page = self.page

        # ⚠️ formId=181 URL 직접 접근 비활성화:
        # tgjeon 계정에서 "권한 없는 메뉴" 팝업 → GW 메인으로 리다이렉트됨.
        # 결재작성 → 양식 검색 경로로만 접근한다.

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

        # 2차: 전자결재 모듈 재진입 후 결재작성
        logger.info(f"현재 페이지에 선급금 {form_type} 양식 없음 -> 결재작성 클릭")
        # URL 직접 이동 실패 후 GW 메인으로 돌아온 경우 → EA 모듈 재진입
        if "APB1020" not in page.url and "EA" not in page.url:
            logger.info("전자결재 모듈 재진입...")
            self._navigate_to_approval_home()
            page.wait_for_timeout(1000)
        self._click_write_approval()
        page.wait_for_timeout(1500)

        if _try_click_form("결재작성 경유"):
            return

        # 3차: 양식 검색 input에 키워드 입력 후 검색
        logger.info("양식 검색 input에 '선급금' 입력 시도...")
        search_input = page.locator(
            "input[placeholder*='양식'], input[placeholder*='검색'], "
            "input[class*='search'], input[type='search']"
        ).first
        try:
            if search_input.is_visible(timeout=2000):
                search_input.fill("선급금")
                page.keyboard.press("Enter")
                page.wait_for_timeout(2000)
                logger.info("양식 검색 완료, 결과에서 양식 찾기 시도...")
                _save_debug(page, f"advance_payment_search_result")
                if _try_click_form("양식 검색 후"):
                    return
        except Exception as e:
            logger.warning(f"양식 검색 input 사용 실패: {e}")

        _save_debug(page, f"error_advance_payment_{form_type}_not_found")
        raise Exception(f"선급금 {form_type} 양식을 찾을 수 없습니다.")

    def _inspect_form_labels(self, page):
        """
        폼의 모든 <th> 라벨 텍스트를 수집하여 로깅하는 진단 도구.

        GW_DEBUG_DOM=1 환경변수 설정 시 _fill_advance_payment_fields() 시작 부분에서 호출.
        실제 GW DOM에서 필드 라벨명을 확인할 때 사용한다.
        """
        try:
            th_elements = page.locator("th").all()
            labels = []
            for th in th_elements:
                try:
                    text = th.inner_text(timeout=1000).strip()
                    if text:
                        labels.append(text)
                except Exception:
                    continue
            logger.info(f"[DOM 검사] 폼 th 라벨 {len(labels)}개: {labels}")
            return labels
        except Exception as e:
            logger.warning(f"[DOM 검사] th 라벨 수집 실패: {e}")
            return []

    def _handle_bank_picker(self, bank_name: str) -> bool:
        """
        금융기관코드도움 picker로 은행 선택.

        placeholder="금융기관코드도움" input 클릭 → OBTDialog2 팝업 → 검색 → 선택.
        expense.py 프로젝트 코드도움 picker 패턴 재사용.

        Args:
            bank_name: 은행 키워드 (예: "국민", "신한", "우리")
        Returns:
            선택 성공 여부
        """
        page = self.page
        _picker_sel = ".OBTDialog2_dialogRootOpen__3PExr"

        try:
            inp = page.locator("input[placeholder='금융기관코드도움']").first
            if not inp.is_visible(timeout=3000):
                logger.warning("금융기관코드도움 input 미발견")
                return False

            # 기존값 초기화 + 클릭
            inp.click(click_count=3, force=True)
            page.wait_for_timeout(300)
            inp.type(bank_name, delay=50)
            page.wait_for_timeout(1000)

            # OBTDialog2 피커 열림 확인
            picker_opened = page.locator(_picker_sel).count() > 0
            if not picker_opened:
                # 피커 미열림 → Enter로 트리거 시도
                page.keyboard.press("Enter")
                page.wait_for_timeout(1000)
                picker_opened = page.locator(_picker_sel).count() > 0

            if not picker_opened:
                logger.warning("금융기관 코드도움 피커가 열리지 않음 — 텍스트 입력으로 폴백")
                return False

            logger.info("금융기관 코드도움 피커 열림 → 검색/선택 시도")

            # 피커 내 검색 버튼 클릭 또는 Enter
            search_btn_found = False
            for sbsel in [
                f"{_picker_sel} button[class*='searchButton']",
                f"{_picker_sel} button:has(img[src*='search'])",
            ]:
                try:
                    sb = page.locator(sbsel).first
                    if sb.is_visible(timeout=500):
                        sb.click()
                        search_btn_found = True
                        break
                except Exception:
                    continue
            if not search_btn_found:
                page.keyboard.press("Enter")

            # 그리드 출현 대기 (최대 5초)
            for _ in range(10):
                grid_cnt = page.locator(f"{_picker_sel} .OBTDataGrid_grid__22Vfl").count()
                canvas_cnt = page.locator(f"{_picker_sel} canvas").count()
                if grid_cnt > 0 or canvas_cnt > 0:
                    break
                page.wait_for_timeout(500)

            page.wait_for_timeout(500)

            # React Fiber API로 첫 행 선택
            selected = False
            if page.locator(f"{_picker_sel} .OBTDataGrid_grid__22Vfl").count() > 0:
                result = page.evaluate("""(pickerSel) => {
                    const picker = document.querySelector(pickerSel);
                    if (!picker) return { success: false, reason: 'no_picker' };
                    const grid = picker.querySelector('.OBTDataGrid_grid__22Vfl');
                    if (!grid) return { success: false, reason: 'no_grid' };
                    const fk = Object.keys(grid).find(k =>
                        k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                    );
                    if (!fk) return { success: false, reason: 'no_fiber' };
                    let f = grid[fk];
                    for (let i = 0; i < 3 && f; i++) f = f.return;
                    const iface = f && f.stateNode && f.stateNode.state && f.stateNode.state.interface;
                    if (!iface || typeof iface.getRowCount !== 'function')
                        return { success: false, reason: 'no_iface' };
                    const rowCount = iface.getRowCount();
                    if (rowCount === 0) return { success: false, reason: 'empty_grid' };
                    iface.setSelection({ rowIndex: 0, columnIndex: 0 });
                    iface.focus({ rowIndex: 0, columnIndex: 0 });
                    return { success: true, rowCount: rowCount };
                }""", _picker_sel)
                logger.info(f"금융기관 피커 React Fiber 결과: {result}")
                if result and result.get("success"):
                    selected = True

            if not selected:
                # 폴백: canvas 더블클릭 (첫 행 y=36)
                canvas = page.locator(f"{_picker_sel} canvas").first
                if canvas.is_visible(timeout=1000):
                    canvas.dblclick(position={"x": 100, "y": 36})
                    selected = True
                    logger.info("금융기관 피커 canvas 더블클릭 폴백")

            if selected:
                page.wait_for_timeout(300)
                # 확인 버튼 클릭
                for btn_sel in [
                    f"{_picker_sel} button:has-text('확인')",
                    f"{_picker_sel} [class*='confirmButton']",
                ]:
                    try:
                        btn = page.locator(btn_sel).first
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            logger.info("금융기관 피커 확인 버튼 클릭")
                            break
                    except Exception:
                        continue
                page.wait_for_timeout(500)

            # 피커 닫기 확인 (남아있으면 취소)
            if page.locator(_picker_sel).count() > 0:
                try:
                    cancel = page.locator(f"{_picker_sel} button:has-text('취소')").first
                    if cancel.is_visible(timeout=500):
                        cancel.click()
                except Exception:
                    pass

            logger.info(f"금융기관 코드도움 피커 처리 완료: selected={selected}")
            return selected

        except Exception as e:
            logger.warning(f"금융기관 코드도움 피커 처리 실패: {e}")
            # 예외 발생 시 열려있는 피커 정리
            try:
                if page.locator(_picker_sel).count() > 0:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
            except Exception:
                pass
            return False

    def _fill_field_by_label_candidates(self, candidates: list[str], value: str) -> bool:
        """
        여러 후보 라벨을 순차 시도하여 필드를 채우는 폴백 메서드.

        _fill_field_by_label()을 후보별로 호출하며 첫 성공 시 True 반환.

        Args:
            candidates: 라벨 후보 리스트 (예: ["요청사유", "사유", "지급사유"])
            value: 입력할 값
        Returns:
            성공 여부
        """
        for label in candidates:
            if self._fill_field_by_label(label, value):
                return True
        logger.warning(f"폴백 라벨 모두 실패: {candidates}")
        return False

    def _fill_advance_payment_fields(self, data: dict, form_type: str = "요청서"):
        """
        선급금 요청서/정산서 필드 채우기

        지출결의서와 동일한 인라인 폼 구조 (APB1020 화면).
        요청서 필드: 제목, 프로젝트, 요청사유, 은행명, 계좌번호, 예금주, 금액 (그리드)
        정산서 필드: 제목, 프로젝트, 정산내역, 선급금액, 사용금액, 반환금액

        GW 검증 상태:
        - formId=181 (요청서) 확인 완료 (Phase 0)
        - 인라인 폼 구조 (APB1020) 확인 완료
        - 개별 필드 라벨("요청사유", "은행명" 등)은 지출결의서와 유사한 구조로 추정
          → GW 실제 DOM에서 th 라벨명 최종 확인 필요
        - 정산서 formId 미확인 → 검색 방식으로만 진입

        Args:
            data: 양식 데이터 딕셔너리
            form_type: "요청서" 또는 "정산서"
        """
        page = self.page

        # DOM 검사: GW_DEBUG_DOM 환경변수 설정 시에만 실행
        if os.environ.get("GW_DEBUG_DOM"):
            self._inspect_form_labels(page)

        title = data.get("title", "")
        project = data.get("project", "")

        # 1. 프로젝트 코드도움 입력 (상단)
        # 지출결의서와 동일한 placeholder="프로젝트코드도움" 사용
        if project:
            self._fill_project_code(project, y_hint=292)
            _save_debug(page, "adv_03a_after_project_top")

            # 프로젝트 입력 후 페이지 이탈 검증
            self.page.wait_for_timeout(300)
            current_url = page.url
            if "/HP/" not in current_url:
                logger.warning(f"프로젝트 입력 후 페이지 이탈 감지: {current_url}")
                _save_debug(page, "adv_03a_page_escaped")

        # 2. 제목 입력
        if title:
            self._fill_field_by_label("제목", title)
        _save_debug(page, "adv_03_after_title")

        # 3. 양식별 텍스트 필드 채우기
        # 폴백 라벨: 실제 GW DOM 라벨이 다를 수 있으므로 후보 리스트로 시도
        if form_type == "요청서":
            # 요청서 필드 맵: (라벨 후보 리스트, data 키)
            # GW DOM 검증 완료 (2026-04-09):
            #   - 요청사유 전용 필드 없음 → "비고" 라벨이 실제 존재 (지출결의서 공유 폼)
            #   - 은행명 단독 라벨 없음 → "은행/계좌번호" 통합 라벨로 노출 (placeholder: 금융기관코드도움)
            #   - 계좌번호는 "은행/계좌번호" td 내 별도 input (placeholder: 거래처계좌번호)
            #   - 예금주 라벨 확인됨 (정확히 일치), 예금주실명 별도 필드 추가 존재
            field_map_candidates = [
                (["비고", "요청사유", "사유", "지급사유"], "purpose"),
                (["은행/계좌번호", "은행명", "금융기관", "지급은행"], "bank_name"),
                (["거래처계좌번호", "계좌번호", "계좌", "입금계좌번호"], "account_number"),
                (["예금주", "예금주명", "수취인"], "account_holder"),
            ]
        else:
            # 정산서 필드 맵 (단일 라벨 — 추후 폴백 추가 가능)
            field_map_candidates = [
                (["정산내역"], "description"),
                (["선급금액"], "original_amount"),
                (["사용금액"], "used_amount"),
                (["반환금액"], "return_amount"),
            ]

        for candidates, key in field_map_candidates:
            val = data.get(key)
            if val is not None and str(val).strip():
                if key == "bank_name":
                    # 은행명: 코드도움 picker 처리 (placeholder="금융기관코드도움")
                    if not self._handle_bank_picker(str(val)):
                        # 피커 실패 시 텍스트 입력 폴백
                        logger.warning("은행 picker 실패 → 텍스트 입력 폴백")
                        self._fill_field_by_label_candidates(candidates, str(val))
                elif key == "account_number":
                    # 계좌번호: placeholder 기반 직접 입력 우선
                    if not self._fill_field_by_placeholder("거래처계좌번호", str(val)):
                        self._fill_field_by_label_candidates(candidates, str(val))
                else:
                    self._fill_field_by_label_candidates(candidates, str(val))

        # 4. 금액 그리드 입력 (요청서: 금액 항목을 그리드에 입력)
        # 지출결의서와 동일한 OBTDataGrid 그리드 구조 사용
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

    def _save_advance_payment_draft(self) -> dict:
        """
        선급금 요청서/정산서 임시보관 (draft 모드)

        인라인 폼에는 '보관' 버튼이 없으므로
        결재상신 클릭 → 팝업 열림 → 팝업에서 '보관' 버튼 클릭 흐름으로 처리.
        (지출결의서 _create_expense_report_via_popup / 증빙발행 _create_proof_issuance_draft 패턴과 동일)

        호출 시점: create_advance_payment_request/settlement에서 필드 채우기 완료 후.
        """
        if not self.context:
            return {"success": False, "message": "BrowserContext가 필요합니다. (팝업 기반 보관)"}

        page = self.page
        popup_page = None

        try:
            # dialog 핸들러: GW가 confirm/alert를 띄울 수 있음
            dialog_messages = []

            def _handle_dialog(dialog):
                msg = dialog.message
                dialog_messages.append(msg)
                logger.info(f"[선급금 보관] dialog 감지: {msg[:100]}")
                dialog.accept()

            page.on("dialog", _handle_dialog)

            # ── 1단계: 결재상신 버튼 찾기 ──
            logger.info("[선급금 보관 1/3] 결재상신 버튼 탐색")
            submit_btn = None
            for sel in [
                "div.topBtn:has-text('결재상신')",
                "button:has-text('결재상신')",
                "[class*='topBtn']:has-text('결재상신')",
                "text=결재상신",
            ]:
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=2000):
                        submit_btn = loc
                        logger.info(f"결재상신 버튼 발견: {sel}")
                        break
                except Exception:
                    continue

            if not submit_btn:
                _save_debug(page, "adv_draft_error_no_submit_btn")
                return {"success": False, "message": "결재상신 버튼을 찾을 수 없습니다."}

            # ── 2단계: 결재상신 클릭 → 팝업 대기 ──
            logger.info("[선급금 보관 2/3] 결재상신 클릭 → 팝업 대기")

            # OBTAlert/dimmed 오버레이 제거 (클릭 차단 방지)
            self._dismiss_obt_alert()
            page.wait_for_timeout(300)

            # expect_page로 팝업 감지 (force=True로 오버레이 우회)
            try:
                with self.context.expect_page(timeout=15000) as new_page_info:
                    submit_btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    try:
                        submit_btn.click(timeout=5000)
                    except Exception:
                        # 오버레이 차단 시 force 클릭
                        logger.info("결재상신 일반 클릭 실패 → force 클릭")
                        submit_btn.click(force=True, timeout=5000)
                    logger.info("결재상신 클릭 → 팝업 대기 (expect_page)")
                popup_page = new_page_info.value
                logger.info(f"결재상신 팝업 감지: {popup_page.url[:100]}")
            except Exception as e:
                logger.warning(f"expect_page 팝업 감지 실패: {e}")

            # expect_page 실패 시 폴링 폴백
            if not popup_page:
                pages_before = set(id(p) for p in self.context.pages)
                try:
                    submit_btn.click()
                    logger.info("결재상신 재클릭 → 폴링 대기")
                except Exception:
                    pass
                for _ in range(20):
                    page.wait_for_timeout(500)
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
            page.remove_listener("dialog", _handle_dialog)

            if not popup_page:
                _save_debug(page, "adv_draft_error_no_popup")
                # dialog 메시지가 있으면 검증 오류로 판단
                if dialog_messages:
                    return {"success": False, "message": f"결재상신 검증 오류: {'; '.join(dialog_messages[:3])}"}
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
                logger.warning("팝업 div.topBtn 대기 타임아웃 -- 계속 진행")
                page.wait_for_timeout(3000)

            _save_debug(popup_page, "adv_draft_02_popup_opened")

            # ── 3단계: 팝업에서 보관 버튼 클릭 ──
            logger.info("[선급금 보관 3/3] 팝업 보관 버튼 클릭")

            # _save_draft_in_popup (vendor.py의 공통 메서드) 사용
            result = self._save_draft_in_popup(popup_page)
            return result

        except PlaywrightTimeout as e:
            logger.warning(f"선급금 보관 타임아웃: {e}")
            _save_debug(page, "adv_draft_error_timeout")
            return {"success": False, "message": f"선급금 보관 타임아웃: {e}"}
        except Exception as e:
            logger.error(f"선급금 보관 실패: {e}", exc_info=True)
            _save_debug(page, "adv_draft_error")
            return {"success": False, "message": f"선급금 보관 실패: {str(e)}"}
        finally:
            # 팝업 정리
            if popup_page and not popup_page.is_closed():
                try:
                    popup_page.close()
                except Exception:
                    pass

    def create_advance_payment_request(self, data: dict) -> dict:
        """
        [본사]선급금 요청서 작성 (인라인 폼 기반, 재시도 포함)

        지출결의서와 동일한 APB1020 인라인 폼 구조.
        formId=181 URL 직접 접근 후 필드 채우기.
        - save_mode="verify" (기본): 필드 작성 검증만 수행
        - save_mode="submit": 결재상신 실행
        - save_mode="draft": 결재상신→팝업→보관 (인라인 폼에 보관 버튼 없으므로 팝업 경유)

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
                    # 팝업 기반 보관 흐름 (인라인 폼에 보관 버튼 없으므로 결재상신→팝업→보관)
                    result = self._save_advance_payment_draft()
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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

            except Exception as e:
                last_error = e
                logger.error(f"선급금 요청서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"adv_req_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        _save_debug(self.page, "adv_req_error_final")
        return {"success": False, "message": f"선급금 요청서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def create_advance_payment_settlement(self, data: dict) -> dict:
        """
        [본사]선급금 정산서 작성 (인라인 폼 기반, 재시도 포함)

        지출결의서와 동일한 APB1020 인라인 폼 구조.
        formId 미확인 -> 검색으로 진입.
        - save_mode="verify" (기본): 필드 작성 검증만 수행
        - save_mode="submit": 결재상신 실행
        - save_mode="draft": 결재상신→팝업→보관 (인라인 폼에 보관 버튼 없으므로 팝업 경유)

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
                    # 팝업 기반 보관 흐름 (인라인 폼에 보관 버튼 없으므로 결재상신→팝업→보관)
                    result = self._save_advance_payment_draft()
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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

            except Exception as e:
                last_error = e
                logger.error(f"선급금 정산서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"adv_sett_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        _save_debug(self.page, "adv_sett_error_final")
        return {"success": False, "message": f"선급금 정산서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def create_overtime_request(self, data: dict) -> dict:
        """
        연장근무신청서 작성 (근태관리 모듈)

        근태관리 모듈 경로:
        - 결재작성 -> "연장근무신청서" 검색 -> 선택 (formId=43)
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

                # 시간외근무(연장근무) 검색 및 선택
                search_keywords = ["시간외근무", "연장근무"]
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
                        # 결과 클릭 (GW 메뉴명은 "시간외근무")
                        for link_text in ["시간외근무", "연장근무"]:
                            try:
                                link = page.locator(f"text={link_text}").first
                                if link.is_visible(timeout=2000):
                                    link.click(force=True)
                                    page.wait_for_timeout(3000)
                                    form_found = True
                                    logger.info(f"시간외근무 양식 클릭 완료 (매치: {link_text})")
                                    break
                            except Exception:
                                continue
                        if form_found:
                            break
                    except Exception:
                        continue

                if not form_found:
                    raise Exception("시간외근무(연장근무) 양식을 찾을 수 없습니다.")

                # 필드 채우기 (date / work_date 동의어 처리)
                work_date = data.get("date") or data.get("work_date", "")
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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
            except Exception as e:
                last_error = e
                logger.error(f"연장근무신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

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

                # 필드 채우기 (date / work_date, reason / purpose 동의어 처리)
                work_date = data.get("date") or data.get("work_date", "")
                destination = data.get("destination", "")
                purpose = data.get("reason") or data.get("purpose", "")
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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
            except Exception as e:
                last_error = e
                logger.error(f"외근신청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        return {"success": False, "message": f"외근신청서 작성 실패: {str(last_error)}"}

    def create_referral_bonus_request(self, data: dict) -> dict:
        """
        사내추천비 자금 요청서 작성

        전자결재 양식. 결재작성 -> "사내추천비" 검색 -> "사내추천비 지급 요청서" 선택.

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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
            except Exception as e:
                last_error = e
                logger.error(f"사내추천비 요청서 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        return {"success": False, "message": f"사내추천비 요청서 작성 실패: {str(last_error)}"}

    # ─────────────────────────────────────────────
    # 공통 헬퍼: HR 근태관리 시간외근무 폼 이동
    # ─────────────────────────────────────────────
    def _navigate_to_hr_attendance(self, page, _target_page_code: str = "") -> bool:
        """
        HR 근태관리 > 시간외근무 폼으로 이동하는 공통 헬퍼.

        ─── 실제 GW 탐색 결과 (2026-04-10) ───
        - UF 모듈(근태관리) URL 직접 이동 시 "권한 없는 메뉴" 팝업 후 게시판으로 리다이렉트됨.
          (UFA1010~UFA1060 전부 권한 없음 — specialLnb 메뉴는 계정 권한에 따라 표시)
        - HR 모듈(임직원업무관리) LNB에서 "근태관리"는 펼침 메뉴이며
          계정에 근태 권한이 있으면 하위에 "근태신청" 항목이 노출됨.
        - 전자결재(EA) 결재작성 경로에서 "시간외근무" 양식을 검색하는 방식이
          권한 문제를 우회하는 가장 안정적인 접근법.

        전략:
        1순위: HR LNB 근태관리 펼치기 → "근태신청" 또는 "시간외근무" 클릭
        2순위: 전자결재 결재작성 → "시간외근무" 양식 검색 후 선택
        3순위: HP 모듈 경로로 근태신청 직접 이동

        Args:
            page: Playwright Page 객체
            _target_page_code: 미사용 (하위 호환성 유지용 파라미터)
        Returns:
            True면 시간외근무 폼 로드 확인, False면 모든 시도 실패
        """
        import os
        gw_url = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")

        def _check_overtime_form_loaded() -> bool:
            """시간외근무 폼이 로드되었는지 확인 (키워드 탐색)"""
            try:
                body = page.evaluate("() => document.body.innerText")
                overtime_kws = ["시간외근무", "연장근무", "근무구분", "근무일", "시작시간"]
                return any(kw in body for kw in overtime_kws)
            except Exception:
                return False

        def _dismiss_popup():
            """권한 없음 팝업 등 자동 닫기"""
            try:
                for btn_text in ["확인", "닫기", "OK"]:
                    btn = page.locator(f"text={btn_text}").first
                    if btn.is_visible(timeout=1000):
                        btn.click(force=True)
                        page.wait_for_timeout(500)
                        break
            except Exception:
                pass

        # ── 1순위: HR 모듈 LNB → 근태관리 → 근태신청 / 시간외근무 ──
        logger.info("[HR 근태관리] 1순위: HR 모듈 LNB 경로")
        try:
            # HR 모듈 진입
            page.goto(f"{gw_url}/#/HP/HPM0110/HPM0110",
                      wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)

            # 근태관리 펼치기 (force=True — 게시판 레이어가 인터셉트 가능)
            attendance_nav = page.locator(".sideLnbMenu .nav-item:has(.nav-text:text-is('근태관리'))")
            if attendance_nav.count() == 0:
                attendance_nav = page.locator("text=근태관리").first
            attendance_nav.click(force=True)
            page.wait_for_timeout(1500)

            # 하위 메뉴 탐색 (근태신청 / 시간외근무)
            for sub_text in ["근태신청", "시간외근무", "연장근무"]:
                try:
                    sub = page.locator(f".sideLnbMenu text={sub_text}").first
                    if sub.count() == 0:
                        sub = page.locator(f"text={sub_text}").first
                    if sub.is_visible(timeout=2000):
                        sub.click(force=True)
                        page.wait_for_timeout(3000)
                        _dismiss_popup()
                        if _check_overtime_form_loaded():
                            logger.info(f"[HR 근태관리] 1순위 성공: '{sub_text}' 클릭")
                            return True
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"[HR 근태관리] 1순위 실패: {e}")

        # ── 2순위: 전자결재 결재작성 → 시간외근무 양식 검색 ──
        logger.info("[HR 근태관리] 2순위: 전자결재 결재작성 경로")
        try:
            # 전자결재 홈 이동
            self._navigate_to_approval_home()
            page.wait_for_timeout(1500)
            _dismiss_popup()

            # 결재작성 버튼 클릭
            self._click_write_approval()
            page.wait_for_timeout(1500)

            # 양식 검색창에 "시간외근무" 입력
            for sel in [
                "input[placeholder*='검색']",
                "input[placeholder*='양식']",
                "input[type='search']",
                "input.OBTTextField",
            ]:
                try:
                    inp = page.locator(sel).first
                    if inp.is_visible(timeout=1500):
                        inp.fill("시간외근무")
                        inp.press("Enter")
                        page.wait_for_timeout(1500)
                        break
                except Exception:
                    continue

            # 검색 결과에서 "시간외근무" 링크 클릭
            for kw in ["시간외근무", "연장근무"]:
                try:
                    link = page.locator(f"text={kw}").first
                    if link.is_visible(timeout=3000):
                        link.click(force=True)
                        page.wait_for_timeout(3000)
                        _dismiss_popup()
                        if _check_overtime_form_loaded():
                            logger.info(f"[HR 근태관리] 2순위 성공: '{kw}' 양식 선택")
                            return True
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"[HR 근태관리] 2순위 실패: {e}")

        # ── 3순위: HP 모듈 직접 URL 패턴 시도 ──
        logger.info("[HR 근태관리] 3순위: HP 모듈 근태 URL 직접 시도")
        hp_attendance_urls = [
            f"{gw_url}/#/HP/HPA0010/HPA0010",   # 근태신청 추정
            f"{gw_url}/#/HP/HPA1010/HPA1010",   # 시간외근무 추정
            f"{gw_url}/#/HP/HPA1020/HPA1020",
        ]
        for url in hp_attendance_urls:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                page.wait_for_timeout(2000)
                _dismiss_popup()
                if _check_overtime_form_loaded():
                    logger.info(f"[HR 근태관리] 3순위 성공: {url}")
                    return True
            except Exception:
                continue

        logger.error("[HR 근태관리] 모든 이동 방식 실패")
        return False

    def _save_overtime_draft(self, data: dict) -> dict:
        """
        연장근무신청서 임시보관 (draft 모드)

        근태관리 모듈은 전자결재 "보관" 버튼 없음.
        신청완료(저장) 버튼을 눌러 저장하는 방식 사용.
        HR 모듈 경로: 임직원업무관리(HR) > 근태신청 > 연장근무신청서

        Args:
            data: {
                "date": "YYYY-MM-DD",      # 연장근무일 (work_date 동의어)
                "work_date": "YYYY-MM-DD", # 연장근무일 (date 동의어)
                "start_time": "HH:MM",     # 시작시각
                "end_time": "HH:MM",       # 종료시각
                "reason": "사유",           # 연장근무 사유
                "project": "프로젝트명",    # 선택사항
                "work_type": "연장근무",    # 근무구분 (조기근무/연장근무/휴일근무)
            }
        Returns:
            {"success": bool, "message": str}
        """
        page = self.page

        try:
            # date / work_date 동의어 처리
            work_date = data.get("date") or data.get("work_date", "")
            start_time = data.get("start_time", "")
            end_time = data.get("end_time", "")
            reason = data.get("reason", "")
            project = data.get("project", "")
            work_type = data.get("work_type", "연장근무")

            self._close_popups()

            # HR 근태관리 > 시간외근무 페이지 이동 (공통 헬퍼 사용)
            logger.info("[연장근무 임시저장 1] HR 근태관리 시간외근무 페이지 이동")
            nav_ok = self._navigate_to_hr_attendance(page, "UFA1010")

            if not nav_ok:
                # 최종 폴백: 전자결재 결재작성 경로에서 시간외근무 검색
                logger.info("[연장근무 임시저장 2-폴백] 결재작성 경로 시도")
                self._navigate_to_approval_home()
                self._click_write_approval()
                page.wait_for_timeout(1500)
                for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                    try:
                        inp = page.locator(sel).first
                        if inp.is_visible(timeout=2000):
                            inp.fill("시간외근무")
                            inp.press("Enter")
                            page.wait_for_timeout(1500)
                            break
                    except Exception:
                        continue
                try:
                    for search_kw in ["시간외근무", "연장근무"]:
                        link = page.locator(f"text={search_kw}").first
                        if link.is_visible(timeout=3000):
                            link.click(force=True)
                            page.wait_for_timeout(3000)
                            nav_ok = True
                            break
                except Exception:
                    pass

            if not nav_ok:
                return {"success": False, "message": "시간외근무(연장근무) 양식을 찾을 수 없습니다."}

            # 근무구분 선택
            if work_type:
                for sel in [f"text={work_type}", f"input[value='{work_type}']"]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=1500):
                            el.click(force=True)
                            page.wait_for_timeout(500)
                            logger.info(f"근무구분 선택: {work_type}")
                            break
                    except Exception:
                        continue

            # 날짜 입력
            logger.info(f"[연장근무 임시저장 3] 날짜 입력: {work_date}")
            if work_date:
                for label in ["연장근무시작일", "근무일", "시작일"]:
                    try:
                        if self._fill_field_by_label(label, work_date):
                            logger.info(f"날짜 필드 '{label}' 입력 완료")
                            break
                    except Exception:
                        continue
                # date input 직접 탐색 폴백
                try:
                    date_inputs = page.locator("input[type='date'], input.OBTDatePickerRebuild_inputYMD").all()
                    if date_inputs:
                        date_inputs[0].fill(work_date)
                        date_inputs[0].press("Tab")
                        page.wait_for_timeout(500)
                        logger.info(f"date input 직접 입력: {work_date}")
                except Exception:
                    pass

            # 시간 입력
            logger.info(f"[연장근무 임시저장 4] 시간 입력: {start_time} ~ {end_time}")
            if start_time:
                for label in ["시작시간", "시작"]:
                    try:
                        if self._fill_field_by_label(label, start_time):
                            break
                    except Exception:
                        continue
            if end_time:
                for label in ["종료시간", "종료"]:
                    try:
                        if self._fill_field_by_label(label, end_time):
                            break
                    except Exception:
                        continue

            # 비고/사유 입력
            if reason:
                for label in ["비고", "사유", "내용"]:
                    try:
                        if self._fill_field_by_label(label, reason):
                            logger.info(f"사유 입력 완료: {reason[:30]}")
                            break
                    except Exception:
                        continue

            # 프로젝트명 입력 (있는 경우)
            if project:
                for label in ["프로젝트", "프로젝트명"]:
                    try:
                        if self._fill_field_by_label(label, project):
                            logger.info(f"프로젝트 입력 완료: {project}")
                            break
                    except Exception:
                        continue

            # 신청완료(저장) 버튼 클릭 — 근태관리 모듈은 "임시저장" 버튼이 없어 "신청완료"로 저장
            logger.info("[연장근무 임시저장 5] 신청완료 버튼 탐색")
            _save_debug(page, "overtime_draft_before_save")
            saved = False
            for btn_text in ["신청완료", "저장", "완료"]:
                try:
                    btn = page.locator(f"button:has-text('{btn_text}')").first
                    if btn.is_visible(timeout=2000):
                        btn.click(force=True)
                        page.wait_for_timeout(2000)
                        logger.info(f"연장근무신청서 저장 완료: {btn_text}")
                        saved = True
                        break
                except Exception:
                    continue

            if not saved:
                _save_debug(page, "overtime_draft_no_save_btn")
                return {
                    "success": False,
                    "message": "저장 버튼을 찾을 수 없습니다. GW 화면을 직접 확인해주세요.",
                }

            _save_debug(page, "overtime_draft_saved")
            return {"success": True, "message": "연장근무신청서가 임시저장되었습니다."}

        except Exception as e:
            logger.error(f"연장근무 임시저장 실패: {e}", exc_info=True)
            _save_debug(page, "overtime_draft_error")
            return {"success": False, "message": f"연장근무신청서 저장 실패: {str(e)}"}

    def _save_outside_work_draft(self, data: dict) -> dict:
        """
        외근신청서(당일) 임시보관 (draft 모드)

        근태관리 모듈은 전자결재 "보관" 버튼 없음.
        저장 버튼을 눌러 저장하는 방식 사용.
        HR 모듈 경로: 임직원업무관리(HR) > 근태신청 > 외근신청서(당일)

        Args:
            data: {
                "date": "YYYY-MM-DD",      # 외근일 (work_date 동의어)
                "work_date": "YYYY-MM-DD", # 외근일 (date 동의어)
                "start_time": "HH:MM",     # 외출시각
                "end_time": "HH:MM",       # 복귀시각
                "destination": "외근지",    # 방문처/목적지
                "reason": "사유",           # 외근 사유 (purpose 동의어)
                "purpose": "사유",          # 외근사유 (reason 동의어)
                "project": "프로젝트명",    # 선택사항
                "work_type": "종일외근",    # 외근구분 (종일외근/외근후출근/출근후외근)
                "transport": "교통수단",    # 선택사항
            }
        Returns:
            {"success": bool, "message": str}
        """
        page = self.page

        try:
            # date / work_date 동의어 처리
            work_date = data.get("date") or data.get("work_date", "")
            start_time = data.get("start_time", "")
            end_time = data.get("end_time", "")
            destination = data.get("destination", "")
            reason = data.get("reason") or data.get("purpose", "")
            project = data.get("project", "")
            work_type = data.get("work_type", "")
            transport = data.get("transport", "")

            self._close_popups()

            # HR 근태관리 페이지 이동 (공통 헬퍼 사용, 외근신청은 UFA1020 추정)
            logger.info("[외근신청 임시저장 1] HR 근태관리 페이지 이동")
            nav_ok = self._navigate_to_hr_attendance(page, "UFA1020")

            if not nav_ok:
                # 최종 폴백: 전자결재 결재작성 경로에서 외근신청서 검색
                logger.info("[외근신청 임시저장 2-폴백] 결재작성 경로 시도")
                self._navigate_to_approval_home()
                self._click_write_approval()
                page.wait_for_timeout(1500)
                for sel in ["input[placeholder*='검색']", "input[type='search']", "input.OBTTextField"]:
                    try:
                        inp = page.locator(sel).first
                        if inp.is_visible(timeout=2000):
                            inp.fill("외근신청서")
                            inp.press("Enter")
                            page.wait_for_timeout(1500)
                            break
                    except Exception:
                        continue
                try:
                    link = page.locator("text=외근신청서").first
                    if link.is_visible(timeout=3000):
                        link.click(force=True)
                        page.wait_for_timeout(3000)
                        nav_ok = True
                except Exception:
                    pass

            if not nav_ok:
                return {"success": False, "message": "외근신청서 양식을 찾을 수 없습니다."}

            # 외근구분 선택
            if work_type:
                for sel in [f"text={work_type}", f"input[value='{work_type}']"]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=1500):
                            el.click(force=True)
                            page.wait_for_timeout(500)
                            logger.info(f"외근구분 선택: {work_type}")
                            break
                    except Exception:
                        continue

            # 날짜 입력
            logger.info(f"[외근신청 임시저장 3] 날짜 입력: {work_date}")
            if work_date:
                for label in ["외근기간", "외근일", "날짜"]:
                    try:
                        if self._fill_field_by_label(label, work_date):
                            logger.info(f"날짜 필드 '{label}' 입력 완료")
                            break
                    except Exception:
                        continue
                # date input 직접 탐색 폴백
                try:
                    date_inputs = page.locator("input[type='date'], input.OBTDatePickerRebuild_inputYMD").all()
                    if date_inputs:
                        date_inputs[0].fill(work_date)
                        date_inputs[0].press("Tab")
                        page.wait_for_timeout(500)
                        logger.info(f"date input 직접 입력: {work_date}")
                except Exception:
                    pass

            # 시간 입력
            logger.info(f"[외근신청 임시저장 4] 시간 입력: {start_time} ~ {end_time}")
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

            # 방문처/교통수단/사유 입력
            if destination:
                for label in ["방문처", "목적지"]:
                    try:
                        if self._fill_field_by_label(label, destination):
                            logger.info(f"방문처 입력 완료: {destination}")
                            break
                    except Exception:
                        continue
            if transport:
                for label in ["교통수단"]:
                    try:
                        if self._fill_field_by_label(label, transport):
                            logger.info(f"교통수단 입력 완료: {transport}")
                            break
                    except Exception:
                        continue
            if reason:
                for label in ["업무내용", "외근사유", "내용", "사유", "비고"]:
                    try:
                        if self._fill_field_by_label(label, reason):
                            logger.info(f"사유 입력 완료: {reason[:30]}")
                            break
                    except Exception:
                        continue

            # 프로젝트명 입력 (있는 경우)
            if project:
                for label in ["프로젝트", "프로젝트명"]:
                    try:
                        if self._fill_field_by_label(label, project):
                            logger.info(f"프로젝트 입력 완료: {project}")
                            break
                    except Exception:
                        continue

            # 저장 버튼 클릭
            logger.info("[외근신청 임시저장 5] 저장 버튼 탐색")
            _save_debug(page, "outside_work_draft_before_save")
            saved = False
            for btn_text in ["저장", "신청완료", "완료"]:
                try:
                    btn = page.locator(f"button:has-text('{btn_text}')").first
                    if btn.is_visible(timeout=2000):
                        btn.click(force=True)
                        page.wait_for_timeout(2000)
                        logger.info(f"외근신청서 저장 완료: {btn_text}")
                        saved = True
                        break
                except Exception:
                    continue

            if not saved:
                _save_debug(page, "outside_work_draft_no_save_btn")
                return {
                    "success": False,
                    "message": "저장 버튼을 찾을 수 없습니다. GW 화면을 직접 확인해주세요.",
                }

            _save_debug(page, "outside_work_draft_saved")
            return {"success": True, "message": "외근신청서가 임시저장되었습니다."}

        except Exception as e:
            logger.error(f"외근신청 임시저장 실패: {e}", exc_info=True)
            _save_debug(page, "outside_work_draft_error")
            return {"success": False, "message": f"외근신청서 저장 실패: {str(e)}"}

    def save_form_draft(self, form_type: str, data: dict) -> dict:
        """
        양식 종류에 따라 임시저장(draft) 메서드로 라우팅.

        전자결재 양식(지출결의서, 선급금 등)은 "보관" 버튼 → 임시보관문서 저장.
        근태관리 양식(연장근무, 외근신청)은 "신청완료/저장" 버튼으로 저장.

        Args:
            form_type: 양식명 또는 영문 키
                       예: "연장근무", "overtime", "시간외근무", "외근신청", "outside_work"
            data: 양식 데이터 딕셔너리
        Returns:
            {"success": bool, "message": str}
        """
        if form_type in ("연장근무", "overtime", "시간외근무"):
            return self._save_overtime_draft(data)
        elif form_type in ("외근신청", "outside_work"):
            return self._save_outside_work_draft(data)
        else:
            return {
                "success": False,
                "message": f"save_form_draft에서 지원하지 않는 양식입니다: {form_type}",
            }

    def create_form(self, form_key: str, data: dict) -> dict:
        """
        양식 키로 적절한 작성 메서드를 라우팅

        Args:
            form_key: FORM_TEMPLATES 키 (예: "지출결의서", "거래처등록")
            data: 양식별 데이터 딕셔너리
        Returns:
            {"success": bool, "message": str}
        """
        # 양식 키 -> 메서드 매핑
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
