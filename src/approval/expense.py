"""
전자결재 자동화 -- 지출결의서 mixin
"""

import logging
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from src.approval.base import (
    GW_URL, MAX_RETRIES, RETRY_DELAY, SCREENSHOT_DIR,
    _GET_GRID_IFACE_JS, _save_debug, _parse_project_text,
)
from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients

logger = logging.getLogger("approval_automation")


class ExpenseReportMixin:
    """지출결의서 작성 관련 메서드"""

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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

            except Exception as e:
                last_error = e
                logger.error(f"지출결의서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        _save_debug(self.page, "error_final")
        return {"success": False, "message": f"지출결의서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def _create_expense_report_via_popup(self, data: dict) -> dict:
        """
        지출결의서 보관 흐름 (인라인 폼 -> 결재상신 -> 팝업 -> 보관)

        지출결의서는 결재작성에서 인라인 폼으로 열리므로:
        1. 전자결재 HOME -> 추천양식 클릭 -> 인라인 폼 로드
        2. _fill_expense_fields(data)로 22단계 필드 채우기
        3. 결재선/수신참조 설정
        4. 결재상신 클릭 -> 새 팝업 감지
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

                # 2. 추천양식에서 지출결의서 클릭 -> 인라인 폼 로드
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
                            logger.warning("검증결과 '부적합' -- 결재상신 팝업이 열리지 않을 수 있습니다")
                            _save_debug(self.page, "error_validation_fail")
                        else:
                            logger.info(f"검증결과 확인: {cell_text}")
                except Exception:
                    logger.info("검증결과 셀 미발견 (계속 진행)")

                # 7. 결재상신 클릭 -> 팝업 대기
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

                # expect_page로 팝업 감지 (결재상신 -> 새 창)
                popup_page = None
                try:
                    with self.context.expect_page(timeout=15000) as new_page_info:
                        submit_btn.scroll_into_view_if_needed()
                        self.page.wait_for_timeout(300)
                        submit_btn.click()
                        logger.info("결재상신 클릭 -> 팝업 대기 (expect_page)")
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
                        logger.info("결재상신 재클릭 -> 폴링 대기")
                    except Exception:
                        pass
                    for _ in range(20):
                        self.page.wait_for_timeout(500)
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
                            # 오류 내용 추출 -- 다양한 패턴 포함
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
                    logger.warning("팝업 div.topBtn 대기 타임아웃 -- 계속 진행")
                    self.page.wait_for_timeout(3000)
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
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
            except RuntimeError as e:
                return {"success": False, "message": str(e)}
            except Exception as e:
                last_error = e
                logger.error(f"지출결의서 보관 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                if popup_page:
                    _save_debug(popup_page, f"error_expense_popup_{attempt}")
                if attempt < MAX_RETRIES:
                    self._close_popups()
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)
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
            self.page.wait_for_timeout(1000)

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

        # 기본정보 필드 (자동 매핑 -- 프로젝트만 수동 설정)
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
        self.page.wait_for_timeout(300)
        submit_btn.click()
        logger.info("결재상신 클릭")
        self.page.wait_for_timeout(3000)

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


    def _click_expense_form(self):
        """결재작성 -> 지출결의서 양식 선택 (인라인 폼)"""
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
                                # URL 변경 안 됨 -> 클릭 재시도
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
        logger.info("현재 페이지에 양식 없음 -> 결재작성 클릭")
        self._click_write_approval()
        page.wait_for_timeout(1500)  # 결재작성 페이지 렌더링 대기

        if _try_click_form("결재작성 경유"):
            return

        _save_debug(page, "error_expense_form_not_found")
        raise Exception("지출결의서 양식을 찾을 수 없습니다.")


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

            # 프로젝트 입력 후 페이지 이탈 검증 (Enter->예산관리 네비게이션 방지)
            self.page.wait_for_timeout(300)
            current_url = page.url
            if "/HP/" not in current_url:
                logger.warning(f"프로젝트 입력 후 페이지 이탈 감지: {current_url}")
                _save_debug(page, "03a_page_escaped")
                # 결재 홈 -> 양식 재진입 복구
                try:
                    page.goto("https://gw.glowseoul.co.kr/#/app/approval")
                    page.wait_for_load_state("networkidle", timeout=10000)
                    logger.info("결재 홈으로 복구 완료 -- 양식 재작성 필요")
                except Exception as e:
                    logger.error(f"페이지 복구 실패: {e}")

        # 2. 제목 입력 (th="제목" -> td > input)
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

        # 4. 증빙유형 -> 세금계산서 모달 (그리드 수동 입력보다 먼저!)
        #    세금계산서 선택 시 그리드가 자동으로 채워짐
        evidence_type = data.get("evidence_type", "")
        invoice_selected = False
        if evidence_type:
            _is_invoice_type = evidence_type in ("세금계산서", "계산서", "계산서내역")
            if _is_invoice_type:
                # 계산서내역 버튼 -> DOM 모달 ("매입(세금)계산서 내역") 열림
                # 그리드 렌더링 실패 시 최대 3회 재시도
                _invoice_row_count = 0
                for _inv_attempt in range(3):
                    if _inv_attempt > 0:
                        logger.warning(f"인보이스 재선택 시도 {_inv_attempt + 1}/3 -- 그리드 비어 있음")
                        # 이전 시도에서 모달이 남아있을 수 있으므로 확인 후 닫기
                        try:
                            leftover = page.locator("text=매입(세금)계산서 내역").first
                            if leftover.is_visible(timeout=500):
                                page.locator("button:has-text('취소')").last.click(force=True)
                                self.page.wait_for_timeout(500)
                        except Exception:
                            pass

                    self._click_evidence_type_button(evidence_type)
                    self.page.wait_for_timeout(1000)
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
                        # 모달 선택 자체 실패 -- 재시도해도 의미 없음
                        logger.warning("세금계산서 모달 선택 실패 -- 재시도 중단")
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
                        self.page.wait_for_timeout(500)
                    else:
                        logger.warning(f"그리드 렌더링 타임아웃 (5초) -- 시도 {_inv_attempt + 1}/3")

                    if _invoice_row_count > 0:
                        invoice_selected = True
                        break
                    # 그리드가 비어 있으면 다음 시도로

                if invoice_selected:
                    _save_debug(page, "03c2_after_invoice_select")
                else:
                    if _invoice_row_count == 0 and _modal_invoice_selected:
                        logger.error("인보이스 선택 후 그리드 행 없음 (3회 재시도 모두 실패) -- 검증 부적합 발생 가능")
                    _save_debug(page, "03c2_after_invoice_select")
            else:
                # 세금계산서가 아닌 증빙유형 (카드, 현금영수증 등) -> 버튼만 클릭
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

        # 7-1. 참조문서 연결 (전자결재 폼 내 기존 문서 참조)
        reference_doc_keyword = data.get("reference_doc_keyword", "")
        if reference_doc_keyword:
            try:
                ref_result = self._link_reference_document(reference_doc_keyword)
                if ref_result:
                    logger.info(f"참조문서 연결 성공: '{reference_doc_keyword}'")
                else:
                    logger.warning(f"참조문서 연결 실패 — 폼 계속 진행: '{reference_doc_keyword}'")
                _save_debug(page, "07_1_after_ref_doc")
            except Exception as e:
                logger.error(f"참조문서 연결 예외: {e}")

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
        # 10~22. 용도코드 -> 예산과목 -> 날짜 -> 검증결과 (22단계 확장)
        # ─────────────────────────────────────────

        # 10. 용도코드 입력 -- OBTDataGrid React interface API 사용 (세션 XI 개선)
        #     기존: window.gridView (null) -> 좌표 클릭 폴백
        #     개선: React fiber -> OBTDataGrid interface -> setValue/getColumns
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

                    # row_count == 0이면 렌더링이 아직 완료되지 않은 것 -- 최대 3초 추가 대기
                    if row_count == 0:
                        logger.warning("step 10 진입 시 그리드 행 없음 -- 렌더링 대기 (최대 3초)")
                        for _extra_wait in range(6):
                            self.page.wait_for_timeout(500)
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
                        # 그리드 행이 없으면 용도코드 입력 불가 -- 인보이스 재선택 실패 후 여기까지 도달한 경우
                        logger.error(
                            "그리드 행 없음 (row_count=0) -- 용도코드 입력 불가, "
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
                                self.page.wait_for_timeout(300)

                                # 편집 input에 용도코드 입력 (자동완성 트리거)
                                page.keyboard.type(str(usage_code), delay=30)
                                self.page.wait_for_timeout(300)
                                page.keyboard.press("Enter")
                                self.page.wait_for_timeout(500)  # 자동완성 반영 및 그리드 상태 업데이트 대기
                                filled_count += 1
                            except Exception:
                                continue

                        logger.info(f"용도코드 '{usage_code}' 입력: {filled_count}/{row_count}행")
                        # 용도코드 입력 완료 후 그리드 검증 상태 반영 대기
                        self.page.wait_for_timeout(500)
                    else:
                        logger.warning(f"용도 컬럼 미발견 (cols: {[c['header'] for c in cols[:5]]})")
                else:
                    logger.warning("OBTDataGrid interface 미발견 -- 용도코드 입력 건너뜀")

                _save_debug(page, "10_after_usage_code")
            except Exception as e:
                logger.warning(f"용도코드 입력 실패: {e}")

        # 10-A. 용도코드 Enter 후 자동 트리거되는 '공통 예산잔액 조회' 팝업 즉시 처리
        #        팝업이 자동으로 열리면 바로 처리, 미열리면 step 11 fallback에서 재시도
        _budget_auto_handled = False
        _auto_budget_keyword = data.get("budget_keyword", "")
        if usage_code and _auto_budget_keyword:
            try:
                from src.approval.budget_helpers import handle_auto_triggered_popup
                _auto_project_kw = project.split(". ", 1)[-1].split("]")[-1].strip() if project else ""
                auto_result = handle_auto_triggered_popup(
                    page=page,
                    project_keyword=_auto_project_kw,
                    budget_keyword=_auto_budget_keyword,
                )
                if auto_result["success"]:
                    logger.info(
                        f"예산과목 자동팝업 완료: "
                        f"{auto_result['budget_code']}. {auto_result['budget_name']}"
                    )
                    _budget_auto_handled = True
                else:
                    logger.warning(f"예산과목 자동팝업 미처리 ({auto_result['message']}) — step 11 fallback 예정")
                _save_debug(page, "10a_after_auto_budget_popup")
            except Exception as e:
                logger.error(f"예산과목 자동팝업 처리 예외: {e}")

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
                                self.page.wait_for_timeout(200)
                                page.keyboard.type(clean_date, delay=20)
                                self.page.wait_for_timeout(200)
                                page.keyboard.press("Tab")
                                self.page.wait_for_timeout(200)
                                filled_count += 1
                            except Exception:
                                continue
                        logger.info(f"지급요청일 '{payment_request_date}' 그리드 입력: {filled_count}/{grid_info['rowCount']}행")
                    else:
                        logger.warning("지급요청일 컬럼 미발견")
                _save_debug(page, "10_1_after_payment_date_grid")
            except Exception as e:
                logger.warning(f"지급요청일 그리드 입력 실패: {e}")

        # 11. 예산과목 선택 폴백 (step 10-A 자동팝업으로 처리되지 않은 경우 fallback)
        #     → 자동팝업이 열리지 않은 환경에서 예산과목 필드 직접 클릭으로 모달 오픈
        budget_keyword = data.get("budget_keyword", "")
        if usage_code and budget_keyword and not _budget_auto_handled:
            self.page.wait_for_timeout(1000)  # 동적 필드 렌더링 대기
            _save_debug(page, "11_after_usage_code_dynamic_fields")

            # 12~17. 예산과목 선택 폴백 (공통 예산잔액 조회 팝업 — 필드 직접 클릭)
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
                                self.page.wait_for_timeout(500)
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

                self.page.wait_for_timeout(500)  # 검증결과 갱신 대기
                _save_debug(page, "21_after_accounting_date")
            except Exception as e:
                logger.warning(f"회계처리일자 처리 중 오류: {e}")

        # 22. 검증결과 확인 ("적합" / "부적합")
        try:
            self.page.wait_for_timeout(500)  # 검증 결과 갱신 완료 대기
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
                # 부적합 시 셀 호버 -> 툴팁으로 미비 사항 확인
                tooltip_text = ""
                try:
                    el = page.locator(
                        "div[class*='rg-cell']:has-text('부적합'), "
                        "td:has-text('부적합'), "
                        "span:has-text('부적합')"
                    ).first
                    if el.is_visible(timeout=1000):
                        el.hover()
                        self.page.wait_for_timeout(500)
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
                logger.warning(f"검증결과: 부적합 ✗ -- {tooltip_text or '미비 사항 확인 필요'}")
            else:
                logger.info("검증결과 셀을 찾을 수 없음 (용도코드/예산과목 미입력 시 정상)")

            _save_debug(page, "22_after_validation_check")
        except Exception as e:
            logger.debug(f"검증결과 확인 중 오류: {e}")

    # ─────────────────────────────────────────
    # 지출내역 그리드 입력
    # ─────────────────────────────────────────

    # 그리드 컬럼 헤더 텍스트 -> 인덱스 매핑 (0-based, 체크박스 제외)
    # ─────────────────────────────────────────
    # Task #4: 프로젝트 코드도움 / 증빙유형 / 증빙일자 / 첨부파일
    # ─────────────────────────────────────────

    def _fill_project_code(self, project: str, y_hint: float = None):
        """
        프로젝트 코드도움 모달 기반 입력.

        GW OBT 위젯 동작:
        1. placeholder="프로젝트코드도움" input 클릭 -> "프로젝트코드도움" 모달 열림
        2. 모달 검색어 필드에 키워드 입력 -> Enter 또는 돋보기 클릭
        3. 필터된 결과에서 행 클릭 -> 확인

        Args:
            project: 프로젝트 코드 또는 이름 일부 (예: '메디빌더', 'GS-25-0088')
            y_hint: 특정 y좌표 근처 input 선택 시 사용 (None이면 첫 번째 visible)
        """
        page = self.page

        # 1. 프로젝트 input 클릭 -> 모달 트리거
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
                self.page.wait_for_timeout(300)
                proj_input.click(click_count=3)  # 전체 선택
                self.page.wait_for_timeout(200)
                page.keyboard.type(project, delay=80)
                logger.info(f"프로젝트 검색어 입력: {project}")
        except Exception as e:
            logger.warning(f"프로젝트 input 클릭 실패: {e}")
            return False

        # 2. "프로젝트코드도움" 모달 대기
        self.page.wait_for_timeout(1000)
        modal_visible = False
        try:
            title_el = page.locator("text=프로젝트코드도움").first
            if title_el.is_visible(timeout=3000):
                modal_visible = True
                logger.info("프로젝트코드도움 모달 열림")
        except Exception:
            pass

        if not modal_visible:
            # 모달이 안 열린 경우 -- input에서 Enter 시도
            try:
                proj_input.press("Enter")
                self.page.wait_for_timeout(1000)
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

            self.page.wait_for_timeout(1500)
        except Exception as e:
            logger.warning(f"모달 검색 실패: {e}")

        _save_debug(page, "proj_modal_search_result")

        # 4. 검색 결과에서 첫 번째 데이터 행 선택
        selected = False

        # 방법 A: OBTDataGrid React Fiber API -- 모달 내 그리드 첫 행 선택
        try:
            react_selected = page.evaluate("""() => {
                const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl');
                for (const grid of grids) {
                    const rect = grid.getBoundingClientRect();
                    if (rect.y < 50 || rect.y > 800) continue;
                    const fKey = Object.keys(grid).find(k => k.startsWith('__reactFiber'));
                    if (!fKey) continue;
                    let node = grid[fKey];
                    for (let i = 0; i < 10; i++) {
                        if (!node) break;
                        if (node.stateNode && node.stateNode.state && node.stateNode.state.interface) {
                            const iface = node.stateNode.state.interface;
                            if (typeof iface.getRowCount === 'function') {
                                const rowCount = iface.getRowCount();
                                if (rowCount > 0) {
                                    iface.setSelection({ rowIndex: 0, columnIndex: 0 });
                                    iface.focus({ rowIndex: 0, columnIndex: 0 });
                                    if (typeof iface.commit === 'function') iface.commit();
                                    return { success: true, rowCount: rowCount };
                                } else {
                                    return { success: false, rowCount: 0 };
                                }
                            }
                        }
                        node = node.child || node.sibling || node.return;
                    }
                }
                return { success: false, rowCount: -1 };
            }""")
            if react_selected and react_selected.get("success"):
                logger.info(f"프로젝트 방법 A 성공: OBTDataGrid 첫 행 선택 ({react_selected.get('rowCount')}건)")
                selected = True
                self.page.wait_for_timeout(800)
            elif react_selected and react_selected.get("rowCount") == 0:
                logger.warning("프로젝트 방법 A: 검색 결과 없음 (0건)")
            else:
                logger.info(f"프로젝트 방법 A 미적용 (결과: {react_selected}) -> 방법 B 시도")
        except Exception as e:
            logger.info(f"프로젝트 방법 A 예외 (무시): {e}")

        # 방법 B: 모달 내 첫 데이터 행 DOM 탐색 후 더블클릭
        if not selected:
            try:
                # B-1: 모달 내 테이블/그리드의 첫 데이터 행을 CSS 셀렉터로 탐색
                modal_row_selectors = [
                    "div:has(h1:has-text('프로젝트코드도움')) tr:not(:first-child) td",
                    "div:has(text='프로젝트코드도움') tr:not(:first-child) td",
                    "div:has(h1:has-text('프로젝트코드도움')) [role='row'] [role='gridcell']",
                ]
                for row_sel in modal_row_selectors:
                    try:
                        first_cell = page.locator(row_sel).first
                        if first_cell.is_visible(timeout=1500):
                            first_cell.dblclick(force=True)
                            logger.info(f"프로젝트 방법 B-1 DOM 더블클릭: '{row_sel}'")
                            selected = True
                            self.page.wait_for_timeout(1000)
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"프로젝트 방법 B-1 DOM 탐색 실패: {e}")

        # 방법 B-2: JS로 모달 내 OBTDataGrid/테이블 첫 데이터 행 탐색 후 더블클릭
        if not selected:
            try:
                first_row_info = page.evaluate("""() => {
                    // 프로젝트코드도움 모달 내 그리드/테이블의 첫 데이터 행 탐색
                    // 1) OBTDataGrid canvas 그리드인 경우 → React fiber로 첫 행 선택
                    const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl, [class*="OBTDataGrid"]');
                    for (const el of grids) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        // 모달 내부인지 확인 (y > 100, 화면에 보이는 그리드)
                        if (rect.y < 50) continue;
                        const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                        if (fk) {
                            let f = el[fk];
                            for (let i = 0; i < 3 && f; i++) f = f.return;
                            if (f && f.stateNode && f.stateNode.state && f.stateNode.state.interface) {
                                const iface = f.stateNode.state.interface;
                                if (typeof iface.setSelection === 'function' && typeof iface.getRowCount === 'function') {
                                    if (iface.getRowCount() > 0) {
                                        iface.setSelection({ rowIndex: 0, columnIndex: 0 });
                                        iface.focus();
                                        return { method: 'api', rowCount: iface.getRowCount() };
                                    }
                                }
                            }
                        }
                    }
                    // 2) 일반 테이블인 경우 → 첫 데이터 행에 직접 dblclick 이벤트 발생
                    const modal = document.querySelector('[class*="modal"], [class*="Modal"], [role="dialog"]');
                    const container = modal || document;
                    const rows = container.querySelectorAll('tr');
                    for (let i = 1; i < rows.length; i++) {
                        const r = rows[i].getBoundingClientRect();
                        if (r.height > 15 && r.height < 60 && r.y > 100) {
                            const tds = rows[i].querySelectorAll('td');
                            if (tds.length > 0) {
                                const target = tds[Math.min(1, tds.length - 1)];
                                target.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }));
                                return { method: 'js_dblclick', clicked: true };
                            }
                        }
                    }
                    return null;
                }""")
                if first_row_info:
                    if first_row_info.get("method") == "api":
                        # OBTDataGrid API로 선택 완료 → Enter로 확정
                        page.keyboard.press("Enter")
                        logger.info(f"프로젝트 방법 B-2 OBTDataGrid API 선택 (행수: {first_row_info.get('rowCount')})")
                        selected = True
                        self.page.wait_for_timeout(1000)
                    elif first_row_info.get("clicked"):
                        # JS 내부에서 직접 dblclick 이벤트 발생 (좌표 불필요)
                        logger.info(f"프로젝트 방법 B-2 JS직접 더블클릭 ({first_row_info.get('method')})")
                        selected = True
                        self.page.wait_for_timeout(1000)
            except Exception as e:
                logger.warning(f"프로젝트 방법 B-2 JS탐색 실패: {e}")

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
                    self.page.wait_for_timeout(500)
                except Exception:
                    pass
            else:
                logger.info("프로젝트 더블클릭으로 모달 자동 닫힘")
        else:
            try:
                page.locator("button:has-text('취소')").last.click()
                self.page.wait_for_timeout(300)
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
            self.page.wait_for_timeout(300)

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

        # 방법 2-1: CSS 속성/role 기반 셀렉터 (탭 버튼 대안)
        for css_sel in [
            f"[data-id*='증빙']",
            f"li[class*='tab'][title*='{btn_text}']",
            f"div[role='tab']:has-text('{btn_text}')",
            f"span[class*='tab']:has-text('{btn_text}')",
            f"[class*='tab']:has-text('{btn_text}')",
            f"[title='{btn_text}']",
            f"[aria-label*='{btn_text}']",
        ]:
            try:
                el = page.locator(css_sel).first
                if el.is_visible(timeout=1500):
                    box = el.bounding_box()
                    if box and grid_y_min < box["y"] < grid_y_max + 200:
                        el.click(force=True)
                        logger.info(f"증빙유형 버튼 클릭 (CSS sel '{css_sel}'): '{btn_text}'")
                        return True
            except Exception:
                continue

        # 방법 3: JS 동적 탐색 — 지출내역 영역 근처에서 버튼 텍스트 매칭 + 직접 클릭
        try:
            js_result = page.evaluate(f"""() => {{
                const target = '{btn_text}';
                // 모든 클릭 가능 요소 중 텍스트 매칭
                const candidates = Array.from(document.querySelectorAll(
                    'button, [role="tab"], [role="button"], li, span, a, div'
                ));
                let best = null, bestDist = Infinity;
                for (const el of candidates) {{
                    const text = el.textContent.trim();
                    if (text !== target && !text.startsWith(target)) continue;
                    // 텍스트가 너무 길면 (부모 컨테이너 등) 스킵
                    if (text.length > target.length + 10) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    if (r.y < 150 || r.y > 800) continue;  // 화면 범위 밖 제외
                    // 지출내역 헤더와의 거리로 우선순위 설정
                    const dist = Math.abs(r.y - 370);  // 대략적 기준 y
                    if (dist < bestDist) {{
                        bestDist = dist;
                        best = el;
                    }}
                }}
                if (best) {{
                    best.click();
                    return {{ clicked: true }};
                }}
                return null;
            }}""")
            if js_result and js_result.get("clicked"):
                logger.info(f"증빙유형 버튼 클릭 (JS직접클릭): '{btn_text}'")
                return True
        except Exception as e:
            logger.warning(f"증빙유형 JS동적탐색 실패: {e}")

        # 방법 3-1: Playwright locator 폴백 (y 범위 무시, 텍스트만 매칭)
        for fallback_sel in [
            f"button:has-text('{btn_text}')",
            f"div:has-text('{btn_text}')",
            f"span:has-text('{btn_text}')",
        ]:
            try:
                fb_el = page.locator(fallback_sel).first
                if fb_el.is_visible(timeout=1500):
                    fb_el.click(force=True)
                    logger.info(f"증빙유형 버튼 클릭 (Playwright locator 폴백 '{fallback_sel}'): '{btn_text}'")
                    return True
            except Exception:
                continue

        # 방법 4: 좌표 폴백 (최종, 해상도 의존)
        coords = coord_map.get(btn_text)
        if coords:
            try:
                logger.warning(f"증빙유형 버튼 셀렉터 모두 실패, 좌표 폴백: {coords}")
                page.mouse.click(*coords)
                logger.info(f"증빙유형 버튼 클릭 (좌표 폴백 {coords}): '{btn_text}'")
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
            """날짜 문자열 정규화 (YYYY-MM-DD / YYYYMMDD / YYYY.MM.DD -> 지정 포맷)"""
            d = d.replace("-", "").replace(".", "")[:8]
            if fmt == "%Y-%m-%d" and len(d) == 8:
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            return d

        # 기본 기간: ±6개월 (3개월에서 확장 -- 분기 지연 발행 계산서 대응)
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

        logger.info(f"계산서 모달 검색 -- vendor='{vendor}' amount={amount} 기간={date_from}~{date_to}")

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
            self.page.wait_for_timeout(250)

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
                # 작성일자 옆의 날짜 range -- 부모 컨테이너 내 input 찾기
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
                    self.page.wait_for_timeout(300)
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
                logger.info("모달 조회 -- Enter 키")
            except Exception:
                pass

        # 결과 로드 대기
        self.page.wait_for_timeout(2000)
        _save_debug(page, "invoice_modal_search_result")

        # ── 미반영 탭 확인 ──
        try:
            tab = page.locator("text=미반영").first
            if tab.is_visible(timeout=1000):
                tab.click(force=True)
                self.page.wait_for_timeout(500)
        except Exception:
            pass

        # ── 결과 테이블에서 행 선택 (체크박스 클릭) ──
        # GW 모달의 체크박스는 커스텀 컴포넌트 (OBTCheckBox)일 수 있음
        # -> input[type=checkbox], div[class*='check'], label 등 다양한 셀렉터 시도
        selected = False

        # ── 방법 0: OBTDataGrid React Fiber API로 모달 내 그리드 첫 행 선택 ──
        logger.info("방법 0: OBTDataGrid React Fiber -- 모달 내 그리드 첫 행 선택 시도")
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
                self.page.wait_for_timeout(500)
            elif react_selected and react_selected.get("rowCount") == 0:
                logger.warning("방법 0: 모달 그리드 데이터 없음 (0건)")
                # 데이터 없는 경우 취소
                try:
                    page.locator("button:has-text('취소')").last.click(force=True)
                except Exception:
                    pass
                return False
            else:
                logger.info(f"방법 0 미적용 (결과: {react_selected}) -> 기존 방법으로 폴백")
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
                logger.info("셀렉터로 체크박스 미발견 -- 모달 기준 상대 좌표 클릭")
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

                # ── 방법 1: 모달 내 체크박스 CSS 셀렉터 직접 탐색 ──
                # 모달 컨테이너 내부의 데이터 행 체크박스를 찾아 클릭
                try:
                    # 모달 제목 기준으로 모달 영역 파악
                    title_el = page.locator("text=매입(세금)계산서 내역").first
                    title_box = title_el.bounding_box() if title_el.is_visible(timeout=1000) else None

                    if title_box:
                        modal_y_min = title_box["y"]
                        modal_y_max = title_box["y"] + 500  # 모달 높이 대략 500px 이내

                        # 모달 영역 내 체크박스 탐색
                        cb_found = False
                        for cb_sel in [
                            "input[type='checkbox']",
                            "[role='checkbox']",
                            "div[class*='checkbox']",
                            "div[class*='Checkbox']",
                        ]:
                            try:
                                all_cbs = page.locator(cb_sel).all()
                                # y 순서 정렬 후 헤더(전체선택) 체크박스 건너뛰기
                                modal_cbs = []
                                for cb in all_cbs:
                                    try:
                                        box = cb.bounding_box()
                                        if box and modal_y_min < box["y"] < modal_y_max:
                                            modal_cbs.append((box["y"], cb))
                                    except Exception:
                                        continue

                                if len(modal_cbs) >= 2:
                                    modal_cbs.sort(key=lambda x: x[0])
                                    # 첫 번째는 헤더(전체선택), 두 번째부터 데이터 행
                                    _, data_cb = modal_cbs[1]
                                    data_cb.click(force=True)
                                    logger.info(f"계산서 체크박스 CSS 셀렉터 클릭 ('{cb_sel}', 모달 내 {len(modal_cbs)}개 중 2번째)")
                                    selected = True
                                    cb_found = True
                                    break
                                elif len(modal_cbs) == 1:
                                    # 체크박스 1개면 바로 클릭
                                    _, only_cb = modal_cbs[0]
                                    only_cb.click(force=True)
                                    logger.info(f"계산서 체크박스 CSS 셀렉터 클릭 ('{cb_sel}', 모달 내 1개)")
                                    selected = True
                                    cb_found = True
                                    break
                            except Exception:
                                continue

                        if cb_found:
                            self.page.wait_for_timeout(300)
                            _save_debug(page, "invoice_modal_css_click")
                        else:
                            raise ValueError("모달 내 체크박스 CSS 셀렉터 미발견")
                    else:
                        raise ValueError("모달 제목 위치 미확인")
                except Exception as e:
                    logger.debug(f"계산서 체크박스 CSS 탐색 실패: {e}")

                # ── 방법 2: JS로 모달 내 체크박스/첫 데이터 행 동적 탐색 (폴백) ──
                if not selected:
                    try:
                        cb_info = page.evaluate("""() => {
                            // 모달 내 체크박스 탐색 (input[type=checkbox] 또는 체크박스 역할 요소)
                            const allCbs = Array.from(document.querySelectorAll(
                                'input[type="checkbox"], [role="checkbox"], [class*="checkbox"], [class*="Checkbox"]'
                            ));
                            // 화면에 보이고 y > 200인 체크박스만 (모달 내부)
                            const visible = allCbs.filter(cb => {
                                const r = cb.getBoundingClientRect();
                                return r.width > 0 && r.height > 0 && r.y > 200;
                            }).sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y);

                            if (visible.length === 0) {
                                // 체크박스 없으면 테이블 첫 데이터 행 좌표 반환
                                const trs = document.querySelectorAll('tr');
                                for (const tr of trs) {
                                    const rect = tr.getBoundingClientRect();
                                    const text = tr.textContent || '';
                                    if (rect.height > 20 && rect.height < 50 && text.includes('20') && rect.y > 200) {
                                        return { method: 'row', x: rect.x + 15, y: rect.y + rect.height / 2 };
                                    }
                                }
                                return null;
                            }

                            // 헤더 체크박스 제외: 첫 번째와 두 번째 y 차이가 15px 이상이면 헤더
                            let dataStart = 0;
                            if (visible.length > 1) {
                                const y0 = visible[0].getBoundingClientRect().y;
                                const y1 = visible[1].getBoundingClientRect().y;
                                if (y1 - y0 > 15) dataStart = 1;
                            }
                            if (dataStart < visible.length) {
                                const target = visible[dataStart];
                                target.click();
                                return { method: 'cb', clicked: true };
                            }
                            return null;
                        }""")
                        if cb_info:
                            if cb_info.get("clicked"):
                                self.page.wait_for_timeout(300)
                                _save_debug(page, "invoice_modal_js_click")
                                logger.info(f"체크박스 JS직접클릭 ({cb_info['method']})")
                                selected = True
                            elif cb_info.get("x"):
                                # 좌표 폴백 (행 클릭 등)
                                page.mouse.click(cb_info["x"], cb_info["y"])
                                self.page.wait_for_timeout(300)
                                _save_debug(page, "invoice_modal_js_click")
                                logger.info(f"체크박스 JS동적좌표 클릭 ({cb_info['method']}): ({cb_info['x']:.0f}, {cb_info['y']:.0f})")
                                selected = True
                    except Exception as e:
                        logger.warning(f"체크박스 JS동적탐색 실패: {e}")
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
                    logger.info(f"헤더 제외 -> 데이터 체크박스 {len(data_checkboxes)}개")

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
                self.page.wait_for_timeout(500)
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
                        self.page.wait_for_timeout(300)
                        break
            except Exception:
                pass
            return False

        # ── 확인 버튼 클릭 ──
        # 모달 하단의 "확인" 버튼 (파란색) -- 모달 제목 기준 상대 위치
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
            self.page.wait_for_timeout(500)

        if modal_closed:
            logger.info("계산서 모달 닫힘 확인")
        else:
            logger.warning("계산서 모달이 아직 열려있음 -- X 버튼으로 닫기 시도")
            try:
                # X 닫기 버튼 클릭
                close_btn = page.locator("button:has-text('x'), button[class*='close']").first
                if close_btn.is_visible(timeout=1000):
                    close_btn.click(force=True)
                    self.page.wait_for_timeout(1000)
            except Exception:
                pass

        # 그리드 반영 대기
        self.page.wait_for_timeout(2000)
        _save_debug(page, "03c3_after_invoice_applied")
        logger.info("계산서 모달 -> 그리드 반영 완료")
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


    def _link_reference_document(self, keyword: str) -> bool:
        """
        참조문서 연결.

        더존 Amaranth GW 지출결의서의 "참조문서" 섹션에서
        기존 결재문서를 검색 후 선택하여 연결.

        흐름:
        1. "참조문서" 버튼/탭 클릭 → 문서 검색 팝업 오픈
        2. 키워드 입력 → 검색
        3. 결과 목록에서 첫 번째 항목 선택
        4. 확인 → 팝업 닫힘 → 메인 폼에 참조문서 반영

        DOM 힌트 (GW 관찰 후 보정 필요):
        - 참조문서 버튼: button:has-text('참조문서'), [title='참조문서추가']
        - 검색 팝업: text=참조문서, h1:has-text('참조문서')
        - 검색 input: input[placeholder*='제목'], input[placeholder*='문서번호']
        - 결과 행: tr > td (테이블), 또는 OBTDataGrid canvas

        Args:
            keyword: 참조문서 검색어 (예: 선급금 품의서 제목, 문서번호)
        Returns:
            True if 참조문서 연결 성공
        """
        page = self.page
        logger.info(f"참조문서 연결 시작: '{keyword}'")
        _save_debug(page, "ref_doc_00_before")

        # ── 단계 1: 참조문서 버튼/링크 클릭 → 팝업 오픈 ──
        ref_btn_selectors = [
            "button:has-text('참조문서')",
            "a:has-text('참조문서')",
            "[title='참조문서추가']",
            "[title='참조문서 추가']",
            "[aria-label*='참조문서']",
            "button:has-text('문서연결')",
            "button:has-text('문서 연결')",
            "button[class*='refDoc']",
            "button[class*='ref_doc']",
            # 더존 GW 공통 아이콘 버튼 패턴
            "span:has-text('참조문서') + button",
            "th:has-text('참조문서') button",
            "td:has-text('참조문서') button",
        ]
        clicked = False
        for sel in ref_btn_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1500):
                    btn.click(force=True)
                    logger.info(f"참조문서 버튼 클릭: '{sel}'")
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # JS 동적 탐색 — "참조문서" 텍스트를 포함하는 클릭 가능한 요소
            try:
                js_clicked = page.evaluate("""() => {
                    const candidates = Array.from(
                        document.querySelectorAll('button, a, [role="button"], span[onclick], div[onclick]')
                    );
                    for (const el of candidates) {
                        const text = (el.textContent || '').trim();
                        const title = el.getAttribute('title') || '';
                        const aria = el.getAttribute('aria-label') || '';
                        if (text === '참조문서' || text === '문서연결'
                                || title.includes('참조문서') || aria.includes('참조문서')) {
                            el.click();
                            return el.tagName + ':' + text;
                        }
                    }
                    return null;
                }""")
                if js_clicked:
                    logger.info(f"참조문서 버튼 JS 클릭: {js_clicked}")
                    clicked = True
            except Exception as e:
                logger.debug(f"참조문서 JS 탐색 실패: {e}")

        if not clicked:
            logger.warning("참조문서 버튼을 찾을 수 없음 — DOM 관찰 후 셀렉터 보정 필요")
            _save_debug(page, "ref_doc_01_btn_not_found")
            return False

        # ── 단계 2: 참조문서 검색 팝업 대기 ──
        self.page.wait_for_timeout(800)
        popup_found = False
        popup_selectors = [
            "text=참조문서",
            "h1:has-text('참조문서')",
            "h2:has-text('참조문서')",
            "div:has-text('참조문서조회')",
            "text=결재문서조회",
        ]
        for sel in popup_selectors:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=5000)
                logger.info(f"참조문서 팝업 감지: '{sel}'")
                popup_found = True
                break
            except Exception:
                continue

        if not popup_found:
            logger.warning("참조문서 팝업 미감지 — 팝업이 열리지 않음")
            _save_debug(page, "ref_doc_02_popup_not_found")
            return False

        _save_debug(page, "ref_doc_02_popup_opened")

        # ── 단계 3: 검색어 입력 → 검색 ──
        search_selectors = [
            "input[placeholder*='제목']",
            "input[placeholder*='문서번호']",
            "input[placeholder*='검색']",
            "input[placeholder*='품의']",
            "input[type='text']:visible",
        ]
        search_input = None
        for sel in search_selectors:
            try:
                inputs = page.locator(sel).all()
                for inp in inputs:
                    if inp.is_visible(timeout=1000):
                        # 팝업 내부 input만 (화면 중앙 이상)
                        box = inp.bounding_box()
                        if box and box["x"] > 200:
                            search_input = inp
                            break
                if search_input:
                    break
            except Exception:
                continue

        if search_input:
            search_input.click(force=True)
            search_input.fill("")
            search_input.type(keyword, delay=60)
            logger.info(f"참조문서 검색어 입력: '{keyword}'")
            search_input.press("Enter")
            self.page.wait_for_timeout(1000)
        else:
            logger.warning("참조문서 검색 input 미발견 — 검색 없이 목록에서 선택 시도")

        _save_debug(page, "ref_doc_03_after_search")

        # ── 단계 4: 결과 목록에서 첫 번째 항목 선택 ──
        selected = False

        # 방법 1: 테이블 행 (tr > td) 클릭
        try:
            rows = page.locator("tr").all()
            for row in rows[1:]:  # 헤더 행 제외
                try:
                    if not row.is_visible(timeout=500):
                        continue
                    cells = row.locator("td").all()
                    if len(cells) < 2:
                        continue
                    first_cell_text = cells[0].inner_text(timeout=500).strip()
                    if first_cell_text and first_cell_text not in ("번호", "No", "#"):
                        row.click()
                        logger.info(f"참조문서 행 선택: '{first_cell_text[:40]}'")
                        selected = True
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"참조문서 테이블 행 선택 실패: {e}")

        # 방법 2: OBTDataGrid canvas — React fiber로 첫 번째 행 선택
        if not selected:
            try:
                result = page.evaluate("""() => {
                    const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl, [class*="OBTDataGrid"]');
                    for (const el of grids) {
                        const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                        if (!fk) continue;
                        let f = el[fk];
                        for (let i = 0; i < 3 && f; i++) f = f.return;
                        if (!f?.stateNode?.state) continue;
                        const iface = f.stateNode.state.interface;
                        if (!iface || typeof iface.getRowCount !== 'function') continue;
                        if (iface.getRowCount() > 0) {
                            iface.setSelection({ rowIndex: 0 });
                            return true;
                        }
                    }
                    return false;
                }""")
                if result:
                    logger.info("참조문서 OBTDataGrid 첫 번째 행 선택")
                    selected = True
            except Exception as e:
                logger.debug(f"참조문서 그리드 API 선택 실패: {e}")

        if not selected:
            logger.warning("참조문서 결과 항목 선택 실패")
            _save_debug(page, "ref_doc_04_no_selection")
            # 팝업 닫기 시도
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

        self.page.wait_for_timeout(300)
        _save_debug(page, "ref_doc_04_selected")

        # ── 단계 5: 확인 버튼 클릭 → 팝업 닫힘 ──
        confirm_selectors = [
            "button:has-text('확인')",
            "button:has-text('선택')",
            "button:has-text('연결')",
            "a:has-text('확인')",
        ]
        confirmed = False
        for sel in confirm_selectors:
            try:
                btns = page.locator(sel).all()
                for btn in reversed(btns):
                    if btn.is_visible(timeout=1000):
                        btn.click(force=True)
                        logger.info(f"참조문서 팝업 확인: '{sel}'")
                        confirmed = True
                        break
                if confirmed:
                    break
            except Exception:
                continue

        if not confirmed:
            # 더블클릭으로 선택 확정 시도
            try:
                rows2 = page.locator("tr").all()
                for row2 in rows2[1:]:
                    if row2.is_visible(timeout=500):
                        row2.dblclick()
                        logger.info("참조문서 행 더블클릭으로 확정")
                        confirmed = True
                        break
            except Exception:
                pass

        self.page.wait_for_timeout(500)
        _save_debug(page, "ref_doc_05_after_confirm")

        if confirmed:
            logger.info(f"참조문서 연결 완료: '{keyword}'")
        else:
            logger.warning("참조문서 확인 버튼 미클릭 — 연결 불확실")

        return confirmed

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

        # YYYY-MM-DD -> YYYYMMDD 변환 (GW 날짜 필드 형식)
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
            "input[class*='DatePicker']:visible",
            "input[placeholder*='날짜']",
            "input[placeholder*='증빙']",
            "label:has-text('증빙일자') + * input",
            "label:has-text('증빙일자') ~ * input",
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

        # 폴백 3: JS로 증빙일자 라벨 인접 input 동적 탐색
        try:
            result = page.evaluate("""() => {
                const cells = Array.from(document.querySelectorAll('th, td, label, span, div'));
                const cell = cells.find(c => c.textContent.trim() === '증빙일자');
                if (!cell) return null;
                // 부모 tr -> 같은 행 input 탐색
                const row = cell.closest('tr');
                if (row) {
                    const inp = row.querySelector('input');
                    if (inp) {
                        const r = inp.getBoundingClientRect();
                        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    }
                }
                // 인접 형제 탐색
                let sib = cell.nextElementSibling;
                while (sib) {
                    const inp = sib.querySelector('input');
                    if (inp) {
                        const r = inp.getBoundingClientRect();
                        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    }
                    sib = sib.nextElementSibling;
                }
                return null;
            }""")
            if result:
                # JS로 찾은 input에 직접 focus + 값 설정 (좌표 클릭 대신)
                filled = page.evaluate(f"""() => {{
                    const cells = Array.from(document.querySelectorAll('th, td, label, span, div'));
                    const cell = cells.find(c => c.textContent.trim() === '증빙일자');
                    if (!cell) return false;
                    let inp = null;
                    const row = cell.closest('tr');
                    if (row) inp = row.querySelector('input');
                    if (!inp) {{
                        let sib = cell.nextElementSibling;
                        while (sib) {{
                            inp = sib.querySelector('input');
                            if (inp) break;
                            sib = sib.nextElementSibling;
                        }}
                    }}
                    if (!inp) return false;
                    inp.focus();
                    inp.value = '{clean_date}';
                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}""")
                if filled:
                    page.keyboard.press("Tab")
                    logger.info(f"증빙일자 입력 (JS직접입력): {date_str}")
                    return True
                else:
                    # JS 직접 입력 실패 시 JS로 찾은 input에 focus + click 후 키보드 입력
                    focused = page.evaluate("""() => {
                        const cells = Array.from(document.querySelectorAll('th, td, label, span, div'));
                        const cell = cells.find(c => c.textContent.trim() === '증빙일자');
                        if (!cell) return false;
                        let inp = null;
                        const row = cell.closest('tr');
                        if (row) inp = row.querySelector('input');
                        if (!inp) {
                            let sib = cell.nextElementSibling;
                            while (sib) {
                                inp = sib.querySelector('input');
                                if (inp) break;
                                sib = sib.nextElementSibling;
                            }
                        }
                        if (!inp) return false;
                        inp.focus();
                        inp.click();
                        return true;
                    }""")
                    if focused:
                        page.keyboard.type(clean_date)
                        page.keyboard.press("Tab")
                        logger.info(f"증빙일자 입력 (JS focus+click 후 keyboard): {date_str}")
                        return True
        except Exception as e:
            logger.debug(f"증빙일자 JS 동적 탐색 실패: {e}")

        # 폴백: Playwright locator로 증빙일자 라벨 인접 input 탐색
        try:
            th_loc = page.locator("th:has-text('증빙일자')")
            if th_loc.count() > 0:
                td_input = th_loc.locator("xpath=following-sibling::td//input").first
                if td_input.is_visible(timeout=2000):
                    td_input.click(force=True)
                    td_input.fill(clean_date)
                    td_input.press("Tab")
                    logger.info(f"증빙일자 입력 (Playwright th+td locator): {date_str}")
                    return True
        except Exception as e:
            logger.debug(f"증빙일자 Playwright locator 실패: {e}")

        # 최종 폴백: 하드코딩 좌표 (x=763, y=857, fullscreen 기준)
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
        - input[type=file][id=uploadFile] (hidden) -- setInputFiles로 직접 처리
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

        # 방법 2: "선택" 버튼 클릭 -> file chooser 처리
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
                        "label:has(input[type='file'])",
                        "button[title*='파일']",
                        "button:has(svg)",
                        "[aria-label*='파일']",
                        "[aria-label*='선택']",
                        "button[class*='upload']",
                        "button[class*='file']",
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
                    # JS 동적 탐색 — 파일/첨부 관련 버튼 찾아서 직접 클릭
                    try:
                        js_clicked = page.evaluate("""() => {
                            const btns = Array.from(document.querySelectorAll('button, [role="button"], label, a'));
                            for (const btn of btns) {
                                const text = btn.textContent.trim();
                                const title = btn.getAttribute('title') || '';
                                const ariaLabel = btn.getAttribute('aria-label') || '';
                                const isMatch = ['선택', '파일선택', '첨부', '파일'].some(
                                    kw => text === kw || title.includes(kw) || ariaLabel.includes(kw)
                                );
                                if (!isMatch) continue;
                                const r = btn.getBoundingClientRect();
                                if (r.width > 0 && r.height > 0 && r.y > 100 && r.y < 400) {
                                    btn.click();
                                    return true;
                                }
                            }
                            return false;
                        }""")
                        if js_clicked:
                            logger.info("첨부 버튼 클릭 (JS직접클릭)")
                            clicked = True
                    except Exception as e:
                        logger.debug(f"첨부 버튼 JS동적탐색 실패: {e}")
                if not clicked:
                    # 최종 폴백: 하드코딩 좌표 (해상도 의존)
                    logger.warning("첨부 선택 버튼 모두 실패, 좌표 최종 폴백: (1865, 246)")
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

    def capture_budget_status_screenshot(self, output_path: str = None, detail_view: bool = True) -> str | None:
        """
        예실대비현황(상세) 화면 스크린샷 캡처.

        GW 예실대비현황:
        - 지출결의서 양식 내 하단 예산 잔액 현황 테이블
        - detail_view=True 시 "상세" 버튼/탭 클릭 후 상세 화면 캡처

        Args:
            output_path: 저장 경로 (None이면 자동 생성)
            detail_view: True이면 상세 뷰 버튼 클릭 시도 (기본값 True)
        Returns:
            저장된 파일 경로 (str) 또는 None
        """
        page = self.page
        if output_path is None:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(SCREENSHOT_DIR / f"budget_status_{ts}.png")

        # ── 상세 뷰 클릭 (detail_view=True 시) ──
        if detail_view:
            self._click_budget_detail_view()

        # ── 하단 예산 영역으로 스크롤 ──
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            self.page.wait_for_timeout(800)
        except Exception:
            pass

        # ── 예실대비현황 섹션 element 캡처 (섹션 특정 가능 시) ──
        # 섹션 셀렉터 우선 시도: 예실대비현황 테이블만 crop
        budget_section_selectors = [
            "text=예실대비현황",
            "div:has(> h3:has-text('예실대비'))",
            "table:has(th:has-text('실행예산'))",
            "table:has(th:has-text('예산잔액'))",
            "table:has(th:has-text('집행액'))",
        ]
        for sel in budget_section_selectors:
            try:
                section = page.locator(sel).first
                if section.is_visible(timeout=1500):
                    section.screenshot(path=output_path)
                    logger.info(f"예실대비현황 섹션 스크린샷 저장: {output_path} (셀렉터: {sel})")
                    return output_path
            except Exception:
                continue

        # ── 폴백: 전체 화면 캡처 ──
        try:
            page.screenshot(path=output_path, full_page=False)
            logger.info(f"예실대비현황 전체화면 스크린샷 저장: {output_path}")
            return output_path
        except Exception as e:
            logger.warning(f"스크린샷 캡처 실패: {e}")
            return None

    def _click_budget_detail_view(self) -> bool:
        """
        예실대비현황(상세) 뷰 전환 버튼 클릭.

        더존 GW 지출결의서 하단에 "상세" 또는 "예실대비현황(상세)" 탭/버튼이 있어
        클릭 시 실행예산액/이월예산액/예산총액/집행액/사용가능여부/예산잔액 표시.

        Returns:
            True if 상세 버튼 클릭 성공
        """
        page = self.page
        detail_selectors = [
            "button:has-text('상세')",
            "a:has-text('상세')",
            "span:has-text('상세')",
            "div[class*='tab']:has-text('상세')",
            "li[class*='tab']:has-text('상세')",
            "button:has-text('예실대비현황')",
            "a:has-text('예실대비현황')",
            "[title='상세']",
            "[title='예실대비현황 상세']",
            "[aria-label*='상세']",
        ]
        for sel in detail_selectors:
            try:
                btns = page.locator(sel).all()
                for btn in btns:
                    if btn.is_visible(timeout=1000):
                        box = btn.bounding_box()
                        # 하단 영역 (y > 화면 50%) 버튼 우선
                        if box:
                            btn.click(force=True)
                            logger.info(f"예실대비현황 상세 버튼 클릭: '{sel}' (y={box['y']:.0f})")
                            self.page.wait_for_timeout(600)
                            return True
            except Exception:
                continue

        # JS로 "상세" 텍스트 포함 클릭 가능 요소 탐색
        try:
            result = page.evaluate("""() => {
                const candidates = Array.from(
                    document.querySelectorAll('button, a, [role="tab"], span[onclick], li[onclick]')
                );
                for (const el of candidates) {
                    const text = (el.textContent || '').trim();
                    if (text === '상세' || text === '예실대비현황(상세)' || text === '예실대비현황 상세') {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            el.click();
                            return text;
                        }
                    }
                }
                return null;
            }""")
            if result:
                logger.info(f"예실대비현황 상세 버튼 JS 클릭: '{result}'")
                self.page.wait_for_timeout(600)
                return True
        except Exception as e:
            logger.debug(f"예실대비현황 상세 JS 탐색 실패: {e}")

        logger.debug("예실대비현황 상세 버튼 미발견 — 일반 뷰 캡처")
        return False

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

    # data.items 키 -> 그리드 컬럼 매핑
    ITEM_KEY_TO_COL = {
        "usage": "용도",       # 용도 (계정과목 코드도움)
        "content": "내용",     # 내용 (텍스트)
        "vendor": "거래처",    # 거래처 (텍스트)
        "supply_amount": "공급가액",  # 공급가액 (숫자)
        "tax_amount": "부가세",       # 부가세 (숫자)
        # 합계액은 자동 계산
        "item": "내용",        # 호환: agent.py의 "item" -> "내용"
        "amount": "공급가액",  # 호환: agent.py의 "amount" -> "공급가액"
        "note": "내용",        # 호환: "note"도 내용에 매핑
    }

