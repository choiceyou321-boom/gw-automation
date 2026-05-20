"""
전자결재 자동화 — 선급금 요청서/정산서 mixin

분할 출처: other_forms.py (세션 LII)
콜백 주입 패턴: self.<method> 의존성을 Callable 인자로 전달하지 않고,
mixin 내부 self 호출로 유지 (선급금 로직이 self 메서드를 광범위하게 사용하여
콜백 분리 시 인자 수가 20개 이상이 되어 가독성을 해침).
따라서 함수 추출 대신 mixin 클래스로 분리한다.

포함 메서드:
- _click_advance_payment_form       : 양식 선택 (요청서/정산서)
- _inspect_form_labels              : DOM 진단 (GW_DEBUG_DOM)
- _handle_bank_picker               : 금융기관코드도움 picker
- _fill_field_by_label_candidates   : 후보 라벨 폴백 입력
- _fill_advance_payment_fields      : 필드 채우기 (요청서/정산서)
- _fill_advance_grid_mandatory_fields : 그리드 필수 필드 (용도/예산/지급일)
- _save_advance_payment_draft       : 임시보관
- create_advance_payment_request    : 선급금 요청서 작성
- create_advance_payment_settlement : 선급금 정산서 작성
"""

import os
import logging
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from src.approval.base import (
    MAX_RETRIES, RETRY_DELAY,
    _GET_GRID_IFACE_JS, _save_debug, _js_str,
)
from src.approval.form_templates import resolve_approval_line, resolve_cc_recipients

logger = logging.getLogger("approval_automation")


class AdvancePaymentMixin:
    """선급금 요청서/정산서 전자결재 mixin"""

    # ──────────────────────────────────────────
    # 양식 진입
    # ──────────────────────────────────────────

    def _click_advance_payment_form(self, form_type: str = "요청서"):
        """
        선급금 요청서/정산서 양식 선택 (인라인 폼).

        formId=181 URL 직접 접근 시도 (요청서), 실패 시 검색 폴백.
        정산서는 formId 미확인이므로 검색으로만 진입.

        Args:
            form_type: "요청서" 또는 "정산서"
        """
        page = self.page

        # ⚠️ formId=181 URL 직접 접근 비활성화:
        # tgjeon 계정에서 "권한 없는 메뉴" 팝업 → GW 메인으로 리다이렉트됨.
        # 결재작성 → 양식 검색 경로로만 접근한다.

        # 검색 키워드 설정
        if form_type == "요청서":
            keywords = ["[본사]선급금 요청서", "선급금 요청서", "선급금"]
        else:
            keywords = ["[본사]선급금 정산서", "선급금 정산서", "선급금정산"]

        def _try_click_form(phase: str) -> bool:
            for keyword in keywords:
                try:
                    links = page.locator(f"text={keyword}").all()
                    for link in links:
                        if link.is_visible():
                            link.click(force=True)
                            logger.info(f"선급금 {form_type} 양식 클릭 ({phase}): '{keyword}'")
                            try:
                                page.wait_for_url("**/APB1020/**", timeout=8000)
                                logger.info(f"양식 페이지 이동 확인: {page.url[:100]}")
                                return True
                            except Exception:
                                logger.warning(f"양식 클릭 후 URL 미변경 (여전히 {page.url[:80]})")
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

        # 2차: 전자결재 모듈 재진입 후 결재작성
        logger.info(f"현재 페이지에 선급금 {form_type} 양식 없음 -> 결재작성 클릭")
        # URL 직접 이동 실패 후 GW 메인으로 돌아온 경우 → EA 모듈 재진입
        if "APB1020" not in page.url and "EA" not in page.url:
            logger.info("전자결재 모듈 재진입...")
            self._navigate_to_approval_home()
            page.wait_for_timeout(1000)
        self._click_write_approval()
        page.wait_for_timeout(1500)

        if _try_click_form("결재작성 경유"):
            return

        # 3차: 양식 검색 input에 키워드 입력 후 검색
        logger.info("양식 검색 input에 '선급금' 입력 시도...")
        search_input = page.locator(
            "input[placeholder*='양식'], input[placeholder*='검색'], "
            "input[class*='search'], input[type='search']"
        ).first
        try:
            if search_input.is_visible(timeout=2000):
                search_input.fill("선급금")
                page.keyboard.press("Enter")
                page.wait_for_timeout(2000)
                logger.info("양식 검색 완료, 결과에서 양식 찾기 시도...")
                _save_debug(page, f"advance_payment_search_result")
                if _try_click_form("양식 검색 후"):
                    return
        except Exception as e:
            logger.warning(f"양식 검색 input 사용 실패: {e}")

        _save_debug(page, f"error_advance_payment_{form_type}_not_found")
        raise Exception(f"선급금 {form_type} 양식을 찾을 수 없습니다.")

    # ──────────────────────────────────────────
    # 진단 도구
    # ──────────────────────────────────────────

    def _inspect_form_labels(self, page):
        """
        폼의 모든 <th> 라벨 텍스트를 수집하여 로깅하는 진단 도구.

        GW_DEBUG_DOM=1 환경변수 설정 시 _fill_advance_payment_fields() 시작 부분에서 호출.
        실제 GW DOM에서 필드 라벨명을 확인할 때 사용한다.
        """
        try:
            th_elements = page.locator("th").all()
            labels = []
            for th in th_elements:
                try:
                    text = th.inner_text(timeout=1000).strip()
                    if text:
                        labels.append(text)
                except Exception:
                    continue
            logger.info(f"[DOM 검사] 폼 th 라벨 {len(labels)}개: {labels}")
            return labels
        except Exception as e:
            logger.warning(f"[DOM 검사] th 라벨 수집 실패: {e}")
            return []

    # ──────────────────────────────────────────
    # 금융기관 picker
    # ──────────────────────────────────────────

    def _handle_bank_picker(self, bank_name: str) -> bool:
        """
        금융기관코드도움 picker로 은행 선택.

        placeholder="금융기관코드도움" input 클릭 → OBTDialog2 팝업 → 검색 → 선택.
        expense.py 프로젝트 코드도움 picker 패턴 재사용.

        Args:
            bank_name: 은행 키워드 (예: "국민", "신한", "우리")
        Returns:
            선택 성공 여부
        """
        page = self.page
        _picker_sel = ".OBTDialog2_dialogRootOpen__3PExr"

        try:
            inp = page.locator("input[placeholder='금융기관코드도움']").first
            if not inp.is_visible(timeout=3000):
                logger.warning("금융기관코드도움 input 미발견")
                return False

            # 기존값 초기화 + 클릭
            inp.click(click_count=3, force=True)
            page.wait_for_timeout(300)
            inp.type(bank_name, delay=50)
            page.wait_for_timeout(1000)

            # OBTDialog2 피커 열림 확인
            picker_opened = page.locator(_picker_sel).count() > 0
            if not picker_opened:
                # 피커 미열림 → Enter로 트리거 시도
                page.keyboard.press("Enter")
                page.wait_for_timeout(1000)
                picker_opened = page.locator(_picker_sel).count() > 0

            if not picker_opened:
                logger.warning("금융기관 코드도움 피커가 열리지 않음 — 텍스트 입력으로 폴백")
                return False

            logger.info("금융기관 코드도움 피커 열림 → 검색/선택 시도")

            # 피커 내 검색 버튼 클릭 또는 Enter
            search_btn_found = False
            for sbsel in [
                f"{_picker_sel} button[class*='searchButton']",
                f"{_picker_sel} button:has(img[src*='search'])",
            ]:
                try:
                    sb = page.locator(sbsel).first
                    if sb.is_visible(timeout=500):
                        sb.click()
                        search_btn_found = True
                        break
                except Exception:
                    continue
            if not search_btn_found:
                page.keyboard.press("Enter")

            # 그리드 출현 대기 (최대 5초)
            for _ in range(10):
                grid_cnt = page.locator(f"{_picker_sel} .OBTDataGrid_grid__22Vfl").count()
                canvas_cnt = page.locator(f"{_picker_sel} canvas").count()
                if grid_cnt > 0 or canvas_cnt > 0:
                    break
                page.wait_for_timeout(500)

            page.wait_for_timeout(500)

            # React Fiber API로 첫 행 선택
            selected = False
            if page.locator(f"{_picker_sel} .OBTDataGrid_grid__22Vfl").count() > 0:
                result = page.evaluate("""(pickerSel) => {
                    const picker = document.querySelector(pickerSel);
                    if (!picker) return { success: false, reason: 'no_picker' };
                    const grid = picker.querySelector('.OBTDataGrid_grid__22Vfl');
                    if (!grid) return { success: false, reason: 'no_grid' };
                    const fk = Object.keys(grid).find(k =>
                        k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                    );
                    if (!fk) return { success: false, reason: 'no_fiber' };
                    let f = grid[fk];
                    for (let i = 0; i < 3 && f; i++) f = f.return;
                    const iface = f && f.stateNode && f.stateNode.state && f.stateNode.state.interface;
                    if (!iface || typeof iface.getRowCount !== 'function')
                        return { success: false, reason: 'no_iface' };
                    const rowCount = iface.getRowCount();
                    if (rowCount === 0) return { success: false, reason: 'empty_grid' };
                    iface.setSelection({ rowIndex: 0, columnIndex: 0 });
                    iface.focus({ rowIndex: 0, columnIndex: 0 });
                    return { success: true, rowCount: rowCount };
                }""", _picker_sel)
                logger.info(f"금융기관 피커 React Fiber 결과: {result}")
                if result and result.get("success"):
                    selected = True

            if not selected:
                # 폴백: canvas 더블클릭 (첫 행 y=36)
                canvas = page.locator(f"{_picker_sel} canvas").first
                if canvas.is_visible(timeout=1000):
                    canvas.dblclick(position={"x": 100, "y": 36})
                    selected = True
                    logger.info("금융기관 피커 canvas 더블클릭 폴백")

            if selected:
                page.wait_for_timeout(300)
                # 확인 버튼 클릭
                for btn_sel in [
                    f"{_picker_sel} button:has-text('확인')",
                    f"{_picker_sel} [class*='confirmButton']",
                ]:
                    try:
                        btn = page.locator(btn_sel).first
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            logger.info("금융기관 피커 확인 버튼 클릭")
                            break
                    except Exception:
                        continue
                page.wait_for_timeout(500)

            # 피커 닫기 확인 (남아있으면 취소)
            if page.locator(_picker_sel).count() > 0:
                try:
                    cancel = page.locator(f"{_picker_sel} button:has-text('취소')").first
                    if cancel.is_visible(timeout=500):
                        cancel.click()
                except Exception:
                    pass

            logger.info(f"금융기관 코드도움 피커 처리 완료: selected={selected}")
            return selected

        except Exception as e:
            logger.warning(f"금융기관 코드도움 피커 처리 실패: {e}")
            # 예외 발생 시 열려있는 피커 정리
            try:
                if page.locator(_picker_sel).count() > 0:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
            except Exception:
                pass
            return False

    # ──────────────────────────────────────────
    # 폴백 필드 입력
    # ──────────────────────────────────────────

    def _fill_field_by_label_candidates(self, candidates: list[str], value: str) -> bool:
        """
        여러 후보 라벨을 순차 시도하여 필드를 채우는 폴백 메서드.

        _fill_field_by_label()을 후보별로 호출하며 첫 성공 시 True 반환.

        Args:
            candidates: 라벨 후보 리스트 (예: ["요청사유", "사유", "지급사유"])
            value: 입력할 값
        Returns:
            성공 여부
        """
        for label in candidates:
            if self._fill_field_by_label(label, value):
                return True
        logger.warning(f"폴백 라벨 모두 실패: {candidates}")
        return False

    # ──────────────────────────────────────────
    # 필드 채우기
    # ──────────────────────────────────────────

    def _fill_advance_payment_fields(self, data: dict, form_type: str = "요청서"):
        """
        선급금 요청서/정산서 필드 채우기.

        지출결의서와 동일한 인라인 폼 구조 (APB1020 화면).
        요청서 필드: 제목, 프로젝트, 요청사유, 은행명, 계좌번호, 예금주, 금액 (그리드)
        정산서 필드: 제목, 프로젝트, 정산내역, 선급금액, 사용금액, 반환금액

        GW 검증 상태:
        - formId=181 (요청서) 확인 완료 (Phase 0)
        - 인라인 폼 구조 (APB1020) 확인 완료
        - 개별 필드 라벨("요청사유", "은행명" 등)은 지출결의서와 유사한 구조로 추정
          → GW 실제 DOM에서 th 라벨명 최종 확인 필요
        - 정산서 formId 미확인 → 검색 방식으로만 진입

        Args:
            data: 양식 데이터 딕셔너리
            form_type: "요청서" 또는 "정산서"
        """
        page = self.page

        # DOM 검사: GW_DEBUG_DOM 환경변수 설정 시에만 실행
        if os.environ.get("GW_DEBUG_DOM"):
            self._inspect_form_labels(page)

        title = data.get("title", "")
        project = data.get("project", "")

        # 1. 프로젝트 코드도움 입력 (상단)
        # 지출결의서와 동일한 placeholder="프로젝트코드도움" 사용
        if project:
            self._fill_project_code(project, y_hint=292)
            _save_debug(page, "adv_03a_after_project_top")

            # 프로젝트 입력 후 페이지 이탈 검증
            self.page.wait_for_timeout(300)
            current_url = page.url
            if "/HP/" not in current_url:
                logger.warning(f"프로젝트 입력 후 페이지 이탈 감지: {current_url}")
                _save_debug(page, "adv_03a_page_escaped")

        # 2. 제목 입력
        if title:
            self._fill_field_by_label("제목", title)
        _save_debug(page, "adv_03_after_title")

        # 3. 양식별 텍스트 필드 채우기
        # 폴백 라벨: 실제 GW DOM 라벨이 다를 수 있으므로 후보 리스트로 시도
        if form_type == "요청서":
            # 요청서 필드 맵: (라벨 후보 리스트, data 키)
            # GW DOM 검증 완료 (2026-04-09):
            #   - 요청사유 전용 필드 없음 → "비고" 라벨이 실제 존재 (지출결의서 공유 폼)
            #   - 은행명 단독 라벨 없음 → "은행/계좌번호" 통합 라벨로 노출 (placeholder: 금융기관코드도움)
            #   - 계좌번호는 "은행/계좌번호" td 내 별도 input (placeholder: 거래처계좌번호)
            #   - 예금주 라벨 확인됨 (정확히 일치), 예금주실명 별도 필드 추가 존재
            field_map_candidates = [
                (["비고", "요청사유", "사유", "지급사유"], "purpose"),
                (["은행/계좌번호", "은행명", "금융기관", "지급은행"], "bank_name"),
                (["거래처계좌번호", "계좌번호", "계좌", "입금계좌번호"], "account_number"),
                (["예금주", "예금주명", "수취인"], "account_holder"),
            ]
        else:
            # 정산서 필드 맵 (단일 라벨 — 추후 폴백 추가 가능)
            field_map_candidates = [
                (["정산내역"], "description"),
                (["선급금액"], "original_amount"),
                (["사용금액"], "used_amount"),
                (["반환금액"], "return_amount"),
            ]

        for candidates, key in field_map_candidates:
            val = data.get(key)
            if val is not None and str(val).strip():
                if key == "bank_name":
                    # 은행명: 코드도움 picker 처리 (placeholder="금융기관코드도움")
                    if not self._handle_bank_picker(str(val)):
                        # 피커 실패 시 텍스트 입력 폴백
                        logger.warning("은행 picker 실패 → 텍스트 입력 폴백")
                        self._fill_field_by_label_candidates(candidates, str(val))
                elif key == "account_number":
                    # 계좌번호: placeholder 기반 직접 입력 우선
                    if not self._fill_field_by_placeholder("거래처계좌번호", str(val)):
                        self._fill_field_by_label_candidates(candidates, str(val))
                else:
                    self._fill_field_by_label_candidates(candidates, str(val))

        # 4. 금액 그리드 입력 (요청서: 금액 항목을 그리드에 입력)
        # 지출결의서와 동일한 OBTDataGrid 그리드 구조 사용
        if form_type == "요청서":
            amount = data.get("amount")
            vendor_name = data.get("vendor_name", "")
            if amount is not None:
                items = [{
                    "item": data.get("purpose", "선급금"),
                    "amount": amount,
                    "vendor": vendor_name,
                }]
                self._fill_grid_items(items)
                _save_debug(page, "adv_03b_after_grid")

        # ── 8~11. 그리드 필수 필드 자동 입력 (expense.py step 10/10-A/10-1 패턴 이식) ──
        # GW 서버 검증 필수: 용도코드 · 예산과목 · 지급요청일
        # 세션 XLVI 발견: 이 필드들이 비면 "검증결과가 부적합인 지출내역이 존재합니다" 반환
        if form_type == "요청서":
            self._fill_advance_grid_mandatory_fields(data)

        # 5. 지급요청일 / 증빙일자 입력 (하단 날짜피커 — 그리드 내 지급요청일과 별개)
        payment_date = data.get("payment_date", "") or data.get("receipt_date", "") or data.get("date", "")
        if payment_date:
            self._fill_receipt_date(payment_date)
            _save_debug(page, "adv_03d_after_date")

        # 6. 하단 프로젝트 코드도움 입력
        if project:
            self._fill_project_code_bottom(project)
            _save_debug(page, "adv_03d2_after_project_bottom")

        # 7. 첨부파일 업로드
        attachment_path = data.get("attachment_path", "")
        if attachment_path:
            self._upload_attachment(attachment_path)
            _save_debug(page, "adv_03e_after_attachment")

        logger.info(f"선급금 {form_type} 필드 채우기 완료")

    # ──────────────────────────────────────────
    # 그리드 필수 필드 (용도코드/예산과목/지급요청일)
    # ──────────────────────────────────────────

    def _fill_advance_grid_mandatory_fields(self, data: dict):
        """
        선급금 요청서 지출내역 그리드의 GW 서버 검증 필수 필드 입력.

        expense.py step 10(용도코드) → 10-A(예산과목 자동팝업) → 10-1(지급요청일) 패턴 이식.
        _fill_grid_items()로 기본 항목(내용/금액/거래처) 입력 후 호출.

        필수 필드:
        - 용도코드 (usage_code): OBTDataGrid 용도 셀 keyboard.type + Enter
        - 예산과목 (budget_keyword): 용도코드 Enter 후 자동 팝업 처리
        - 지급요청일 (payment_date): 그리드 날짜 셀 직접 입력

        Args:
            data: {
                "usage_code": "8020",         # 용도코드 (예: 8020=재료비)
                "budget_keyword": "공사",     # 예산과목 검색 키워드
                "project": "GS",              # 프로젝트 (예산팝업용)
                "payment_date": "2026-04-30", # 지급요청일
            }
        """
        page = self.page
        usage_code = data.get("usage_code", "")
        budget_keyword = data.get("budget_keyword", "")
        project = data.get("project", "")
        payment_date = data.get("payment_date", "") or data.get("payment_request_date", "")

        if not usage_code and not payment_date:
            logger.info("선급금 그리드 필수 필드: usage_code/payment_date 모두 미지정 — 건너뜀")
            return

        # ── Step 8: 용도코드 입력 (OBTDataGrid canvas 셀 keyboard.type + Enter) ──
        if usage_code:
            try:
                grid_info = page.evaluate(f"""() => {{
                    const iface = {_GET_GRID_IFACE_JS};
                    if (!iface || typeof iface.getRowCount !== 'function') return null;
                    const rowCount = iface.getRowCount();
                    const cols = iface.getColumns().map(c => ({{name: c.name, header: c.header || ''}}));
                    return {{rowCount, cols}};
                }}""")

                if grid_info:
                    row_count = grid_info["rowCount"]
                    cols = grid_info["cols"]
                    logger.info(f"[선급금 그리드] 행 수: {row_count}, 컬럼: {[c['header'] for c in cols[:10]]}")

                    # 그리드 행 렌더링 대기 (최대 3초)
                    if row_count == 0:
                        logger.warning("[선급금 그리드] 행 없음 — 렌더링 대기 (최대 3초)")
                        for _w in range(6):
                            page.wait_for_timeout(500)
                            row_count = page.evaluate(f"""() => {{
                                const iface = {_GET_GRID_IFACE_JS};
                                return (iface && typeof iface.getRowCount === 'function') ? iface.getRowCount() : 0;
                            }}""")
                            if row_count > 0:
                                logger.info(f"[선급금 그리드] 대기 후 행 확인: {row_count}행 ({(_w+1)*0.5:.1f}초)")
                                break

                    # 용도 컬럼 찾기
                    usage_col = None
                    for c in cols:
                        h = str(c.get("header", ""))
                        if isinstance(h, dict):
                            h = h.get("text", "")
                        if "용도" in h or "usage" in c.get("name", "").lower():
                            usage_col = c
                            break

                    if usage_col and row_count > 0:
                        # 용도 컬럼 인덱스 계산 (canvas 좌표 산출용)
                        usage_col_idx = next(
                            (i for i, c in enumerate(cols)
                             if c.get("name") == usage_col["name"]),
                            0
                        )

                        filled_count = 0
                        for row_idx in range(row_count):
                            try:
                                # 1단계: setSelection + focus (셀 선택)
                                page.evaluate(f"""() => {{
                                    const iface = {_GET_GRID_IFACE_JS};
                                    if (!iface) return;
                                    iface.setSelection({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }});
                                    if (typeof iface.focus === 'function') {{
                                        try {{ iface.focus({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }}); }} catch(e) {{
                                            try {{ iface.focus(); }} catch(e2) {{}}
                                        }}
                                    }}
                                }}""")
                                page.wait_for_timeout(400)

                                # 2단계: activeElement가 그리드 셀 에디터인지 확인
                                # OBTDataGrid 셀 에디터는 className에 'OBTDataGrid' 포함
                                # cls가 비면 다른 input에 포커스된 것 → canvas dblclick 필요
                                _active_info = page.evaluate("""() => {
                                    const el = document.activeElement;
                                    if (!el) return {tag: 'none', cls: '', inGrid: false};
                                    const inGrid = !!el.closest('.OBTDataGrid_grid__22Vfl');
                                    return {tag: el.tagName, cls: (el.className || '').slice(0, 80), inGrid: inGrid};
                                }""")
                                _active_tag = _active_info.get("tag", "none")
                                _active_cls = _active_info.get("cls", "")
                                _in_grid = _active_info.get("inGrid", False)
                                logger.info(f"[선급금 그리드] focus 후 activeElement: {_active_tag} cls={_active_cls} inGrid={_in_grid}")

                                # 셀 에디터가 아닌 경우 (INPUT이지만 grid 밖 or INPUT이 아님)
                                if _active_tag != "INPUT" or not _in_grid:
                                    # canvas dblclick으로 셀 에디터 강제 활성화
                                    # 용도 컬럼은 체크박스(~30px) 다음 첫 번째 데이터 컬럼
                                    # 행 높이: 헤더 ~24px + (row_idx * ~24px) + 12px(행 중앙)
                                    _cv = page.locator(".OBTDataGrid_grid__22Vfl canvas").first
                                    _cv_box = _cv.bounding_box()
                                    if _cv_box:
                                        _cell_x = 30 + (usage_col_idx * 60) + 30  # 체크박스 + 컬럼 오프셋
                                        _cell_y = 24 + (row_idx * 24) + 12  # 헤더 + 행 오프셋
                                        logger.info(f"[선급금 그리드] canvas dblclick 시도: ({_cell_x}, {_cell_y})")
                                        _cv.dblclick(position={"x": _cell_x, "y": _cell_y})
                                        page.wait_for_timeout(500)

                                        # dblclick 후 activeElement 재확인
                                        _active_tag2 = page.evaluate("() => document.activeElement ? document.activeElement.tagName : 'none'")
                                        _active_cls2 = page.evaluate("() => document.activeElement ? document.activeElement.className.slice(0,60) : ''")
                                        logger.info(f"[선급금 그리드] dblclick 후 activeElement: {_active_tag2} cls={_active_cls2}")

                                        # 여전히 INPUT이 아니면 single click 폴백 (다른 위치)
                                        if _active_tag2 != "INPUT":
                                            _cv.click(position={"x": 52, "y": 36})
                                            page.wait_for_timeout(400)
                                            _active_tag3 = page.evaluate("() => document.activeElement ? document.activeElement.tagName : 'none'")
                                            logger.info(f"[선급금 그리드] click 폴백 후 activeElement: {_active_tag3}")

                                # 3단계: 기존값 클리어
                                page.keyboard.press("Control+A")
                                page.wait_for_timeout(100)
                                page.keyboard.press("Delete")
                                page.wait_for_timeout(200)

                                # 4단계: 용도코드 타이핑 + Enter (자동완성 트리거)
                                page.keyboard.type(str(usage_code), delay=50)
                                page.wait_for_timeout(1000)  # 자동완성 드롭다운 대기

                                # 자동완성 드롭다운 존재 여부 확인
                                _has_dropdown = page.evaluate("""() => {
                                    const dd = document.querySelector('[class*="autocomplete"], [class*="AutoComplete"], [class*="dropdown"], [class*="suggest"]');
                                    return dd ? dd.textContent.slice(0, 100) : null;
                                }""")
                                logger.info(f"[선급금 그리드] 자동완성 드롭다운: {_has_dropdown}")

                                page.keyboard.press("Enter")
                                page.wait_for_timeout(500)

                                # Tab으로 셀 이탈 (값 커밋 보장)
                                page.keyboard.press("Tab")
                                page.wait_for_timeout(300)

                                # 5단계: 입력 확인
                                try:
                                    _val = page.evaluate(f"""() => {{
                                        const iface = {_GET_GRID_IFACE_JS};
                                        return iface?.getValue ? iface.getValue({row_idx}, {_js_str(usage_col["name"])}) : null;
                                    }}""")
                                    logger.info(f"[선급금 그리드] 용도 셀 값: '{_val}'")

                                    # 값이 비었으면 setValue API 직접 시도 (폴백)
                                    if not _val:
                                        logger.warning("[선급금 그리드] 용도코드 keyboard 입력 실패 → setValue API 폴백")
                                        page.evaluate(f"""() => {{
                                            const iface = {_GET_GRID_IFACE_JS};
                                            if (iface && typeof iface.setValue === 'function') {{
                                                iface.setValue({row_idx}, {_js_str(usage_col["name"])}, {_js_str(usage_code)});
                                            }}
                                            if (iface && typeof iface.commit === 'function') iface.commit();
                                        }}""")
                                        page.wait_for_timeout(300)
                                        _val2 = page.evaluate(f"""() => {{
                                            const iface = {_GET_GRID_IFACE_JS};
                                            return iface?.getValue ? iface.getValue({row_idx}, {_js_str(usage_col["name"])}) : null;
                                        }}""")
                                        logger.info(f"[선급금 그리드] setValue 폴백 후 값: '{_val2}'")
                                except Exception:
                                    pass

                                filled_count += 1
                            except Exception as _re:
                                logger.warning(f"[선급금 그리드] 용도코드 행 {row_idx} 실패: {_re}")
                                continue

                        logger.info(f"[선급금 그리드] 용도코드 '{usage_code}' 입력: {filled_count}/{row_count}행")
                        page.wait_for_timeout(500)
                    elif row_count == 0:
                        logger.error("[선급금 그리드] 행 없음 — 용도코드 입력 불가")
                    else:
                        logger.warning(f"[선급금 그리드] 용도 컬럼 미발견: {[c['header'] for c in cols[:10]]}")
                else:
                    logger.warning("[선급금 그리드] OBTDataGrid interface 미발견 — 용도코드 건너뜀")

                _save_debug(page, "adv_08_after_usage_code")
            except Exception as e:
                logger.warning(f"[선급금 그리드] 용도코드 입력 실패: {e}")

        # ── Step 9: 예산과목 자동 팝업 처리 (용도코드 Enter 후 트리거) ──
        _budget_handled = False
        if usage_code and budget_keyword:
            try:
                from src.approval.budget_helpers import handle_auto_triggered_popup
                _proj_kw = project.split(". ", 1)[-1].split("]")[-1].strip() if project else ""
                auto_result = handle_auto_triggered_popup(
                    page=page,
                    project_keyword=_proj_kw,
                    budget_keyword=budget_keyword,
                )
                if auto_result["success"]:
                    logger.info(f"[선급금 그리드] 예산과목 자동팝업 완료: {auto_result['budget_code']}. {auto_result['budget_name']}")
                    _budget_handled = True
                else:
                    logger.warning(f"[선급금 그리드] 예산과목 자동팝업 미처리: {auto_result['message']}")
                _save_debug(page, "adv_09_after_budget_popup")
            except Exception as e:
                logger.error(f"[선급금 그리드] 예산과목 자동팝업 예외: {e}")

        # Step 9 폴백: 자동팝업 미처리 시 select_budget_code() 직접 호출
        if usage_code and budget_keyword and not _budget_handled:
            try:
                from src.approval.budget_helpers import select_budget_code
                _proj_kw = project.split(". ", 1)[-1].split("]")[-1].strip() if project else ""
                budget_result = select_budget_code(
                    page=page,
                    project_keyword=_proj_kw,
                    budget_keyword=budget_keyword,
                )
                if budget_result["success"]:
                    logger.info(f"[선급금 그리드] 예산과목 폴백 완료: {budget_result['budget_code']}. {budget_result['budget_name']}")
                else:
                    logger.warning(f"[선급금 그리드] 예산과목 폴백 실패: {budget_result['message']}")
                _save_debug(page, "adv_09b_after_budget_fallback")
            except Exception as e:
                logger.error(f"[선급금 그리드] 예산과목 폴백 예외: {e}")

        # ── Step 10: 지급요청일 그리드 입력 ──
        if payment_date and usage_code:
            try:
                clean_date = payment_date.replace("-", "")
                grid_info = page.evaluate(f"""() => {{
                    const iface = {_GET_GRID_IFACE_JS};
                    if (!iface || typeof iface.getRowCount !== 'function') return null;
                    const rowCount = iface.getRowCount();
                    const cols = iface.getColumns().map(c => ({{name: c.name, header: c.header || ''}}));
                    return {{rowCount, cols}};
                }}""")

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
                                    const iface = {_GET_GRID_IFACE_JS};
                                    if (!iface) return;
                                    iface.setSelection({{ rowIndex: {row_idx}, columnName: {_js_str(pay_col["name"])} }});
                                    if (typeof iface.focus === 'function') {{
                                        try {{ iface.focus({{ rowIndex: {row_idx}, columnName: {_js_str(pay_col["name"])} }}); }} catch(e) {{
                                            try {{ iface.focus(); }} catch(e2) {{}}
                                        }}
                                    }}
                                }}""")
                                page.wait_for_timeout(300)
                                page.keyboard.type(clean_date, delay=20)
                                page.wait_for_timeout(300)
                                page.keyboard.press("Tab")
                                page.wait_for_timeout(200)
                                filled_count += 1
                            except Exception:
                                continue
                        logger.info(f"[선급금 그리드] 지급요청일 '{payment_date}' 입력: {filled_count}/{grid_info['rowCount']}행")
                    else:
                        logger.warning(f"[선급금 그리드] 지급요청일 컬럼 미발견: {[c['header'] for c in grid_info.get('cols', [])[:10]]}")

                _save_debug(page, "adv_10_after_payment_date_grid")
            except Exception as e:
                logger.warning(f"[선급금 그리드] 지급요청일 그리드 입력 실패: {e}")

        # ── 진단: 전체 그리드 셀 값 덤프 (검증 부적합 원인 추적) ──
        try:
            _grid_dump = page.evaluate(f"""() => {{
                const iface = {_GET_GRID_IFACE_JS};
                if (!iface) return null;
                const rowCount = iface.getRowCount();
                const cols = iface.getColumns().map(c => c.name);
                const rows = [];
                for (let r = 0; r < rowCount; r++) {{
                    const row = {{}};
                    for (const cn of cols) {{
                        try {{ row[cn] = iface.getValue(r, cn); }} catch(e) {{ row[cn] = '?'; }}
                    }}
                    rows.push(row);
                }}
                return {{cols, rows}};
            }}""")
            if _grid_dump:
                logger.info(f"[선급금 그리드 진단] 컬럼: {_grid_dump['cols']}")
                for i, row in enumerate(_grid_dump.get("rows", [])):
                    logger.info(f"[선급금 그리드 진단] 행 {i}: {row}")
        except Exception as _de:
            logger.warning(f"[선급금 그리드 진단] 덤프 실패: {_de}")

    # ──────────────────────────────────────────
    # 임시보관
    # ──────────────────────────────────────────

    def _save_advance_payment_draft(self) -> dict:
        """
        선급금 요청서/정산서 임시보관 (draft 모드).

        지출결의서 `_create_expense_report_via_popup`의 post-submit 핸들링을 그대로 이식.
        플로우 우선순위:
        1. 인라인 폼에 '보관' 버튼이 직접 존재하면 클릭 (팝업 불필요)
        2. 결재상신 클릭 전 OBTAlert/모달 정리 루프 (최대 3회)
        3. 결재상신 클릭 → expect_page로 팝업 감지 (force/JS 폴백)
        4. 팝업 미감지 시 GW 검증 오류 모달 텍스트 추출 +
           `_try_archive_via_navigate_away()` (문서목록 이탈 → 보관 다이얼로그) 폴백
        5. 팝업 감지 시 `_save_draft_in_popup()`로 보관 버튼 클릭

        호출 시점: create_advance_payment_request/settlement에서 필드 채우기 완료 후.
        """
        if not self.context:
            return {"success": False, "message": "BrowserContext가 필요합니다. (팝업 기반 보관)"}

        page = self.page
        popup_page = None

        try:
            _save_debug(page, "adv_draft_01_form_ready")

            # ── 0단계: 결재상신 전 OBTAlert/모달 정리 (최대 3회) ──
            for _cleanup_try in range(3):
                self._dismiss_obt_alert()
                self._close_open_modals()
                page.wait_for_timeout(300)
                try:
                    still_blocked = page.evaluate("""() => {
                        return !!document.querySelector('[class*="OBTAlert"][class*="dimmed"]');
                    }""")
                    if not still_blocked:
                        break
                    logger.info(f"[선급금 보관] OBTAlert 잔존 (시도 {_cleanup_try+1}) → Escape 시도")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:
                    break

            # ── 1-A단계: 인라인 폼에 '보관' 버튼이 직접 있으면 클릭 ──
            _draft_btn = None
            for _ds in [
                "div.topBtn:has-text('보관')",
                "button:has-text('보관')",
                "[class*='topBtn']:has-text('보관')",
                "text=보관",
            ]:
                try:
                    _dloc = page.locator(_ds).first
                    if _dloc.is_visible(timeout=1500):
                        _draft_btn = _dloc
                        logger.info(f"[선급금 보관] 보관 버튼 직접 발견 (팝업 불필요): {_ds}")
                        break
                except Exception:
                    continue
            if _draft_btn:
                try:
                    _draft_btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(200)
                    _draft_btn.click()
                    page.wait_for_timeout(2000)
                    self._dismiss_obt_alert()
                    logger.info("[선급금 보관] 보관 직접 클릭 완료 (메인 폼)")
                    return {"success": True, "message": "선급금 요청서가 임시보관함에 저장되었습니다."}
                except Exception as _de:
                    logger.warning(f"[선급금 보관] 보관 직접 클릭 실패: {_de} — 결재상신 경로로 폴백")

            # dialog 핸들러: GW가 confirm/alert를 띄울 수 있음
            dialog_messages = []

            def _handle_dialog(dialog):
                msg = dialog.message
                dialog_messages.append(msg)
                logger.info(f"[선급금 보관] dialog 감지: {msg[:100]}")
                dialog.accept()

            page.on("dialog", _handle_dialog)

            # ── 1단계: 결재상신 버튼 찾기 ──
            logger.info("[선급금 보관 1/3] 결재상신 버튼 탐색")
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
                _save_debug(page, "adv_draft_error_no_submit_btn")
                try:
                    page.remove_listener("dialog", _handle_dialog)
                except Exception:
                    pass
                return {"success": False, "message": "결재상신 버튼을 찾을 수 없습니다."}

            # ── 2단계: 결재상신 클릭 → 팝업 대기 ──
            logger.info("[선급금 보관 2/3] 결재상신 클릭 → 팝업 대기")

            # expect_page로 팝업 감지 (force/JS click 폴백)
            try:
                with self.context.expect_page(timeout=15000) as new_page_info:
                    submit_btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    try:
                        submit_btn.click(timeout=3000)
                    except Exception as _ce:
                        logger.warning(
                            f"결재상신 click 차단됨({_ce.__class__.__name__}) → JS click 폴백"
                        )
                        try:
                            submit_btn.evaluate("btn => btn.click()")
                        except Exception:
                            submit_btn.click(force=True, timeout=5000)
                    logger.info("결재상신 클릭 → 팝업 대기 (expect_page)")
                popup_page = new_page_info.value
                logger.info(f"결재상신 팝업 감지: {popup_page.url[:100]}")
            except Exception as e:
                logger.warning(f"expect_page 팝업 감지 실패: {e}")

            # expect_page 실패 시 폴링 폴백
            if not popup_page:
                pages_before = set(id(p) for p in self.context.pages)
                # 잔존 OBTDialog 다시 닫기 후 재클릭
                self._close_open_modals()
                page.wait_for_timeout(300)
                try:
                    try:
                        submit_btn.click(timeout=3000)
                    except Exception:
                        submit_btn.evaluate("btn => btn.click()")
                    logger.info("결재상신 재클릭 → 폴링 대기")
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
            try:
                page.remove_listener("dialog", _handle_dialog)
            except Exception:
                pass

            if not popup_page:
                _save_debug(page, "adv_draft_error_no_popup")
                # dialog 메시지가 있으면 검증 오류로 판단
                if dialog_messages:
                    return {
                        "success": False,
                        "message": f"결재상신 검증 오류: {'; '.join(dialog_messages[:3])}",
                    }
                # 부적합 오류 모달 확인 ("검증결과가 부적합인" 텍스트)
                try:
                    error_modal = page.locator("text=부적합").first
                    if error_modal.is_visible(timeout=2000):
                        # 오류 내용 추출 -- 다양한 패턴 포함
                        error_text = page.evaluate("""() => {
                            const els = document.querySelectorAll('div, span, li, p, td');
                            const errors = [];
                            const PATTERNS = ['입력해주세요', '오류 내용', '필수', '부적합', '미입력', '확인하세요'];
                            for (const el of els) {
                                const t = el.textContent?.trim() || '';
                                if (t.length > 3 && t.length < 200 && PATTERNS.some(p => t.includes(p))) {
                                    errors.push(t.substring(0, 100));
                                }
                            }
                            return [...new Set(errors)].slice(0, 10).join('; ');
                        }""")
                        if not error_text:
                            error_text = page.evaluate("""() => {
                                const modal = document.querySelector(
                                    '[class*="modal"], [class*="dialog"], [class*="popup"], [role="dialog"]'
                                );
                                return modal ? modal.textContent?.trim().substring(0, 300) : '(오류 내용 추출 실패)';
                            }""")
                        logger.warning(f"[선급금 보관] 검증 부적합 감지: {error_text[:200]}")
                        # 닫기 버튼 클릭
                        try:
                            close_btn = page.locator("button:has-text('닫기')").first
                            if close_btn.is_visible(timeout=1000):
                                close_btn.click()
                                page.wait_for_timeout(800)
                        except Exception:
                            pass
                        # 검증 부적합 상태에서도 문서목록 이탈 후 보관 시도
                        # (선급금 폼은 이탈 시 '확인/취소' 다이얼로그만 떠서 보관 대안이 없음 — 폴백이 무용할 가능성 큼)
                        logger.info("[선급금 보관] 검증 부적합 → 문서목록 이탈 후 보관 시도")
                        if self._try_archive_via_navigate_away():
                            return {
                                "success": True,
                                "message": "선급금 요청서가 임시보관함에 저장되었습니다. (navigate-away 폴백)",
                            }
                        # GW 서버 검증 실패 — 지출내역 그리드의 필수 필드(용도코드/거래처/예산과목 등) 누락 가능성
                        return {
                            "success": False,
                            "message": (
                                f"검증 부적합: {error_text[:250]} "
                                "— 지출내역 그리드의 필수 필드(용도코드·거래처·예산과목 등)를 확인하세요."
                            ),
                        }
                except Exception:
                    pass
                # 일반 모달 오류 확인
                try:
                    modal_text = page.evaluate("""() => {
                        let text = '';
                        document.querySelectorAll('[class*="modal"], [class*="dialog"], [role="dialog"]').forEach(el => {
                            if (el.offsetParent !== null) {
                                text = el.textContent?.trim()?.substring(0, 300) || '';
                            }
                        });
                        return text;
                    }""")
                    if modal_text:
                        logger.warning(f"[선급금 보관] 일반 모달 감지: {modal_text[:150]}")
                        # navigate-away 폴백 시도 (모달이 있든 없든)
                        try:
                            close_btn = page.locator("button:has-text('닫기')").first
                            if close_btn.is_visible(timeout=800):
                                close_btn.click()
                                page.wait_for_timeout(500)
                        except Exception:
                            pass
                        if self._try_archive_via_navigate_away():
                            return {
                                "success": True,
                                "message": "선급금 요청서가 임시보관함에 저장되었습니다. (navigate-away 폴백)",
                            }
                        return {"success": False, "message": f"결재상신 오류 모달: {modal_text[:150]}"}
                except Exception:
                    pass
                # 모달도 없는 경우: 마지막 수단으로 navigate-away 시도
                logger.info("[선급금 보관] 팝업/모달 미감지 → navigate-away 최종 폴백")
                if self._try_archive_via_navigate_away():
                    return {
                        "success": True,
                        "message": "선급금 요청서가 임시보관함에 저장되었습니다. (navigate-away 폴백)",
                    }
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

            _save_debug(popup_page, "adv_draft_02_popup_opened")

            # ── 3단계: 팝업에서 보관 버튼 클릭 ──
            logger.info("[선급금 보관 3/3] 팝업 보관 버튼 클릭")

            # _save_draft_in_popup (vendor.py의 공통 메서드) 사용
            result = self._save_draft_in_popup(popup_page)
            return result

        except PlaywrightTimeout as e:
            logger.warning(f"선급금 보관 타임아웃: {e}")
            _save_debug(page, "adv_draft_error_timeout")
            return {"success": False, "message": f"선급금 보관 타임아웃: {e}"}
        except Exception as e:
            logger.error(f"선급금 보관 실패: {e}", exc_info=True)
            _save_debug(page, "adv_draft_error")
            return {"success": False, "message": f"선급금 보관 실패: {str(e)}"}
        finally:
            # 팝업 정리
            if popup_page and not popup_page.is_closed():
                try:
                    popup_page.close()
                except Exception:
                    pass

    # ──────────────────────────────────────────
    # 공개 진입점
    # ──────────────────────────────────────────

    def create_advance_payment_request(self, data: dict) -> dict:
        """
        [본사]선급금 요청서 작성 (인라인 폼 기반, 재시도 포함).

        지출결의서와 동일한 APB1020 인라인 폼 구조.
        formId=181 URL 직접 접근 후 필드 채우기.
        - save_mode="verify" (기본): 필드 작성 검증만 수행
        - save_mode="submit": 결재상신 실행
        - save_mode="draft": 결재상신→팝업→보관 (인라인 폼에 보관 버튼 없으므로 팝업 경유)

        Args:
            data: {
                "title": "제목",                    # 필수
                "project": "프로젝트 (코드도움)",    # 선택
                "vendor_name": "거래처명",           # 선택
                "amount": 요청금액(숫자),             # 선택
                "payment_date": "지급요청일 (YYYY-MM-DD)",  # 선택
                "purpose": "요청사유",               # 선택
                "bank_name": "은행명",               # 선택
                "account_number": "계좌번호",        # 선택
                "account_holder": "예금주",          # 선택
                "usage_code": "8020",               # 용도코드 (그리드 필수)
                "budget_keyword": "공사",           # 예산과목 키워드 (그리드 필수)
                "attachment_path": "/path.pdf",      # 첨부파일 경로 (선택)
                "save_mode": "verify",               # "verify" | "submit" | "draft"
            }
        Returns:
            {"success": bool, "message": str}
        """
        # 필수 필드 검증
        validation = self._validate_required_fields(data, ["title"], "선급금요청")
        if validation:
            return validation

        # 세션 확인
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        save_mode = data.get("save_mode", "verify")

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()

                # 1. 전자결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 선급금 요청서 양식 클릭 (인라인 폼)
                self._click_advance_payment_form(form_type="요청서")

                # 3. 양식 로드 대기
                self._wait_for_form_load()

                # 4. 필드 채우기
                self._fill_advance_payment_fields(data, form_type="요청서")

                # 4-1. 결재선 커스텀 설정
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "선급금요청")
                    self.set_approval_line(self.page, resolved_line)

                # 4-2. 수신참조 설정
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "선급금요청")
                    self.set_cc_recipients(self.page, resolved_cc)

                # 5. 저장/검증
                if save_mode == "submit":
                    result = self._submit_inline_form()
                elif save_mode == "draft":
                    # 팝업 기반 보관 흐름 (인라인 폼에 보관 버튼 없으므로 결재상신→팝업→보관)
                    result = self._save_advance_payment_draft()
                else:
                    # verify: 필드 작성 검증만
                    result = self._verify_expense_fields(data)

                return result

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"선급금 요청서 작성 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(self.page, f"adv_req_error_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}
                    self._close_popups()
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

            except Exception as e:
                last_error = e
                logger.error(f"선급금 요청서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"adv_req_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        _save_debug(self.page, "adv_req_error_final")
        return {"success": False, "message": f"선급금 요청서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}

    def create_advance_payment_settlement(self, data: dict) -> dict:
        """
        [본사]선급금 정산서 작성 (인라인 폼 기반, 재시도 포함).

        지출결의서와 동일한 APB1020 인라인 폼 구조.
        formId 미확인 -> 검색으로 진입.
        - save_mode="verify" (기본): 필드 작성 검증만 수행
        - save_mode="submit": 결재상신 실행
        - save_mode="draft": 결재상신→팝업→보관 (인라인 폼에 보관 버튼 없으므로 팝업 경유)

        Args:
            data: {
                "title": "제목",                    # 필수
                "project": "프로젝트 (코드도움)",    # 선택
                "vendor_name": "거래처명",           # 선택
                "original_amount": 선급금액(숫자),   # 선택
                "used_amount": 사용금액(숫자),        # 선택
                "return_amount": 반환금액(숫자),      # 선택 (자동계산 가능)
                "description": "정산내역",           # 선택
                "attachment_path": "/path.pdf",      # 첨부파일 경로 (선택)
                "save_mode": "verify",               # "verify" | "submit" | "draft"
            }
        Returns:
            {"success": bool, "message": str}
        """
        # 필수 필드 검증
        validation = self._validate_required_fields(data, ["title"], "선급금정산")
        if validation:
            return validation

        # 세션 확인
        if not self._check_session_valid():
            return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}

        save_mode = data.get("save_mode", "verify")

        # return_amount 자동 계산 (미입력 시)
        if not data.get("return_amount"):
            orig = data.get("original_amount")
            used = data.get("used_amount")
            if orig is not None and used is not None:
                try:
                    data = dict(data)  # 원본 수정 방지
                    data["return_amount"] = int(orig) - int(used)
                    logger.info(f"반환금액 자동 계산: {orig} - {used} = {data['return_amount']}")
                except Exception:
                    pass

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._close_popups()

                # 1. 전자결재 HOME 이동
                self._navigate_to_approval_home()

                # 2. 선급금 정산서 양식 클릭 (인라인 폼)
                self._click_advance_payment_form(form_type="정산서")

                # 3. 양식 로드 대기
                self._wait_for_form_load()

                # 4. 필드 채우기
                self._fill_advance_payment_fields(data, form_type="정산서")

                # 4-1. 결재선 커스텀 설정
                if data.get("approval_line"):
                    resolved_line = resolve_approval_line(data["approval_line"], "선급금정산")
                    self.set_approval_line(self.page, resolved_line)

                # 4-2. 수신참조 설정
                if data.get("cc"):
                    resolved_cc = resolve_cc_recipients(data["cc"], "선급금정산")
                    self.set_cc_recipients(self.page, resolved_cc)

                # 5. 저장/검증
                if save_mode == "submit":
                    result = self._submit_inline_form()
                elif save_mode == "draft":
                    # 팝업 기반 보관 흐름 (인라인 폼에 보관 버튼 없으므로 결재상신→팝업→보관)
                    result = self._save_advance_payment_draft()
                else:
                    result = self._verify_expense_fields(data)

                return result

            except PlaywrightTimeout as e:
                last_error = e
                logger.warning(f"선급금 정산서 작성 타임아웃 (시도 {attempt}/{MAX_RETRIES}): {e}")
                _save_debug(self.page, f"adv_sett_error_timeout_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    if not self._check_session_valid():
                        return {"success": False, "message": "세션이 만료되었습니다. 다시 로그인해주세요."}
                    self._close_popups()
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

            except Exception as e:
                last_error = e
                logger.error(f"선급금 정산서 작성 실패 (시도 {attempt}/{MAX_RETRIES}): {e}", exc_info=True)
                _save_debug(self.page, f"adv_sett_error_attempt{attempt}")
                if attempt < MAX_RETRIES:
                    self.page.wait_for_timeout(RETRY_DELAY * 1000)

        _save_debug(self.page, "adv_sett_error_final")
        return {"success": False, "message": f"선급금 정산서 작성 실패 ({MAX_RETRIES}회 시도): {str(last_error)}"}
