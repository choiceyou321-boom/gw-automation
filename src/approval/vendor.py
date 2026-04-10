"""
전자결재 자동화 -- 거래처등록 mixin
"""

import logging
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from src.approval.base import GW_URL, MAX_RETRIES, RETRY_DELAY, SCREENSHOT_DIR, _save_debug
from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients

logger = logging.getLogger("approval_automation")


class VendorRegistrationMixin:
    """거래처등록 양식 작성"""

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

                # 2. 양식 선택 -> 팝업 창 열기
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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
            except RuntimeError as e:
                return {"success": False, "message": str(e)}
            except Exception as e:
                last_error = e
                logger.error(f"거래처등록 작성 오류 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"error_vendor_{attempt}")
                if popup_page:
                    _save_debug(popup_page, f"error_vendor_popup_{attempt}")
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        _save_debug(self.page, "error_vendor_final")
        return {"success": False, "message": f"거래처등록 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def _click_form_by_keyword(self, *keywords: str):
        """
        양식 찾기: 추천양식 직접 클릭 -> 실패 시 결재작성 -> 양식 검색
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

        # 방법 2: "결재작성" 메뉴 클릭 -> 양식 검색
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
                        self.page.wait_for_timeout(3000)
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
                self.page.wait_for_timeout(2000)

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
        3. 검색 결과 첫 번째 항목 클릭 -> Enter
        4. 새 팝업 페이지 감지 및 반환

        Args:
            search_term: 양식 검색어 (예: "국내 거래처")
        Returns:
            팝업 Page 객체
        """
        page = self.page

        # 현재 열린 페이지 목록 기록 (팝업 감지용)
        pages_before = set(self.context.pages)

        # 1. 전자결재 HOME -> 결재작성 클릭 (UBA6000 URL은 HR 모듈로 변경되어 사용 불가)
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

        # 3. 검색어 입력 + Enter -> 결과 로드 대기
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
        # search_term에서 부분 키워드 추출 (예: "[프로젝트]지출결의서" -> "지출결의서")
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

        self.page.wait_for_timeout(1000)

        # 5. Enter 키 -> 팝업 열기
        page.keyboard.press("Enter")
        logger.info("Enter 키 눌러 팝업 열기 시도")

        # 6. 새 팝업 페이지 감지 (최대 15초 대기)
        popup_page = None
        for _ in range(30):
            self.page.wait_for_timeout(500)
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
            self.page.wait_for_timeout(3000)

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

        # 1. 제목 -- (거래처명) 부분만 업체명으로 교체
        try:
            inputs = popup_page.locator("input[type='text']:visible, input:not([type]):visible").all()
            for inp in inputs:
                val = inp.input_value()
                if "(거래처명)" in val:
                    new_title = val.replace("(거래처명)", vendor_name or "(거래처명)")
                    inp.click()
                    inp.fill(new_title)
                    logger.info(f"팝업 제목 교체: {val} -> {new_title}")
                    break
        except Exception as e:
            logger.warning(f"팝업 제목 교체 실패: {e}")

        _save_debug(popup_page, "vendor_04_after_title")

        # 2. 본문 -- dzeditor_0 iframe 내부 테이블 셀에 정보 기입
        self._fill_vendor_body_cells(popup_page, data)

        _save_debug(popup_page, "vendor_05_after_body")

    def _fill_vendor_body_cells(self, popup_page: Page, data: dict):
        """
        dzEditor API(setEditorHTMLCodeIframe)를 사용하여 본문 기입

        동작 방식:
        1. getEditorHTMLCodeIframe(0)으로 현재 HTML 가져오기
        2. 양식 HTML에서 placeholder 텍스트를 실제 값으로 교체
        3. setEditorHTMLCodeIframe(html, 0)으로 설정
        -> dzEditor 내부 상태에 반영되므로 보관 시 정상 저장됨
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
            self.page.wait_for_timeout(1000)

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

        # 빈 셀 교체 헬퍼: 라벨 뒤 빈 td의 <p><br></p> -> <p>값</p>
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

        self.page.wait_for_timeout(1000)

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
                popup_page.evaluate("""(htmlText) => {
                    const el = document.querySelector("[contenteditable='true']");
                    if (el) { el.innerHTML = htmlText; }
                }""", html_text)
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
                        frame.evaluate("""(htmlText) => {
                            const el = document.querySelector('[contenteditable]') || document.body;
                            el.innerHTML = htmlText;
                        }""", html_text)
                        logger.info("팝업 본문 입력 완료 (iframe)")
                        return
        except Exception:
            pass

        # 방법 3: 키보드 입력 폴백
        try:
            popup_page.keyboard.press("Tab")
            self.page.wait_for_timeout(500)
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
        # "보관" 버튼 찾기 -- 팝업 상단 div.topBtn 중 텍스트 "보관"
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
            self.page.wait_for_timeout(3000)
        except Exception:
            self.page.wait_for_timeout(3000)

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
                logger.info("팝업 자동 닫힘 -- 보관 완료")
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
                                # 줄바꿈을 위해 HTML로 입력 (인자 전달로 JS 인젝션 방지)
                                html_text = text.replace("\n", "<br>")
                                frame.evaluate(
                                    "(htmlText) => { const el = document.querySelector('[contenteditable]'); if (el) el.innerHTML = htmlText; }",
                                    html_text
                                )
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
                page.evaluate("""(htmlText) => {
                    const el = document.querySelector("[contenteditable='true']");
                    if (el) { el.innerHTML = htmlText; }
                }""", html_text)
                logger.info("본문 입력 완료 (contentEditable)")
                return
            except Exception as e:
                logger.warning(f"contentEditable 입력 실패: {e}")

        # 최종 폴백: 키보드 입력
        try:
            # Tab 등으로 본문 영역으로 이동 시도
            page.keyboard.press("Tab")
            self.page.wait_for_timeout(500)
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

