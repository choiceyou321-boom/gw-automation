"""
전자결재 자동화 -- 지출결의서 mixin
"""
from __future__ import annotations

import logging
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from src.gw.approval.base import (
    GW_URL, MAX_RETRIES, RETRY_DELAY, SCREENSHOT_DIR,
    _GET_GRID_IFACE_JS, _save_debug, _parse_project_text, _js_str,
    _find_first_visible,
)
from src.gw.approval.form_templates import resolve_approval_line, resolve_cc_recipients

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

                # 결재상신 버튼 찾기 — 4개 셀렉터 후보를 헬퍼로 통합 polling
                submit_btn = _find_first_visible(self.page, [
                    "div.topBtn:has-text('결재상신')",
                    "button:has-text('결재상신')",
                    "[class*='topBtn']:has-text('결재상신')",
                    "text=결재상신",
                ], total_budget_ms=2000)
                if submit_btn:
                    logger.info("결재상신 버튼 발견")
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
        """지출결의서 필드 채우기 — expense_fields.fill_expense_fields 로 위임 (Phase D)."""
        from src.gw.approval.expense_fields import fill_expense_fields
        return fill_expense_fields(
            self.page,
            self._dismiss_obt_alert,
            self._fill_project_code,
            self._fill_field_by_label,
            self._check_field_has_value,
            self._close_open_modals,
            self._click_evidence_type_button,
            self._select_invoice_in_modal,
            self._fill_grid_items,
            self._fill_receipt_date,
            self._fill_project_code_bottom,
            self._link_reference_document,
            self._upload_attachment,
            self._capture_and_attach_budget_screenshot,
            data,
        )

    def _fill_project_code(self, project: str, y_hint: float = None):
        """프로젝트 코드도움 모달 — `src.gw.approval.project_picker`로 위임."""
        from src.gw.approval.project_picker import fill_project_code
        return fill_project_code(
            self.page, self._dismiss_obt_alert, self._close_open_modals,
            project=project, y_hint=y_hint,
        )

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
        """매입(세금)계산서 모달 — `src.gw.approval.invoice_modal`로 위임."""
        from src.gw.approval.invoice_modal import select_invoice_in_modal
        return select_invoice_in_modal(
            self.page, self._dismiss_obt_alert,
            vendor=vendor, amount=amount, date_from=date_from, date_to=date_to,
        )

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

        _save_debug(page, "error_expense_date_selector_exhausted")
        logger.error(
            "증빙일자 입력 실패: 모든 셀렉터(JS focus+click, th[증빙일자]+td input)가 실패했습니다. "
            "DOM 구조 변경 가능성 — 스크린샷 확인."
        )
        return False

    def _upload_attachment(self, file_path: str) -> bool:
        """첨부파일 업로드 — `src.gw.approval.attachment.upload_attachment`로 위임."""
        from src.gw.approval.attachment import upload_attachment
        return upload_attachment(self.page, file_path)

    # ─────────────────────────────────────────
    # 예실대비현황 스크린샷 캡처
    # ─────────────────────────────────────────

    def capture_budget_status_screenshot(self, output_path: str = None, detail_view: bool = True) -> str | None:
        """예실대비현황(상세) 스크린샷 — `src.gw.approval.budget_capture`로 위임."""
        from src.gw.approval.budget_capture import capture_budget_status_screenshot
        return capture_budget_status_screenshot(self.page, output_path, detail_view)

    def _click_budget_detail_view(self) -> bool:
        """예실대비현황 "상세" 뷰 클릭 — `src.gw.approval.budget_capture`로 위임."""
        from src.gw.approval.budget_capture import click_budget_detail_view
        return click_budget_detail_view(self.page)

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

