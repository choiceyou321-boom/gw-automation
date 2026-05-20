"""
expense_fields.py — 지출결의서 필드 채우기 함수 (Phase D 분할, 세션 LII)

ExpenseReportMixin._fill_expense_fields (722줄)를 콜백 주입 패턴으로 추출.
mixin 메서드 의존성(self._*)은 Callable 인자로 주입받으며,
self.page는 page 인자로 교체된다.

콜백 인자 목록:
    dismiss_alert_fn        → self._dismiss_obt_alert
    fill_project_code_fn    → self._fill_project_code
    fill_field_by_label_fn  → self._fill_field_by_label
    check_field_has_value_fn→ self._check_field_has_value
    close_modals_fn         → self._close_open_modals
    click_evidence_type_fn  → self._click_evidence_type_button
    select_invoice_fn       → self._select_invoice_in_modal
    fill_grid_items_fn      → self._fill_grid_items
    fill_receipt_date_fn    → self._fill_receipt_date
    fill_project_code_bottom_fn → self._fill_project_code_bottom
    link_reference_doc_fn   → self._link_reference_document
    upload_attachment_fn    → self._upload_attachment
    capture_budget_fn       → self._capture_and_attach_budget_screenshot
"""
from __future__ import annotations

import logging
from typing import Callable
from playwright.sync_api import Page

from src.approval.base import _GET_GRID_IFACE_JS, _save_debug, _js_str

logger = logging.getLogger("approval_automation")


def fill_expense_fields(
    page,
    dismiss_alert_fn,
    fill_project_code_fn,
    fill_field_by_label_fn,
    check_field_has_value_fn,
    close_modals_fn,
    click_evidence_type_fn,
    select_invoice_fn,
    fill_grid_items_fn,
    fill_receipt_date_fn,
    fill_project_code_bottom_fn,
    link_reference_doc_fn,
    upload_attachment_fn,
    capture_budget_fn,
    data: dict,
):
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
    page = page
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
    dismiss_alert_fn()
    page.wait_for_timeout(300)  # 닫힘 후 UI 안정화 대기

    # 1. 프로젝트 코드도움 입력 (상단, y≈292)
    project = data.get("project", "")
    if project:
        fill_project_code_fn(project, y_hint=292)
        _save_debug(page, "03a_after_project_top")

        # 프로젝트 입력 후 페이지 이탈 검증 (Enter->예산관리 네비게이션 방지)
        page.wait_for_timeout(300)
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
        fill_field_by_label_fn("제목", title)

    # 3. 제목 못 찾았으면 좌표 기반 (rect y=332 영역)
    if title and not check_field_has_value_fn("제목", title):
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
                            page.wait_for_timeout(500)
                    except Exception:
                        pass

                # 열린 모달이 있으면 먼저 닫기 (dimClicker 차단 방지)
                close_modals_fn()
                page.wait_for_timeout(500)

                click_evidence_type_fn(evidence_type)
                page.wait_for_timeout(2000)  # 모달 로딩 대기 늘림
                _modal_invoice_selected = False
                try:
                    _modal_invoice_selected = select_invoice_fn(
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
                    close_modals_fn()
                    # 모달 취소 후 GW가 OBTAlert를 비동기로 표시할 수 있음 → 1.5초 대기 후 dismiss
                    page.wait_for_timeout(1500)
                    dismiss_alert_fn()
                    page.wait_for_timeout(500)
                    break

                # 인보이스 선택 후 그리드 렌더링 대기 (최대 5초)
                for _wait in range(10):
                    _invoice_row_count = page.evaluate(f"""() => {{
                        const iface = {_GET_GRID_IFACE_JS};
                        return (iface && typeof iface.getRowCount === 'function') ? iface.getRowCount() : 0;
                    }}""")
                    if _invoice_row_count > 0:
                        logger.info(f"그리드 렌더링 완료: {_invoice_row_count}행 (시도 {_inv_attempt + 1}/3)")
                        break
                    page.wait_for_timeout(500)
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
            click_evidence_type_fn(evidence_type)
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
            fill_grid_items_fn(items)
            _save_debug(page, "03b_after_grid")

    # 6. 증빙일자 입력 (하단 테이블, y=857)
    receipt_date = data.get("receipt_date", "") or data.get("date", "")
    if receipt_date:
        fill_receipt_date_fn(receipt_date)
        _save_debug(page, "03d_after_receipt_date")

    # 7. 하단 테이블 프로젝트 코드도움 입력 (y≈857 근처, 테이블 7)
    if project:
        result = fill_project_code_bottom_fn(project)
        if not result:
            close_modals_fn()
        _save_debug(page, "03d2_after_project_bottom")

    # 7-1. 참조문서 연결 (전자결재 폼 내 기존 문서 참조)
    reference_doc_keyword = data.get("reference_doc_keyword", "")
    if reference_doc_keyword:
        try:
            ref_result = link_reference_doc_fn(reference_doc_keyword)
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
        upload_attachment_fn(attachment_path)
        _save_debug(page, "03e_after_attachment")

    # 9. 예실대비현황 자동 캡처 후 첨부 (auto_capture_budget=True 시)
    if data.get("auto_capture_budget") and not attachment_path:
        capture_budget_fn()
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
                logger.info(f"OBTDataGrid 행 수: {row_count}, 컬럼: {[c['header'] for c in cols[:10]]}")

                # row_count == 0이면 렌더링이 아직 완료되지 않은 것 -- 최대 3초 추가 대기
                if row_count == 0:
                    logger.warning("step 10 진입 시 그리드 행 없음 -- 렌더링 대기 (최대 3초)")
                    for _extra_wait in range(6):
                        page.wait_for_timeout(500)
                        row_count = page.evaluate(f"""() => {{
                            const iface = {_GET_GRID_IFACE_JS};
                            return (iface && typeof iface.getRowCount === 'function') ? iface.getRowCount() : 0;
                        }}""")
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
                                const iface = {_GET_GRID_IFACE_JS};
                                if (!iface) return;
                                iface.setSelection({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }});
                                // focus에 좌표 전달: 셀 에디터 활성화
                                if (typeof iface.focus === 'function') {{
                                    try {{ iface.focus({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }}); }} catch(e) {{
                                        try {{ iface.focus(); }} catch(e2) {{}}
                                    }}
                                }}
                            }}""")
                            page.wait_for_timeout(400)

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
                                        page.wait_for_timeout(400)
                                        _active_tag = page.evaluate("() => document.activeElement ? document.activeElement.tagName : 'none'")
                                        logger.info(f"canvas 직접 클릭 후 activeElement: {_active_tag}")
                                except Exception as _ce:
                                    logger.warning(f"canvas 직접 클릭 실패: {_ce}")

                            # 셀 기존값 초기화 → change event 강제 발생 위해 빈 문자열로 커밋
                            # setValue API로 즉각 클리어 (Escape는 원래 값으로 되돌리므로 부적합)

                            # [진단] setValue 전 현재 셀 값 확인
                            try:
                                _val_before_clear = page.evaluate(f"""() => {{
                                    const iface = {_GET_GRID_IFACE_JS};
                                    return iface?.getValue ? iface.getValue({row_idx}, {_js_str(usage_col["name"])}) : null;
                                }}""")
                                logger.info(f"[진단] 용도 셀 setValue 전 값: '{_val_before_clear}'")
                            except Exception:
                                pass

                            try:
                                page.evaluate(f"""() => {{
                                    const iface = {_GET_GRID_IFACE_JS};
                                    if (!iface) return;
                                    if (typeof iface.setValue === 'function') {{
                                        iface.setValue({row_idx}, {_js_str(usage_col["name"])}, '');
                                    }}
                                    if (typeof iface.commit === 'function') iface.commit();
                                }}""")
                                page.wait_for_timeout(200)
                                # [진단] setValue('') 후, retype 전 값 확인
                                try:
                                    _val_after_clear = page.evaluate(f"""() => {{
                                        const iface = {_GET_GRID_IFACE_JS};
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
                                page.wait_for_timeout(200)
                                page.keyboard.press("Tab")  # 빈 값 커밋
                                page.wait_for_timeout(200)
                            # 셀 재포커스 (클리어 후 포커스 재설정)
                            page.evaluate(f"""() => {{
                                const iface = {_GET_GRID_IFACE_JS};
                                if (!iface) return;
                                iface.setSelection({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }});
                                if (typeof iface.focus === 'function') {{
                                    try {{ iface.focus({{ rowIndex: {row_idx}, columnName: {_js_str(usage_col["name"])} }}); }} catch(e) {{}}
                                }}
                            }}""")
                            page.wait_for_timeout(300)

                            # 편집 input에 용도코드 입력 (자동완성 트리거)
                            page.keyboard.type(str(usage_code), delay=50)
                            page.wait_for_timeout(800)  # 자동완성 드롭다운 대기
                            page.keyboard.press("Enter")
                            page.wait_for_timeout(500)  # 자동완성 선택 반영 대기

                            # 입력된 값 확인 (진단용)
                            try:
                                _cell_val = page.evaluate(f"""() => {{
                                    const iface = {_GET_GRID_IFACE_JS};
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
                    page.wait_for_timeout(500)
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
                                // focus에 좌표 전달: 셀 에디터 활성화
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
        page.wait_for_timeout(1000)  # 동적 필드 렌더링 대기
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
                            page.wait_for_timeout(500)
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

            page.wait_for_timeout(500)  # 검증결과 갱신 대기
            _save_debug(page, "21_after_accounting_date")
        except Exception as e:
            logger.warning(f"회계처리일자 처리 중 오류: {e}")

    # 22. 검증결과 확인 ("적합" / "부적합")
    try:
        page.wait_for_timeout(500)  # 검증 결과 갱신 완료 대기
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
                    page.wait_for_timeout(500)
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

