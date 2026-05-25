"""
전자결재 자동화 — 사내추천비 지급 요청서 mixin

분할 출처: other_forms.py (세션 LII)
콜백 주입 패턴: self 메서드 직접 참조 (mixin 클래스로 분리).

포함 메서드:
- create_referral_bonus_request : 사내추천비 지급 요청서 작성
"""

import logging
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from src.gw.approval.base import MAX_RETRIES, RETRY_DELAY, _save_debug
from src.gw.approval.form_templates import resolve_approval_line

logger = logging.getLogger("approval_automation")


class ReferralBonusMixin:
    """사내추천비 지급 요청서 전자결재 mixin"""

    def create_referral_bonus_request(self, data: dict) -> dict:
        """
        사내추천비 자금 요청서 작성.

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
