"""
예실대비현황(사업별) GW 크롤러
- 기간 선택 가능 → 전기+당기 데이터 모두 조회
- Playwright로 GW 접속 → BM 모듈 → 예실대비현황(사업별) → 기간 설정 → 사업코드 입력 → 그리드 추출
- budget_crawler.py(상세)를 보충하는 메인 크롤러 역할

사용법:
    from src.fund_table.budget_crawler_by_project import crawl_budget_by_project, crawl_all_by_project
    result = crawl_budget_by_project(gw_id, project_id, "GS-25-0088", "20250101", "20261231")
    result = crawl_all_by_project(gw_id)
"""

import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("budget_crawler_by_project")

GW_URL = os.environ.get("GW_URL", "https://gw.glowseoul.co.kr")
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "approval_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# OBTDataGrid 데이터 추출 JS — leaf 컬럼까지 재귀 탐색
_EXTRACT_GRID_DATA_JS = """
(() => {
    const grids = document.querySelectorAll('.OBTDataGrid_grid__22Vfl');
    if (!grids.length) return { error: 'grid_not_found', grids_count: 0 };

    const results = [];
    for (let gi = 0; gi < grids.length; gi++) {
        const el = grids[gi];
        const fk = Object.keys(el).find(k =>
            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
        );
        if (!fk) continue;

        let f = el[fk];
        for (let i = 0; i < 3 && f; i++) f = f.return;
        if (!f || !f.stateNode || !f.stateNode.state) continue;

        const iface = f.stateNode.state.interface;
        if (!iface) continue;

        try {
            const rowCount = iface.getRowCount();
            // leaf columns 추출 (그룹 헤더의 하위 컬럼까지)
            const allCols = iface.getColumns();
            const leafCols = [];
            const extractLeaf = (col) => {
                if (col.columns && col.columns.length > 0) {
                    col.columns.forEach(extractLeaf);
                } else {
                    leafCols.push(col);
                }
            };
            allCols.forEach(extractLeaf);

            const cols = leafCols.map(c => ({
                name: c.name || c.fieldName,
                header: c.header ? (c.header.text || c.header) : (c.name || c.fieldName),
                fieldName: c.fieldName || c.name
            }));

            const rows = [];
            for (let r = 0; r < rowCount; r++) {
                const row = {};
                cols.forEach(col => {
                    try { row[col.name] = iface.getValue(r, col.name); } catch(e) {}
                });
                rows.push(row);
            }
            results.push({
                grid_index: gi,
                columns: cols,
                rows: rows,
                row_count: rowCount
            });
        } catch (e) {
            results.push({ grid_index: gi, error: e.message });
        }
    }
    return { grids_count: grids.length, results: results };
})()
"""

# RealGridJS / DataProvider 패턴 (깊은 depth 탐색)
_EXTRACT_DEEP_DATA_JS = """
(() => {
    const grids = document.querySelectorAll('[class*="OBTDataGrid"]');
    for (const el of grids) {
        const fk = Object.keys(el).find(k =>
            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
        );
        if (!fk) continue;

        let f = el[fk];
        for (let d = 0; d < 15 && f; d++) {
            f = f.return;
            if (!f?.stateNode?.state) continue;
            const state = f.stateNode.state;

            // detailList 형태 데이터
            if (state.detailList && Array.isArray(state.detailList) && state.detailList.length > 0) {
                const rows = state.detailList;
                const colNames = Object.keys(rows[0]);
                const columns = colNames.map(k => ({ name: k, header: k }));
                const extra = {};
                if (state.addSumList) extra.addSumList = state.addSumList;
                if (state.subSumList) extra.subSumList = state.subSumList;
                if (state.totSumList) extra.totSumList = state.totSumList;
                return {
                    depth: d + 1, source: 'state.detailList',
                    columns, rows, row_count: rows.length, summary: extra
                };
            }

            // interface + DataProvider
            if (state.interface && typeof state.interface.getRowCount === 'function') {
                try {
                    const iface = state.interface;
                    const rowCount = iface.getRowCount();
                    if (rowCount === 0) continue;

                    let ds = null;
                    try { ds = iface.getDataSource ? iface.getDataSource() : null; } catch(e) {}

                    if (ds && ds.getJsonRows) {
                        try {
                            const jsonRows = ds.getJsonRows(0, -1);
                            if (jsonRows && jsonRows.length > 0) {
                                const fieldNames = Object.keys(jsonRows[0]);
                                return {
                                    depth: d + 1, source: 'DataProvider.getJsonRows',
                                    columns: fieldNames.map(n => ({ name: n, header: n })),
                                    rows: jsonRows, row_count: jsonRows.length
                                };
                            }
                        } catch(e) {}
                    }

                    // getColumns + getValue fallback
                    const allCols = iface.getColumns();
                    const leafCols = [];
                    const extractLeaf = (col) => {
                        if (col.columns && col.columns.length > 0) {
                            col.columns.forEach(extractLeaf);
                        } else { leafCols.push(col); }
                    };
                    allCols.forEach(extractLeaf);
                    const cols = leafCols.map(c => ({
                        name: c.name || c.fieldName,
                        header: c.header ? (c.header.text || c.header) : (c.name || c.fieldName)
                    }));
                    if (cols.length > 0) {
                        const rows = [];
                        for (let r = 0; r < rowCount; r++) {
                            const row = {};
                            cols.forEach(col => {
                                try { row[col.name] = iface.getValue(r, col.name); } catch(e) {}
                            });
                            rows.push(row);
                        }
                        return { depth: d + 1, source: 'interface+leafCols', columns: cols, rows, row_count: rowCount };
                    }
                } catch(e) { continue; }
            }
        }
    }
    return { error: 'no_data_found' };
})()
"""


def crawl_budget_by_project(
    gw_id: str,
    project_id: int = None,
    project_code: str = None,
    start_date: str = None,
    end_date: str = None,
):
    """
    예실대비현황(사업별) 크롤링 — 단일 프로젝트.

    Args:
        gw_id: GW 로그인 ID
        project_id: fund_management.db 프로젝트 ID (저장용)
        project_code: GW 사업코드 (예: GS-25-0088)
        start_date: 조회 시작일 (YYYYMMDD). None이면 전년도 1월 1일
        end_date: 조회 종료일 (YYYYMMDD). None이면 오늘

    Returns:
        dict: { success, message, data?, error? }
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password

    if not project_code:
        return {"success": False, "error": "project_code가 필요합니다."}

    # 기본 기간: 전년도 1월 1일 ~ 오늘
    now = datetime.now()
    if not start_date:
        start_date = f"{now.year - 1}0101"
    if not end_date:
        end_date = now.strftime("%Y%m%d")

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    pw = sync_playwright().start()
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        result = _navigate_and_extract_by_project(page, project_code, start_date, end_date)

        if result.get("success") and result.get("data"):
            from src.fund_table import db
            records = _transform_by_project_data(result["data"], project_id, project_code, start_date, end_date)
            if records:
                _clear_old_budget(project_id)
                save_result = db.save_budget_actual(records, project_id=project_id)
                result["saved"] = save_result
                result["record_count"] = len(records)
            else:
                result["message"] = "그리드 데이터를 변환할 수 없습니다."
                result["success"] = False

        close_session(browser)
        return result

    except Exception as e:
        logger.error(f"예실대비(사업별) 크롤링 실패: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        pw.stop()


def crawl_all_by_project(gw_id: str):
    """
    등록된 모든 프로젝트의 예실대비현황(사업별) 일괄 크롤링.
    project_code가 설정된 프로젝트만 대상.

    Returns:
        dict: { success, message, results: [{project_id, project_name, status, message}] }
    """
    from playwright.sync_api import sync_playwright
    from src.auth.login import login_and_get_context, close_session
    from src.auth.user_db import get_decrypted_password
    from src.fund_table import db

    gw_pw = get_decrypted_password(gw_id)
    if not gw_pw:
        return {"success": False, "error": f"사용자 '{gw_id}'의 비밀번호를 찾을 수 없습니다."}

    projects = db.list_projects()
    targets = [p for p in projects if p.get("project_code")]

    if not targets:
        return {"success": False, "error": "project_code가 설정된 프로젝트가 없습니다."}

    # 기본 기간: 전년도 1월 1일 ~ 오늘
    now = datetime.now()
    default_start = f"{now.year - 1}0101"
    default_end = now.strftime("%Y%m%d")

    pw = sync_playwright().start()
    results = []
    try:
        browser, context, page = login_and_get_context(
            playwright_instance=pw,
            headless=True,
            user_id=gw_id,
            user_pw=gw_pw,
        )

        for proj in targets:
            pid = proj["id"]
            pcode = proj["project_code"]
            pname = proj.get("name", "")

            # 프로젝트 코드에서 연도 추출 시도 (GS-25-XXXX → 2025)
            start_date = default_start
            try:
                code_parts = pcode.split("-")
                if len(code_parts) >= 2 and code_parts[1].isdigit():
                    year_prefix = int(code_parts[1])
                    if year_prefix < 100:
                        year_prefix += 2000
                    start_date = f"{year_prefix}0101"
            except Exception:
                pass

            logger.info(f"크롤링 시작: {pname} ({pcode}) 기간: {start_date}~{default_end}")

            try:
                result = _navigate_and_extract_by_project(page, pcode, start_date, default_end)
                if result.get("success") and result.get("data"):
                    records = _transform_by_project_data(result["data"], pid, pcode, start_date, default_end)
                    if records:
                        _clear_old_budget(pid)
                        db.save_budget_actual(records, project_id=pid)
                        results.append({
                            "project_id": pid, "project_name": pname,
                            "status": "success", "message": f"{len(records)}건 저장",
                        })
                    else:
                        results.append({
                            "project_id": pid, "project_name": pname,
                            "status": "fail", "message": "데이터 변환 실패",
                        })
                else:
                    results.append({
                        "project_id": pid, "project_name": pname,
                        "status": "fail", "message": result.get("error", "추출 실패"),
                    })
            except Exception as e:
                logger.error(f"프로젝트 {pname} 크롤링 오류: {e}")
                results.append({
                    "project_id": pid, "project_name": pname,
                    "status": "error", "message": str(e),
                })

        close_session(browser)
    except Exception as e:
        logger.error(f"일괄 크롤링 실패: {e}", exc_info=True)
        return {"success": False, "error": str(e), "results": results}
    finally:
        pw.stop()

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "success": True,
        "message": f"{success_count}/{len(targets)} 프로젝트 크롤링 완료 (사업별)",
        "results": results,
    }


# ─────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────

def _dismiss_alerts(page, max_tries=3):
    """OBTAlert 팝업 닫기 (확인 버튼 반복 클릭)"""
    for _ in range(max_tries):
        try:
            alert_btn = page.locator(
                ".OBTAlert_alertBoxStyle__WdE7R button, "
                ".OBTButton_labelText__1s2qO:has-text('확인')"
            )
            if alert_btn.count() > 0:
                alert_btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
                logger.info("OBTAlert 팝업 닫음")
            else:
                break
        except Exception:
            break


def _close_sidebar(page):
    """좌측 사이드바 닫기 (오버레이 차단 방지)"""
    try:
        page.evaluate("""
            () => {
                const sw = document.getElementById('sideWrap');
                if (sw && sw.classList.contains('on')) {
                    sw.classList.remove('on');
                }
                const toggle = document.querySelector('.sidebar-toggle, .gnb-toggle, [class*="hamburger"]');
                if (toggle) toggle.click();
            }
        """)
        logger.info("사이드바 닫기 시도")
    except Exception:
        pass


def _save_screenshot(page, name: str):
    """디버그 스크린샷 저장"""
    try:
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 저장 실패: {e}")


def _navigate_to_by_project_page(page) -> bool:
    """
    BM 모듈 → 예산장부 → 예실대비현황(사업별) 페이지 이동.
    이미 해당 페이지에 있으면 스킵.

    Returns: 페이지 로드 성공 여부
    """
    # 현재 URL에 이미 사업별 페이지가 있는지 확인
    current_url = page.url
    if "NCC" in current_url and "BM" in current_url:
        # 이미 BM 모듈의 어떤 페이지에 있음 → 그리드 확인
        grid = page.locator("[class*='OBTDataGrid']")
        if grid.count() > 0:
            logger.info("이미 예산 페이지에 있음 (그리드 발견)")
            return True

    # 메인 → BM 모듈 이동
    page.goto(f"{GW_URL}/#/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    _dismiss_alerts(page)

    # 예산관리 모듈 클릭
    bm_link = page.locator("span.module-link.BM")
    if bm_link.count() == 0:
        logger.warning("BM 모듈 링크를 찾을 수 없습니다.")
        return False

    bm_link.first.click()
    page.wait_for_timeout(4000)
    _dismiss_alerts(page)
    _close_sidebar(page)
    page.wait_for_timeout(1000)
    logger.info(f"BM 모듈 클릭 후 URL: {page.url}")

    # 예산장부 메뉴 클릭 (하위 메뉴 펼치기)
    clicked1 = page.evaluate("""
        () => {
            const items = document.querySelectorAll('.nav-text, [class*="menu-text"], [class*="menuText"]');
            for (const el of items) {
                if (el.textContent.trim() === '예산장부') {
                    el.click();
                    return { found: true };
                }
            }
            return { found: false };
        }
    """)
    logger.info(f"예산장부 메뉴 클릭: {clicked1}")
    page.wait_for_timeout(2000)

    # 예실대비현황(사업별) 클릭
    clicked2 = page.evaluate("""
        () => {
            const items = document.querySelectorAll('.nav-text, [class*="menu-text"], [class*="menuText"], a, span');
            for (const el of items) {
                const txt = el.textContent.trim();
                if (txt === '예실대비현황(사업별)') {
                    el.click();
                    return { found: true, text: txt };
                }
            }
            // 정확히 '사업별'이 없으면 부분 매치 시도
            for (const el of items) {
                const txt = el.textContent.trim();
                if (txt.includes('예실대비') && txt.includes('사업')) {
                    el.click();
                    return { found: true, text: txt, partial: true };
                }
            }
            return { found: false };
        }
    """)
    logger.info(f"예실대비현황(사업별) 메뉴 클릭: {clicked2}")
    page.wait_for_timeout(4000)
    _dismiss_alerts(page)

    if not clicked2.get("found"):
        _save_screenshot(page, "byprj_menu_not_found")
        logger.error("예실대비현황(사업별) 메뉴를 찾을 수 없습니다.")
        return False

    # 페이지 로드 확인 — 그리드 또는 조건 패널 존재
    return _verify_by_project_page(page)


def _verify_by_project_page(page) -> bool:
    """예실대비현황(사업별) 페이지 로드 확인"""
    try:
        grid = page.locator("[class*='OBTDataGrid']")
        if grid.count() > 0:
            logger.info("사업별 페이지 확인: OBTDataGrid 발견")
            return True
        condition = page.locator("[class*='OBTConditionPanel']")
        if condition.count() > 0:
            logger.info("사업별 페이지 확인: OBTConditionPanel 발견")
            return True
    except Exception as e:
        logger.debug(f"페이지 확인 오류: {e}")
    return False


def _set_date_range(page, start_date: str, end_date: str) -> bool:
    """
    DatePicker에 기간 설정.
    여러 방법을 순차 시도:
      1) OBTDatePicker input에 직접 fill
      2) JS로 React state 변경 (fiber 접근)
      3) 날짜 input에 dispatchEvent

    Args:
        start_date: YYYYMMDD 형식
        end_date: YYYYMMDD 형식
    """
    logger.info(f"기간 설정: {start_date} ~ {end_date}")

    # 방법 1: OBTDatePicker/날짜 input에 직접 fill
    filled = page.evaluate("""
        (dates) => {
            const { start, end } = dates;
            const results = [];

            // OBTDatePicker 컴포넌트 내 input 찾기
            const datePickers = document.querySelectorAll(
                '[class*="OBTDatePicker"] input[type="text"], ' +
                '[class*="DatePicker"] input[type="text"], ' +
                '[class*="datePicker"] input[type="text"]'
            );

            // 조건 패널 내 날짜 input도 포함
            const condInputs = document.querySelectorAll(
                '[class*="OBTConditionPanel"] input[type="text"]'
            );

            // 모든 날짜 후보 input 수집
            const candidates = [];
            const seen = new Set();

            // DatePicker 컴포넌트 내 input 우선
            datePickers.forEach(inp => {
                if (!seen.has(inp)) { candidates.push(inp); seen.add(inp); }
            });

            // 조건 패널 내 input 중 날짜 형식 값을 가진 것
            condInputs.forEach(inp => {
                if (seen.has(inp)) return;
                const val = inp.value;
                // YYYYMMDD 또는 YYYY-MM-DD 또는 빈 값 (날짜 필드일 수 있음)
                if (/^\\d{4}[-/]?\\d{2}[-/]?\\d{2}$/.test(val) || !val) {
                    // 부모 클래스에 Date 포함 여부로 필터
                    const pClass = (inp.parentElement?.className || '') + (inp.parentElement?.parentElement?.className || '');
                    if (pClass.includes('Date') || pClass.includes('date') || pClass.includes('Period') || pClass.includes('period')) {
                        candidates.push(inp);
                        seen.add(inp);
                    }
                }
            });

            if (candidates.length === 0) {
                return { success: false, error: 'no_date_inputs', datePickerCount: datePickers.length };
            }

            // 첫 번째 = 시작일, 두 번째 = 종료일 (일반적 패턴)
            const setInputValue = (input, value) => {
                // React controlled input에 값 설정
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(input, value);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                // blur로 확정
                input.dispatchEvent(new Event('blur', { bubbles: true }));
                return input.value;
            };

            if (candidates.length >= 2) {
                // 시작일, 종료일 각각 설정
                const r1 = setInputValue(candidates[0], start);
                const r2 = setInputValue(candidates[1], end);
                results.push({ field: 'start', result: r1, target: candidates[0].placeholder || 'input[0]' });
                results.push({ field: 'end', result: r2, target: candidates[1].placeholder || 'input[1]' });
            } else if (candidates.length === 1) {
                // 하나만 있으면 시작일만 설정 (기간 조회가 아닌 단일 날짜)
                const r = setInputValue(candidates[0], start);
                results.push({ field: 'start', result: r, target: candidates[0].placeholder || 'input[0]' });
            }

            return { success: true, candidates: candidates.length, results };
        }
    """, {"start": start_date, "end": end_date})

    logger.info(f"날짜 직접 fill 결과: {filled}")

    if filled.get("success"):
        page.wait_for_timeout(500)
        return True

    # 방법 2: Playwright locator로 fill 시도
    logger.info("방법 2: Playwright locator fill 시도...")
    date_inputs = page.locator("[class*='OBTDatePicker'] input[type='text'], [class*='DatePicker'] input[type='text']")
    count = date_inputs.count()
    if count >= 2:
        try:
            date_inputs.nth(0).click(timeout=3000)
            date_inputs.nth(0).fill(start_date)
            page.wait_for_timeout(300)
            date_inputs.nth(0).press("Tab")
            page.wait_for_timeout(300)

            date_inputs.nth(1).click(timeout=3000)
            date_inputs.nth(1).fill(end_date)
            page.wait_for_timeout(300)
            date_inputs.nth(1).press("Tab")
            page.wait_for_timeout(300)
            logger.info("Playwright locator fill 성공")
            return True
        except Exception as e:
            logger.warning(f"Playwright fill 실패: {e}")
    elif count == 1:
        try:
            date_inputs.nth(0).click(timeout=3000)
            date_inputs.nth(0).fill(start_date)
            page.wait_for_timeout(300)
            date_inputs.nth(0).press("Tab")
            logger.info("단일 날짜 Playwright fill 성공")
            return True
        except Exception as e:
            logger.warning(f"Playwright fill 실패: {e}")

    # 방법 3: 조건 패널 내 모든 text input 중 날짜 형식인 것에 fill
    logger.info("방법 3: 조건 패널 input 중 날짜 형식 탐색...")
    cond_inputs = page.locator("[class*='OBTConditionPanel'] input[type='text']")
    cond_count = cond_inputs.count()
    date_filled = 0
    for i in range(cond_count):
        try:
            val = cond_inputs.nth(i).input_value()
            # YYYYMMDD 패턴이면 날짜 필드로 간주
            if len(val) == 8 and val.isdigit():
                target_val = start_date if date_filled == 0 else end_date
                cond_inputs.nth(i).click(timeout=2000)
                cond_inputs.nth(i).fill(target_val)
                page.wait_for_timeout(200)
                cond_inputs.nth(i).press("Tab")
                date_filled += 1
                logger.info(f"조건패널 input[{i}] 날짜 설정: {val} → {target_val}")
                if date_filled >= 2:
                    break
        except Exception:
            continue

    if date_filled > 0:
        page.wait_for_timeout(500)
        return True

    logger.warning("날짜 설정 실패 — 모든 방법 시도 완료")
    _save_screenshot(page, "byprj_date_set_failed")
    return False


def _search_project(page, project_code: str) -> dict:
    """사업코드 검색 입력 — budget_crawler.py의 패턴 재사용"""
    try:
        _dismiss_alerts(page)

        # 사업코드 입력 필드 탐색 (통합검색 제외)
        search_input = page.locator("input[placeholder*='사업코드']:not(#search_input):not(#searchInput)")
        if search_input.count() == 0:
            search_input = page.locator("input[placeholder*='프로젝트']:not(#search_input)")
        if search_input.count() == 0:
            search_input = page.locator("[class*='OBTSearchHelp'] input[type='text']")
        if search_input.count() == 0:
            search_input = page.locator("[class*='OBTConditionPanel'] input[type='text'], [class*='conditionPanel'] input[type='text']")

        if search_input.count() == 0:
            all_inputs = page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input[type="text"]');
                    return Array.from(inputs).map(el => ({
                        placeholder: el.placeholder, id: el.id, name: el.name,
                        className: el.className.substring(0, 60),
                        value: el.value, visible: el.offsetParent !== null
                    }));
                }
            """)
            logger.warning(f"사업코드 필드 미발견. text inputs: {all_inputs}")
            _save_screenshot(page, "byprj_no_search_input")
            return {"success": False, "error": "사업코드 입력 필드를 찾을 수 없습니다.", "inputs_found": all_inputs}

        logger.info(f"사업코드 입력 필드 {search_input.count()}개 발견")

        # 입력 → 엔터 (자동완성/팝업 트리거)
        search_input.first.click(timeout=5000)
        search_input.first.fill("")
        page.wait_for_timeout(300)
        search_input.first.fill(project_code)
        page.wait_for_timeout(500)
        search_input.first.press("Enter")
        page.wait_for_timeout(2000)
        _dismiss_alerts(page)

        # 팝업에서 항목 선택
        popup_selected = _select_search_popup_item(page, project_code)

        if not popup_selected:
            # 돋보기 아이콘 클릭 시도
            logger.info("엔터 후 팝업 미발생, 돋보기 아이콘 클릭...")
            search_icon = page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll("input[placeholder*='사업코드']");
                    for (const inp of inputs) {
                        if (inp.id === 'search_input' || inp.id === 'searchInput') continue;
                        const parent = inp.closest('[class*="OBTSearchHelp"], [class*="searchHelp"]') || inp.parentElement;
                        if (parent) {
                            const btn = parent.querySelector('button, [class*="searchIcon"], [class*="SearchIcon"]');
                            if (btn) { btn.click(); return { clicked: true }; }
                        }
                        const next = inp.nextElementSibling;
                        if (next && (next.tagName === 'BUTTON' || next.querySelector('button'))) {
                            (next.querySelector('button') || next).click();
                            return { clicked: true };
                        }
                    }
                    return { clicked: false };
                }
            """)
            if search_icon.get("clicked"):
                page.wait_for_timeout(2000)
                _dismiss_alerts(page)
                popup_selected = _select_search_popup_item(page, project_code)

        if not popup_selected:
            field_value = search_input.first.input_value()
            logger.info(f"현재 사업코드 필드 값: '{field_value}'")
            if project_code in str(field_value):
                logger.info("자동완성으로 코드 설정됨")
            else:
                _save_screenshot(page, "byprj_code_not_set")
                return {"success": False, "error": f"사업코드 입력 실패. 필드값: '{field_value}'"}

        _dismiss_search_popups(page)
        page.wait_for_timeout(500)
        return {"success": True}

    except Exception as e:
        _save_screenshot(page, "byprj_search_error")
        return {"success": False, "error": f"프로젝트 검색 오류: {e}"}


def _select_search_popup_item(page, project_code: str) -> bool:
    """OBTSearchHelp 팝업 그리드에서 코드 행 선택"""
    try:
        portal = page.locator(".OBTPortal_orbitPortalRoot__3FIEo, [class*='OBTDialog'], [class*='OBTPopup']")
        if portal.count() == 0:
            return False

        _save_screenshot(page, "byprj_search_popup")
        logger.info(f"검색 팝업 발견: {portal.count()}개")

        result = page.evaluate("""
            (code) => {
                const portals = document.querySelectorAll('.OBTPortal_orbitPortalRoot__3FIEo');
                for (const portal of portals) {
                    const grids = portal.querySelectorAll('[class*="OBTDataGrid"]');
                    for (const el of grids) {
                        const fk = Object.keys(el).find(k =>
                            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                        );
                        if (!fk) continue;

                        let f = el[fk];
                        for (let i = 0; i < 5 && f; i++) f = f.return;
                        if (!f?.stateNode?.state?.interface) {
                            f = el[fk];
                            for (let i = 0; i < 3 && f; i++) f = f.return;
                        }
                        if (!f?.stateNode?.state?.interface) continue;

                        const iface = f.stateNode.state.interface;
                        const rowCount = iface.getRowCount();

                        for (let r = 0; r < rowCount; r++) {
                            let val = '';
                            try { val = iface.getValue(r, 'mgtCd'); } catch(e) {}
                            if (!val) try { val = iface.getValue(r, 'pjtCd'); } catch(e) {}

                            if (val === code) {
                                try {
                                    iface.setSelection({ startRow: r, endRow: r, startColumn: 0, endColumn: 0 });
                                    iface.focus();
                                } catch(e) {}

                                const canvas = el.querySelector('canvas');
                                if (canvas) {
                                    const y = 30 + r * 30 + 15;
                                    const x = 50;
                                    canvas.dispatchEvent(new MouseEvent('dblclick', {
                                        bubbles: true, clientX: x,
                                        clientY: canvas.getBoundingClientRect().top + y
                                    }));
                                }
                                return { found: true, row: r, code: val };
                            }
                        }
                        return { found: false, rowCount, searched: code };
                    }
                }
                return { found: false, noGrid: true };
            }
        """, project_code)
        logger.info(f"팝업 행 선택 결과: {result}")

        if result.get("found"):
            page.wait_for_timeout(1500)
            if portal.count() > 0:
                page.evaluate("""
                    () => {
                        const portals = document.querySelectorAll('.OBTPortal_orbitPortalRoot__3FIEo');
                        for (const p of portals) {
                            const btns = p.querySelectorAll('button');
                            for (const btn of btns) {
                                if (btn.textContent.trim() === '확인' || btn.textContent.trim() === '선택') {
                                    btn.click(); return true;
                                }
                            }
                        }
                        return false;
                    }
                """)
                page.wait_for_timeout(1000)
            return True

        return False
    except Exception as e:
        logger.warning(f"팝업 선택 오류: {e}")
        return False


def _dismiss_search_popups(page):
    """검색 팝업 모두 닫기"""
    try:
        page.evaluate("""
            () => {
                const portals = document.querySelectorAll('.OBTPortal_orbitPortalRoot__3FIEo');
                for (const p of portals) {
                    const closeBtn = p.querySelector('[class*="close"], [class*="Close"], button[title="닫기"]');
                    if (closeBtn) { closeBtn.click(); continue; }
                    const btns = p.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.textContent.trim() === '취소' || btn.textContent.trim() === '닫기') {
                            btn.click(); break;
                        }
                    }
                }
            }
        """)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def _click_search_button(page):
    """조회 버튼 클릭"""
    result = page.evaluate("""
        () => {
            const searchBtn = document.querySelector('.OBTConditionPanel_searchButton__2cpwg');
            if (searchBtn) {
                searchBtn.click();
                return { method: 'OBTConditionPanel_searchButton', clicked: true };
            }
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const txt = btn.textContent.trim();
                if (txt === '조회' || txt === '검색') {
                    btn.click();
                    return { method: 'text_match', text: txt, clicked: true };
                }
            }
            return { clicked: false };
        }
    """)
    logger.info(f"조회 버튼 클릭: {result}")
    if not result.get("clicked"):
        logger.info("조회 버튼 못 찾음, 엔터 키 사용")
        page.keyboard.press("Enter")


def _extract_data(page) -> dict:
    """
    그리드 데이터 추출 (OBTDataGrid → Deep search 순서 시도).
    예산 관련 컬럼이 있는 그리드만 선택.
    """
    budget_keywords = {"예산", "집행", "잔액", "대비", "과목", "사업", "budget", "actual"}

    def _is_budget_grid(grid):
        cols = grid.get("columns", [])
        for col in cols:
            header = str(col.get("header", ""))
            if any(kw in header for kw in budget_keywords):
                return True
        return False

    # 시도 1: OBTDataGrid
    data = page.evaluate(_EXTRACT_GRID_DATA_JS)
    if data and not data.get("error") and data.get("results"):
        for grid in data["results"]:
            if grid.get("rows") and _is_budget_grid(grid):
                logger.info(f"예산 그리드 발견 (grid_index={grid.get('grid_index')})")
                return grid
        for grid in data["results"]:
            if grid.get("rows") and len(grid["rows"]) > 0:
                logger.info(f"비예산 그리드 선택 (fallback)")
                return grid

    # 시도 2: 깊은 depth 탐색 (detailList, DataProvider 등)
    data2 = page.evaluate(_EXTRACT_DEEP_DATA_JS)
    if data2 and not data2.get("error") and data2.get("rows"):
        logger.info(f"Deep search 성공: depth={data2.get('depth')}, rows={data2.get('row_count')}")
        return data2

    # 디버깅 정보
    debug_info = page.evaluate("""
        (() => {
            const grids = document.querySelectorAll('[class*="OBTDataGrid"]');
            const info = [];
            for (const el of grids) {
                const fk = Object.keys(el).find(k =>
                    k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                );
                if (!fk) { info.push({no_fiber: true}); continue; }
                let f = el[fk];
                const depths = {};
                for (let d = 0; d < 15 && f; d++) {
                    f = f.return;
                    if (f?.stateNode?.state) {
                        const keys = Object.keys(f.stateNode.state);
                        depths[d+1] = keys;
                    }
                }
                info.push({depths});
            }
            return info;
        })()
    """)
    logger.warning(f"그리드 디버깅: {debug_info}")
    return {"error": "그리드 데이터 추출 실패", "debug": debug_info}


def _navigate_and_extract_by_project(page, project_code: str, start_date: str, end_date: str) -> dict:
    """
    예실대비현황(사업별) 페이지 이동 → 기간 설정 → 사업코드 입력 → 조회 → 데이터 추출.
    """
    try:
        # 1. 페이지 이동
        page_loaded = _navigate_to_by_project_page(page)
        if not page_loaded:
            _save_screenshot(page, f"byprj_page_not_found_{project_code}")
            return {
                "success": False,
                "error": "예실대비현황(사업별) 페이지를 찾을 수 없습니다.",
                "url": page.url,
            }

        _save_screenshot(page, f"byprj_page_loaded_{project_code}")

        # 2. 기간 설정
        date_ok = _set_date_range(page, start_date, end_date)
        if not date_ok:
            logger.warning("날짜 설정 실패, 기본 기간으로 진행합니다.")

        # 3. 사업코드 입력
        search_result = _search_project(page, project_code)
        if not search_result.get("success"):
            return search_result

        # 4. 조회 실행
        _click_search_button(page)
        page.wait_for_timeout(5000)  # 데이터 로드 대기

        # 5. 그리드 데이터 추출
        _save_screenshot(page, f"byprj_after_search_{project_code}")
        data = _extract_data(page)
        if data.get("error"):
            _save_screenshot(page, f"byprj_extract_error_{project_code}")
            return {"success": False, "error": data["error"], "raw": data}

        if not data.get("rows") and not data.get("results"):
            _save_screenshot(page, f"byprj_no_data_{project_code}")
            return {"success": False, "error": "그리드에 데이터가 없습니다.", "raw": data}

        return {
            "success": True,
            "data": data,
            "project_code": project_code,
            "date_range": {"start": start_date, "end": end_date},
        }

    except Exception as e:
        _save_screenshot(page, f"byprj_exception_{project_code}")
        logger.error(f"네비게이션/추출 오류: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _transform_by_project_data(
    data: dict,
    project_id: int,
    project_code: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    사업별 그리드 원시 데이터를 budget_actual 레코드로 변환.
    사업별 페이지는 기간에 걸쳐 누적 데이터를 보여주므로,
    각 행에 대해 적절한 year를 할당.
    """
    rows = data.get("rows", [])
    columns = data.get("columns", [])
    if not rows:
        return []

    col_map = _build_column_mapping(columns)

    # 기간에서 연도 범위 추출
    try:
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
    except (ValueError, IndexError):
        start_year = end_year = datetime.now().year

    records = []
    for row in rows:
        category = _get_mapped_value(row, col_map, "category", "")
        budget_code = _get_mapped_value(row, col_map, "budget_code", "")
        sub_category = _get_mapped_value(row, col_map, "sub_category", "")
        budget_amt = _parse_number(_get_mapped_value(row, col_map, "budget_amount", 0))
        actual_amt = _parse_number(_get_mapped_value(row, col_map, "actual_amount", 0))
        diff = _parse_number(_get_mapped_value(row, col_map, "difference", 0))
        rate = _parse_float(_get_mapped_value(row, col_map, "execution_rate", 0))

        # 빈 행 스킵
        if not category and not sub_category and budget_amt == 0 and actual_amt == 0:
            continue

        # 연도 할당: 행에 연도 정보가 있으면 사용, 없으면 기간 종료 연도
        row_year = _get_mapped_value(row, col_map, "year", None)
        if row_year:
            try:
                row_year = int(row_year)
            except (ValueError, TypeError):
                row_year = end_year
        else:
            # 사업별 페이지는 기간 전체 누적이므로 종료 연도 사용
            # 복수 연도인 경우 budget_code 또는 category에서 연도 힌트가 있을 수 있음
            row_year = end_year

        records.append({
            "project_id": project_id,
            "project_name": project_code,
            "year": row_year,
            "budget_code": str(budget_code),
            "budget_category": str(category),
            "budget_sub_category": str(sub_category),
            "budget_amount": budget_amt,
            "actual_amount": actual_amt,
            "difference": diff if diff else budget_amt - actual_amt,
            "execution_rate": rate if rate else (actual_amt / budget_amt * 100 if budget_amt else 0),
        })

    return records


def _build_column_mapping(columns: list[dict]) -> dict:
    """
    그리드 컬럼 → 표준 필드 매핑.
    사업별 페이지의 필드명은 상세 페이지와 다를 수 있으므로 확장 매핑.
    """
    mapping = {}

    # GW 예실대비 필드명 직접 매핑 (상세/사업별 공용)
    direct_map = {
        "defNm": "category",
        "bgtCd": "budget_code",
        "bgtNm": "sub_category",
        "abgtSumAm": "budget_amount",
        "unitAm": "actual_amount",
        "subAm": "difference",
        "sumRt": "execution_rate",
        # 사업별 페이지에서 추가로 나올 수 있는 필드명
        "pjtCd": "project_code_field",
        "pjtNm": "project_name_field",
        "bgtYy": "year",
        "mgtYy": "year",
        "bgtAm": "budget_amount",
        "excAm": "actual_amount",
        "remAm": "difference",
        "excRt": "execution_rate",
        "T0abgtSumAm": "budget_amount",
        "T0unitAm": "actual_amount",
        "T0subAm": "difference",
        "T0sumRt": "execution_rate",
    }

    for col in columns:
        name = col.get("name", "")
        header = str(col.get("header", "")).strip()

        if name in direct_map:
            field = direct_map[name]
            mapping.setdefault(field, name)
            continue

        # 헤더 텍스트 기반 매핑
        if any(kw in header for kw in ["과목구분", "구분", "분류"]):
            mapping.setdefault("category", name)
        elif any(kw in header for kw in ["예산과목명", "과목명", "항목명", "사업명"]):
            mapping.setdefault("sub_category", name)
        elif any(kw in header for kw in ["예산과목코드", "과목코드", "사업코드"]):
            mapping.setdefault("budget_code", name)
        elif any(kw in header for kw in ["예산액", "예산금액", "배정"]):
            mapping.setdefault("budget_amount", name)
        elif any(kw in header for kw in ["집행액", "실행액", "사용"]):
            mapping.setdefault("actual_amount", name)
        elif any(kw in header for kw in ["잔액", "잔여"]):
            mapping.setdefault("difference", name)
        elif any(kw in header for kw in ["대비", "집행률", "비율", "실행율"]):
            mapping.setdefault("execution_rate", name)
        elif any(kw in header for kw in ["연도", "년도"]):
            mapping.setdefault("year", name)

    return mapping


def _get_mapped_value(row: dict, col_map: dict, field: str, default):
    """매핑된 컬럼명으로 행에서 값 가져오기"""
    col_name = col_map.get(field)
    if col_name and col_name in row:
        return row[col_name]
    return default


def _parse_number(val) -> int:
    """숫자 파싱 (문자열, 콤마 포함 등)"""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        cleaned = val.replace(",", "").replace(" ", "").strip()
        if not cleaned or cleaned == "-":
            return 0
        try:
            return int(float(cleaned))
        except ValueError:
            return 0
    return 0


def _parse_float(val) -> float:
    """실수 파싱"""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace(",", "").replace("%", "").replace(" ", "").strip()
        if not cleaned or cleaned == "-":
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _clear_old_budget(project_id: int):
    """기존 예실대비 데이터 삭제 (최신 데이터로 대체)"""
    if not project_id:
        return
    from src.fund_table.db import get_db
    conn = get_db()
    try:
        conn.execute("DELETE FROM budget_actual WHERE project_id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()
