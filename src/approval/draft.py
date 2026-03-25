"""
전자결재 자동화 -- 임시보관 문서 상신 mixin
"""

import logging
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from src.approval.base import GW_URL, _save_debug

logger = logging.getLogger("approval_automation")


class DraftSubmissionMixin:
    """임시보관 문서 조회/상신"""

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

            # 방법 1: 전자결재 모듈 이동 -> 사이드바 클릭
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
                logger.info("임시보관문서 텍스트 미발견 -> 폴백 URL 시도")
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
                logger.debug("titDiv 셀렉터 대기 타임아웃 -- networkidle 폴백")
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
                logger.info(f"[dry_run] 상신 버튼 확인: '{btn_text}' -- 클릭 안 함")
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
                self.page.wait_for_timeout(500)
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
                logger.info(f"bounding box 더블클릭 (force): {sel}")
                pages_before = set(id(p) for p in self.context.pages)
                el.dblclick(force=True)
                self.page.wait_for_timeout(1000)
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
                    self.page.wait_for_timeout(500)
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
                    self.page.wait_for_timeout(500)
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

        logger.error("모든 클릭 방법 실패 -- 임시보관문서 열기 불가")
        return None

    def _find_submit_button(self, doc_page: "Page"):
        """
        팝업 문서 페이지에서 결재상신 버튼을 찾아 반환.

        우선순위:
        1. div.topBtn:has-text('상신')  <- 실제 GW 패턴
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
            logger.warning("상신 후 networkidle 타임아웃 -- 계속 진행")
            self.page.wait_for_timeout(3000)
        except Exception:
            self.page.wait_for_timeout(3000)

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
                logger.info("상신 완료 -- 팝업 자동 닫힘")
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

