"""
Project code picker — extracted from ExpenseReportMixin._fill_project_code (784 lines).

GW flow:
1. Click 프로젝트 input field (y_hint optionally targets bottom field)
2. OBTDialog2 modal opens with project search
3. Type keyword → autocomplete dropdown → click first match
4. Confirm button → modal closes

self deps: page (arg), _dismiss_obt_alert + _close_open_modals (callbacks).
"""
from __future__ import annotations

import logging
from typing import Callable
from playwright.sync_api import Page

from src.gw.approval.base import _GET_GRID_IFACE_JS, _save_debug, _parse_project_text, _js_str

logger = logging.getLogger("approval_automation")


def fill_project_code(
    page: Page,
    dismiss_alert_fn: Callable[[], None],
    close_modals_fn: Callable[[], None],
    project: str,
    y_hint: float = None,
):
    """프로젝트 코드도움 모달 검색/선택 진입점."""
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
    page = page

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
                        dismiss_alert_fn()
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
                    dismiss_alert_fn()
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
                dismiss_alert_fn()
                proj_input.dispatch_event("mousedown")
                proj_input.dispatch_event("mouseup")
                proj_input.dispatch_event("click")

            page.wait_for_timeout(800)  # 모달 열림 대기
            logger.info("프로젝트 input 클릭 완료 — 모달 대기")
    except Exception as e:
        logger.warning(f"프로젝트 input 클릭 실패: {e}")
        # 열린 모달이 있으면 닫기
        close_modals_fn()
        return False

    # 2. "프로젝트코드도움" 모달 대기 (타임아웃 증가: 3000 → 8000ms)
    page.wait_for_timeout(1000)
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
        page.wait_for_timeout(2000)
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
                    dismiss_alert_fn()
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

        page.wait_for_timeout(1500)
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
            page.wait_for_timeout(800)
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
                        page.wait_for_timeout(1000)
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
                    page.wait_for_timeout(1000)
                elif first_row_info.get("clicked"):
                    # JS 내부에서 직접 dblclick 이벤트 발생 (좌표 불필요)
                    logger.info(f"프로젝트 방법 B-2 JS직접 더블클릭 ({first_row_info.get('method')})")
                    selected = True
                    page.wait_for_timeout(1000)
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
                page.wait_for_timeout(500)
            except Exception:
                pass
        else:
            logger.info("프로젝트 더블클릭으로 모달 자동 닫힘")
    else:
        try:
            page.locator("button:has-text('취소')").last.click()
            page.wait_for_timeout(300)
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
        page.wait_for_timeout(300)

    return selected

