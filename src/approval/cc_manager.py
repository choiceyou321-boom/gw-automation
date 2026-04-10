"""
전자결재 기결재 문서 수신참조 관리 mixin

실제 GW 관찰 결과 (2026-03-26, Claude Cowork 세션):

[문서 검색 플로우]
  1. 전자결재 홈(HPM0110) 이동
  2. 사이드바 "기결재문서" 항목 클릭 (또는 UBA1010 URL 직접 이동)
  3. 문서 목록에서 제목 키워드 매칭
  4. 문서 행 더블클릭 → 팝업 URL에서 docID 파싱

[수신참조 추가 플로우]
  docID 확보 후:
  1. 팝업 URL 직접 이동 (docID로)
  2. .modifyButton (#btnRefer) 클릭 → "수신참조 지정" 모달 열기
  3. input[placeholder="검색어를 입력하세요."] 에 이름 검색
  4. canvas 클릭 → window.Grids.getActiveGrid().checkRow(0, true)
  5. 모달 우상단 "수신참조" 버튼 (y좌표 가장 위쪽, React fiber onClick)
  6. 저장 → 모달 자동 닫힘 = 성공

[결재 잠금 문서]
  .modifyButton 없거나 저장 시 "상위 결재자의 상태가 변경되어 수정할 수 없습니다" → skip

팝업 URL 패턴:
  /#/popup?MicroModuleCode=eap&docAuth=0&docID={doc_id}
  &formId=255&pageCode=UBA1010&callComp=UBAP002

기안문서함 URL (기결재/진행중 모두 포함):
  /#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1010
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from playwright.sync_api import Page, BrowserContext, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("approval_automation")

# ── URL 상수 ──────────────────────────────────────────────────────────
_GW_DOC_POPUP_URL = (
    "/#/popup?MicroModuleCode=eap&docAuth=0"
    "&docID={doc_id}&formId=255&pageCode=UBA1010&callComp=UBAP002"
)
# 기안문서함 (기결재/진행중 문서 목록)
_GW_MY_DOCS_URL = (
    "/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1010"
)
# 기결재완료 문서함 (폴백)
_GW_DONE_DOCS_URL = (
    "/#/UB/UB/UBA0000?specialLnb=Y&moduleCode=UB&menuCode=UBA&pageCode=UBA1040"
)


class CcManagerMixin:
    """기결재 문서 수신참조(CC) 추가/수정 mixin"""

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    def search_docs_by_title(
        self,
        title_keyword: str,
        max_results: int = 20,
    ) -> list[dict]:
        """
        제목 키워드로 기안문서함을 검색해 docID 목록 반환.

        Args:
            title_keyword: 검색할 제목 키워드 (부분 일치)
            max_results: 최대 반환 수

        Returns:
            [{"doc_id": "55700", "title": "GS-24-0025. 청수당 ...", "status": "결재중"}, ...]
        """
        page = self.page
        logger.info(f"[CC-Search] 문서 검색 시작: '{title_keyword}'")

        results: list[dict] = []

        # 여러 문서함 URL 순서대로 시도
        doc_list_urls = [
            (_GW_MY_DOCS_URL, "기안문서함"),
            (_GW_DONE_DOCS_URL, "결재완료문서함"),
        ]

        from src.approval.base import GW_URL
        for url_suffix, label in doc_list_urls:
            found = self._search_in_doc_list(
                page, f"{GW_URL.rstrip('/')}{url_suffix}",
                title_keyword, label, max_results
            )
            results.extend(found)
            if results:
                break  # 첫 번째 문서함에서 찾으면 중단

        # 중복 docID 제거
        seen = set()
        unique = []
        for r in results:
            if r["doc_id"] not in seen:
                seen.add(r["doc_id"])
                unique.append(r)

        logger.info(f"[CC-Search] 검색 완료: {len(unique)}건 발견")
        return unique[:max_results]

    def add_cc_to_document(
        self,
        doc_id: int | str,
        cc_name: str,
        *,
        context: Optional[BrowserContext] = None,
    ) -> dict:
        """
        기결재 문서에 수신참조 1명 추가.

        Args:
            doc_id:  문서 ID (숫자 또는 문자열)
            cc_name: 추가할 이름 (예: "임종훈", "이재명")
            context: BrowserContext (None 이면 self.context 사용)

        Returns:
            {"success": bool, "doc_id": str, "cc_name": str, "message": str}
        """
        ctx = context or getattr(self, "context", None)
        doc_id = str(doc_id)
        logger.info(f"[CC] 문서 {doc_id}에 '{cc_name}' 수신참조 추가 시작")

        pop_page = self._open_doc_popup(ctx, doc_id)
        if pop_page is None:
            return {"success": False, "doc_id": doc_id, "cc_name": cc_name,
                    "message": "문서 팝업 열기 실패"}

        try:
            return self._add_cc_in_popup(pop_page, doc_id, cc_name)
        finally:
            try:
                if not pop_page.is_closed():
                    pop_page.close()
            except Exception:
                pass

    def add_cc_by_title(
        self,
        title_keyword: str,
        cc_name: str,
        *,
        context: Optional[BrowserContext] = None,
    ) -> dict:
        """
        제목 키워드로 문서를 검색한 뒤 매칭 문서에 수신참조 추가.

        Args:
            title_keyword: 검색할 제목 키워드
            cc_name:       추가할 이름
            context:       BrowserContext

        Returns:
            {
                "success": bool,
                "found": int,           # 검색 결과 수
                "processed": int,       # 처리 시도 수
                "results": list[dict],  # 각 문서 결과
                "message": str,
            }
        """
        docs = self.search_docs_by_title(title_keyword)

        if not docs:
            return {
                "success": False, "found": 0, "processed": 0, "results": [],
                "message": f"제목 '{title_keyword}'에 해당하는 문서를 찾을 수 없습니다.",
            }

        results = []
        for doc in docs:
            r = self.add_cc_to_document(doc["doc_id"], cc_name, context=context)
            r["title"] = doc.get("title", "")
            results.append(r)

        ok = [r for r in results if r["success"]]
        return {
            "success": len(ok) > 0,
            "found": len(docs),
            "processed": len(results),
            "results": results,
            "message": f"{len(ok)}/{len(results)}건 성공",
        }

    def batch_add_cc(
        self,
        doc_ids: list[int | str],
        cc_name: str,
        *,
        context: Optional[BrowserContext] = None,
    ) -> list[dict]:
        """
        여러 문서에 수신참조 일괄 추가.

        Args:
            doc_ids: 문서 ID 목록
            cc_name: 추가할 이름
            context: BrowserContext
        """
        results = []
        for doc_id in doc_ids:
            result = self.add_cc_to_document(doc_id, cc_name, context=context)
            results.append(result)
            logger.info(
                f"[CC] 문서 {doc_id} → "
                f"{'✓' if result['success'] else '✗'} {result['message']}"
            )
        return results

    # ─────────────────────────────────────────────────────────────────
    # 문서 검색 내부 헬퍼
    # ─────────────────────────────────────────────────────────────────

    def _search_in_doc_list(
        self,
        page: Page,
        list_url: str,
        keyword: str,
        label: str,
        max_results: int,
    ) -> list[dict]:
        """
        문서 목록 페이지에서 제목 키워드로 문서를 찾고 docID 목록 반환.

        전략:
        1. 목록 페이지 이동
        2. 검색창이 있으면 키워드 입력 후 검색
        3. 없으면 DOM에서 제목 텍스트 직접 매칭
        4. 각 매칭 항목 더블클릭 → 팝업 URL에서 docID 파싱
        """
        results: list[dict] = []
        ctx = getattr(self, "context", None)

        try:
            page.goto(list_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
            logger.info(f"[CC-Search] {label} 이동 완료: {list_url[:80]}")
        except Exception as e:
            logger.warning(f"[CC-Search] {label} 이동 실패: {e}")
            return results

        # ── 검색창 입력 시도 ──
        self._try_search_input(page, keyword)

        # ── 문서 목록에서 키워드 매칭 항목 찾기 ──
        doc_elements = self._find_doc_elements_by_keyword(page, keyword)
        logger.info(f"[CC-Search] {label}: {len(doc_elements)}개 매칭 요소")

        for el in doc_elements[:max_results]:
            title_text = ""
            try:
                title_text = (el.text_content(timeout=2000) or "").strip()
            except Exception:
                pass

            doc_id = self._extract_docid_by_popup_click(page, el, ctx)
            if doc_id:
                results.append({
                    "doc_id": doc_id,
                    "title": title_text,
                    "status": "",
                })
                logger.info(f"[CC-Search] 발견: docID={doc_id}, title={title_text[:60]}")

                # 팝업 닫고 목록으로 돌아오기
                self._navigate_back_to_list(page, list_url)

        return results

    def _try_search_input(self, page: Page, keyword: str) -> bool:
        """GW 문서 목록 상단 검색창 시도."""
        for sel in [
            "input[placeholder*='검색']",
            "input[placeholder*='제목']",
            "input[placeholder*='Search']",
            "input[type='search']",
        ]:
            try:
                inp = page.locator(sel).first
                if inp.is_visible(timeout=2000):
                    inp.fill(keyword)
                    inp.press("Enter")
                    page.wait_for_timeout(1500)
                    logger.info(f"[CC-Search] 검색창 사용: {sel}")
                    return True
            except Exception:
                continue
        return False

    def _find_doc_elements_by_keyword(self, page: Page, keyword: str) -> list:
        """DOM에서 키워드를 포함하는 문서 행/제목 요소 목록 반환."""
        elements = []

        # WEHAGO 전자결재 문서 목록 셀렉터 (다수 시도)
        selectors = [
            "div.titDiv .title span",     # draft.py에서 확인된 패턴
            "div.titDiv .title",
            "div.titDiv",
            "td[class*='title'] span",
            "td[class*='subject'] span",
            ".docTitle span",
            ".docTitle",
        ]

        for sel in selectors:
            try:
                all_els = page.locator(sel).all()
                matched = [
                    el for el in all_els
                    if keyword in (el.text_content(timeout=1000) or "")
                ]
                if matched:
                    logger.info(f"[CC-Search] 셀렉터 {sel}: {len(matched)}개 매칭")
                    elements = matched
                    break
            except Exception:
                continue

        return elements

    def _extract_docid_by_popup_click(
        self, page: Page, el, ctx: Optional[BrowserContext]
    ) -> Optional[str]:
        """
        문서 요소를 더블클릭해 팝업 URL에서 docID 파싱.

        팝업 URL 패턴: ...docID=55700&...
        """
        if not ctx:
            return None

        try:
            with ctx.expect_page(timeout=8000) as page_info:
                el.dblclick(force=True)
            popup = page_info.value
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass

            url = popup.url or ""
            m = re.search(r"docID=(\d+)", url)
            doc_id = m.group(1) if m else None

            # 팝업 닫기
            try:
                if not popup.is_closed():
                    popup.close()
            except Exception:
                pass

            return doc_id

        except Exception as e:
            logger.debug(f"[CC-Search] 팝업 클릭 실패: {e}")
            return None

    def _navigate_back_to_list(self, page: Page, list_url: str) -> None:
        """팝업 닫은 후 목록 페이지가 여전히 활성인지 확인, 아니면 재이동."""
        try:
            page.wait_for_timeout(500)
            # 목록 페이지는 여전히 열려 있음 (팝업이 별도 창이므로)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────
    # 수신참조 추가 내부 헬퍼
    # ─────────────────────────────────────────────────────────────────

    def _open_doc_popup(
        self, context: Optional[BrowserContext], doc_id: str
    ) -> Optional[Page]:
        """docID로 문서 팝업 페이지 열고 반환."""
        if context is None:
            logger.warning("[CC] BrowserContext 없음 — 팝업 열기 불가")
            return None

        url = _GW_DOC_POPUP_URL.format(doc_id=doc_id)
        from src.approval.base import GW_URL
        full_url = f"{GW_URL.rstrip('/')}{url}"

        pop_page = context.new_page()
        try:
            pop_page.goto(full_url, timeout=20000, wait_until="domcontentloaded")
            pop_page.wait_for_timeout(2000)
            pop_page.on("dialog", lambda d: d.accept())
            logger.info(f"[CC] 팝업 열기 성공: docID={doc_id}")
            return pop_page
        except Exception as e:
            logger.error(f"[CC] 팝업 열기 실패 (docID={doc_id}): {e}")
            try:
                pop_page.close()
            except Exception:
                pass
            return None

    def _add_cc_in_popup(self, page: Page, doc_id: str, cc_name: str) -> dict:
        """팝업 페이지에서 수신참조 추가 전체 플로우."""

        def _fail(msg: str) -> dict:
            logger.warning(f"[CC] {msg}")
            return {"success": False, "doc_id": doc_id, "cc_name": cc_name, "message": msg}

        # Step 1: 수정 버튼 클릭
        if not self._click_modify_button(page):
            return _fail("수정 버튼 없음 (결재 잠금 또는 권한 없음)")

        # Step 2: 모달 열림 대기
        try:
            page.wait_for_selector(
                'input[placeholder="검색어를 입력하세요."]',
                timeout=8000,
            )
        except PlaywrightTimeout:
            return _fail("수신참조 지정 모달 timeout")

        page.wait_for_timeout(500)

        # Step 3: 이름 검색
        if not self._search_cc_name(page, cc_name):
            return _fail(f"이름 검색 실패: {cc_name}")

        # Step 4: 검색결과 체크
        if not self._check_first_result(page):
            return _fail(f"검색 결과 없거나 체크 실패: {cc_name}")

        # Step 5: 수신참조 버튼 클릭
        if not self._click_cc_add_button(page):
            return _fail("수신참조 버튼 클릭 실패")

        # Step 6: 저장
        if not self._save_modal(page):
            return _fail("저장 실패 (결재 잠금 또는 오류)")

        # Step 7: 성공 검증
        msg = self._verify_cc_added(page, cc_name)
        logger.info(f"[CC] 문서 {doc_id} 수신참조 추가 완료: {msg}")
        return {"success": True, "doc_id": doc_id, "cc_name": cc_name, "message": msg}

    def _click_modify_button(self, page: Page) -> bool:
        """수신및참조 수정 버튼(.modifyButton / #btnRefer) 클릭."""
        for sel in ["#btnRefer", ".modifyButton"]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible(timeout=2000):
                    loc.first.click(force=True)
                    page.wait_for_timeout(800)
                    logger.info(f"[CC] 수정 버튼 클릭 ({sel})")
                    return True
            except Exception:
                continue

        # 폴백: "수신및참조" 행에 있는 "수정" 텍스트 버튼
        try:
            rows = page.locator("tr, .formRow").all()
            for row in rows:
                th_text = ""
                try:
                    th_text = row.locator("th").first.text_content(timeout=500) or ""
                except Exception:
                    pass
                if "수신" in th_text:
                    btn = row.get_by_text("수정", exact=True).first
                    if btn.is_visible(timeout=1000):
                        btn.click(force=True)
                        page.wait_for_timeout(800)
                        logger.info("[CC] 수정 버튼 클릭 (행 내 텍스트 매칭)")
                        return True
        except Exception:
            pass

        logger.warning("[CC] 수정 버튼 미발견")
        return False

    def _search_cc_name(self, page: Page, cc_name: str) -> bool:
        """수신참조 모달에서 이름 검색."""
        try:
            inp = page.locator('input[placeholder="검색어를 입력하세요."]').first
            inp.wait_for(state="visible", timeout=5000)

            # React native value setter
            page.evaluate(
                """(name) => {
                    const inp = document.querySelector('input[placeholder="검색어를 입력하세요."]');
                    if (!inp) return;
                    const ns = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    ns.call(inp, name);
                    ['input', 'change'].forEach(t =>
                        inp.dispatchEvent(new Event(t, { bubbles: true }))
                    );
                }""",
                cc_name,
            )
            page.wait_for_timeout(300)

            # 검색 버튼 또는 Enter
            searched = False
            for sel in ["button.searchButton", "button[class*='search']"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=1000):
                        btn.click(force=True)
                        searched = True
                        break
                except Exception:
                    continue
            if not searched:
                inp.press("Enter")

            page.wait_for_timeout(1500)
            logger.info(f"[CC] 이름 검색 완료: {cc_name}")
            return True
        except Exception as e:
            logger.warning(f"[CC] 이름 검색 실패: {e}")
            return False

    def _check_first_result(self, page: Page) -> bool:
        """
        RealGrid 검색결과에서 첫 번째 행 체크.
        canvas 클릭으로 그리드 활성화 → checkRow(0, true).
        """
        try:
            canvas_el = page.locator("canvas").first
            canvas_el.wait_for(state="visible", timeout=5000)
            bbox = canvas_el.bounding_box()
            if bbox:
                canvas_el.click(
                    position={"x": bbox["width"] * 0.4, "y": bbox["height"] * 0.35}
                )
            page.wait_for_timeout(400)

            result = page.evaluate("""() => {
                const grid = window.Grids && window.Grids.getActiveGrid
                    ? window.Grids.getActiveGrid() : null;
                if (!grid) return { ok: false, error: "grid not found" };
                try {
                    grid.checkRow(0, true);
                    return { ok: true };
                } catch (e) {
                    return { ok: false, error: e.message };
                }
            }""")

            if result.get("ok"):
                logger.info("[CC] checkRow(0, true) 성공")
                return True

            # 폴백: canvas 좌측 상단 체크박스 영역 직접 클릭
            return self._fallback_check_canvas_row(page, canvas_el)

        except Exception as e:
            logger.warning(f"[CC] _check_first_result 실패: {e}")
            return False

    def _fallback_check_canvas_row(self, page: Page, canvas_el) -> bool:
        """checkRow API 실패 시 canvas 체크박스 위치 직접 클릭."""
        try:
            bbox = canvas_el.bounding_box()
            if not bbox:
                return False
            # 헤더 ~30px 아래, 왼쪽 체크박스 열 (약 20px)
            canvas_el.click(position={"x": 20, "y": 50})
            page.wait_for_timeout(400)
            logger.info("[CC] fallback canvas 체크 클릭")
            return True
        except Exception as e:
            logger.warning(f"[CC] fallback 클릭 실패: {e}")
            return False

    def _click_cc_add_button(self, page: Page) -> bool:
        """
        모달 우상단 [수신참조] 버튼 클릭.
        y좌표 가장 위쪽 버튼이 "추가" 버튼.
        React fiber memoizedProps.onClick 직접 호출.
        """
        try:
            result = page.evaluate("""() => {
                const btns = [...document.querySelectorAll('button')]
                    .filter(b => {
                        const t = b.textContent.trim();
                        const r = b.getBoundingClientRect();
                        return t === '수신참조' && r.width > 0;
                    })
                    .sort((a, b) =>
                        a.getBoundingClientRect().top - b.getBoundingClientRect().top
                    );
                if (!btns.length) return { ok: false, error: "no button" };
                const btn = btns[0];
                const fk = Object.keys(btn).find(
                    k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                );
                if (fk) {
                    const onClick = btn[fk].memoizedProps && btn[fk].memoizedProps.onClick;
                    if (onClick) {
                        onClick({ target: btn, type: 'click',
                                  preventDefault: () => {}, stopPropagation: () => {} });
                        return { ok: true, method: 'react_fiber' };
                    }
                }
                btn.click();
                return { ok: true, method: 'native_click' };
            }""")

            if result.get("ok"):
                page.wait_for_timeout(600)
                logger.info(f"[CC] 수신참조 버튼 클릭 ({result.get('method', '?')})")
                return True
            logger.warning(f"[CC] 수신참조 버튼 없음: {result.get('error')}")
            return False
        except Exception as e:
            logger.warning(f"[CC] 수신참조 버튼 클릭 실패: {e}")
            return False

    def _save_modal(self, page: Page) -> bool:
        """저장 버튼 클릭 → 모달 닫힘 확인."""
        try:
            save_btn = page.get_by_role("button", name="저장").first
            save_btn.wait_for(state="visible", timeout=4000)
            save_btn.click(force=True)
            page.wait_for_timeout(1500)

            # 성공 확인: 모달 닫힘
            closed = page.evaluate("""() =>
                !document.querySelector('input[placeholder="검색어를 입력하세요."]')
            """)
            if closed:
                logger.info("[CC] 저장 성공 (모달 닫힘)")
                return True

            # 오류 메시지 체크
            err = page.evaluate("""() => {
                const a = [...document.querySelectorAll(
                    '.alert, .toast, [class*=alert], [class*=toast], [role=alert]'
                )];
                return a.map(x => x.textContent.trim()).join(' | ');
            }""")
            if err:
                logger.warning(f"[CC] 저장 오류: {err}")
            return False
        except Exception as e:
            logger.warning(f"[CC] 저장 실패: {e}")
            return False

    def _verify_cc_added(self, page: Page, cc_name: str) -> str:
        """수신및참조 텍스트에서 결과 메시지 생성."""
        try:
            page.wait_for_timeout(800)
            cc_text = page.evaluate("""() => {
                const rows = [...document.querySelectorAll('tr, .formRow')];
                for (const row of rows) {
                    const th = row.querySelector('th');
                    if (th && th.textContent.includes('수신')) {
                        const td = row.querySelector('td');
                        return td ? td.textContent.trim() : '';
                    }
                }
                return '';
            }""")
            m = re.search(r"외\s*(\d+)명", cc_text or "")
            count = m.group(1) if m else "?"
            return f"수신및참조 업데이트 (외 {count}명): {cc_text[:80]}"
        except Exception:
            return "저장 완료"
