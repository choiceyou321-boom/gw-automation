"""
전자결재 자동화 -- 지출결의서 mixin
"""
from __future__ import annotations

import logging
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from src.approval.base import (
    GW_URL, MAX_RETRIES, RETRY_DELAY, SCREENSHOT_DIR,
    _GET_GRID_IFACE_JS, _save_debug, _parse_project_text, _js_str,
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
        - save_mode="draft" (기본): 임시보관 저장
        - save_mode="verify": 필드 작성 검증만 수행, 실제 저장/상신 안 함
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

                # 7-A. 보관 버튼 직접 클릭 시도 (팝업 없이 바로 임시저장 가능 시)
                # 진단: 현재 페이지의 모든 버튼 텍스트 확인
                try:
                    _btn_scan = self.page.evaluate("""() => {
                        const btns = [...document.querySelectorAll('button, [class*="topBtn"]')];
                        return btns
                            .filter(b => b.offsetParent !== null)
                            .map(b => ({tag: b.tagName, text: b.textContent.trim().slice(0, 20), cls: b.className.slice(0, 40)}))
                            .filter(b => b.text);
                    }""")
                    logger.info(f"7-A 진단 버튼 목록: {_btn_scan}")
                except Exception:
                    pass
                _draft_btn = None
                for _ds in ["div.topBtn:has-text('보관')", "button:has-text('보관')",
                             "[class*='topBtn']:has-text('보관')", "text=보관"]:
                    try:
                        _dloc = self.page.locator(_ds).first
                        if _dloc.is_visible(timeout=1500):
                            _draft_btn = _dloc
                            logger.info(f"보관 버튼 직접 발견 (팝업 불필요): {_ds}")
                            break
                    except Exception:
                        continue
                if _draft_btn:
                    try:
                        _draft_btn.scroll_into_view_if_needed()
                        self.page.wait_for_timeout(200)
                        _draft_btn.click()
                        self.page.wait_for_timeout(2000)
                        self._dismiss_obt_alert()
                        logger.info("보관 직접 클릭 완료 (메인 폼)")
                        return {"success": True, "message": "지출결의서가 임시보관함에 저장되었습니다."}
                    except Exception as _de:
                        logger.warning(f"보관 직접 클릭 실패: {_de} — 결재상신 경로로 폴백")

                # 7. 결재상신 클릭 -> 팝업 대기
                # 결재상신 전 남아있는 OBTAlert 및 모달 닫기 (최대 3회 반복)
                for _cleanup_try in range(3):
                    self._dismiss_obt_alert()
                    self._close_open_modals()
                    self.page.wait_for_timeout(300)
                    # 아직 OBTAlert dimmed가 남아있으면 Escape로도 시도
                    try:
                        still_blocked = self.page.evaluate("""() => {
                            return !!document.querySelector('[class*="OBTAlert"][class*="dimmed"]');
                        }""")
                        if not still_blocked:
                            break
                        logger.info(f"OBTAlert 잔존 (시도 {_cleanup_try+1}) → Escape 시도")
                        self.page.keyboard.press("Escape")
                        self.page.wait_for_timeout(500)
                    except Exception:
                        break
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
                        # _dimClicker 차단 대비: 짧은 타임아웃으로 시도, 실패 시 JS click
                        try:
                            submit_btn.click(timeout=3000)
                        except Exception as _ce:
                            logger.warning(f"결재상신 click 차단됨({_ce.__class__.__name__}) → JS click 폴백")
                            submit_btn.evaluate("btn => btn.click()")
                        logger.info("결재상신 클릭 -> 팝업 대기 (expect_page)")
                    popup_page = new_page_info.value
                    logger.info(f"결재상신 팝업 감지: {popup_page.url[:100]}")
                except Exception as e:
                    logger.warning(f"expect_page 팝업 감지 실패: {e}")

                # expect_page 실패 시 폴링 폴백
                if not popup_page:
                    pages_before = set(id(p) for p in self.context.pages)
                    # 잔존 OBTDialog 다시 닫기 시도 후 재클릭
                    self._close_open_modals()
                    self.page.wait_for_timeout(300)
                    try:
                        try:
                            submit_btn.click(timeout=3000)
                        except Exception:
                            submit_btn.evaluate("btn => btn.click()")
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
                                    self.page.wait_for_timeout(800)
                            except Exception:
                                pass
                            # 검증 부적합 상태에서도 문서목록 이탈 후 보관 시도
                            logger.info("검증 부적합 → 문서목록 이탈 후 보관 시도")
                            if self._try_archive_via_navigate_away():
                                return {"success": True, "message": "지출결의서가 임시보관함에 저장되었습니다."}
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

        # 3차: 직접 URL 네비게이션 (클릭 방식 실패 시 최후 수단)
        logger.info("클릭 방식 실패 → 직접 URL 네비게이션 시도")
        try:
            base_url = page.url.split("/#/")[0] if "/#/" in page.url else page.url.rstrip("/")
            direct_url = f"{base_url}/#/HP/APB1020/APB1020?formDTp=APB1020_00001&formId=255"
            page.goto(direct_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_url("**/APB1020/**", timeout=10000)
            logger.info(f"직접 URL 네비게이션 성공: {page.url[:100]}")
            return
        except Exception as e:
            logger.warning(f"직접 URL 네비게이션 실패: {e}")

        _save_debug(page, "error_expense_form_not_found")
        raise Exception("지출결의서 양식을 찾을 수 없습니다.")


    def _try_archive_via_navigate_away(self) -> bool:
        """
        검증 부적합 상황에서 문서목록 이탈 후 GW 보관 다이얼로그 처리.
        GW는 작성 중 폼에서 이탈 시 OBTAlert로 '보관' 옵션을 제공함.

        Returns:
            True if 보관 성공, False otherwise
        """
        page = self.page
        try:
            # 문서목록 버튼 클릭 → 폼 이탈 트리거
            doc_btn = page.locator("button:has-text('문서목록')").first
            if not doc_btn.is_visible(timeout=2000):
                logger.warning("_try_archive_via_navigate_away: 문서목록 버튼 미발견")
                return False
            doc_btn.click()
            page.wait_for_timeout(2000)
            _save_debug(page, "archive_via_navigate_01_after_doclist")

            # OBTAlert 내 '보관' 버튼 탐색
            # _dismiss_obt_alert()는 '취소'/'저장안함'을 우선하므로 사용 금지
            for sel in [
                "[class*='OBTAlert'] button:has-text('보관')",
                "[class*='OBTAlert_container'] button:has-text('보관')",
                "[class*='modal'] button:has-text('보관')",
                "button:has-text('보관')",
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2500):
                        btn.click()
                        page.wait_for_timeout(2000)
                        _save_debug(page, "archive_via_navigate_02_after_archive_btn")
                        logger.info(f"navigate-away 보관 버튼 클릭 성공: {sel}")
                        # 남은 OBTAlert 닫기
                        self._dismiss_obt_alert()
                        return True
                except Exception:
                    continue

            # '보관' 버튼 없으면 현재 상태 디버그
            _save_debug(page, "archive_via_navigate_03_no_archive_btn")
            logger.warning("navigate-away: 보관 버튼 미발견 (GW 다이얼로그 미출현 또는 다른 UI)")
            return False
        except Exception as e:
            logger.warning(f"_try_archive_via_navigate_away 예외: {e}")
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

        # 폼 진입 직후 GW OBTAlert(저장여부 등) 남아있을 수 있음 → 먼저 닫기
        # OBTAlert는 form 로드 후 react-reveal 애니메이션으로 최대 3초 지연 등장
        # → 나타날 때까지 대기한 뒤 처리 (없으면 최대 3초 후 그냥 진행)
        try:
            page.wait_for_selector(
                '[class*="OBTAlert_dimmed"]',
                state="attached",
                timeout=3000,
            )
            logger.info("OBTAlert_dimmed 감지 — dismiss 시작")
        except Exception:
            logger.debug("OBTAlert_dimmed 미감지 (3초 내) — 그냥 진행")
        self._dismiss_obt_alert()
        page.wait_for_timeout(300)  # 닫힘 후 UI 안정화 대기

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
                    from src.approval.base import GW_URL
                    page.goto(f"{GW_URL}/#/app/approval")
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
        _invoice_auto_budget_handled = False  # 인보이스 선택 직후 예산팝업 처리 여부
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

                    # 열린 모달이 있으면 먼저 닫기 (dimClicker 차단 방지)
                    self._close_open_modals()
                    self.page.wait_for_timeout(500)

                    self._click_evidence_type_button(evidence_type)
                    self.page.wait_for_timeout(2000)  # 모달 로딩 대기 늘림
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
                        # 모달 선택 자체 실패 -- 열린 모달 닫고 재시도 중단
                        logger.warning("세금계산서 모달 선택 실패 -- 재시도 중단")
                        self._close_open_modals()
                        # 모달 취소 후 GW가 OBTAlert를 비동기로 표시할 수 있음 → 1.5초 대기 후 dismiss
                        page.wait_for_timeout(1500)
                        self._dismiss_obt_alert()
                        page.wait_for_timeout(500)
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
                    # GW는 인보이스 선택 직후 용도코드를 자동 설정하면서 예산잔액 조회 팝업을
                    # 즉시 트리거할 수 있음. 이후 다른 단계들(receipt_date, project_bottom 등)을
                    # 진행하기 전에 여기서 바로 감지/처리해야 함 (step 10-A는 너무 늦을 수 있음).
                    _bkw_early = data.get("budget_keyword", "")
                    _ukw_early = data.get("usage_code", "")
                    if _bkw_early and _ukw_early:
                        try:
                            from src.approval.budget_helpers import handle_auto_triggered_popup
                            _proj_kw_early = (
                                project.split(". ", 1)[-1].split("]")[-1].strip()
                                if project else ""
                            )
                            _early_result = handle_auto_triggered_popup(
                                page=page,
                                project_keyword=_proj_kw_early,
                                budget_keyword=_bkw_early,
                                timeout_ms=4000,  # 짧은 타임아웃 — 팝업이 이미 열렸거나 없으면 빠르게 skip
                            )
                            if _early_result["success"]:
                                logger.info(
                                    f"인보이스 선택 직후 예산팝업 처리 완료: "
                                    f"{_early_result['budget_code']}. {_early_result['budget_name']}"
                                )
                                _invoice_auto_budget_handled = True
                            else:
                                logger.info(
                                    f"인보이스 선택 직후 예산팝업 없음 — "
                                    f"step 10-A에서 재처리: {_early_result['message']}"
                                )
                        except Exception as _e_early:
                            logger.warning(f"인보이스 선택 직후 예산팝업 처리 예외: {_e_early}")
                else:
                    if _invoice_row_count == 0 and _modal_invoice_selected:
                        logger.error("인보이스 선택 후 그리드 행 없음 (3회 재시도 모두 실패) -- 검증 부적합 발생 가능")
                    _save_debug(page, "03c2_after_invoice_select")
            else:
                # 세금계산서가 아닌 증빙유형 (카드, 현금영수증 등) -> 버튼만 클릭
                self._click_evidence_type_button(evidence_type)
                _save_debug(page, "03c_after_evidence")

        # 5. 지출내역 그리드 수동 입력 (세금계산서 미선택 시만)
        if not invoice_selected:
            if not items:
                # 세금계산서 검색 실패 시 폴백: total_amount + description으로 수동 항목 생성
                fallback_amount = data.get("total_amount") or data.get("amount", 0)
                fallback_desc = data.get("description", "")
                fallback_vendor = data.get("invoice_vendor", "")
                if fallback_amount:
                    items = [{"description": fallback_desc or "대금 지급", "amount": fallback_amount, "vendor": fallback_vendor}]
                    logger.info(f"세금계산서 미선택 → 폴백 그리드 항목 생성: {items}")
            if items:
                self._fill_grid_items(items)
                _save_debug(page, "03b_after_grid")

        # 6. 증빙일자 입력 (하단 테이블, y=857)
        receipt_date = data.get("receipt_date", "") or data.get("date", "")
        if receipt_date:
            self._fill_receipt_date(receipt_date)
            _save_debug(page, "03d_after_receipt_date")

        # 7. 하단 테이블 프로젝트 코드도움 입력 (y≈857 근처, 테이블 7)
        if project:
            result = self._fill_project_code_bottom(project)
            if not result:
                self._close_open_modals()
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
        #     인보이스 선택 시 GW가 용도코드를 자동 설정하므로, 이미 설정된 경우 재입력 건너뜀
        usage_code = data.get("usage_code", "")
        if usage_code and _invoice_auto_budget_handled:
            # 인보이스 선택 직후 예산팝업이 처리됨 = GW가 용도코드를 이미 올바르게 자동설정
            # → 재입력 시도 없이 다음 단계로 (재입력이 오히려 GW 상태를 교란할 수 있음)
            logger.info(f"용도코드 '{usage_code}' 재입력 건너뜀 — GW 자동설정 + 예산팝업 처리 완료")
        elif usage_code:
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
                                # interface.setSelection + focus으로 셀 포커스
                                # focus()에 rowIndex/columnName 전달 → 실제 셀 에디터 오픈 (no-args는 그리드 컨테이너만 포커스)
                                page.evaluate(f"""() => {{
                                    const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                    let f = el[fk];
                                    for (let i = 0; i < 3; i++) f = f.return;
                                    const iface = f.stateNode.state.interface;
                                    iface.setSelection({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }});
                                    // focus에 좌표 전달: 셀 에디터 활성화
                                    if (typeof iface.focus === 'function') {{
                                        try {{ iface.focus({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }}); }} catch(e) {{
                                            try {{ iface.focus(); }} catch(e2) {{}}
                                        }}
                                    }}
                                }}""")
                                self.page.wait_for_timeout(400)

                                # 활성화된 input 확인 (OBTDataGrid 셀 에디터)
                                _active_tag = page.evaluate("() => document.activeElement ? document.activeElement.tagName : 'none'")
                                _active_class = page.evaluate("() => document.activeElement ? document.activeElement.className : 'none'")
                                logger.info(f"용도 셀 포커스 후 activeElement: {_active_tag} class={_active_class[:60]}")

                                # focus()가 CANVAS만 활성화된 경우 → canvas 클릭으로 셀 에디터 직접 트리거
                                if _active_tag == "CANVAS":
                                    try:
                                        _cv_grid = page.locator(".OBTDataGrid_grid__22Vfl canvas").first
                                        _cv_box = _cv_grid.bounding_box()
                                        if _cv_box:
                                            # 첫 번째 데이터 행: 헤더 ~24px + 행 높이 절반 ~12px = y≈36
                                            # 용도 컬럼: 체크박스(약 32px) + 컬럼 너비 절반(약 40px)
                                            _cv_grid.click(position={"x": 52, "y": 36})
                                            self.page.wait_for_timeout(400)
                                            _active_tag = page.evaluate("() => document.activeElement ? document.activeElement.tagName : 'none'")
                                            logger.info(f"canvas 직접 클릭 후 activeElement: {_active_tag}")
                                    except Exception as _ce:
                                        logger.warning(f"canvas 직접 클릭 실패: {_ce}")

                                # 셀 기존값 초기화 → change event 강제 발생 위해 빈 문자열로 커밋
                                # setValue API로 즉각 클리어 (Escape는 원래 값으로 되돌리므로 부적합)

                                # [진단] setValue 전 현재 셀 값 확인
                                try:
                                    _val_before_clear = page.evaluate(f"""() => {{
                                        const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                        if (!el) return null;
                                        const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                        if (!fk) return null;
                                        let f = el[fk];
                                        for (let i = 0; i < 3 && f; i++) f = f.return;
                                        const iface = f?.stateNode?.state?.interface;
                                        return iface?.getValue ? iface.getValue({row_idx}, {_js_str(usage_col["name"])}) : null;
                                    }}""")
                                    logger.info(f"[진단] 용도 셀 setValue 전 값: '{_val_before_clear}'")
                                except Exception:
                                    pass

                                try:
                                    page.evaluate(f"""() => {{
                                        const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                        if (!el) return;
                                        const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                        if (!fk) return;
                                        let f = el[fk];
                                        for (let i = 0; i < 3 && f; i++) f = f.return;
                                        const iface = f?.stateNode?.state?.interface;
                                        if (!iface) return;
                                        if (typeof iface.setValue === 'function') {{
                                            iface.setValue({row_idx}, {_js_str(usage_col["name"])}, '');
                                        }}
                                        if (typeof iface.commit === 'function') iface.commit();
                                    }}""")
                                    self.page.wait_for_timeout(200)
                                    # [진단] setValue('') 후, retype 전 값 확인
                                    try:
                                        _val_after_clear = page.evaluate(f"""() => {{
                                            const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                            if (!el) return null;
                                            const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                            if (!fk) return null;
                                            let f = el[fk];
                                            for (let i = 0; i < 3 && f; i++) f = f.return;
                                            const iface = f?.stateNode?.state?.interface;
                                            return iface?.getValue ? iface.getValue({row_idx}, {_js_str(usage_col["name"])}) : null;
                                        }}""")
                                        logger.info(f"[진단] 용도 셀 setValue('') 후 값: '{_val_after_clear}'")
                                        if _val_after_clear:
                                            logger.warning(
                                                f"[진단] setValue('') 후에도 값 잔존 ('{_val_after_clear}') "
                                                "— OBT 코드도움 컬럼은 setValue로 클리어 안 될 수 있음"
                                            )
                                    except Exception:
                                        pass
                                except Exception:
                                    # 폴백: Ctrl+A + Delete (Escape 제거 — Escape는 원래 값 복원)
                                    page.keyboard.press("Control+A")
                                    page.keyboard.press("Delete")
                                    self.page.wait_for_timeout(200)
                                    page.keyboard.press("Tab")  # 빈 값 커밋
                                    self.page.wait_for_timeout(200)
                                # 셀 재포커스 (클리어 후 포커스 재설정)
                                page.evaluate(f"""() => {{
                                    const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                    if (!el) return;
                                    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                    if (!fk) return;
                                    let f = el[fk];
                                    for (let i = 0; i < 3; i++) f = f.return;
                                    const iface = f?.stateNode?.state?.interface;
                                    if (!iface) return;
                                    iface.setSelection({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }});
                                    if (typeof iface.focus === 'function') {{
                                        try {{ iface.focus({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }}); }} catch(e) {{}}
                                    }}
                                }}""")
                                self.page.wait_for_timeout(300)

                                # 편집 input에 용도코드 입력 (자동완성 트리거)
                                page.keyboard.type(str(usage_code), delay=50)
                                self.page.wait_for_timeout(800)  # 자동완성 드롭다운 대기
                                page.keyboard.press("Enter")
                                self.page.wait_for_timeout(500)  # 자동완성 선택 반영 대기

                                # 입력된 값 확인 (진단용)
                                try:
                                    _cell_val = page.evaluate(f"""() => {{
                                        const el = document.querySelector('.OBTDataGrid_grid__22Vfl');
                                        const fk = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                        let f = el[fk];
                                        for (let i = 0; i < 3 && f; i++) f = f.return;
                                        const iface = f?.stateNode?.state?.interface;
                                        if (!iface) return null;
                                        return iface.getValue ? iface.getValue({row_idx}, {_js_str(usage_col["name"])}) : null;
                                    }}""")
                                    logger.info(f"용도 셀 getValue 확인: '{_cell_val}'")
                                except Exception:
                                    pass

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
        #        인보이스 선택 직후 이미 처리된 경우 건너뜀; 아닌 경우 여기서 재시도
        _budget_auto_handled = _invoice_auto_budget_handled  # 인보이스 직후 처리 결과 반영
        _auto_budget_keyword = data.get("budget_keyword", "")
        if usage_code and _auto_budget_keyword:
            if _invoice_auto_budget_handled:
                logger.info("인보이스 선택 직후 예산팝업 이미 처리됨 — step 10-A 건너뜀")
            else:
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
                                    iface.setSelection({{ rowIndex: {row_idx}, columnName: {_js_str(pay_col["name"])} }});
                                    // focus에 좌표 전달: 셀 에디터 활성화
                                    if (typeof iface.focus === 'function') {{
                                        try {{ iface.focus({{ rowIndex: {row_idx}, columnName: {_js_str(pay_col["name"])} }}); }} catch(e) {{
                                            try {{ iface.focus(); }} catch(e2) {{}}
                                        }}
                                    }}
                                }}""")
                                self.page.wait_for_timeout(300)
                                page.keyboard.type(clean_date, delay=20)
                                self.page.wait_for_timeout(300)
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
                # 클릭 직전 OBTAlert_dimmed 재확인 — 연속 2회 clean 확인으로 안정성 보장
                # (용도코드 입력 후 GW 검증 알림 등 cascade alert 대응)
                _consecutive_clean = 0
                for _retry in range(10):  # 최대 5초
                    try:
                        has_obt = page.locator('[class*="OBTAlert_dimmed"]').count() > 0
                        if has_obt:
                            logger.info(f"프로젝트 클릭 전 OBTAlert_dimmed 감지 ({_retry+1}/10) — 재처리")
                            self._dismiss_obt_alert()
                            _consecutive_clean = 0
                        else:
                            _consecutive_clean += 1
                            if _consecutive_clean >= 2:  # 1초(0.5s×2) 연속 안정
                                break
                        page.wait_for_timeout(500)
                    except Exception:
                        break

                # invoice modal이 열려있으면 먼저 닫기 (project input 클릭 차단 방지)
                # "매칭된(매입)계산서가 없습니다." OBTAlert 처리 후 modal 자체가 남아 있는 경우
                try:
                    invoice_modal_visible = page.locator(
                        "text=매입(세금)계산서 내역"
                    ).first.is_visible(timeout=500)
                    if invoice_modal_visible:
                        logger.warning("invoice modal 열려있음 — 닫기 후 project input 클릭")
                        # 취소 버튼 우선 시도
                        _closed_modal = False
                        for _close_sel in ["button:has-text('취소')", "button:has-text('닫기')"]:
                            try:
                                _close_btn = page.locator(_close_sel).last
                                if _close_btn.is_visible(timeout=300):
                                    _close_btn.click(force=True)
                                    page.wait_for_timeout(500)
                                    _closed_modal = True
                                    logger.info(f"invoice modal 닫기 버튼 클릭: '{_close_sel}'")
                                    break
                            except Exception:
                                pass
                        if not _closed_modal:
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(500)
                            logger.info("invoice modal Escape 닫기")
                        # 닫힌 후 OBTAlert 추가 처리
                        self._dismiss_obt_alert()
                        page.wait_for_timeout(300)
                except Exception:
                    pass

                # 기존값 초기화: input에 값이 있으면 GW picker 미열림
                # fill() 후 포커스가 input에 남아있으면 재클릭 시 GW FOCUS 이벤트 미발생 →
                # Tab으로 blur 한 뒤 클릭해야 fresh FOCUS 이벤트로 picker 트리거됨
                try:
                    current_val = proj_input.input_value()
                    if current_val and current_val.strip():
                        logger.info(f"프로젝트 input 기존값 초기화: '{current_val[:50]}'")
                        proj_input.fill('')
                        page.keyboard.press('Tab')  # blur: 포커스를 다음 요소로 이동
                        page.wait_for_timeout(300)
                except Exception:
                    pass

                # 클릭 (GW React onFocus → 프로젝트코드도움 모달 트리거)
                # blur 상태에서 클릭해야 FOCUS 이벤트 발생 → picker 오픈
                try:
                    proj_input.click(timeout=5000)
                    logger.info("프로젝트 input 클릭 성공")
                except Exception as ce:
                    logger.warning(f"프로젝트 input 클릭 실패({ce.__class__.__name__}: {str(ce)[:100]}) — dispatch_event fallback")
                    self._dismiss_obt_alert()
                    proj_input.dispatch_event("mousedown")
                    proj_input.dispatch_event("mouseup")
                    proj_input.dispatch_event("click")

                self.page.wait_for_timeout(800)  # 모달 열림 대기
                logger.info("프로젝트 input 클릭 완료 — 모달 대기")
        except Exception as e:
            logger.warning(f"프로젝트 input 클릭 실패: {e}")
            # 열린 모달이 있으면 닫기
            self._close_open_modals()
            return False

        # 2. "프로젝트코드도움" 모달 대기 (타임아웃 증가: 3000 → 8000ms)
        self.page.wait_for_timeout(1000)
        modal_visible = False
        try:
            title_el = page.locator("text=프로젝트코드도움").first
            if title_el.is_visible(timeout=8000):
                modal_visible = True
                logger.info("프로젝트코드도움 모달 열림")
        except Exception:
            pass

        if not modal_visible:
            # 모달이 안 열린 경우 -- 잠시 기다린 후 재확인 (페이지 이탈 방지 위해 Enter 금지)
            self.page.wait_for_timeout(2000)
            try:
                title_el = page.locator("text=프로젝트코드도움").first
                if title_el.is_visible(timeout=3000):
                    modal_visible = True
                    logger.info("프로젝트코드도움 모달 열림 (지연 감지)")
            except Exception:
                pass

        if not modal_visible:
            logger.warning("프로젝트코드도움 모달 미열림")
            # ── 폴백: 프로젝트 코드 직접 입력 (GS-XX-XXXX 패턴 추출) ──
            # 모달이 열리지 않을 경우 코드를 직접 타이핑하면 GW가 자동 조회함
            import re as _re
            _code_match = _re.search(r'GS-\d{2}-\d{4}', project)
            _direct_code = _code_match.group() if _code_match else project.split()[0] if project.strip() else ""
            logger.info(f"프로젝트 코드 직접 입력 폴백 시도: '{_direct_code}' (y_hint={y_hint})")
            if _direct_code:
                try:
                    # JS로 모든 project code input 탐색 (placeholder 기반)
                    _inp_info = page.evaluate("""() => {
                        const inputs = Array.from(document.querySelectorAll("input[placeholder='프로젝트코드도움']"));
                        return inputs.map((inp, i) => {
                            const r = inp.getBoundingClientRect();
                            return { i, x: r.x, y: r.y, w: r.width, h: r.height, visible: r.width > 0 && r.height > 0, val: inp.value };
                        });
                    }""")
                    logger.info(f"프로젝트 코드 input 목록: {_inp_info}")

                    # y_hint 기반으로 가장 가까운 input 인덱스 선택
                    _best_idx = 0
                    if y_hint is not None and _inp_info:
                        _best_dist = float("inf")
                        for _ii in _inp_info:
                            if _ii.get("visible"):
                                _d = abs(_ii["y"] - y_hint)
                                if _d < _best_dist:
                                    _best_dist = _d
                                    _best_idx = _ii["i"]
                    elif _inp_info:
                        # visible한 첫 번째
                        for _ii in _inp_info:
                            if _ii.get("visible"):
                                _best_idx = _ii["i"]
                                break

                    # JS로 직접 입력 (React onChange 트리거 포함)
                    _typed = page.evaluate("""(args) => {
                        const inputs = document.querySelectorAll("input[placeholder='프로젝트코드도움']");
                        const inp = inputs[args.idx];
                        if (!inp) return { ok: false, reason: 'input_not_found', count: inputs.length };
                        inp.focus();
                        // React synthetic input event
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(inp, args.code);
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        inp.dispatchEvent(new Event('blur', { bubbles: true }));
                        return { ok: true, idx: args.idx, code: args.code, val: inp.value };
                    }""", {"idx": _best_idx, "code": _direct_code})
                    logger.info(f"JS 직접 입력 결과: {_typed}")

                    # Playwright type() 방식: keydown/keypress/keyup 이벤트로 GW OBTDialog2 피커 트리거
                    # type() 입력 시 GW가 OBTDialog2 프로젝트 피커를 열면 검색/선택하여 React 상태 갱신
                    try:
                        _proj_loc = page.locator("input[placeholder='프로젝트코드도움']").nth(_best_idx)
                        # 클릭 전 OBTAlert/overlay 해제 (invoice modal 닫기 후 GW cascade alert 가능)
                        self._dismiss_obt_alert()
                        page.wait_for_timeout(300)
                        try:
                            _proj_loc.click(click_count=3, timeout=8000)  # 전체 선택
                        except Exception as _ce:
                            logger.warning(f"프로젝트 input click 실패 ({_ce.__class__.__name__}) — force 클릭 시도")
                            try:
                                _proj_loc.click(click_count=3, force=True)
                            except Exception:
                                pass
                        _proj_loc.type(_direct_code, delay=50)  # 한 글자씩 입력 (GW OBTDialog2 피커 트리거)
                        page.wait_for_timeout(1000)   # OBTDialog2 피커 열림 대기

                        _picker_sel = ".OBTDialog2_dialogRootOpen__3PExr"
                        _picker_opened = page.locator(_picker_sel).count() > 0
                        _ac_found = False

                        if _picker_opened:
                            # OBTDialog2 프로젝트 피커 열림 → 검색 후 첫 행 선택 → 확인
                            # (단순 취소 대신 실제 선택하여 GW React 내부 프로젝트 상태 갱신)
                            logger.info("프로젝트 type() → OBTDialog2 피커 열림 → 검색/선택 시도")
                            _picker_selected = False
                            try:
                                # 피커 내 검색 버튼 클릭 (코드가 이미 검색 input에 입력된 상태)
                                _search_btn_found = False
                                for _sbsel in [
                                    f"{_picker_sel} button[class*='searchButton']",
                                    f"{_picker_sel} button:has(img[src*='search'])",
                                ]:
                                    try:
                                        _sb = page.locator(_sbsel).first
                                        if _sb.is_visible(timeout=500):
                                            _sb.click()
                                            _search_btn_found = True
                                            logger.info(f"피커 검색 버튼 클릭: {_sbsel}")
                                            break
                                    except Exception:
                                        continue
                                if not _search_btn_found:
                                    page.keyboard.press("Enter")
                                    logger.info("피커 검색 Enter 폴백")

                                # 피커 그리드 출현 폴링 (OBTDataGrid 또는 canvas, 최대 5초)
                                _grid_cnt = 0
                                _canvas_cnt = 0
                                for _ri in range(10):
                                    _grid_cnt = page.locator(f"{_picker_sel} .OBTDataGrid_grid__22Vfl").count()
                                    _canvas_cnt = page.locator(f"{_picker_sel} canvas").count()
                                    if _grid_cnt > 0 or _canvas_cnt > 0:
                                        break
                                    page.wait_for_timeout(500)
                                logger.info(f"피커 그리드 감지: OBTDataGrid={_grid_cnt}, canvas={_canvas_cnt}")
                                _save_debug(page, "picker_after_search")

                                # 방법 A: React Fiber (invoice modal과 동일 패턴: __reactInternalInstance + .return×3)
                                # OBTDataGrid_grid__22Vfl 엘리먼트에서 __reactFiber 또는 __reactInternalInstance 탐색
                                _picker_react = None
                                if _grid_cnt > 0:
                                    _picker_react = page.evaluate("""(args) => {
                                        const pickerSel = args.pickerSel;
                                        const codeToFind = args.code;
                                        const picker = document.querySelector(pickerSel);
                                        if (!picker) return { success: false, reason: 'no_picker' };
                                        const grid = picker.querySelector('.OBTDataGrid_grid__22Vfl');
                                        if (!grid) return { success: false, reason: 'no_grid' };
                                        // __reactFiber 또는 __reactInternalInstance 탐색
                                        const fk = Object.keys(grid).find(k =>
                                            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                                        );
                                        if (!fk) {
                                            // Root 엘리먼트도 시도
                                            const rootEl = picker.querySelector('[class*="OBTDataGrid_root"]');
                                            if (!rootEl) return { success: false, reason: 'no_fiber', sampleKeys: Object.keys(grid).filter(k => k.startsWith('__')).slice(0, 5) };
                                            const rootFk = Object.keys(rootEl).find(k =>
                                                k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                                            );
                                            if (!rootFk) return { success: false, reason: 'no_fiber_on_root', rootSampleKeys: Object.keys(rootEl).filter(k => k.startsWith('__')).slice(0, 5) };
                                            let f2 = rootEl[rootFk];
                                            for (let i = 0; i < 5 && f2; i++) f2 = f2.return;
                                            const iface2 = f2 && f2.stateNode && f2.stateNode.state && f2.stateNode.state.interface;
                                            if (!iface2 || typeof iface2.getRowCount !== 'function') return { success: false, reason: 'no_iface_from_root' };
                                            const rowCount2 = iface2.getRowCount();
                                            if (rowCount2 === 0) return { success: false, rowCount: 0 };
                                            let targetRow2 = 0;
                                            try {
                                                const cols2 = iface2.getColumns ? iface2.getColumns() : [];
                                                for (let r = 0; r < Math.min(rowCount2, 200); r++) {
                                                    for (const c of cols2) {
                                                        const cn = c.name || (c.columns && c.columns[0] && c.columns[0].name);
                                                        if (!cn) continue;
                                                        const v = String(iface2.getValue(r, cn) || '');
                                                        if (v.includes(codeToFind)) { targetRow2 = r; break; }
                                                    }
                                                    if (targetRow2 !== 0) break;
                                                }
                                            } catch(e2) {}
                                            iface2.setSelection({ rowIndex: targetRow2, columnIndex: 0 });
                                            iface2.focus({ rowIndex: targetRow2, columnIndex: 0 });
                                            if (typeof iface2.setCheckedRows === 'function') try { iface2.setCheckedRows([targetRow2]); } catch(e2c) {}
                                            if (typeof iface2.checkRow === 'function') try { iface2.checkRow(targetRow2, true); } catch(e2c) {}
                                            if (typeof iface2.commit === 'function') iface2.commit();
                                            return { success: true, rowCount: rowCount2, selectedRow: targetRow2, via: 'root' };
                                        }
                                        // grid 엘리먼트에서 .return 3회 상향 (invoice modal 패턴 동일)
                                        let f = grid[fk];
                                        for (let i = 0; i < 3 && f; i++) f = f.return;
                                        const iface = f && f.stateNode && f.stateNode.state && f.stateNode.state.interface;
                                        if (!iface || typeof iface.getRowCount !== 'function') return { success: false, reason: 'no_iface' };
                                        const rowCount = iface.getRowCount();
                                        if (rowCount === 0) return { success: false, rowCount: 0 };
                                        // 코드와 일치하는 행 찾기 (기본: 0번 행)
                                        let targetRow = 0;
                                        try {
                                            const cols = iface.getColumns ? iface.getColumns() : [];
                                            for (let r = 0; r < Math.min(rowCount, 200); r++) {
                                                for (const c of cols) {
                                                    const cn = c.name || (c.columns && c.columns[0] && c.columns[0].name);
                                                    if (!cn) continue;
                                                    const v = String(iface.getValue(r, cn) || '');
                                                    if (v.includes(codeToFind)) { targetRow = r; break; }
                                                }
                                                if (targetRow !== 0) break;
                                            }
                                        } catch(e) {}
                                        iface.setSelection({ rowIndex: targetRow, columnIndex: 0 });
                                        iface.focus({ rowIndex: targetRow, columnIndex: 0 });
                                        if (typeof iface.setCheckedRows === 'function') try { iface.setCheckedRows([targetRow]); } catch(ec) {}
                                        if (typeof iface.checkRow === 'function') try { iface.checkRow(targetRow, true); } catch(ec) {}
                                        if (typeof iface.commit === 'function') iface.commit();
                                        return { success: true, rowCount: rowCount, selectedRow: targetRow, via: 'grid' };
                                    }""", {"pickerSel": _picker_sel, "code": _direct_code})

                                if _picker_react and _picker_react.get("success"):
                                    logger.info(f"피커 방법A React Fiber 첫 행 선택 ({_picker_react.get('rowCount')}건)")
                                    page.wait_for_timeout(400)
                                    # 캔버스 클릭으로 GW 네이티브 행 선택 트리거 (setSelection 보완)
                                    # React Fiber setSelection은 UI 하이라이트만 변경 → 네이티브 클릭이 GW onRowSelect 실행
                                    try:
                                        _cv_p = page.locator(f"{_picker_sel} canvas").first
                                        _cv_pbox = _cv_p.bounding_box()
                                        if _cv_pbox:
                                            # 첫 번째 데이터 행: 헤더 약 24px + 행 높이 절반 12px = y≈36
                                            _cv_p.click(position={"x": _cv_pbox["width"] / 2, "y": 36})
                                            page.wait_for_timeout(400)
                                            logger.info("피커 캔버스 클릭: 첫 번째 행 GW 네이티브 선택")
                                    except Exception as _cpe:
                                        logger.warning(f"피커 캔버스 클릭 실패: {_cpe}")
                                    # 캔버스 클릭으로 피커가 자동 닫힌 경우 (dblclick 처럼 동작)
                                    if page.locator(_picker_sel).count() == 0:
                                        logger.info("피커 캔버스 클릭 후 자동 닫힘 → 선택 완료")
                                        _picker_selected = True
                                        _ac_found = True
                                    else:
                                        # 확인 버튼 클릭
                                        for _confirmsel in [
                                            f"{_picker_sel} button:has-text('확인')",
                                            "button:has-text('확인')",
                                        ]:
                                            try:
                                                _cbtn = page.locator(_confirmsel).last
                                                if _cbtn.is_visible(timeout=500):
                                                    _cbtn.click()
                                                    page.wait_for_timeout(800)
                                                    logger.info("피커 확인 버튼 클릭")
                                                    _picker_selected = True
                                                    _ac_found = True
                                                    break
                                            except Exception:
                                                continue
                                elif _picker_react and _picker_react.get("rowCount") == 0:
                                    logger.warning("피커 방법A: 검색 결과 없음 (0건)")
                                else:
                                    # 방법 B: canvas dblclick (OBTGrid canvas 방식 — locator.dblclick() 사용)
                                    _canvas_clicked = False
                                    if _canvas_cnt > 0:
                                        try:
                                            _cv = page.locator(f"{_picker_sel} canvas").first
                                            _cv_box = _cv.bounding_box()
                                            if _cv_box:
                                                # 코드 행 y 추정: 행 높이 약 22px, 첫 행=+11, 헤더 건너뜀
                                                # 첫 번째 데이터 행: 헤더 24px + 행 높이 절반 12px = y≈36
                                                _row_y = _cv_box["y"] + 36  # 첫 행
                                                _row_x = _cv_box["x"] + _cv_box["width"] / 2
                                                _cv.dblclick(position={"x": _cv_box["width"] / 2, "y": 36})
                                                page.wait_for_timeout(600)
                                                _canvas_clicked = True
                                                logger.info(f"피커 방법B canvas dblclick: y={_row_y:.0f}")
                                        except Exception as _cve:
                                            logger.warning(f"피커 방법B canvas 클릭 실패: {_cve}")

                                    # 방법 C: 키보드 ArrowDown + Enter (최후 수단)
                                    if not _canvas_clicked:
                                        logger.info("피커 방법C 키보드 ArrowDown+Enter 시도")
                                        page.keyboard.press("ArrowDown")
                                        page.wait_for_timeout(400)
                                        page.keyboard.press("Enter")
                                        page.wait_for_timeout(500)

                                    # 피커 닫힘 여부로 성공 판단
                                    if page.locator(_picker_sel).count() == 0:
                                        logger.info("피커 방법B/C 선택 후 닫힘 확인 → 성공")
                                        _picker_selected = True
                                        _ac_found = True
                                    else:
                                        # 확인 버튼 직접 클릭
                                        for _confirmsel in [
                                            f"{_picker_sel} button:has-text('확인')",
                                            "button:has-text('확인')",
                                        ]:
                                            try:
                                                _cbtn = page.locator(_confirmsel).last
                                                if _cbtn.is_visible(timeout=500):
                                                    _cbtn.click()
                                                    page.wait_for_timeout(800)
                                                    logger.info(f"피커 방법B/C 확인 버튼 클릭: {_confirmsel}")
                                                    _picker_selected = True
                                                    _ac_found = True
                                                    break
                                            except Exception:
                                                continue
                                    if not _picker_selected:
                                        logger.warning(f"피커 방법A/B/C 모두 실패: React={_picker_react}")
                            except Exception as _pe:
                                logger.warning(f"OBTDialog2 피커 선택 중 예외: {_pe}")

                            # 피커가 아직 열려있으면 닫기
                            if page.locator(_picker_sel).count() > 0:
                                try:
                                    _cancel = page.locator(f"{_picker_sel} button:has-text('취소')").last
                                    if _cancel.is_visible(timeout=300):
                                        _cancel.click()
                                        page.wait_for_timeout(500)
                                        logger.info("피커 미선택 → 취소로 닫기")
                                except Exception:
                                    pass

                            if _picker_selected:
                                logger.info(f"프로젝트 코드 OBTDialog2 피커 선택 완료: '{_direct_code}'")
                                # 피커 확인 후 하단 프로젝트 input 현재값 로깅 (진단용)
                                try:
                                    _post_val = page.evaluate("""() => {
                                        const inputs = [...document.querySelectorAll("input[placeholder='프로젝트코드도움']")]
                                            .filter(inp => inp.getBoundingClientRect().y > 500);
                                        return inputs.length > 0 ? inputs[inputs.length - 1].value : '(not found)';
                                    }""")
                                    logger.info(f"피커 확인 후 하단 project input 값: '{_post_val}'")
                                except Exception:
                                    pass
                            else:
                                logger.warning(f"프로젝트 코드 OBTDialog2 피커 선택 실패: '{_direct_code}'")
                        else:
                            # 피커 미열림 → 자동완성 드롭다운 확인
                            for _asel in [
                                "ul[class*='autocomplete'] li:first-child",
                                "div[class*='OBTAutoComplete'] li:first-child",
                                "li[class*='item']:first-child",
                            ]:
                                try:
                                    _ac = page.locator(_asel).first
                                    if _ac.is_visible(timeout=300):
                                        _ac.click()
                                        _ac_found = True
                                        page.wait_for_timeout(400)
                                        logger.info(f"프로젝트 자동완성 선택: {_asel}")
                                        break
                                except Exception:
                                    continue
                            if not _ac_found:
                                page.keyboard.press("Enter")
                                page.wait_for_timeout(400)

                        logger.info(f"프로젝트 코드 type() 방식 완료: '{_direct_code}' (피커={_picker_opened}, 선택={_ac_found})")
                    except Exception as _te:
                        logger.warning(f"프로젝트 코드 type() 방식 실패: {_te}")

                    # Tab으로 blur → GW 자동조회 최종 트리거
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(800)

                    if _typed and _typed.get("ok"):
                        logger.info(f"프로젝트 코드 직접 입력 폴백 성공: '{_direct_code}'")
                        return True
                except Exception as _fe:
                    logger.warning(f"프로젝트 코드 직접 입력 폴백 실패: {_fe}")
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

            # 모달 검색 키워드: 전체 프로젝트 문자열 대신 짧은 이름/코드 사용
            # 예: "GS-25-0088. [종로] 메디빌더" → "메디빌더" (GW 검색 정확도 향상)
            _search_kw = project
            if ". " in project:
                _search_kw = project.split(". ", 1)[1]  # "[종로] 메디빌더"
                if "]" in _search_kw:
                    _search_kw = _search_kw.split("]", 1)[1].strip()  # "메디빌더"
            if not _search_kw.strip():
                _search_kw = project

            modal_search = None
            if modal_search_idx >= 0:
                modal_search = page.locator("input").nth(modal_search_idx)
                current_val = modal_search.input_value()
                if _search_kw.lower() not in current_val.lower():
                    modal_search.click(force=True)
                    modal_search.fill(_search_kw)
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
                const target = {_js_str(btn_text)};
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
        매입(세금)계산서 내역 모달에서 세금계산서를 검색/선택.

        실제 GW 조작 플로우 (2026-03-29 관찰):
        1. 모달 열림 대기 ("매입(세금)계산서 내역" 제목)
        2. 달력 팝업으로 시작일 변경 (기본 2일 → 넓은 범위)
        3. ▼ 버튼 클릭 → 상세검색 영역 토글
        4. 거래처/사업자번호 input에 vendor 타이핑
        5. 🔍 조회 버튼 클릭
        6. 결과 체크박스 선택
        7. 확인 클릭 → 그리드 자동 반영
        """
        page = self.page
        import datetime as _dt

        # 기본 기간 계산 (±12개월)
        today = _dt.date.today()
        if not date_from:
            start = (today.replace(day=1) - _dt.timedelta(days=365)).replace(day=1)
            date_from = start.strftime("%Y-%m-%d")
        if not date_to:
            next_m = today.replace(day=28) + _dt.timedelta(days=4)
            date_to = (next_m.replace(day=1) - _dt.timedelta(days=1)).strftime("%Y-%m-%d")

        logger.info(f"계산서 모달 검색 -- vendor='{vendor}' amount={amount} 기간={date_from}~{date_to}")

        # ── 1. 모달 표시 대기 ──
        modal_visible = False
        modal_selectors = ["text=매입(세금)계산서 내역", "text=/매입.*계산서.*내역/", "text=계산서 내역"]
        for _ in range(40):
            for sel in modal_selectors:
                try:
                    if page.locator(sel).first.is_visible(timeout=100):
                        modal_visible = True
                        break
                except Exception:
                    pass
            if modal_visible:
                break
            self.page.wait_for_timeout(250)

        if not modal_visible:
            logger.warning("계산서 모달 미표시")
            _save_debug(page, "invoice_modal_not_found")
            return False

        logger.info("계산서 모달 표시 확인")
        self.page.wait_for_timeout(2000)  # 모달 내부 렌더링 대기

        # ── 2. 시작일 날짜 변경 ──
        # OBT DatePicker의 input.value가 evaluate에서 빈 문자열일 수 있음
        # → "작성일자" 레이블 근처 + width 50~80px + y:240~280 기준으로 찾기
        try:
            # 먼저 모달 내 모든 input 덤프 (디버그)
            all_inputs_debug = page.evaluate("""() => {
                const inputs = document.querySelectorAll('input');
                return Array.from(inputs).filter(inp => {
                    const r = inp.getBoundingClientRect();
                    return r.y > 200 && r.y < 350 && r.width > 30 && r.height > 0;
                }).map(inp => {
                    const r = inp.getBoundingClientRect();
                    return {
                        type: inp.type, value: (inp.value || '').substring(0, 30),
                        placeholder: inp.placeholder || '',
                        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width)
                    };
                });
            }""")
            logger.info(f"모달 상단 input 덤프: {all_inputs_debug}")

            date_coords = page.evaluate("""() => {
                // "작성일자" 레이블 찾기 (모달 내)
                let labelY = 260;
                const allEls = document.querySelectorAll('th, td, label, span, div');
                for (const el of allEls) {
                    if (el.textContent.trim() === '작성일자' && el.getBoundingClientRect().height > 0) {
                        const ey = el.getBoundingClientRect().y + el.getBoundingClientRect().height / 2;
                        // 모달 영역 (y > 200)
                        if (ey > 200) { labelY = ey; break; }
                    }
                }

                // 날짜 input 찾기: width 55~70px + "작성일자" 레이블과 같은 y 라인
                // value 조건 완화 (OBT DatePicker가 value를 지연 반영하므로)
                const inputs = document.querySelectorAll('input');
                const candidates = [];
                for (const inp of inputs) {
                    const r = inp.getBoundingClientRect();
                    if (r.width < 50 || r.width > 85 || r.height === 0) continue;
                    if (r.x < 500) continue;  // 좌측 사업장 제외
                    // labelY와 y 차이 25px 이내
                    const yCenter = r.y + r.height / 2;
                    if (Math.abs(yCenter - labelY) > 25) continue;
                    // value 확인 (있으면 날짜 패턴, 없어도 후보로 포함)
                    const val = inp.value || '';
                    candidates.push({
                        x: r.x + r.width / 2,
                        y: yCenter,
                        w: Math.round(r.width),
                        val: val
                    });
                }
                candidates.sort((a, b) => a.x - b.x);
                return { labelY: Math.round(labelY), dates: candidates };
            }""")
            logger.info(f"날짜 input 탐색: {date_coords}")

            dates = date_coords.get("dates", []) if date_coords else []
            if len(dates) >= 1:
                # 시작일 변경: triple_click → type
                coord = dates[0]
                page.mouse.click(coord["x"], coord["y"], click_count=3)
                self.page.wait_for_timeout(300)
                # 기존 값 전체 선택 후 덮어쓰기
                page.keyboard.press("Control+a")
                self.page.wait_for_timeout(100)
                page.keyboard.type(date_from, delay=30)
                page.keyboard.press("Tab")
                self.page.wait_for_timeout(500)
                logger.info(f"시작일 변경: {coord.get('val','')} → {date_from} (w={coord['w']})")

                # Tab 키 후 GW가 자동 조회 시작 → 로딩 완료 대기
                # OBT 로딩 오버레이가 뜨고 사라질 때까지 대기 (최대 15초)
                self.page.wait_for_timeout(2000)  # 로딩 시작 대기
                for _wait in range(26):  # 최대 13초 추가
                    try:
                        # 로딩 인디케이터가 보이면 대기
                        loading_visible = page.evaluate("""() => {
                            const els = document.querySelectorAll('*');
                            for (const el of els) {
                                const text = el.textContent.trim();
                                const r = el.getBoundingClientRect();
                                if ((text.includes('조회하고 있습니다') || text.includes('잠시 기다려')) && r.height > 0 && r.width > 0) {
                                    return true;
                                }
                            }
                            return false;
                        }""")
                        if loading_visible:
                            self.page.wait_for_timeout(500)
                            continue
                        break
                    except Exception:
                        break
                self.page.wait_for_timeout(1000)  # 렌더링 안정화
                logger.info("날짜 변경 후 자동 조회 완료 대기 끝")

                # 종료일은 변경하지 않음 — 시작일만 date_from으로 좁혀서 date_from~오늘 범위 조회
                logger.info(f"종료일 유지: {dates[1].get('val','') if len(dates) >= 2 else '(불명)'}")
            else:
                logger.warning(f"날짜 input 미발견 (labelY={date_coords.get('labelY')}, candidates=0)")
        except Exception as e:
            logger.warning(f"날짜 변경 실패: {e}")

        _save_debug(page, "invoice_modal_after_date_change")


        # 날짜 변경 후 자동 조회로 전체 목록이 로드됨
        # 상세검색/조회 버튼 불필요 — 전체 목록에서 vendor명으로 행 선택
        self.page.wait_for_timeout(3000)  # 자동 조회 결과 렌더링 대기
        _save_debug(page, "invoice_modal_search_result")


        # 디버그: 모달 내 그리드 구조 + React fiber 탐색
        try:
            modal_html = page.evaluate("""() => {
                const allEls = document.querySelectorAll('*');
                let modal = null;
                for (const el of allEls) {
                    if (el.textContent.includes('계산서 내역') && el.children.length < 5) {
                        modal = el.closest('[data-orbit-component], [class*="dialog"], [class*="Dialog"]');
                        if (modal) break;
                    }
                }
                if (!modal) return { error: 'no_modal' };

                // grid/canvas 요소의 클래스명 수집
                const gridEls = modal.querySelectorAll('[class*="grid"], [class*="Grid"], canvas');
                const gridClasses = Array.from(gridEls).slice(0, 10).map(el => ({
                    tag: el.tagName,
                    cls: (el.className || '').substring(0, 80),
                    w: Math.round(el.getBoundingClientRect().width),
                    h: Math.round(el.getBoundingClientRect().height),
                    hasFiber: !!Object.keys(el).find(k => k.startsWith('__reactFiber'))
                }));

                // React fiber로 OBTDataGrid interface 찾기
                // fiber가 grid 자체가 아닌 부모에 있을 수 있음 → 부모 3단계까지 탐색
                let gridAPI = null;
                for (const el of gridEls) {
                    let target = el;
                    for (let parentDepth = 0; parentDepth < 4 && target; parentDepth++) {
                        const fiberKey = Object.keys(target).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                        if (fiberKey) {
                            let node = target[fiberKey];
                            for (let d = 0; d < 20 && node; d++) {
                                try {
                                    const st = node?.stateNode?.state;
                                    const iface = st?.interface;
                                    if (iface && typeof iface.getRowCount === 'function') {
                                        gridAPI = {
                                            rowCount: iface.getRowCount(),
                                            depth: d,
                                            parentDepth: parentDepth,
                                            tag: el.tagName,
                                            cls: (el.className || '').substring(0, 40),
                                            methods: Object.keys(iface).filter(k => typeof iface[k] === 'function').slice(0, 20)
                                        };
                                        break;
                                    }
                                } catch(e) {}
                                node = node.return;
                            }
                            if (gridAPI) break;
                        }
                        target = target.parentElement;
                    }
                    if (gridAPI) break;
                }

                return {
                    gridElCount: gridEls.length,
                    gridClasses: gridClasses,
                    gridAPI: gridAPI,
                    trCount: modal.querySelectorAll('tr').length,
                    checkboxCount: modal.querySelectorAll('input[type="checkbox"]').length,
                    modalClass: modal.className?.substring(0, 60),
                    sampleTrs: Array.from(modal.querySelectorAll('tr')).slice(0, 5).map(tr => ({
                        tdCount: tr.querySelectorAll('td').length,
                        text: tr.textContent.substring(0, 80)
                    }))
                };
            }""")
            logger.info(f"모달 HTML 구조: {modal_html}")
        except Exception as e:
            logger.warning(f"모달 HTML 덤프 실패: {e}")

        # ── 6. 결과 행 선택 ──
        # 우선순위: A) dataProvider API → B) 상세검색 거래처 필터 → C) 좌표 클릭 폴백
        selected = False
        _vendor_found_by_dp = False  # 6-A에서 dataProvider로 vendor 행 인덱스 확보 여부

        # gridAPI에서 rowCount 가져오기 (디버그 덤프 결과 활용)
        grid_row_count = 0
        if isinstance(modal_html, dict) and modal_html.get("gridAPI"):
            grid_row_count = modal_html["gridAPI"].get("rowCount", 0)
            logger.info(f"모달 그리드 행 수: {grid_row_count}")

        if grid_row_count == 0:
            logger.warning("계산서 모달: 데이터가 존재하지 않습니다")
            return False

        # invoice modal 그리드 클릭 → window.Grids.getActiveGrid()가 invoice modal grid를 가리키도록
        # (헤더 오른쪽 영역 클릭: 체크박스 열 및 정렬 트리거 방지)
        try:
            _mgb = page.evaluate("""() => {
                const scope = document.querySelector('.obtdialog.open, [class*="OBTDialog"][class*="open"]') || document;
                const grid = scope.querySelector('.OBTDataGrid_grid__22Vfl');
                if (!grid) return null;
                const r = grid.getBoundingClientRect();
                return r.width > 0 ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
            }""")
            if _mgb and _mgb["w"] > 0:
                # 그리드 데이터 영역 중앙(x) + 헤더 바로 아래 첫 행(y) 클릭
                # x: 체크박스 열(x+15) 제외, 데이터 중앙(x + w//2)
                # y: 헤더 하단(35px) + 첫 행 중앙(14px)
                _fx = _mgb["x"] + _mgb["w"] // 2
                _fy = _mgb["y"] + 49  # header 35 + first row center 14
                page.mouse.click(_fx, _fy)
                self.page.wait_for_timeout(400)
                logger.info(f"invoice modal 그리드 포커스 클릭: ({_fx:.0f}, {_fy:.0f})")
        except Exception:
            pass

        # ── 6-A. OBTDataGrid 내부 dataProvider 심층 탐색 + vendor 행 checkRow ──
        # 전략: stateNode 내부 모든 객체를 재귀적으로 탐색해 getRowCount/getJsonRow가 있는 dataProvider 찾기
        try:
            # amount: 공급가액(supply amount) 또는 합계(total) 문자열로 인보이스 특정
            _amount_kw = str(int(amount)) if amount else ""
            # 날짜 키워드: date_from "2026-02-28" → "20260228" (GW issDt 형식)
            _date_dt_kw = date_from.replace("-", "") if date_from else ""
            select_result = page.evaluate(f"""() => {{
                const vendorKw = {_js_str(vendor or "")};
                const amountKw = {_js_str(_amount_kw)};
                const dateDtKw = {_js_str(_date_dt_kw)};  // issDt 형식: "20260228"

                // ── 방법 0: window.Grids.getActiveGrid() (클릭으로 invoice modal grid가 활성화) ──
                try {{
                    const ag = window.Grids ? window.Grids.getActiveGrid() : null;
                    if (ag) {{
                        const dp0 = ag.getDataProvider ? ag.getDataProvider() : null;
                        if (dp0) {{
                            const cnt0 = dp0.getRowCount ? dp0.getRowCount() : 0;
                            if (cnt0 >= 5) {{  // expense form(1행) 제외
                                const tr0 = findVendorRow(dp0, cnt0);
                                if (tr0 >= 0) {{
                                    const rd0 = dp0.getJsonRow ? dp0.getJsonRow(tr0) : null;
                                    // 금액 불일치여도 거래처 매칭 우선 선택 (중도금/부분지급 시나리오)
                                    if (typeof ag.checkRow === 'function') {{
                                        ag.checkRow(tr0, true);
                                        return {{ matched: true, targetRow: tr0, rowCount: cnt0, method: 'grid_native_checkRow', rowData: rd0 }};
                                    }}
                                    if (typeof ag.setTopItem === 'function') ag.setTopItem(tr0);
                                    return {{ matched: false, targetRow: tr0, rowCount: cnt0, method: 'grid_setTopItem', rowData: rd0 }};
                                }}
                                // tr0 < 0: vendor 미발견 → React fiber 방법으로 폴백
                            }}
                        }}
                    }}
                }} catch(e) {{}}

                // dataProvider 후보 객체에서 vendor 행 인덱스 찾기
                // 전략 (순서대로):
                //   1) vendor + amount 동시 매칭
                //   2) vendor만 매칭 (GW 등록명이 다를 수 있음)
                //   3) date + amount 매칭 (vendor명 불일치 시)
                //   4) amount만 매칭 (최후 수단)
                function findVendorRow(dp, rowCount) {{
                    if (!vendorKw && !amountKw && !dateDtKw) return 0;
                    const limit = Math.min(rowCount, 500);

                    // 전략 1: vendor + amount 동시 매칭
                    if (vendorKw && amountKw) {{
                        for (let i = 0; i < limit; i++) {{
                            try {{
                                const row = dp.getJsonRow ? dp.getJsonRow(i) : null;
                                if (!row) continue;
                                const s = JSON.stringify(row);
                                if (s.includes(vendorKw) && s.includes(amountKw)) return i;
                            }} catch(e) {{}}
                        }}
                    }}

                    // 전략 2: vendor만 매칭 (GW 등록 상호명이 다를 수 있음)
                    if (vendorKw) {{
                        for (let i = 0; i < limit; i++) {{
                            try {{
                                const row = dp.getJsonRow ? dp.getJsonRow(i) : null;
                                if (row && JSON.stringify(row).includes(vendorKw)) return i;
                            }} catch(e) {{}}
                        }}
                    }}

                    // 전략 3: date (issDt) + amount 매칭
                    if (dateDtKw && amountKw) {{
                        for (let i = 0; i < limit; i++) {{
                            try {{
                                const row = dp.getJsonRow ? dp.getJsonRow(i) : null;
                                if (!row) continue;
                                const s = JSON.stringify(row);
                                if (s.includes(dateDtKw) && s.includes(amountKw)) return i;
                            }} catch(e) {{}}
                        }}
                    }}

                    // 전략 4: amount만 매칭 (최후 수단)
                    if (amountKw) {{
                        for (let i = 0; i < limit; i++) {{
                            try {{
                                const row = dp.getJsonRow ? dp.getJsonRow(i) : null;
                                if (row && JSON.stringify(row).includes(amountKw)) return i;
                            }} catch(e) {{}}
                        }}
                    }}

                    return -1;
                }}

                // 객체를 재귀 탐색해 dataProvider 찾기
                function findDP(obj, depth) {{
                    if (!obj || depth > 5 || typeof obj !== 'object') return null;
                    try {{
                        if (typeof obj.getRowCount === 'function' && typeof obj.getJsonRow === 'function') {{
                            return obj;
                        }}
                        const keys = Object.getOwnPropertyNames(obj);
                        for (const k of keys) {{
                            try {{
                                const val = obj[k];
                                if (val && typeof val === 'object' && val !== obj) {{
                                    const found = findDP(val, depth + 1);
                                    if (found) return found;
                                }}
                            }} catch(e) {{}}
                        }}
                    }} catch(e) {{}}
                    return null;
                }}

                // 모달 컨테이너 먼저 찾기 (expense form 그리드와 구별)
                // invoice modal은 OBTDialog 계열 컨테이너 안에 있음
                let modalContainer = null;
                for (const el of document.querySelectorAll('[class*="OBTDialog"], [class*="obtdialog"], [class*="OBTPortal"]')) {{
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && el.textContent.includes('계산서')) {{
                        modalContainer = el;
                        break;
                    }}
                }}
                const gridScope = modalContainer || document;

                // grid 요소에서 fiber 탐색 (모달 내부 우선)
                const gridEls = gridScope.querySelectorAll('.OBTDataGrid_grid__22Vfl, .OBTDataGrid_root__mruAZ');
                for (const gridEl of gridEls) {{
                    let target = gridEl;
                    for (let p = 0; p < 6; p++) {{
                        if (!target) break;
                        const fiberKey = Object.keys(target).find(k =>
                            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                        if (fiberKey) {{
                            let node = target[fiberKey];
                            for (let d = 0; d < 30 && node; d++) {{
                                try {{
                                    const st = node?.stateNode;
                                    if (st && typeof st === 'object') {{
                                        // 방법 1: stateNode 직접 탐색 → dataProvider
                                        const dp = findDP(st, 0);
                                        if (dp) {{
                                            const rowCount = dp.getRowCount();
                                            // rowCount < 5 이면 expense form 그리드 (행 1개) → 스킵하고 계속 탐색
                                            if (rowCount >= 5) {{
                                                const targetRow = findVendorRow(dp, rowCount);
                                                const firstRowData = dp.getJsonRow ? dp.getJsonRow(targetRow) : null;

                                                // gridView 찾기 (체크박스 API 시도)
                                                const gv = st?._gridView || st?.gridView ||
                                                           st?.gridRef?.current || st?.state?._gridView;
                                                if (gv && typeof gv.checkRow === 'function') {{
                                                    gv.checkRow(targetRow, true);
                                                    return {{ matched: true, targetRow, rowCount, method: 'dp_checkRow', rowData: firstRowData }};
                                                }}
                                                if (gv && typeof gv.setCheck === 'function') {{
                                                    gv.setCheck(targetRow, true);
                                                    return {{ matched: true, targetRow, rowCount, method: 'dp_setCheck', rowData: firstRowData }};
                                                }}
                                                // gv 미발견 → iface.checkRow 직접 시도 (off-screen 행도 선택 가능)
                                                const iface2 = st?.state?.interface;
                                                if (iface2) {{
                                                    if (typeof iface2.checkRow === 'function') {{
                                                        iface2.checkRow(targetRow, true);
                                                        return {{ matched: true, targetRow, rowCount, method: 'dp_iface_checkRow', rowData: firstRowData }};
                                                    }}
                                                    if (typeof iface2.setSelection === 'function') {{
                                                        iface2.setSelection({{ startRow: targetRow, endRow: targetRow }});
                                                        return {{ matched: true, targetRow, rowCount, method: 'dp_iface_setSelection', rowData: firstRowData }};
                                                    }}
                                                }}
                                                // iface도 없음 → 행 인덱스만 반환 (좌표 계산용)
                                                return {{ matched: false, targetRow, rowCount, method: 'dp_found_no_gv', rowData: firstRowData }};
                                            }}
                                            // rowCount < 5: expense form 그리드 → 방법 2로 진행
                                        }}

                                        // 방법 2: state.interface 직접 사용 (invoice modal 전용)
                                        const iface = st?.state?.interface;
                                        if (iface && typeof iface.getRowCount === 'function') {{
                                            const rowCount = iface.getRowCount();
                                            if (rowCount >= 5) {{  // expense form(1행) 제외
                                                // vendor 행 인덱스 찾기: getValue + getDataSource 시도
                                                let targetRow = 0;
                                                if (vendorKw) {{
                                                    outer2: for (let i = 0; i < Math.min(rowCount, 300); i++) {{
                                                        for (const fn of ['trNm', 'vendorNm', 'cdDc', 'trCd', 'issNm', 'buyNm']) {{
                                                            try {{
                                                                const v = typeof iface.getValue === 'function'
                                                                    ? iface.getValue(i, fn) : null;
                                                                if (v && String(v).includes(vendorKw)) {{ targetRow = i; break outer2; }}
                                                            }} catch(e) {{}}
                                                        }}
                                                        try {{
                                                            const ds = typeof iface.getDataSource === 'function'
                                                                ? iface.getDataSource() : null;
                                                            if (ds && typeof ds.getJsonRow === 'function') {{
                                                                const row = ds.getJsonRow(i);
                                                                if (row && JSON.stringify(row).includes(vendorKw)) {{ targetRow = i; break; }}
                                                            }}
                                                        }} catch(e) {{}}
                                                    }}
                                                }}
                                                // checkRow 직접 시도
                                                if (typeof iface.checkRow === 'function') {{
                                                    iface.checkRow(targetRow, true);
                                                    return {{ matched: true, targetRow, rowCount, method: 'iface_direct_checkRow' }};
                                                }}
                                                // setSelection으로 대체 (행 선택)
                                                if (typeof iface.setSelection === 'function') {{
                                                    iface.setSelection({{ startRow: targetRow, endRow: targetRow }});
                                                    return {{ matched: true, targetRow, rowCount, method: 'iface_setSelection' }};
                                                }}
                                                // API 없음 → targetRow를 좌표 계산에 활용
                                                return {{ matched: false, targetRow, rowCount, method: 'iface_no_api', depth: d }};
                                            }}
                                        }}
                                    }}
                                }} catch(e) {{}}
                                node = node.return;
                            }}
                        }}
                        target = target.parentElement;
                    }}
                }}
                return {{ error: 'no_dp_found' }};
            }}""")
            logger.info(f"그리드 dataProvider 탐색 결과: {select_result}")

            if select_result and select_result.get("matched"):
                selected = True
                logger.info(
                    f"세금계산서 선택 성공 (dataProvider API): "
                    f"row={select_result.get('targetRow')}, method={select_result.get('method')}"
                )
            elif select_result and select_result.get("method") in ("dp_found_no_gv", "iface_no_api"):
                # dataProvider/iface는 찾았지만 checkRow 불가 → vendor 행 인덱스를 좌표 계산에 활용
                _dp_row_count = select_result.get("rowCount", 0)
                _vendor_row_idx = select_result.get("targetRow", 0)
                # rowCount가 5 미만이면 expense form 그리드를 잘못 읽은 것 → 6-B 스킵하지 않음
                if _dp_row_count >= 5:
                    _vendor_found_by_dp = True  # 6-B 거래처 필터 스킵 (사업장코드도움 팝업 방지)
                    logger.info(
                        f"invoice 행 인덱스 확보 ({select_result.get('method')}) → vendor 행={_vendor_row_idx} 좌표 클릭 예정 (6-B 스킵, rowCount={_dp_row_count})"
                    )
                else:
                    logger.warning(
                        f"rowCount={_dp_row_count} — expense form 그리드로 의심, 6-B 거래처 필터 진행"
                    )
            elif select_result and select_result.get("method") == "amount_mismatch_skip":
                # 거래처는 찾았지만 금액 불일치 → 잘못된 인보이스 선택 방지, 6-B/6-C 스킵
                _vendor_row_idx = -1  # sentinel: 6-C 좌표 클릭도 스킵
                logger.warning(
                    f"인보이스 금액 불일치 → 선택 건너뜀 (row={select_result.get('targetRow')}, "
                    f"기대금액={invoice_amount}, 행데이터={str(select_result.get('rowData', {}))[:100]})"
                )
            elif select_result and select_result.get("method") == "vendor_not_found_in_grid":
                # 거래처 키워드가 그리드에 없음 → 세금계산서 미선택, 6-B/6-C 스킵
                _vendor_row_idx = -1  # sentinel: 6-C 좌표 클릭도 스킵
                logger.warning(
                    f"거래처 '{vendor}' 미발견 (rowCount={select_result.get('rowCount', 0)}) → 세금계산서 미선택, 취소 예정"
                )
            elif select_result and select_result.get("method") in ("wrapper_only",):
                # iface wrapper만 찾음 (행 API 없음) → 6-B 거래처 필터로 진행
                _dp_row_count = select_result.get("rowCount", 0)
                logger.warning(
                    f"wrapper_only (rowCount={_dp_row_count}) → 6-B 거래처 필터 진행"
                )
                _vendor_row_idx = 0
            else:
                _vendor_row_idx = 0

        except Exception as e:
            logger.warning(f"그리드 dataProvider 탐색 실패: {e}")
            _vendor_row_idx = 0

        # ── 6-B. 상세검색 거래처 필터 (vendor 지정 시) ──
        # vendor 키워드가 있고 아직 선택 안 된 경우, 모달 내 거래처 input을 JS로 직접 조작
        # 단, 6-A에서 이미 dataProvider로 vendor 행 인덱스를 확보한 경우 스킵
        # (거래처 input이 사업장코드도움 팝업을 열어 혼란을 일으키는 것을 방지)
        if not selected and vendor and not _vendor_found_by_dp:
            # 상세검색 영역이 닫혀있으면 토글 → 거래처 input이 hidden(height=0)인 경우 열기
            try:
                toggle_result = page.evaluate("""() => {
                    const modal = document.querySelector('.obtdialog.open, [class*="OBTDialog"][class*="open"]');
                    const scope = modal || document;
                    const gridEl = scope.querySelector('.OBTDataGrid_grid__22Vfl');
                    const gridY = gridEl ? gridEl.getBoundingClientRect().y : 9999;
                    const modalBox = modal ? modal.getBoundingClientRect() : null;
                    const modalRight = modalBox ? modalBox.x + modalBox.width : 99999;

                    // 거래처 input이 이미 visible한지 확인
                    // 사업장코드도움 input(placeholder='사업장코드도움')은 제외 (항상 visible)
                    const allInputs = scope.querySelectorAll('input[type="text"], input:not([type])');
                    for (const inp of allInputs) {
                        const ir = inp.getBoundingClientRect();
                        const ph = (inp.placeholder || '').toLowerCase();
                        if (ir.height > 0 && ir.y > 200 && ir.y < gridY) {
                            // 사업장/날짜 input 제외
                            if (ph.includes('사업장') || ph.includes('date') || ir.width <= 100) continue;
                            return { already_visible: true };
                        }
                    }

                    // 상세검색 토글 버튼 찾기: "▼", "상세검색" 텍스트 포함 + 모달 오른쪽 20% 제외
                    const allEls = scope.querySelectorAll('*');
                    for (const el of allEls) {
                        const text = el.textContent.trim();
                        const r = el.getBoundingClientRect();
                        if (r.height === 0 || r.y < 200 || r.y > gridY) continue;
                        const isToggle = (text === '▼' || text === '▲' || text.includes('상세검색'));
                        // 모달 오른쪽 20% 안에 있는 요소는 프로젝트코드도움 ▼ 가능성 높으므로 제외
                        if (isToggle && r.x < modalRight * 0.82) {
                            return { found: true, x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), text };
                        }
                    }
                    return { found: false };
                }""")

                if toggle_result and toggle_result.get("found"):
                    page.mouse.click(toggle_result["x"], toggle_result["y"])
                    self.page.wait_for_timeout(800)
                    logger.info(
                        f"상세검색 토글 클릭: ({toggle_result['x']}, {toggle_result['y']}) "
                        f"text='{toggle_result.get('text')}'"
                    )
                elif toggle_result and toggle_result.get("already_visible"):
                    logger.info("상세검색 이미 열려있음 (거래처 input visible)")
                else:
                    logger.info("상세검색 토글 버튼 미발견 → 직접 거래처 input 탐색")
            except Exception as et:
                logger.warning(f"상세검색 토글 실패: {et}")

            try:
                # 모달 내 거래처 input 찾기 (placeholder 또는 근처 레이블로 식별)
                vendor_input_result = page.evaluate(f"""() => {{
                    const vendorKw = {_js_str(vendor)};

                    // 모달 컨테이너 찾기
                    const modal = document.querySelector('.obtdialog.open, [class*="OBTDialog"][class*="open"]');
                    const searchScope = modal || document;

                    // 거래처 레이블 근처 input 찾기
                    const allEls = searchScope.querySelectorAll('th, td, label, span, div');
                    let vendorInputEl = null;

                    for (const el of allEls) {{
                        const text = el.textContent.trim();
                        if (text === '거래처' || text === '공급자' || text === '거래처명') {{
                            const r = el.getBoundingClientRect();
                            if (r.height === 0 || r.y < 200) continue;
                            // 같은 행(y좌표 유사)에 있는 input 찾기
                            const allInputs = searchScope.querySelectorAll('input[type="text"], input:not([type])');
                            for (const inp of allInputs) {{
                                const ir = inp.getBoundingClientRect();
                                if (Math.abs(ir.y - r.y) < 20 && ir.x > r.x) {{
                                    vendorInputEl = inp;
                                    break;
                                }}
                            }}
                            if (vendorInputEl) break;
                        }}
                    }}

                    if (!vendorInputEl) {{
                        // 폴백: 모달 내에서 상세검색 영역에 있는 input (그리드 위)
                        // 사업장코드도움 input은 제외 (항상 visible, 거래처 input이 아님)
                        const gridEl = searchScope.querySelector('.OBTDataGrid_grid__22Vfl');
                        if (gridEl) {{
                            const gridY = gridEl.getBoundingClientRect().y;
                            const allInputs = searchScope.querySelectorAll('input[type="text"], input:not([type])');
                            for (const inp of allInputs) {{
                                const ir = inp.getBoundingClientRect();
                                const ph = (inp.placeholder || '').toLowerCase();
                                // 사업장/날짜 input 제외
                                if (ph.includes('사업장') || ir.width <= 85) continue;
                                if (ir.y > 200 && ir.y < gridY && ir.height > 0) {{
                                    vendorInputEl = inp;
                                    break;
                                }}
                            }}
                        }}
                    }}

                    if (!vendorInputEl) return {{ error: 'no_vendor_input' }};

                    const ir = vendorInputEl.getBoundingClientRect();
                    return {{
                        found: true,
                        x: Math.round(ir.x + ir.width / 2),
                        y: Math.round(ir.y + ir.height / 2),
                        w: Math.round(ir.width),
                        currentValue: vendorInputEl.value || ''
                    }};
                }}""")
                logger.info(f"거래처 input 탐색: {vendor_input_result}")

                if vendor_input_result and vendor_input_result.get("found"):
                    # 거래처 input 클릭 → 기존값 삭제 → vendor 타이핑
                    vi_x = vendor_input_result["x"]
                    vi_y = vendor_input_result["y"]
                    page.mouse.click(vi_x, vi_y, click_count=3)
                    self.page.wait_for_timeout(200)
                    page.keyboard.press("Control+a")
                    self.page.wait_for_timeout(100)
                    page.keyboard.type(vendor, delay=50)
                    self.page.wait_for_timeout(300)
                    logger.info(f"거래처 input에 '{vendor}' 입력 완료 (x={vi_x}, y={vi_y})")

                    # 조회 버튼 클릭 (모달 내 "조회" 버튼 또는 Enter)
                    searched = False
                    try:
                        # 모달 내에서 조회 버튼 찾기
                        search_btn_result = page.evaluate("""() => {
                            const modal = document.querySelector('.obtdialog.open, [class*="OBTDialog"][class*="open"]');
                            const scope = modal || document;
                            // "조회" 텍스트가 있는 버튼
                            const btns = scope.querySelectorAll('button, [class*="btn"], [class*="Btn"]');
                            for (const btn of btns) {
                                const t = btn.textContent.trim();
                                if (t === '조회' || t.includes('조회')) {
                                    const r = btn.getBoundingClientRect();
                                    if (r.height > 0 && r.y > 200) {
                                        return { found: true, x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
                                    }
                                }
                            }
                            return { found: false };
                        }""")
                        if search_btn_result and search_btn_result.get("found"):
                            page.mouse.click(search_btn_result["x"], search_btn_result["y"])
                            self.page.wait_for_timeout(500)
                            logger.info(f"조회 버튼 클릭: ({search_btn_result['x']}, {search_btn_result['y']})")
                            searched = True
                    except Exception as eb:
                        logger.warning(f"조회 버튼 클릭 실패: {eb}")

                    if not searched:
                        # 조회 버튼 미발견 → Enter 키로 조회
                        page.keyboard.press("Enter")
                        self.page.wait_for_timeout(500)
                        logger.info("조회 Enter 키 전송")

                    # 조회 후 로딩 대기 (최대 10초)
                    self.page.wait_for_timeout(2000)
                    for _w in range(16):
                        try:
                            loading = page.evaluate("""() => {
                                const els = document.querySelectorAll('*');
                                for (const el of els) {
                                    const t = el.textContent.trim();
                                    const r = el.getBoundingClientRect();
                                    if ((t.includes('조회하고 있습니다') || t.includes('잠시 기다려')) && r.height > 0) return true;
                                }
                                return false;
                            }""")
                            if loading:
                                self.page.wait_for_timeout(500)
                                continue
                            break
                        except Exception:
                            break
                    self.page.wait_for_timeout(1000)
                    # 조회 결과 없음 알림("세금계산서가 없습니다.") 처리
                    self._dismiss_obt_alert()
                    _save_debug(page, "invoice_modal_after_vendor_search")
                    logger.info("거래처 필터 조회 완료")

                    # 조회 후 그리드 행 수 재확인
                    try:
                        new_row_count_result = page.evaluate("""() => {
                            const gridEls = document.querySelectorAll('.OBTDataGrid_grid__22Vfl, .OBTDataGrid_root__mruAZ');
                            for (const gridEl of gridEls) {
                                let target = gridEl;
                                for (let p = 0; p < 6; p++) {
                                    if (!target) break;
                                    const fk = Object.keys(target).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                                    if (fk) {
                                        let node = target[fk];
                                        for (let d = 0; d < 20 && node; d++) {
                                            try {
                                                const iface = node?.stateNode?.state?.interface;
                                                if (iface && typeof iface.getRowCount === 'function') {
                                                    return { rowCount: iface.getRowCount() };
                                                }
                                            } catch(e) {}
                                            node = node.return;
                                        }
                                    }
                                    target = target.parentElement;
                                }
                            }
                            return { rowCount: 0 };
                        }""")
                        new_row_count = new_row_count_result.get("rowCount", 0) if new_row_count_result else 0
                        logger.info(f"거래처 필터 후 그리드 행 수: {new_row_count}")
                        if new_row_count == 0:
                            logger.warning(f"거래처 '{vendor}' 필터 결과 없음 → 전체 목록 재조회 필요")
                    except Exception as erc:
                        logger.warning(f"필터 후 행 수 확인 실패: {erc}")
                        new_row_count = 1  # 실패 시 클릭 시도

                    # 거래처 필터된 첫 번째 행 체크 (결과가 vendor만 남아있으므로 첫 행 = 정확한 행)
                    if new_row_count > 0 or new_row_count_result is None:
                        _vendor_row_idx = 0  # 필터 후 첫 행이 목표 행
                        # 체크박스 좌표 클릭 (필터 후) — 모달 내 그리드 우선
                        grid_box_filtered = page.evaluate("""() => {
                            let modal = null;
                            for (const el of document.querySelectorAll('[class*="OBTDialog"], [class*="obtdialog"], [class*="OBTPortal"]')) {
                                const r = el.getBoundingClientRect();
                                if (r.width > 0 && el.textContent.includes('계산서')) { modal = el; break; }
                            }
                            const scope = modal || document;
                            const grid = scope.querySelector('.OBTDataGrid_grid__22Vfl');
                            if (!grid) return null;
                            const r = grid.getBoundingClientRect();
                            return r.width > 0 ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
                        }""")
                        if grid_box_filtered and grid_box_filtered["w"] > 0:
                            cb_x = grid_box_filtered["x"] + 15
                            cb_y = grid_box_filtered["y"] + 35 + 14
                            page.mouse.click(cb_x, cb_y)
                            self.page.wait_for_timeout(500)
                            logger.info(
                                f"거래처 필터 후 체크박스 클릭: ({cb_x:.0f}, {cb_y:.0f}) "
                                f"→ vendor='{vendor}' 첫 행 선택"
                            )
                            selected = True
                            _save_debug(page, "invoice_modal_after_vendor_filter_click")
                else:
                    logger.info(f"거래처 input 미발견 → 좌표 클릭 폴백으로 진행")

            except Exception as e_vendor:
                logger.warning(f"상세검색 거래처 필터 실패: {e_vendor}")

        # ── 6-C. 좌표 클릭 폴백: vendor 행 인덱스 기반 y좌표 계산 후 클릭 ──
        # dataProvider가 vendor 행 인덱스를 반환한 경우 해당 y좌표로 이동, 아니면 첫 행 클릭
        # _vendor_row_idx == -1 인 경우: 거래처 미발견 → 6-C 스킵 (모달 취소로 이어짐)
        if not selected and _vendor_row_idx != -1:
            try:
                # OBTDataGrid_grid 영역의 좌표 기준으로 체크박스 클릭
                # 헤더 높이 ~35px, 행 높이 ~28px, 체크박스 x ~왼쪽 15px
                row_height = 28  # OBTDataGrid 기본 행 높이 (픽셀)
                header_height = 35  # 헤더 높이 (픽셀)
                target_row = getattr(locals().get('_vendor_row_idx', None), '__index__', None)
                # locals()는 closure에서 접근 불가 → 직접 변수 참조
                try:
                    target_row = _vendor_row_idx
                except NameError:
                    target_row = 0

                grid_box = page.evaluate("""() => {
                    // 모달 내 그리드 우선 (expense form 그리드와 구별)
                    let modal = null;
                    for (const el of document.querySelectorAll('[class*="OBTDialog"], [class*="obtdialog"], [class*="OBTPortal"]')) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && el.textContent.includes('계산서')) { modal = el; break; }
                    }
                    const scope = modal || document;
                    const grid = scope.querySelector('.OBTDataGrid_grid__22Vfl');
                    if (!grid) return null;
                    const r = grid.getBoundingClientRect();
                    if (r.width === 0) return null;
                    return { x: r.x, y: r.y, w: r.width, h: r.height };
                }""")

                if grid_box and grid_box["w"] > 0:
                    cb_x = grid_box["x"] + 15
                    # vendor 행 인덱스를 y좌표로 변환: header + 행인덱스 * 행높이 + 행높이/2
                    cb_y = grid_box["y"] + header_height + target_row * row_height + row_height // 2

                    # 화면 내 유효한 y좌표 범위 확인 (그리드 영역 내)
                    grid_bottom = grid_box["y"] + grid_box["h"]
                    if cb_y > grid_bottom - 5:
                        # 그리드 화면 밖 → JS로 그리드 스크롤 시도 후 재계산
                        try:
                            page.evaluate(f"""() => {{
                                const selectors = ['.OBTDataGrid_grid__22Vfl', '.OBTDataGrid_root__mruAZ'];
                                for (const sel of selectors) {{
                                    const el = document.querySelector(sel);
                                    if (el) {{
                                        // canvas 그리드 스크롤: 부모 컨테이너 시도
                                        const parent = el.parentElement;
                                        if (parent) parent.scrollTop = {target_row} * {row_height};
                                        el.scrollTop = {target_row} * {row_height};
                                        break;
                                    }}
                                }}
                            }}""")
                            self.page.wait_for_timeout(500)
                        except Exception:
                            pass
                        # 스크롤 후에도 화면 밖이면 첫 행으로 폴백
                        cb_y = grid_box["y"] + header_height + target_row * row_height + row_height // 2
                        if cb_y > grid_bottom - 5:
                            cb_y = grid_box["y"] + header_height + row_height // 2
                            logger.info(
                                f"vendor 행(idx={target_row})이 화면 밖 (스크롤 시도 후 폴백) → 첫 번째 보이는 행"
                            )
                        else:
                            logger.info(f"그리드 스크롤 후 vendor 행 y={cb_y:.0f}")
                    else:
                        logger.info(
                            f"vendor 행 인덱스 기반 좌표 클릭: row={target_row} → y={cb_y:.0f}"
                        )

                    page.mouse.click(cb_x, cb_y)
                    self.page.wait_for_timeout(500)
                    logger.info(f"체크박스 좌표 클릭: ({cb_x:.0f}, {cb_y:.0f})")
                    selected = True
                    _save_debug(page, "invoice_modal_after_checkbox_click")
                else:
                    logger.warning("그리드 영역을 찾지 못함")
            except Exception as e:
                logger.warning(f"체크박스 좌표 클릭 실패: {e}")

        if not selected:
            logger.warning("계산서 선택 실패 → 인보이스 모달 취소 버튼으로 닫기")
            # Escape 대신 모달 내 취소 버튼 직접 클릭:
            # Escape는 GW 확인 다이얼로그("취소하시겠습니까?")를 트리거하고,
            # 후속 코드가 그 다이얼로그의 "취소" 버튼을 클릭하여 모달이 닫히지 않는 버그 방지
            self._dismiss_obt_alert()
            try:
                # 인보이스 모달 스코프 내 취소 버튼 클릭 (모달 외 취소 버튼 오클릭 방지)
                _modal_sel = '.obtdialog.open, [class*="OBTDialog_dialogRoot"][class*="open"]'
                _modal_el = page.locator(_modal_sel)
                _modal_closed = False
                if _modal_el.count() > 0:
                    for _csel in ["button:has-text('취소')", "button:has-text('닫기')"]:
                        try:
                            _cbtn = _modal_el.locator(_csel).last
                            if _cbtn.is_visible(timeout=500):
                                _cbtn.click(force=True)
                                self.page.wait_for_timeout(800)
                                logger.info(f"인보이스 모달 취소 클릭: {_csel}")
                                _modal_closed = True
                                break
                        except Exception:
                            continue
                if not _modal_closed:
                    # 모달 내 취소 버튼 없음 → Escape 폴백 (확인 다이얼로그에서 "확인" 클릭)
                    page.keyboard.press("Escape")
                    self.page.wait_for_timeout(500)
                    # Escape 후 GW 확인 다이얼로그 → "확인"/"저장안함" 클릭 (취소 아님)
                    page.evaluate("""() => {
                        const portals = document.querySelectorAll('[class*="OBTPortal"]');
                        for (const portal of portals) {
                            const dimmed = portal.querySelector('[class*="OBTAlert_dimmed"]');
                            if (!dimmed) continue;
                            const btns = portal.querySelectorAll('button');
                            for (const t of ['저장안함', '확인', 'OK', '닫기']) {
                                for (const btn of btns) {
                                    if (btn.textContent.trim() === t) { btn.click(); return t; }
                                }
                            }
                        }
                        return null;
                    }""")
                    self.page.wait_for_timeout(500)
                # 모달 닫힘 확인 (최대 5초)
                for _ in range(10):
                    try:
                        if not page.locator("text=매입(세금)계산서 내역").first.is_visible(timeout=200):
                            logger.info("인보이스 모달 닫힘 확인")
                            break
                    except Exception:
                        break
                    self.page.wait_for_timeout(500)
                else:
                    logger.warning("인보이스 모달이 아직 열려있음 (닫기 실패)")
            except Exception as _me:
                logger.warning(f"인보이스 모달 닫기 오류: {_me}")
            return False

        self.page.wait_for_timeout(500)

        # ── 7. 확인 버튼 클릭 ──
        try:
            confirm_btn = page.locator("button:has-text('확인')").all()
            for btn in confirm_btn:
                try:
                    box = btn.bounding_box()
                    if box and box["y"] > 550:  # 모달 하단 확인 버튼
                        btn.click()
                        logger.info("계산서 모달 확인 클릭")
                        break
                except Exception:
                    continue
        except Exception:
            pass

        # 확인 클릭 후 OBTAlert 처리 (매칭된 없음 등)
        self.page.wait_for_timeout(1000)
        try:
            if page.locator('[class*="OBTAlert_dimmed"]').count() > 0:
                logger.info("확인 클릭 후 OBTAlert 감지 — dismiss")
                self._dismiss_obt_alert()
                self.page.wait_for_timeout(500)
        except Exception:
            pass

        # 모달이 아직 열려있는지 확인 → 열려있으면 취소 버튼으로 닫기
        try:
            still_open = page.locator("text=매입(세금)계산서 내역").first.is_visible(timeout=800)
            if still_open:
                logger.warning("확인 클릭 후에도 invoice modal 열려있음 — 취소로 닫기")
                for _close_sel in ["button:has-text('취소')", "button:has-text('닫기')"]:
                    try:
                        _b = page.locator(_close_sel).last
                        if _b.is_visible(timeout=300):
                            _b.click(force=True)
                            self.page.wait_for_timeout(500)
                            break
                    except Exception:
                        pass
                else:
                    page.keyboard.press("Escape")
                    self.page.wait_for_timeout(500)
                # modal 닫힘 후 OBTAlert 처리
                self._dismiss_obt_alert()
                self.page.wait_for_timeout(300)
        except Exception:
            pass

        # 그리드 반영 대기
        self.page.wait_for_timeout(2000)
        _save_debug(page, "03c3_after_invoice_applied")
        logger.info("계산서 모달 -> 그리드 반영 완료")
        return selected

    def _select_invoice_in_modal_legacy(
        self,
        vendor: str = "",
        amount: float = None,
        date_from: str = "",
        date_to: str = "",
    ) -> bool:
        """
        [레거시] 계산서내역 DOM 모달 — 이전 버전 (참고용, 사용하지 않음).

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

        # 기본 기간: ±12개월 (지연 발행 계산서 대응)
        today = _dt.date.today()
        if not date_from:
            start = (today.replace(day=1) - _dt.timedelta(days=365)).replace(day=1)
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
        # 모달 제목: "매입(세금)계산서 내역" — 괄호 호환 위해 복수 셀렉터 시도
        modal_selectors = [
            "text=매입(세금)계산서 내역",
            "text=/매입.*계산서.*내역/",
            "text=계산서 내역",
        ]
        for _ in range(40):  # 최대 10초
            for sel in modal_selectors:
                try:
                    title_el = page.locator(sel).first
                    if title_el.is_visible(timeout=100):
                        modal_visible = True
                        break
                except Exception:
                    pass
            if modal_visible:
                break
            self.page.wait_for_timeout(250)

        if not modal_visible:
            logger.warning("계산서 모달 미표시")
            _save_debug(page, "invoice_modal_not_found")
            return False

        logger.info("계산서 모달 표시 확인")

        # 모달 내부 렌더링 대기 (input 필드가 로드될 때까지)
        self.page.wait_for_timeout(3000)

        # 디버그: 모달 내 모든 input 필드 덤프 (여러 셀렉터 시도)
        try:
            modal_inputs = page.evaluate("""() => {
                // 여러 셀렉터로 모달 찾기
                const selectors = [
                    '.OBTDialog2_dialogRootOpen__3PExr',
                    '[data-orbit-component="OBTDialog"].open',
                    '.obtdialog.open',
                    '.OBTDialog2_dialogRoot__3rMeW',
                ];
                let modal = null;
                let usedSel = '';
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        if (el.offsetParent !== null && el.getBoundingClientRect().height > 100) {
                            modal = el;
                            usedSel = sel;
                            break;
                        }
                    }
                    if (modal) break;
                }
                if (!modal) {
                    // 제목 텍스트 기준으로 찾기
                    const titles = document.querySelectorAll('*');
                    for (const t of titles) {
                        if (t.textContent.includes('계산서 내역') && t.getBoundingClientRect().height > 0) {
                            modal = t.closest('[data-orbit-component], .obtdialog, [class*="dialog"], [class*="Dialog"]');
                            if (modal) { usedSel = 'title-ancestor'; break; }
                        }
                    }
                }
                if (!modal) return { error: 'no_modal_found', selectors_tried: selectors.length };
                const inputs = modal.querySelectorAll('input');
                return {
                    selector: usedSel,
                    modalClass: modal.className?.substring(0, 80),
                    inputs: Array.from(inputs).map((inp, i) => ({
                        idx: i, type: inp.type, value: (inp.value || '').substring(0, 40),
                        placeholder: inp.placeholder || '', name: inp.name || '',
                        x: Math.round(inp.getBoundingClientRect().x),
                        y: Math.round(inp.getBoundingClientRect().y),
                        w: Math.round(inp.getBoundingClientRect().width),
                    }))
                };
            }""")
            logger.info(f"모달 input 덤프: {modal_inputs}")
        except Exception as e:
            logger.warning(f"모달 input 덤프 실패: {e}")

        # 참고: 상세검색 CSS 펼침은 날짜 변경 이후에 실행 (step 3)
        # (사전 펼침 시 DOM 재렌더링으로 날짜 input이 사라지는 문제 방지)

        # ── 모달 내 날짜 설정 ──
        try:
            date_result = page.evaluate(f"""() => {{
                // 모달 컨테이너 찾기
                let modal = null;
                const allEls = document.querySelectorAll('*');
                for (const el of allEls) {{
                    if (el.textContent.includes('계산서 내역') && el.children.length < 5) {{
                        modal = el.closest('[class*="dialog"], [class*="Dialog"], [data-orbit-component]');
                        if (modal) break;
                    }}
                }}
                if (!modal) modal = document;

                const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                const inputs = modal.querySelectorAll('input[type="text"]');
                const dateInputs = [];
                for (const inp of inputs) {{
                    const val = inp.value || '';
                    // 날짜 형식: YYYY-MM-DD (10자, - 포함)
                    if (/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(val)) {{
                        dateInputs.push(inp);
                    }}
                }}
                if (dateInputs.length >= 2) {{
                    // 시작일
                    nativeSetter.call(dateInputs[0], '{date_from}');
                    dateInputs[0].dispatchEvent(new Event('input', {{bubbles: true}}));
                    dateInputs[0].dispatchEvent(new Event('change', {{bubbles: true}}));
                    // 종료일
                    nativeSetter.call(dateInputs[1], '{date_to}');
                    dateInputs[1].dispatchEvent(new Event('input', {{bubbles: true}}));
                    dateInputs[1].dispatchEvent(new Event('change', {{bubbles: true}}));
                    return {{ set: true, count: dateInputs.length, from: '{date_from}', to: '{date_to}' }};
                }}
                return {{ set: false, count: dateInputs.length }};
            }}""")
            logger.info(f"모달 날짜 설정: {date_result}")
        except Exception as e:
            logger.warning(f"모달 날짜 설정 실패: {e}")

        # ── 상세검색 영역 강제 펼치기 (CSS overflow/height 제거) ──
        try:
            expanded = page.evaluate("""() => {
                // 방법 1: "상세검색열기" 또는 "상세검색닫기" 텍스트 클릭
                const els = document.querySelectorAll('span, a, button, div');
                for (const el of els) {
                    const text = el.textContent.trim();
                    if (text === '상세검색열기' || text === '상세검색 열기') {
                        el.click();
                        return 'clicked_open';
                    }
                }
                // 방법 2: 숨겨진 상세검색 영역을 CSS로 강제 표시
                // y좌표가 음수인 input의 부모 컨테이너들의 height/overflow를 변경
                const allInputs = document.querySelectorAll('input[type="text"]');
                let fixed = 0;
                for (const inp of allInputs) {
                    const r = inp.getBoundingClientRect();
                    if (r.y < 0 && r.width > 50) {
                        let parent = inp.parentElement;
                        for (let i = 0; i < 10 && parent; i++) {
                            const style = window.getComputedStyle(parent);
                            if (style.overflow === 'hidden' || style.maxHeight === '0px' || style.height === '0px') {
                                parent.style.overflow = 'visible';
                                parent.style.maxHeight = 'none';
                                parent.style.height = 'auto';
                                fixed++;
                            }
                            parent = parent.parentElement;
                        }
                    }
                }
                return fixed > 0 ? 'css_fixed_' + fixed : 'no_hidden_found';
            }""")
            logger.info(f"계산서 모달 상세검색 펼침: {expanded}")
            self.page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"상세검색 펼침 실패: {e}")

        # ── 거래처명 입력 (페이지 전체 input 스캔 + keyboard.type) ──
        if vendor:
            try:
                vendor_filled = False
                # 모달 타이틀 기준으로 모달 컨테이너를 찾고, 그 안에서 거래처 input 탐색
                focus_result = page.evaluate("""() => {
                    // 모달 컨테이너 찾기 (타이틀 텍스트 기준)
                    let modal = null;
                    const allEls = document.querySelectorAll('*');
                    for (const el of allEls) {
                        if (el.textContent.includes('계산서 내역') && el.children.length < 5) {
                            modal = el.closest('[class*="dialog"], [class*="Dialog"], [data-orbit-component]');
                            if (modal) break;
                        }
                    }
                    if (!modal) modal = document;

                    const inputs = modal.querySelectorAll('input[type="text"]');
                    // 거래처 input 찾기: placeholder='사업장코드도움'이 아닌, 날짜가 아닌, 빈 input
                    for (const inp of inputs) {
                        const val = inp.value || '';
                        const ph = inp.placeholder || '';
                        // 제외: 사업장, 날짜, 암호화 토큰, 숨겨진(width 0)
                        if (ph.includes('사업장')) continue;
                        if (val.includes('-') && val.length >= 8) continue;
                        if (val.includes('글로우') || val.includes('1000')) continue;
                        if (val.length > 20) continue;  // 토큰 제외
                        const r = inp.getBoundingClientRect();
                        if (r.width < 50) continue;
                        // 빈 input이면 거래처 후보
                        if (val === '' || val.length < 3) {
                            // 스크롤하여 visible 만들기
                            inp.scrollIntoView({ behavior: 'instant', block: 'center' });
                            const r2 = inp.getBoundingClientRect();
                            inp.focus();
                            inp.click();
                            return { x: r2.x + r2.width / 2, y: r2.y + r2.height / 2, found: true };
                        }
                    }
                    return null;
                }""")
                if focus_result:
                    # focus()가 이미 됐으므로 마우스 클릭 없이 keyboard.type으로 직접 입력
                    self.page.wait_for_timeout(300)
                    page.keyboard.type(vendor, delay=50)
                    page.keyboard.press("Tab")
                    self.page.wait_for_timeout(500)
                    logger.info(f"모달 거래처명 입력 (keyboard.type after focus): '{vendor}'")
                    vendor_filled = True
                    _save_debug(page, "invoice_modal_after_vendor_input")
                else:
                    logger.warning("거래처 input을 찾지 못함 — 전체 검색 실패")
            except Exception as e:
                logger.warning(f"모달 거래처명 입력 실패: {e}")

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
            # OBTAlert("세금계산서가 없습니다.") 먼저 닫기
            self._dismiss_obt_alert()
            # 모달 취소 (선택 없이 닫기)
            try:
                cancel_loc = page.locator("button:has-text('취소')")
                if cancel_loc.count() > 0:
                    cancel_loc.last.dispatch_event("click")
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

