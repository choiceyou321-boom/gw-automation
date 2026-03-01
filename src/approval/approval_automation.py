"""
전자결재 자동 작성 모듈 (Playwright 기반)
- 지출결의서 양식 자동 채우기
- 결재상신 지원

Phase 0 DOM 탐색 결과 반영 (2026-03-01):
- 네비게이션: span.module-link.EA → 추천양식 "[프로젝트]지출결의서" 직접 클릭
- URL 패턴: /#/HP/APB1020/APB1020?...formDTp=APB1020_00001&formId=255
- 양식 테이블: table.OBTFormPanel_table__1fRyk
- 필드 접근: th 라벨 → 형제 td 내 input (placeholder 기반)
- 액션 버튼: "결재상신" (보관 버튼 없음)
"""
import time
import logging
from pathlib import Path
from playwright.sync_api import Page, BrowserContext

logger = logging.getLogger("approval_automation")

GW_URL = "https://gw.glowseoul.co.kr"

# 스크린샷 저장 디렉토리
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"


def _save_debug(page: Page, name: str):
    """디버그용 스크린샷 저장"""
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 저장 실패: {e}")


class ApprovalAutomation:
    """전자결재 폼 자동화 클래스"""

    def __init__(self, page: Page, context: BrowserContext = None):
        self.page = page
        self.context = context

    def create_expense_report(self, data: dict) -> dict:
        """
        지출결의서 작성 + 결재상신

        Args:
            data: {
                "title": "결의서 제목",
                "date": "2026-03-01",  # 증빙일자
                "description": "내용 설명",
                "items": [{"item": "항목명", "amount": 100000, "note": "비고"}],
                "total_amount": 100000,
            }
        Returns:
            {"success": bool, "message": str}
        """
        try:
            # 1. 전자결재 모듈 → 결재 HOME 이동
            self._navigate_to_approval_home()

            # 2. 추천양식에서 "[프로젝트]지출결의서" 클릭
            self._click_expense_form()

            # 3. 양식 로드 대기
            self._wait_for_form_load()

            # 4. 필드 채우기
            self._fill_expense_fields(data)

            # 5. 결재상신
            return self._submit()

        except Exception as e:
            logger.error(f"지출결의서 작성 실패: {e}", exc_info=True)
            _save_debug(self.page, "error_final")
            return {"success": False, "message": f"작성 중 오류: {str(e)}"}

    def _navigate_to_approval_home(self):
        """전자결재 모듈 HOME으로 이동"""
        page = self.page

        # 전자결재 모듈 아이콘 클릭 (span.module-link.EA)
        ea_link = page.locator("span.module-link.EA").first
        try:
            if ea_link.is_visible(timeout=5000):
                ea_link.click(force=True)
                logger.info("전자결재 모듈 클릭")
                time.sleep(4)
            else:
                raise Exception("전자결재 모듈 링크를 찾을 수 없습니다.")
        except Exception:
            # 대안: text로 찾기
            page.locator("text=전자결재").first.click(force=True)
            time.sleep(4)

        # 결재 HOME 확인
        try:
            page.wait_for_selector("text=결재 HOME", timeout=10000)
            logger.info("결재 HOME 도달")
        except Exception:
            logger.warning("결재 HOME 텍스트 미발견, 계속 진행")

        _save_debug(page, "01_approval_home")

    def _click_expense_form(self):
        """추천양식에서 지출결의서 클릭"""
        page = self.page

        # 다이얼로그 자동 처리
        page.on("dialog", lambda d: d.accept())

        # 추천양식에서 "[프로젝트]지출결의서" 찾기
        for keyword in ["[프로젝트]지출결의서", "프로젝트]지출", "지출결의서"]:
            try:
                links = page.locator(f"text={keyword}").all()
                for link in links:
                    if link.is_visible():
                        link.click(force=True)
                        logger.info(f"양식 클릭: '{keyword}'")
                        return
            except Exception:
                continue

        raise Exception("지출결의서 양식을 찾을 수 없습니다.")

    def _wait_for_form_load(self):
        """양식 폼 로드 대기 (URL 변경 + input 요소 확인)"""
        page = self.page
        logger.info("양식 로드 대기 (12초)...")
        time.sleep(12)

        # 팝업 닫기 (로그인 시 자동 열리는 팝업들)
        if self.context:
            all_pages = self.context.pages
            for p in all_pages:
                if "popup" in p.url and p != page:
                    try:
                        p.close()
                    except Exception:
                        pass

        # URL에 APB1020 (결재작성 페이지) 확인
        if "APB1020" in page.url:
            logger.info(f"결재작성 페이지 로드 확인: {page.url[:100]}")
        else:
            logger.warning(f"예상치 못한 URL: {page.url[:100]}")

        # 제목 필드가 보이는지 확인
        try:
            page.locator("th:has-text('제목')").first.wait_for(state="visible", timeout=10000)
            logger.info("양식 필드 로드 완료")
        except Exception:
            logger.warning("제목 필드 미발견, 계속 진행")

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
        """
        page = self.page
        title = data.get("title", "")
        description = data.get("description", "")

        # 1. 제목 입력 (th="제목" → td > input)
        if title:
            self._fill_field_by_label("제목", title)

        # 2. 제목 못 찾았으면 좌표 기반 (rect y=332 영역)
        if title and not self._check_field_has_value("제목", title):
            try:
                # 제목은 상단 테이블의 row5에 있는 빈 input (y~332)
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

    def _check_field_has_value(self, label: str, expected: str) -> bool:
        """필드에 값이 입력되었는지 확인"""
        try:
            th_el = self.page.locator(f"th:has-text('{label}')").first
            td_el = th_el.locator("xpath=following-sibling::td").first
            inp = td_el.locator("input:visible").first
            return inp.input_value() == expected
        except Exception:
            return False

    def _submit(self) -> dict:
        """결재상신 클릭"""
        page = self.page

        # "결재상신" 버튼 찾기
        submit_btn = page.locator("button:has-text('결재상신')").first
        if not submit_btn.is_visible():
            # 대안: 텍스트로 찾기
            submit_btn = page.locator("text=결재상신").first

        if not submit_btn.is_visible():
            _save_debug(page, "error_no_submit_btn")
            return {"success": False, "message": "'결재상신' 버튼을 찾을 수 없습니다."}

        # 다이얼로그 자동 수락
        page.on("dialog", lambda d: d.accept())

        _save_debug(page, "04_before_submit")

        submit_btn.click(force=True)
        time.sleep(5)

        _save_debug(page, "05_after_submit")

        logger.info("결재상신 완료")
        return {"success": True, "message": "지출결의서가 결재상신되었습니다."}

    # ─────────────────────────────────────────
    # 양식별 작성 메서드 (스텁)
    # ─────────────────────────────────────────

    def create_vendor_registration(self, data: dict) -> dict:
        """
        [회계팀] 국내 거래처등록 신청서 작성

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
        # TODO: DOM 탐색 후 구현 (Phase 0 필요)
        return {"success": False, "message": "거래처등록 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_proof_issuance(self, data: dict) -> dict:
        """
        [회계팀] 증빙발행 신청서 작성

        Args:
            data: {
                "title": "제목",
                "issue_type": "발행구분 (세금계산서/영수증/계산서)",
                "vendor_name": "발행처(거래처명)",
                "business_number": "사업자번호",
                "supply_amount": 공급가액(숫자),
                "tax_amount": 세액(숫자),
                "issue_date": "발행일 (YYYY-MM-DD)",
                "item_description": "품목/내용",
                "note": "비고 (선택)",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "증빙발행 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_advance_payment_request(self, data: dict) -> dict:
        """
        [본사]선급금 요청서 작성

        Args:
            data: {
                "title": "제목",
                "project": "프로젝트 (코드도움)",
                "vendor_name": "거래처명",
                "amount": 요청금액(숫자),
                "payment_date": "지급요청일 (YYYY-MM-DD)",
                "purpose": "요청사유",
                "bank_name": "은행명",
                "account_number": "계좌번호",
                "account_holder": "예금주",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "선급금요청 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_advance_payment_settlement(self, data: dict) -> dict:
        """
        [본사]선급금 정산서 작성

        Args:
            data: {
                "title": "제목",
                "project": "프로젝트 (코드도움)",
                "vendor_name": "거래처명",
                "original_amount": 선급금액(숫자),
                "used_amount": 사용금액(숫자),
                "description": "정산내역",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "선급금정산 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_overtime_request(self, data: dict) -> dict:
        """
        연장근무신청서 작성

        Args:
            data: {
                "title": "제목",
                "work_date": "근무일 (YYYY-MM-DD)",
                "start_time": "시작시간 (HH:MM)",
                "end_time": "종료시간 (HH:MM)",
                "reason": "사유",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "연장근무 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_outside_work_request(self, data: dict) -> dict:
        """
        외근신청서(당일) 작성

        Args:
            data: {
                "title": "제목",
                "work_date": "외근일 (YYYY-MM-DD)",
                "destination": "방문처",
                "purpose": "외근사유",
                "start_time": "출발시간 (HH:MM, 선택)",
                "end_time": "복귀시간 (HH:MM, 선택)",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "외근신청 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

    def create_referral_bonus_request(self, data: dict) -> dict:
        """
        사내추천비 자금 요청서 작성

        Args:
            data: {
                "title": "제목",
                "recommended_person": "추천대상자",
                "recommender": "추천인",
                "amount": 요청금액(숫자),
                "purpose": "사용목적",
                "description": "상세내용 (선택)",
            }
        Returns:
            {"success": bool, "message": str}
        """
        # TODO: DOM 탐색 후 구현
        return {"success": False, "message": "사내추천비 양식은 아직 DOM 탐색이 완료되지 않았습니다."}

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
