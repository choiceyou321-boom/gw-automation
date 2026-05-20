"""
전자결재 자동화 — 기타 양식 mixin (facade)

세션 LII에서 4개 파일로 분할:
- advance_payment.py : 선급금 요청서/정산서
- overtime.py        : 연장근무신청서
- outside_work.py    : 외근신청서(당일)
- recommendation.py  : 사내추천비 지급 요청서

이 파일(OtherFormsMixin)은 4개 mixin을 조합하여 하위 호환성을 유지하는 facade.
또한 분할 대상이 아닌 공통 메서드를 직접 포함:
- search_project_codes          : 프로젝트 코드도움 자동완성 검색
- create_proof_issuance         : [회계팀] 증빙발행 신청서 작성
- _create_proof_issuance_draft  : 증빙발행 신청서 임시보관
- save_form_draft               : 양식 종류별 draft 라우팅
- create_form                   : 양식 키별 작성 메서드 라우팅
"""

import logging
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from src.approval.base import MAX_RETRIES, RETRY_DELAY, _save_debug, _parse_project_text
from src.approval.form_templates import resolve_approval_line

# 분할된 mixin import
from src.approval.advance_payment import AdvancePaymentMixin
from src.approval.overtime import OvertimeMixin
from src.approval.outside_work import OutsideWorkMixin
from src.approval.recommendation import ReferralBonusMixin

logger = logging.getLogger("approval_automation")


class OtherFormsMixin(
    AdvancePaymentMixin,
    OvertimeMixin,
    OutsideWorkMixin,
    ReferralBonusMixin,
):
    """기타 전자결재 양식 — 4개 mixin 조합 facade"""

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
        [회계팀] 증빙발행 신청서 작성.

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
        증빙발행 신청서 임시보관 (draft 모드).

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
        양식 키로 적절한 작성 메서드를 라우팅.

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
