"""
Invoice modal handler — extracted from ExpenseReportMixin._select_invoice_in_modal (1013 lines).

GW flow (2026-03-29):
1. Wait for "매입(세금)계산서 내역" modal
2. Adjust start date via calendar popup
3. Toggle advanced search
4. Type vendor in 거래처/사업자번호 input
5. Click 조회
6. Select result checkbox
7. Click 확인 → grid auto-reflect

self deps: page (arg), _dismiss_obt_alert (callback).
"""
from __future__ import annotations

import logging
from typing import Callable
from playwright.sync_api import Page

from src.approval.base import _GET_GRID_IFACE_JS, _save_debug, _js_str

logger = logging.getLogger("approval_automation")


def select_invoice_in_modal(
    page: Page,
    dismiss_alert_fn: Callable[[], None],
    vendor: str = "",
    amount: float = None,
    date_from: str = "",
    date_to: str = "",
) -> bool:
    """매입(세금)계산서 내역 모달에서 검색/선택. mixin 위임 진입점."""
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
    page = page
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
        page.wait_for_timeout(250)

    if not modal_visible:
        logger.warning("계산서 모달 미표시")
        _save_debug(page, "invoice_modal_not_found")
        return False

    logger.info("계산서 모달 표시 확인")
    page.wait_for_timeout(2000)  # 모달 내부 렌더링 대기

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
            page.wait_for_timeout(300)
            # 기존 값 전체 선택 후 덮어쓰기
            page.keyboard.press("Control+a")
            page.wait_for_timeout(100)
            page.keyboard.type(date_from, delay=30)
            page.keyboard.press("Tab")
            page.wait_for_timeout(500)
            logger.info(f"시작일 변경: {coord.get('val','')} → {date_from} (w={coord['w']})")

            # Tab 키 후 GW가 자동 조회 시작 → 로딩 완료 대기
            # OBT 로딩 오버레이가 뜨고 사라질 때까지 대기 (최대 15초)
            page.wait_for_timeout(2000)  # 로딩 시작 대기
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
                        page.wait_for_timeout(500)
                        continue
                    break
                except Exception:
                    break
            page.wait_for_timeout(1000)  # 렌더링 안정화
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
    page.wait_for_timeout(3000)  # 자동 조회 결과 렌더링 대기
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
            page.wait_for_timeout(400)
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
                page.wait_for_timeout(800)
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
                page.wait_for_timeout(200)
                page.keyboard.press("Control+a")
                page.wait_for_timeout(100)
                page.keyboard.type(vendor, delay=50)
                page.wait_for_timeout(300)
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
                        page.wait_for_timeout(500)
                        logger.info(f"조회 버튼 클릭: ({search_btn_result['x']}, {search_btn_result['y']})")
                        searched = True
                except Exception as eb:
                    logger.warning(f"조회 버튼 클릭 실패: {eb}")

                if not searched:
                    # 조회 버튼 미발견 → Enter 키로 조회
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(500)
                    logger.info("조회 Enter 키 전송")

                # 조회 후 로딩 대기 (최대 10초)
                page.wait_for_timeout(2000)
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
                            page.wait_for_timeout(500)
                            continue
                        break
                    except Exception:
                        break
                page.wait_for_timeout(1000)
                # 조회 결과 없음 알림("세금계산서가 없습니다.") 처리
                dismiss_alert_fn()
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
                        page.wait_for_timeout(500)
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
                        page.wait_for_timeout(500)
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
                page.wait_for_timeout(500)
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
        dismiss_alert_fn()
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
                            page.wait_for_timeout(800)
                            logger.info(f"인보이스 모달 취소 클릭: {_csel}")
                            _modal_closed = True
                            break
                    except Exception:
                        continue
            if not _modal_closed:
                # 모달 내 취소 버튼 없음 → Escape 폴백 (확인 다이얼로그에서 "확인" 클릭)
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
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
                page.wait_for_timeout(500)
            # 모달 닫힘 확인 (최대 5초)
            for _ in range(10):
                try:
                    if not page.locator("text=매입(세금)계산서 내역").first.is_visible(timeout=200):
                        logger.info("인보이스 모달 닫힘 확인")
                        break
                except Exception:
                    break
                page.wait_for_timeout(500)
            else:
                logger.warning("인보이스 모달이 아직 열려있음 (닫기 실패)")
        except Exception as _me:
            logger.warning(f"인보이스 모달 닫기 오류: {_me}")
        return False

    page.wait_for_timeout(500)

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
    page.wait_for_timeout(1000)
    try:
        if page.locator('[class*="OBTAlert_dimmed"]').count() > 0:
            logger.info("확인 클릭 후 OBTAlert 감지 — dismiss")
            dismiss_alert_fn()
            page.wait_for_timeout(500)
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
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    pass
            else:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            # modal 닫힘 후 OBTAlert 처리
            dismiss_alert_fn()
            page.wait_for_timeout(300)
    except Exception:
        pass

    # 그리드 반영 대기
    page.wait_for_timeout(2000)
    _save_debug(page, "03c3_after_invoice_applied")
    logger.info("계산서 모달 -> 그리드 반영 완료")
    return selected
