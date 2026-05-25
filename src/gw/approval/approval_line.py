"""
전자결재 자동화 -- 결재선 설정 mixin
"""

import logging
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("approval_automation")


class ApprovalLineMixin:
    """결재선/수신참조 설정"""

    def set_approval_line(self, page: Page, approval_line: dict) -> bool:
        """
        결재선 동적 설정 (GW 결재선 팝업 조작)

        GW 결재선 UI 흐름:
        1. "결재선" 또는 "결재선 설정" 버튼 클릭 -> 팝업 열림
        2. 기존 결재선 초기화 (선택적)
        3. 결재자 검색 입력 -> 선택 -> 결재 단계 지정
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

        # 기안자는 자동 (로그인 사용자) -- 건너뜀
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
            logger.warning("결재선 버튼을 찾을 수 없음 -- 기본 결재선 유지")
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
            logger.warning("수신참조 버튼 미발견 -- 수신참조 설정 스킵")
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

